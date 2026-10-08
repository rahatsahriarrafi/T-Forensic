"""Read-only SQLite browser for evidence DBs (Autopsy-style table browse).

Evidence bytes are materialized once under the session export cache and opened
with SQLite URI mode=ro. Never modifies the source image.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Optional

# Cap materialize size — large browser DBs still OK; huge dumps stay hex-only
MAX_SQLITE_BYTES = 64 * 1024 * 1024
DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 500

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_cache: dict[str, str] = {}  # key -> local tempfile path


def _quote_ident(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("invalid table name")
    # Always quote; allow letters/digits/underscore unescaped, else double-quote
    safe = name.replace('"', '""')
    return f'"{safe}"'


def _cache_key(evidence_path: str, size: int, digest: str) -> str:
    return hashlib.sha1(f"{evidence_path}|{size}|{digest}".encode()).hexdigest()


def _merge_wal(dest: Path, wal: bytes) -> bool:
    """Replay a -wal sidecar into our private cache copy (never the evidence)."""
    wal_path = Path(f"{dest}-wal")
    wal_path.write_bytes(wal)
    try:
        con = sqlite3.connect(str(dest), timeout=10)
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute("PRAGMA journal_mode=DELETE")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False
    finally:
        for side in (wal_path, Path(f"{dest}-shm")):
            try:
                side.unlink()
            except OSError:
                pass


def materialize_sqlite(
    evidence_path: str,
    data: bytes,
    cache_dir: Optional[str] = None,
    wal: Optional[bytes] = None,
) -> dict[str, Any]:
    """
    Write evidence DB bytes to a cache file, replaying the -wal sidecar when given.
    Apps like Discord keep nearly all rows in the WAL; without it the DB looks empty.
    Returns {path, size, truncated, key, wal_merged}.
    """
    truncated = len(data) > MAX_SQLITE_BYTES
    blob = data[:MAX_SQLITE_BYTES]
    h = hashlib.sha256(blob[:65536])
    if wal:
        h.update(hashlib.sha256(wal).digest())
    digest = h.hexdigest()[:16]
    key = _cache_key(evidence_path, len(blob), digest)
    if key in _cache and os.path.isfile(_cache[key]):
        return {
            "key": key,
            "path": _cache[key],
            "size": len(blob),
            "truncated": truncated,
            "cached": True,
            "wal_merged": bool(wal),
        }
    root = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "tforensic-sqlite"
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{key}.sqlite"
    dest.write_bytes(blob)
    merged = _merge_wal(dest, wal) if wal else False
    _cache[key] = str(dest)
    return {
        "key": key,
        "path": str(dest),
        "size": len(blob),
        "truncated": truncated,
        "cached": False,
        "wal_merged": merged,
    }


def _connect(db_path: str) -> sqlite3.Connection:
    # Prefer immutable RO; fall back if the build rejects the flag
    for uri in (
        f"file:{db_path}?mode=ro&immutable=1",
        f"file:{db_path}?mode=ro",
    ):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=10)
            con.row_factory = sqlite3.Row
            return con
        except sqlite3.Error:
            continue
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def list_tables(db_path: str) -> list[dict[str, Any]]:
    con = _connect(db_path)
    try:
        cur = con.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
        out = []
        for r in cur.fetchall():
            name = r["name"]
            count = None
            if r["type"] == "table":
                try:
                    c2 = con.execute(f"SELECT COUNT(*) AS c FROM {_quote_ident(name)}")
                    count = int(c2.fetchone()[0])
                except Exception:
                    count = None
            out.append({
                "name": name,
                "type": r["type"],
                "sql": r["sql"] or "",
                "row_count": count,
            })
        return out
    finally:
        con.close()


def table_schema(db_path: str, table: str) -> dict[str, Any]:
    con = _connect(db_path)
    try:
        q = _quote_ident(table)
        cols = []
        for r in con.execute(f"PRAGMA table_info({q})").fetchall():
            cols.append({
                "cid": r[0],
                "name": r[1],
                "type": r[2] or "",
                "notnull": bool(r[3]),
                "default": r[4],
                "pk": bool(r[5]),
            })
        indexes = []
        for r in con.execute(f"PRAGMA index_list({q})").fetchall():
            indexes.append({
                "name": r[1],
                "unique": bool(r[2]),
                "origin": r[3] if len(r) > 3 else "",
            })
        sql_row = con.execute(
            "SELECT sql FROM sqlite_master WHERE name=? LIMIT 1", (table,)
        ).fetchone()
        return {
            "table": table,
            "columns": cols,
            "indexes": indexes,
            "sql": (sql_row[0] if sql_row else "") or "",
        }
    finally:
        con.close()


def _format_time_value(col: str, value: Any) -> Optional[str]:
    """Turn Chrome/Firefox/Unix epoch columns into readable UTC text."""
    if value is None:
        return None
    name = (col or "").lower()
    timeish = any(
        k in name
        for k in (
            "time", "date", "visited", "created", "modified", "expires",
            "timestamp", "last_access", "last_update", "start", "end",
        )
    )
    if not timeish and name not in {"day", "when"}:
        return None
    try:
        if isinstance(value, bytes):
            return None
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None

    from datetime import datetime, timezone

    # Chrome/WebKit: microseconds since 1601-01-01
    if n >= 10_000_000_000_000:  # ~year 1601+ in µs (Chrome history scale)
        unix = (n / 1_000_000.0) - 11_644_473_600
        kind = "webkit"
    elif n >= 10_000_000_000:  # ms since unix epoch
        unix = n / 1000.0
        kind = "unix-ms"
    elif n >= 1_000_000_000_000:  # µs since unix (Firefox PRTime)
        unix = n / 1_000_000.0
        kind = "unix-us"
    elif n >= 1_000_000_000:  # seconds since unix
        unix = float(n)
        kind = "unix"
    else:
        return None
    # sanity: 1990 .. 2100
    if unix < 631_152_000 or unix > 4_102_444_800:
        return None
    try:
        dt = datetime.fromtimestamp(unix, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    human = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    # Readable UTC + original raw (with epoch kind) side by side
    return f"{human}  |  {kind}:{n}"


def _blob_text(value: bytes) -> Optional[str]:
    """UTF-8 text stored as BLOB (JSON messages, keys) -> readable string."""
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    bad = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r")
    if bad > max(2, len(text) // 20):
        return None
    return "".join(ch if ord(ch) >= 32 or ch in "\t\n\r" else "·" for ch in text)


def _cell_display(col: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = _blob_text(value)
        if text is not None:
            return text
        preview = value[:48].hex()
        return f"BLOB({len(value)}) {preview}{'…' if len(value) > 48 else ''}"
    human = _format_time_value(col, value)
    if human:
        return human
    return str(value)


def table_rows(
    db_path: str,
    table: str,
    offset: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
) -> dict[str, Any]:
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or DEFAULT_ROW_LIMIT), MAX_ROW_LIMIT))
    con = _connect(db_path)
    try:
        q = _quote_ident(table)
        total = None
        try:
            total = int(con.execute(f"SELECT COUNT(*) FROM {q}").fetchone()[0])
        except Exception:
            pass
        cur = con.execute(f"SELECT * FROM {q} LIMIT ? OFFSET ?", (limit, offset))
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = []
        for row in cur.fetchall():
            cells = [_cell_display(columns[i] if i < len(columns) else "", v)
                     for i, v in enumerate(row)]
            rows.append(cells)
        return {
            "table": table,
            "columns": columns,
            "rows": rows,
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(rows),
        }
    finally:
        con.close()


def table_search(
    db_path: str,
    table: str,
    term: str,
    limit: int = MAX_ROW_LIMIT,
) -> dict[str, Any]:
    """Full-table string search across all columns (Chrome History email hunt, etc.)."""
    term = (term or "").strip()
    limit = max(1, min(int(limit or MAX_ROW_LIMIT), MAX_ROW_LIMIT))
    if not term:
        return table_rows(db_path, table, 0, min(100, limit))
    con = _connect(db_path)
    try:
        q = _quote_ident(table)
        # Column list
        info = con.execute(f"PRAGMA table_info({q})").fetchall()
        cols = [r[1] for r in info]  # name
        if not cols:
            return {
                "table": table,
                "columns": [],
                "rows": [],
                "offset": 0,
                "limit": limit,
                "total": 0,
                "returned": 0,
                "search": term,
            }
        # Build OR LIKE across all columns (cast to text)
        clauses = []
        params: list[Any] = []
        needle = f"%{term}%"
        for c in cols:
            clauses.append(f"CAST({_quote_ident(c)} AS TEXT) LIKE ? COLLATE NOCASE")
            params.append(needle)
        where = " OR ".join(clauses)
        try:
            total = int(
                con.execute(
                    f"SELECT COUNT(*) FROM {q} WHERE {where}", params
                ).fetchone()[0]
            )
        except Exception:
            total = None
        params2 = list(params) + [limit]
        cur = con.execute(
            f"SELECT * FROM {q} WHERE {where} LIMIT ?",
            params2,
        )
        columns = [d[0] for d in cur.description] if cur.description else cols
        rows = []
        for row in cur.fetchall():
            cells = [
                _cell_display(columns[i] if i < len(columns) else "", v)
                for i, v in enumerate(row)
            ]
            rows.append(cells)
        return {
            "table": table,
            "columns": columns,
            "rows": rows,
            "offset": 0,
            "limit": limit,
            "total": total if total is not None else len(rows),
            "returned": len(rows),
            "search": term,
            "mode": "search",
        }
    finally:
        con.close()


def browse_summary(
    db_path: str,
    size: int = 0,
    truncated: bool = False,
    wal_merged: bool = False,
) -> dict[str, Any]:
    """First-open payload: tables + first table sample (Autopsy-like overview)."""
    tables = list_tables(db_path)
    sample = None
    schema = None
    active = None
    if tables:
        names = {t["name"]: t for t in tables}
        # Chrome History / browser DBs: prefer urls for email/IOC hunts
        for prefer in ("urls", "downloads", "visits", "messages0", "messages", "message"):
            if prefer in names and names[prefer].get("row_count"):
                active = prefer
                break
        if not active:
            filled = [t for t in tables if t.get("row_count")]
            active = (filled or tables)[0]["name"]
        sample = table_rows(db_path, active, 0, 50)
        try:
            schema = table_schema(db_path, active)
        except Exception:
            schema = None
    return {
        "kind": "sqlite",
        "accessor": "sqlite",
        "label": "SQLite",
        "mode": "sqlite-browser",
        "mime": "application/x-sqlite3",
        "size": size,
        "truncated": truncated,
        "tables": tables,
        "items": [{"name": t["name"], "type": t["type"]} for t in tables],
        "active_table": active,
        "columns": (sample or {}).get("columns"),
        "rows": (sample or {}).get("rows"),
        "schema": schema,
        "note": f"{len(tables)} tables/views"
        + (" · -wal merged (rows not yet checkpointed are included)" if wal_merged else "")
        + (" · DB truncated for preview" if truncated else ""),
        "browser": True,
    }


def looks_like_sqlite(data: bytes, name: str = "") -> bool:
    if data[:15] == b"SQLite format 3":
        return True
    ext = Path(name).suffix.lower().lstrip(".")
    return ext in {"sqlite", "sqlite3", "db", "db3"}
