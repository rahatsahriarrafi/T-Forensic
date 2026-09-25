"""Keyword / filename content index for searchable case DB."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

# Seed keywords commonly useful in LE triage; users add more via search API.
DEFAULT_KEYWORDS = [
    "password",
    "secret",
    "confidential",
    "bitcoin",
    "wallet",
    "ssn",
    "passport",
    "invoice",
    "crypto",
    "ransom",
]


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB, keywords: Optional[list[str]] = None) -> dict:
    kws = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    total = max(len(rows), 1)
    for i, r in enumerate(rows):
        blob = f"{r['name']} {r['path']}".lower()
        for kw in kws:
            if kw in blob:
                db.add_keyword_hit(
                    {
                        "evidence_id": evidence_id,
                        "file_id": r["id"],
                        "path": r["path"],
                        "keyword": kw,
                        "context": r["name"],
                        "offset": blob.find(kw),
                    }
                )
                hits += 1
        if i % 400 == 0:
            progress_cb((i + 1) / total, f"{hits} keyword hits", None)
    progress_cb(1.0, f"{hits} keyword hits", 0)
    return {"hits": hits, "keywords": kws}
