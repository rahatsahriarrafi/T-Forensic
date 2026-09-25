"""Email store locator (PST/OST/MBOX/HxStore)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

RULES = [
    (re.compile(r"\.(pst|ost)$", re.I), "outlook", "Outlook data file"),
    (re.compile(r"\.mbox$", re.I), "mbox", "MBOX mail"),
    (re.compile(r"^hxstore\.hxd$", re.I), "windows_mail", "Windows Mail HxStore"),
    (re.compile(r"^store\.vol$", re.I), "windows_mail", "Unistore DB"),
]


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name, size FROM files WHERE evidence_id=? AND is_dir=0",
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
                        "module": "email",
                        "category": cat,
                        "label": label,
                        "path": r["path"],
                        "detail": {"size": r["size"]},
                    }
                )
                hits += 1
                break
        if i % 300 == 0:
            progress_cb(min(0.99, (i + 1) / max(len(rows), 1)), f"{hits} mail stores", None)
    progress_cb(1.0, f"{hits} email artifacts", 0)
    return {"hits": hits}
