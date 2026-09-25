"""LNK / Prefetch / Jump List locator."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

RULES = [
    (re.compile(r"\.lnk$", re.I), "lnk", "LNK shortcut"),
    (re.compile(r"\.pf$", re.I), "prefetch", "Prefetch"),
    (re.compile(r"\.automaticdestinations-ms$", re.I), "jumplist", "Automatic Destinations"),
    (re.compile(r"\.customdestinations-ms$", re.I), "jumplist", "Custom Destinations"),
]


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    for i, r in enumerate(rows):
        for rx, cat, label in RULES:
            if rx.search(r["name"] or ""):
                db.add_artifact(
                    {
                        "evidence_id": evidence_id,
                        "file_id": r["id"],
                        "module": "lnk_prefetch",
                        "category": cat,
                        "label": label,
                        "path": r["path"],
                    }
                )
                hits += 1
                break
        if i % 300 == 0:
            progress_cb(min(0.99, (i + 1) / max(len(rows), 1)), f"{hits} exec artifacts", None)
    progress_cb(1.0, f"{hits} execution artifacts", 0)
    return {"hits": hits}
