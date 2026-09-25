"""Persistent forensic case database (SQLite) — Autopsy-class case core."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from tforensic.workspace import hash_file

CASE_ENV = "TFOR_CASE"
CASE_ROOT_ENV = "TFOR_CASE_ROOT"
SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  sha256 TEXT,
  size INTEGER DEFAULT 0,
  added_at REAL NOT NULL,
  status TEXT DEFAULT 'added',
  meta_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  is_dir INTEGER DEFAULT 0,
  size INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0,
  inode TEXT,
  mtime REAL,
  atime REAL,
  ctime REAL,
  crtime REAL,
  md5 TEXT,
  sha1 TEXT,
  sha256 TEXT,
  hash_status TEXT,
  UNIQUE(evidence_id, path)
);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(file_id, tag)
);

CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  evidence_id TEXT REFERENCES evidence(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmarks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  label TEXT,
  created_at REAL NOT NULL,
  UNIQUE(file_id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  evidence_id TEXT,
  status TEXT NOT NULL,
  progress REAL DEFAULT 0,
  message TEXT DEFAULT '',
  eta_seconds REAL,
  result_json TEXT DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  error TEXT
);

CREATE TABLE IF NOT EXISTS timeline (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evidence_id TEXT NOT NULL,
  file_id INTEGER,
  ts REAL NOT NULL,
  event_type TEXT NOT NULL,
  source TEXT NOT NULL,
  description TEXT NOT NULL,
  path TEXT,
  extra_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS keyword_hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evidence_id TEXT NOT NULL,
  file_id INTEGER,
  path TEXT NOT NULL,
  keyword TEXT NOT NULL,
  context TEXT,
  offset INTEGER
);

CREATE TABLE IF NOT EXISTS hash_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'notable',
  algo TEXT NOT NULL DEFAULT 'md5',
  imported_at REAL NOT NULL,
  count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hash_set_entries (
  hash TEXT NOT NULL,
  set_id INTEGER NOT NULL REFERENCES hash_sets(id) ON DELETE CASCADE,
  label TEXT,
  PRIMARY KEY(set_id, hash)
);

CREATE TABLE IF NOT EXISTS artifact_hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evidence_id TEXT NOT NULL,
  file_id INTEGER,
  module TEXT NOT NULL,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  path TEXT,
  detail_json TEXT DEFAULT '{}',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS custody_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  actor TEXT DEFAULT 'local',
  action TEXT NOT NULL,
  detail TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_evidence ON files(evidence_id);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_timeline_ts ON timeline(ts);
CREATE INDEX IF NOT EXISTS idx_keyword_kw ON keyword_hits(keyword);
CREATE INDEX IF NOT EXISTS idx_hash_entries ON hash_set_entries(hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_mod ON artifact_hits(module, category);
"""


def default_cases_root() -> Path:
    override = os.environ.get(CASE_ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tforensic" / "cases"


@dataclass
class CaseInfo:
    id: str
    name: str
    path: str
    created_at: float
    examiner: str = ""
    description: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "created_at": self.created_at,
            "examiner": self.examiner,
            "description": self.description,
        }


class CaseDB:
    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir).resolve()
        self.db_path = self.case_dir / "case.db"
        if not self.db_path.is_file():
            raise FileNotFoundError(f"case.db not found: {self.db_path}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def info(self) -> CaseInfo:
        return CaseInfo(
            id=self.get_meta("id"),
            name=self.get_meta("name"),
            path=str(self.case_dir),
            created_at=float(self.get_meta("created_at") or 0),
            examiner=self.get_meta("examiner"),
            description=self.get_meta("description"),
        )

    def log_custody(self, action: str, detail: str, actor: str = "local") -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO custody_log(ts, actor, action, detail) VALUES(?,?,?,?)",
                (time.time(), actor, action, detail),
            )

    # ---- evidence ----
    def add_evidence(
        self,
        path: str | Path,
        *,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> dict:
        from tforensic.evidence import classify_evidence

        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"evidence not found: {path}")
        eid = uuid.uuid4().hex[:12]
        kind = kind or classify_evidence(path)
        digest = sha256 or hash_file(path)
        size = path.stat().st_size
        ename = name or path.name
        # register symlink for bookkeeping
        link_dir = self.case_dir / "evidence"
        link_dir.mkdir(parents=True, exist_ok=True)
        link = link_dir / f"{eid}_{path.name}"
        if not link.exists():
            try:
                link.symlink_to(path)
            except OSError:
                (link_dir / f"{eid}.path").write_text(str(path), encoding="utf-8")
        now = time.time()
        with self.connect() as c:
            c.execute(
                "INSERT INTO evidence(id,name,path,kind,sha256,size,added_at,status) VALUES(?,?,?,?,?,?,?,?)",
                (eid, ename, str(path), kind, digest, size, now, "added"),
            )
        self.log_custody("evidence_add", f"{ename} ({kind}) sha256={digest} path={path}")
        return self.get_evidence(eid)

    def get_evidence(self, eid: str) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
            if not row:
                raise KeyError(f"evidence not found: {eid}")
            return dict(row)

    def list_evidence(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM evidence ORDER BY added_at")]

    def set_evidence_status(self, eid: str, status: str) -> None:
        with self.connect() as c:
            c.execute("UPDATE evidence SET status=? WHERE id=?", (status, eid))

    # ---- files ----
    def upsert_file(self, evidence_id: str, rec: dict) -> int:
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO files(evidence_id,path,name,is_dir,size,deleted,inode,mtime,atime,ctime,crtime,md5,sha1,sha256,hash_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(evidence_id, path) DO UPDATE SET
                  name=excluded.name, is_dir=excluded.is_dir, size=excluded.size,
                  deleted=excluded.deleted, inode=excluded.inode,
                  mtime=excluded.mtime, atime=excluded.atime, ctime=excluded.ctime, crtime=excluded.crtime,
                  md5=COALESCE(excluded.md5, files.md5),
                  sha1=COALESCE(excluded.sha1, files.sha1),
                  sha256=COALESCE(excluded.sha256, files.sha256),
                  hash_status=COALESCE(excluded.hash_status, files.hash_status)
                """,
                (
                    evidence_id,
                    rec["path"],
                    rec.get("name") or Path(rec["path"]).name,
                    1 if rec.get("is_dir") else 0,
                    int(rec.get("size") or 0),
                    1 if rec.get("deleted") else 0,
                    rec.get("inode"),
                    rec.get("mtime"),
                    rec.get("atime"),
                    rec.get("ctime"),
                    rec.get("crtime"),
                    rec.get("md5"),
                    rec.get("sha1"),
                    rec.get("sha256"),
                    rec.get("hash_status"),
                ),
            )
            row = c.execute(
                "SELECT id FROM files WHERE evidence_id=? AND path=?",
                (evidence_id, rec["path"]),
            ).fetchone()
            return int(row["id"])

    def count_files(self, evidence_id: Optional[str] = None) -> int:
        with self.connect() as c:
            if evidence_id:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM files WHERE evidence_id=?", (evidence_id,)
                ).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) AS n FROM files").fetchone()
            return int(row["n"])

    def search_files(self, q: str, limit: int = 200) -> list[dict]:
        like = f"%{q}%"
        with self.connect() as c:
            rows = c.execute(
                """
                SELECT f.*, e.name AS evidence_name FROM files f
                JOIN evidence e ON e.id=f.evidence_id
                WHERE f.name LIKE ? OR f.path LIKE ?
                ORDER BY f.path LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_file(self, file_id: int) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
            if not row:
                raise KeyError(f"file not found: {file_id}")
            return dict(row)

    # ---- tags / notes / bookmarks ----
    def add_tag(self, file_id: int, tag: str) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO tags(file_id, tag, created_at) VALUES(?,?,?)",
                (file_id, tag.strip(), time.time()),
            )
        self.log_custody("tag_add", f"file_id={file_id} tag={tag}")

    def list_tags(self, file_id: Optional[int] = None) -> list[dict]:
        with self.connect() as c:
            if file_id is not None:
                rows = c.execute("SELECT * FROM tags WHERE file_id=?", (file_id,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM tags ORDER BY created_at DESC LIMIT 500").fetchall()
            return [dict(r) for r in rows]

    def add_note(self, body: str, *, file_id: Optional[int] = None, evidence_id: Optional[str] = None) -> int:
        now = time.time()
        with self.connect() as c:
            cur = c.execute(
                "INSERT INTO notes(file_id, evidence_id, body, created_at, updated_at) VALUES(?,?,?,?,?)",
                (file_id, evidence_id, body, now, now),
            )
            nid = int(cur.lastrowid)
        self.log_custody("note_add", f"note_id={nid}")
        return nid

    def list_notes(self, file_id: Optional[int] = None) -> list[dict]:
        with self.connect() as c:
            if file_id is not None:
                rows = c.execute(
                    "SELECT * FROM notes WHERE file_id=? ORDER BY created_at DESC", (file_id,)
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM notes ORDER BY created_at DESC LIMIT 200").fetchall()
            return [dict(r) for r in rows]

    def add_bookmark(self, file_id: int, label: str = "") -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO bookmarks(file_id, label, created_at) VALUES(?,?,?) "
                "ON CONFLICT(file_id) DO UPDATE SET label=excluded.label",
                (file_id, label, time.time()),
            )

    def list_bookmarks(self) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                """
                SELECT b.*, f.path, f.name, f.evidence_id FROM bookmarks b
                JOIN files f ON f.id=b.file_id ORDER BY b.created_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- jobs ----
    def create_job(self, kind: str, evidence_id: Optional[str] = None, eta_seconds: Optional[float] = None) -> str:
        jid = uuid.uuid4().hex[:12]
        now = time.time()
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO jobs(id, kind, evidence_id, status, progress, message, eta_seconds, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (jid, kind, evidence_id, "queued", 0.0, "queued", eta_seconds, now, now),
            )
        return jid

    def update_job(
        self,
        jid: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        eta_seconds: Optional[float] = None,
        error: Optional[str] = None,
        result: Optional[dict] = None,
    ) -> None:
        fields = ["updated_at=?"]
        vals: list[Any] = [time.time()]
        if status is not None:
            fields.append("status=?")
            vals.append(status)
        if progress is not None:
            fields.append("progress=?")
            vals.append(progress)
        if message is not None:
            fields.append("message=?")
            vals.append(message)
        if eta_seconds is not None:
            fields.append("eta_seconds=?")
            vals.append(eta_seconds)
        if error is not None:
            fields.append("error=?")
            vals.append(error)
        if result is not None:
            fields.append("result_json=?")
            vals.append(json.dumps(result))
        vals.append(jid)
        with self.connect() as c:
            c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", vals)

    def get_job(self, jid: str) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise KeyError(f"job not found: {jid}")
            d = dict(row)
            try:
                d["result"] = json.loads(d.get("result_json") or "{}")
            except json.JSONDecodeError:
                d["result"] = {}
            return d

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["result"] = json.loads(d.get("result_json") or "{}")
                except json.JSONDecodeError:
                    d["result"] = {}
                out.append(d)
            return out

    # ---- timeline / keyword / artifacts ----
    def add_timeline_event(self, ev: dict) -> None:
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO timeline(evidence_id, file_id, ts, event_type, source, description, path, extra_json)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    ev["evidence_id"],
                    ev.get("file_id"),
                    float(ev["ts"]),
                    ev["event_type"],
                    ev.get("source") or "index",
                    ev["description"],
                    ev.get("path"),
                    json.dumps(ev.get("extra") or {}),
                ),
            )

    def query_timeline(
        self,
        *,
        start: Optional[float] = None,
        end: Optional[float] = None,
        event_type: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        clauses = ["1=1"]
        vals: list[Any] = []
        if start is not None:
            clauses.append("ts >= ?")
            vals.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            vals.append(end)
        if event_type:
            clauses.append("event_type = ?")
            vals.append(event_type)
        vals.extend([limit, offset])
        sql = f"SELECT * FROM timeline WHERE {' AND '.join(clauses)} ORDER BY ts DESC LIMIT ? OFFSET ?"
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, vals).fetchall()]

    def add_keyword_hit(self, hit: dict) -> None:
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO keyword_hits(evidence_id, file_id, path, keyword, context, offset)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    hit["evidence_id"],
                    hit.get("file_id"),
                    hit["path"],
                    hit["keyword"],
                    hit.get("context"),
                    hit.get("offset"),
                ),
            )

    def search_keyword(self, q: str, limit: int = 200) -> list[dict]:
        like = f"%{q}%"
        with self.connect() as c:
            rows = c.execute(
                """
                SELECT * FROM keyword_hits
                WHERE keyword LIKE ? OR context LIKE ? OR path LIKE ?
                ORDER BY id DESC LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_artifact(self, art: dict) -> None:
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO artifact_hits(evidence_id, file_id, module, category, label, path, detail_json, created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    art["evidence_id"],
                    art.get("file_id"),
                    art["module"],
                    art["category"],
                    art["label"],
                    art.get("path"),
                    json.dumps(art.get("detail") or {}),
                    time.time(),
                ),
            )

    def list_artifacts(self, module: Optional[str] = None, limit: int = 500) -> list[dict]:
        with self.connect() as c:
            if module:
                rows = c.execute(
                    "SELECT * FROM artifact_hits WHERE module=? ORDER BY created_at DESC LIMIT ?",
                    (module, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM artifact_hits ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # ---- hash sets ----
    def import_hash_set(
        self,
        name: str,
        hashes: list[str],
        *,
        kind: str = "notable",
        algo: str = "md5",
        labels: Optional[dict[str, str]] = None,
    ) -> dict:
        labels = labels or {}
        now = time.time()
        with self.connect() as c:
            c.execute(
                """
                INSERT INTO hash_sets(name, kind, algo, imported_at, count) VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, algo=excluded.algo,
                  imported_at=excluded.imported_at, count=excluded.count
                """,
                (name, kind, algo, now, len(hashes)),
            )
            row = c.execute("SELECT id FROM hash_sets WHERE name=?", (name,)).fetchone()
            sid = int(row["id"])
            c.execute("DELETE FROM hash_set_entries WHERE set_id=?", (sid,))
            for h in hashes:
                hh = h.strip().lower()
                if not hh:
                    continue
                c.execute(
                    "INSERT OR IGNORE INTO hash_set_entries(hash, set_id, label) VALUES(?,?,?)",
                    (hh, sid, labels.get(hh)),
                )
            count = c.execute(
                "SELECT COUNT(*) AS n FROM hash_set_entries WHERE set_id=?", (sid,)
            ).fetchone()["n"]
            c.execute("UPDATE hash_sets SET count=? WHERE id=?", (count, sid))
        self.log_custody("hash_set_import", f"{name} algo={algo} kind={kind} count={count}")
        return {"id": sid, "name": name, "kind": kind, "algo": algo, "count": count}

    def list_hash_sets(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM hash_sets ORDER BY name")]

    def match_hash(self, digest: str) -> list[dict]:
        digest = digest.lower().strip()
        with self.connect() as c:
            rows = c.execute(
                """
                SELECT e.hash, e.label, s.name AS set_name, s.kind, s.algo
                FROM hash_set_entries e JOIN hash_sets s ON s.id=e.set_id
                WHERE e.hash=?
                """,
                (digest,),
            ).fetchall()
            return [dict(r) for r in rows]

    def apply_hash_sets_to_files(self) -> int:
        """Mark files whose md5/sha1/sha256 hit a hash set."""
        updated = 0
        with self.connect() as c:
            files = c.execute(
                "SELECT id, md5, sha1, sha256 FROM files WHERE md5 IS NOT NULL OR sha1 IS NOT NULL OR sha256 IS NOT NULL"
            ).fetchall()
            for f in files:
                status = None
                for algo, col in (("md5", "md5"), ("sha1", "sha1"), ("sha256", "sha256")):
                    val = f[col]
                    if not val:
                        continue
                    hits = c.execute(
                        """
                        SELECT s.kind FROM hash_set_entries e
                        JOIN hash_sets s ON s.id=e.set_id
                        WHERE e.hash=? AND s.algo=?
                        """,
                        (val.lower(), algo),
                    ).fetchall()
                    if hits:
                        # notable beats known
                        kinds = {h["kind"] for h in hits}
                        status = "notable" if "notable" in kinds else "known"
                        break
                if status:
                    c.execute("UPDATE files SET hash_status=? WHERE id=?", (status, f["id"]))
                    updated += 1
        return updated

    def custody_entries(self, limit: int = 200) -> list[dict]:
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM custody_log ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    def stats(self) -> dict:
        with self.connect() as c:
            return {
                "evidence": c.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"],
                "files": c.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"],
                "tags": c.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"],
                "notes": c.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"],
                "bookmarks": c.execute("SELECT COUNT(*) AS n FROM bookmarks").fetchone()["n"],
                "timeline": c.execute("SELECT COUNT(*) AS n FROM timeline").fetchone()["n"],
                "artifacts": c.execute("SELECT COUNT(*) AS n FROM artifact_hits").fetchone()["n"],
                "jobs": c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"],
                "hash_sets": c.execute("SELECT COUNT(*) AS n FROM hash_sets").fetchone()["n"],
            }

    def chart_data(self) -> dict:
        """Aggregates for Case Overview charts (extensions, artifacts, timeline)."""
        with self.connect() as c:
            metrics = self.stats()
            metrics["deleted"] = c.execute(
                "SELECT COUNT(*) AS n FROM files WHERE deleted=1"
            ).fetchone()["n"]
            metrics["dirs"] = c.execute(
                "SELECT COUNT(*) AS n FROM files WHERE is_dir=1"
            ).fetchone()["n"]
            metrics["hash_marked"] = c.execute(
                "SELECT COUNT(*) AS n FROM files WHERE hash_status IS NOT NULL AND hash_status!=''"
            ).fetchone()["n"]
            metrics["keyword_hits"] = c.execute(
                "SELECT COUNT(*) AS n FROM keyword_hits"
            ).fetchone()["n"]

            # Top extensions (files only)
            ext_counts: dict[str, int] = {}
            for row in c.execute("SELECT name FROM files WHERE is_dir=0"):
                name = row["name"] or ""
                if "." in name and not name.startswith("."):
                    ext = name.rsplit(".", 1)[-1].lower()[:24] or "(none)"
                else:
                    ext = "(none)"
                if len(ext) > 16:
                    ext = ext[:16]
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
            extensions = [
                {"label": k, "count": v}
                for k, v in sorted(ext_counts.items(), key=lambda x: -x[1])[:14]
            ]

            artifacts = [
                {"label": r["module"] or "unknown", "count": r["n"]}
                for r in c.execute(
                    "SELECT module, COUNT(*) AS n FROM artifact_hits "
                    "GROUP BY module ORDER BY n DESC LIMIT 14"
                )
            ]

            categories = [
                {"label": r["category"] or "unknown", "count": r["n"]}
                for r in c.execute(
                    "SELECT category, COUNT(*) AS n FROM artifact_hits "
                    "GROUP BY category ORDER BY n DESC LIMIT 14"
                )
            ]

            tags = [
                {"label": r["tag"], "count": r["n"]}
                for r in c.execute(
                    "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC LIMIT 12"
                )
            ]

            # Timeline density by day (unix day bucket)
            timeline = [
                {
                    "ts": int(r["day"]) * 86400,
                    "label": time.strftime("%Y-%m-%d", time.gmtime(int(r["day"]) * 86400)),
                    "count": r["n"],
                }
                for r in c.execute(
                    "SELECT CAST(ts / 86400 AS INTEGER) AS day, COUNT(*) AS n "
                    "FROM timeline WHERE ts > 0 GROUP BY day ORDER BY day"
                )
            ]
            # Cap to last 60 days of activity if huge
            if len(timeline) > 60:
                timeline = timeline[-60:]

            event_types = [
                {"label": r["event_type"] or "?", "count": r["n"]}
                for r in c.execute(
                    "SELECT event_type, COUNT(*) AS n FROM timeline "
                    "GROUP BY event_type ORDER BY n DESC LIMIT 12"
                )
            ]

            evidence = [
                {
                    "label": (r["name"] or r["id"])[:40],
                    "kind": r["kind"],
                    "count": r["n"],
                }
                for r in c.execute(
                    "SELECT e.id, e.name, e.kind, COUNT(f.id) AS n "
                    "FROM evidence e LEFT JOIN files f ON f.evidence_id=e.id "
                    "GROUP BY e.id ORDER BY n DESC"
                )
            ]

        return {
            "metrics": metrics,
            "extensions": extensions,
            "artifacts": artifacts,
            "categories": categories,
            "tags": tags,
            "timeline": timeline,
            "event_types": event_types,
            "evidence": evidence,
        }


def create_case(
    name: str,
    *,
    examiner: str = "",
    description: str = "",
    cases_root: Optional[Path] = None,
) -> CaseDB:
    root = cases_root or default_cases_root()
    root.mkdir(parents=True, exist_ok=True)
    cid = uuid.uuid4().hex[:12]
    case_dir = root / cid
    for sub in ("evidence", "index", "exports", "reports"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "case.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        now = str(time.time())
        conn.execute("INSERT INTO meta(key,value) VALUES('id',?)", (cid,))
        conn.execute("INSERT INTO meta(key,value) VALUES('name',?)", (name,))
        conn.execute("INSERT INTO meta(key,value) VALUES('examiner',?)", (examiner,))
        conn.execute("INSERT INTO meta(key,value) VALUES('description',?)", (description,))
        conn.execute("INSERT INTO meta(key,value) VALUES('created_at',?)", (now,))
        conn.execute("INSERT INTO meta(key,value) VALUES('schema',?)", (str(SCHEMA_VERSION),))
        conn.execute(
            "INSERT INTO custody_log(ts, actor, action, detail) VALUES(?,?,?,?)",
            (time.time(), examiner or "local", "case_create", f"Created case {name!r}"),
        )
        conn.commit()
    finally:
        conn.close()
    # active pointer
    (root / "active").write_text(cid, encoding="utf-8")
    return CaseDB(case_dir)


def list_cases(cases_root: Optional[Path] = None) -> list[dict]:
    root = cases_root or default_cases_root()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not (p / "case.db").is_file():
            continue
        try:
            db = CaseDB(p)
            info = db.info().as_dict()
            info["stats"] = db.stats()
            out.append(info)
        except Exception:
            continue
    return out


def open_case(case_id: Optional[str] = None, cases_root: Optional[Path] = None) -> CaseDB:
    root = cases_root or default_cases_root()
    cid = case_id or os.environ.get(CASE_ENV)
    if not cid and (root / "active").is_file():
        cid = (root / "active").read_text(encoding="utf-8").strip()
    if not cid:
        raise FileNotFoundError("no case id; create/open a case or set TFOR_CASE")
    case_dir = root / cid
    if not (case_dir / "case.db").is_file():
        raise FileNotFoundError(f"case not found: {cid}")
    (root / "active").write_text(cid, encoding="utf-8")
    return CaseDB(case_dir)


def resolve_case(case_id: Optional[str] = None) -> CaseDB:
    return open_case(case_id)
