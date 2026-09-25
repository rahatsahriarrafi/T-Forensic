"""Browser artifact locator (History, places.sqlite, cookies, etc.)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]

PATTERNS = [
    (r"^history$", "history", "Chrome/Edge History"),
    (r"^places\.sqlite$", "history", "Firefox places"),
    (r"^cookies$", "cookies", "Chrome Cookies"),
    (r"^cookies\.sqlite$", "cookies", "Firefox cookies"),
    (r"^web data$", "downloads", "Chrome Web Data"),
    (r"^downloads\.sqlite$", "downloads", "Firefox downloads"),
    (r"^login data$", "logins", "Chrome Login Data"),
    (r"^favicons$", "favicons", "Chrome Favicons"),
]


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    compiled = [(re.compile(p, re.I), cat, label) for p, cat, label in PATTERNS]
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    for i, r in enumerate(rows):
        for rx, cat, label in compiled:
            if rx.search(r["name"] or ""):
                db.add_artifact(
                    {
                        "evidence_id": evidence_id,
                        "file_id": r["id"],
                        "module": "web",
                        "category": cat,
                        "label": label,
                        "path": r["path"],
                    }
                )
                db.add_timeline_event(
                    {
                        "evidence_id": evidence_id,
                        "file_id": r["id"],
                        "ts": __import__("time").time(),
                        "event_type": "web_artifact",
                        "source": "web",
                        "description": label,
                        "path": r["path"],
                    }
                )
                hits += 1
                break
        if i % 300 == 0:
            progress_cb(min(0.99, (i + 1) / max(len(rows), 1)), f"{hits} web artifacts", None)
    progress_cb(1.0, f"{hits} web artifacts", 0)
    return {"hits": hits}
