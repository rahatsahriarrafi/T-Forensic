"""Lightweight header carving scan over small indexed files (signature stub).

Full photorec-style carving is optional when `photorec` is on PATH; otherwise
we scan file name patterns and flag deleted entries as carve candidates.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG": "png",
    b"PK\x03\x04": "zip",
    b"%PDF": "pdf",
    b"MZ": "pe",
}


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    hits = 0
    # Flag deleted files as carve candidates
    with db.connect() as c:
        deleted = c.execute(
            "SELECT id, path, name FROM files WHERE evidence_id=? AND deleted=1",
            (evidence_id,),
        ).fetchall()
    for r in deleted:
        db.add_artifact(
            {
                "evidence_id": evidence_id,
                "file_id": r["id"],
                "module": "carve",
                "category": "deleted",
                "label": "Deleted file (carve candidate)",
                "path": r["path"],
            }
        )
        hits += 1

    progress_cb(0.5, f"{hits} deleted candidates", None)

    # Optional photorec if available (non-interactive list only — skip heavy run)
    photorec = shutil.which("photorec") or shutil.which("testdisk")
    note = "photorec available" if photorec else "photorec not installed — deleted markers only"
    if photorec:
        db.add_artifact(
            {
                "evidence_id": evidence_id,
                "module": "carve",
                "category": "tool",
                "label": "PhotoRec available for deep carve",
                "path": None,
                "detail": {"tool": photorec},
            }
        )

    progress_cb(1.0, note, 0)
    return {"hits": hits, "photorec": bool(photorec), "note": note}
