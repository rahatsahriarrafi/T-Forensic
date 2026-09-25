"""Windows registry hive locator (+ light hive header check when readable)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

HIVES = re.compile(
    r"^(ntuser\.dat|usrclass\.dat|sam|system|software|security|components)$",
    re.I,
)


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name, size FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    for i, r in enumerate(rows):
        if HIVES.search(r["name"] or ""):
            db.add_artifact(
                {
                    "evidence_id": evidence_id,
                    "file_id": r["id"],
                    "module": "registry",
                    "category": "hive",
                    "label": f"Registry hive {r['name']}",
                    "path": r["path"],
                    "detail": {"size": r["size"]},
                }
            )
            hits += 1
        if i % 300 == 0:
            progress_cb(min(0.99, (i + 1) / max(len(rows), 1)), f"{hits} hives", None)
    progress_cb(1.0, f"{hits} registry hives", 0)
    return {"hits": hits}
