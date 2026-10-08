"""Index evidence into case.db files + timeline, then run ingest modules."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from tforensic.casedb import CaseDB
from tforensic.estimate import estimate_open
from tforensic.ingest import modules as modpkg

ProgressCB = Callable[[float, str, Optional[float]], None]


def _index_ad1(db: CaseDB, evidence: dict, progress_cb: ProgressCB) -> dict:
    from tforensic.case import open_case as open_ad1_session

    progress_cb(0.05, "Opening AD1…", None)
    case = open_ad1_session(evidence["path"])
    files = list(case.files)
    total = max(len(files), 1)
    indexed = 0
    t0 = time.time()
    for i, node in enumerate(files):
        fid = db.upsert_file(
            evidence["id"],
            {
                "path": node.path,
                "name": node.name,
                "is_dir": False,
                "size": getattr(node, "size", 0) or 0,
                "deleted": False,
            },
        )
        # crude mtime from attrs if present
        mtime = None
        attrs = getattr(node, "attrs", None) or {}
        for k, v in attrs.items() if isinstance(attrs, dict) else []:
            if "time" in str(k).lower() or "date" in str(k).lower():
                try:
                    mtime = float(v)
                except (TypeError, ValueError):
                    pass
        if mtime:
            db.add_timeline_event(
                {
                    "evidence_id": evidence["id"],
                    "file_id": fid,
                    "ts": mtime,
                    "event_type": "mtime",
                    "source": "ad1",
                    "description": f"AD1 file {node.name}",
                    "path": node.path,
                }
            )
        indexed += 1
        if i % 50 == 0 or i == total - 1:
            pct = 0.05 + 0.55 * (i + 1) / total
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 1
            left = (total - i - 1) / rate if rate else None
            progress_cb(pct, f"Indexing AD1 {i+1}/{total}", left)
    # also index dirs lightly
    try:
        root = case.img.root

        def walk(n, depth=0):
            if depth > 40:
                return
            if getattr(n, "is_dir", False):
                db.upsert_file(
                    evidence["id"],
                    {"path": n.path, "name": n.name, "is_dir": True, "size": 0},
                )
                for c in getattr(n, "children", []) or []:
                    walk(c, depth + 1)

        walk(root)
    except Exception:
        pass
    return {"indexed": indexed, "kind": "ad1"}


def _index_disk(db: CaseDB, evidence: dict, progress_cb: ProgressCB) -> dict:
    """Mount via open_evidence and walk partitions with fls (limited depth)."""
    from tforensic.evidence import open_evidence
    from tforensic import xmount_wrap as xm

    progress_cb(0.05, "Opening disk/OVA…", None)
    opened = open_evidence(evidence["path"])
    mount = getattr(opened, "mount", None)
    if not mount:
        progress_cb(0.5, "No xmount device; recorded evidence only", 0)
        db.upsert_file(
            evidence["id"],
            {
                "path": "/",
                "name": Path(evidence["path"]).name,
                "is_dir": False,
                "size": evidence.get("size") or 0,
            },
        )
        return {"indexed": 1, "kind": "disk-meta"}

    device = mount.virtual_device
    progress_cb(0.15, "Listing partitions…", None)
    try:
        parts = xm.mmls_partitions(device)
    except Exception as e:
        progress_cb(0.2, f"mmls failed: {e}", None)
        parts = [{"start": 0, "desc": "whole", "slot": "000"}]

    indexed = 0
    usable = [p for p in parts if int(p.get("start") or 0) >= 0]
    if not usable:
        usable = [{"start": 0, "desc": "0"}]
    for pi, part in enumerate(usable[:8]):
        offset = int(part.get("start") or 0)
        progress_cb(
            0.2 + 0.5 * (pi / max(len(usable), 1)),
            f"fls partition start={offset}",
            None,
        )
        try:
            entries = xm.fls_list(device, offset_sectors=offset, recursive=True, limit=5000)
        except Exception:
            try:
                entries = xm.fls_list(device, offset_sectors=offset, recursive=False, limit=2000)
            except Exception:
                continue
        for e in entries:
            path = f"/{offset}{e.get('name') or ''}"
            if not path.startswith("/"):
                path = "/" + path
            name = Path(e.get("name") or "unknown").name
            fid = db.upsert_file(
                evidence["id"],
                {
                    "path": path if e.get("name", "").startswith("/") else f"/{offset}/{e.get('name','')}",
                    "name": name,
                    "is_dir": bool(e.get("is_dir")),
                    "size": 0,
                    "deleted": bool(e.get("deleted")),
                    "inode": str(e.get("inode") or ""),
                },
            )
            if e.get("deleted"):
                db.add_timeline_event(
                    {
                        "evidence_id": evidence["id"],
                        "file_id": fid,
                        "ts": time.time(),
                        "event_type": "deleted",
                        "source": "fls",
                        "description": f"Deleted entry {name}",
                        "path": path,
                    }
                )
            indexed += 1
    return {"indexed": indexed, "kind": "disk", "device": device}


def run_file_index(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    evidence = db.get_evidence(evidence_id)
    kind = evidence.get("kind") or "unknown"
    est = estimate_open(evidence["path"])
    progress_cb(0.02, f"Estimate {est['human']}", est["seconds"])

    if kind in ("ad1", "folder"):
        stats = _index_ad1(db, evidence, progress_cb)
    elif kind in ("disk", "ova"):
        stats = _index_disk(db, evidence, progress_cb)
    else:
        # Loose file / unknown: register as a single logical file for keyword/artifact modules
        progress_cb(0.3, "Indexing loose file…", None)
        name = Path(evidence["path"]).name
        db.upsert_file(
            evidence["id"],
            {
                "path": f"/{name}",
                "name": name,
                "is_dir": False,
                "size": evidence.get("size") or 0,
            },
        )
        db.add_keyword_hit(
            {
                "evidence_id": evidence["id"],
                "path": f"/{name}",
                "keyword": name.lower(),
                "context": name,
            }
        )
        # also scan filename against default keywords
        low = name.lower()
        for kw in ("password", "secret", "confidential", "wallet", "ransom"):
            if kw in low:
                db.add_keyword_hit(
                    {
                        "evidence_id": evidence["id"],
                        "path": f"/{name}",
                        "keyword": kw,
                        "context": name,
                    }
                )
        stats = {"indexed": 1, "kind": "file"}

    if stats.get("indexed", 0) == 0 and kind in ("disk", "ova"):
        # Ensure at least a placeholder so modules have something to scan
        name = Path(evidence["path"]).name
        db.upsert_file(
            evidence["id"],
            {"path": f"/{name}", "name": name, "is_dir": False, "size": evidence.get("size") or 0},
        )
        stats["indexed"] = max(stats.get("indexed", 0), 1)
        stats["placeholder"] = True

    db.set_evidence_status(evidence_id, "indexed")
    progress_cb(0.65, f"Indexed {stats.get('indexed', 0)} files", None)
    return stats


def run_ingest(
    db: CaseDB,
    evidence_id: str,
    progress_cb: ProgressCB,
    *,
    modules: Optional[list[str]] = None,
) -> dict:
    """Full ingest: index files then run selected modules."""
    index_stats = run_file_index(db, evidence_id, progress_cb)
    selected = modules or list(MODULES.keys())
    module_stats = {}
    n = max(len(selected), 1)
    for i, name in enumerate(selected):
        mod = MODULES.get(name)
        if not mod:
            continue
        base = 0.65 + 0.3 * (i / n)
        progress_cb(base, f"Module {name}…", None)

        def mod_progress(p, msg, eta=None, _base=base, _i=i):
            progress_cb(_base + 0.3 * (p / n), f"[{name}] {msg}", eta)

        try:
            module_stats[name] = mod.run(db, evidence_id, mod_progress)
        except Exception as e:
            module_stats[name] = {"error": str(e)}
    # apply hash sets
    progress_cb(0.96, "Matching hash sets…", 1)
    matched = db.apply_hash_sets_to_files()
    db.set_evidence_status(evidence_id, "ingested")
    db.log_custody("ingest_done", f"evidence={evidence_id} files={index_stats.get('indexed')} hash_matched={matched}")
    progress_cb(1.0, "Ingest complete", 0)
    return {"index": index_stats, "modules": module_stats, "hash_matched": matched}


# Module registry name -> module
MODULES = {
    "artifacts": modpkg.artifacts,
    "web": modpkg.web,
    "registry": modpkg.registry,
    "lnk_prefetch": modpkg.lnk_prefetch,
    "email": modpkg.email_mod,
    "exif_media": modpkg.exif_media,
    "carve": modpkg.carve,
    "keyword": modpkg.keyword,
}
