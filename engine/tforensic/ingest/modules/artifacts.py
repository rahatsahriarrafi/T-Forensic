"""Path-based artifact classifier module."""
from __future__ import annotations

from typing import Callable, Optional

from tforensic.analysis import ARTIFACT_RULES
from tforensic.casedb import CaseDB
import re

ProgressCB = Callable[[float, str, Optional[float]], None]
_COMPILED = [(label, cat, re.compile(rx, re.IGNORECASE)) for label, cat, rx in ARTIFACT_RULES]


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name, size FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    total = max(len(rows), 1)
    for i, r in enumerate(rows):
        for label, cat, rx in _COMPILED:
            if rx.search(r["name"] or ""):
                db.add_artifact(
                    {
                        "evidence_id": evidence_id,
                        "file_id": r["id"],
                        "module": "artifacts",
                        "category": cat,
                        "label": label,
                        "path": r["path"],
                        "detail": {"size": r["size"]},
                    }
                )
                hits += 1
                break
        if i % 200 == 0:
            progress_cb((i + 1) / total, f"artifacts {hits} hits", None)
    progress_cb(1.0, f"{hits} artifact hits", 0)
    return {"hits": hits}
