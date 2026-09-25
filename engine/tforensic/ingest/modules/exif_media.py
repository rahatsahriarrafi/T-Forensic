"""Media/EXIF candidate locator (images/video by extension)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from tforensic.casedb import CaseDB

ProgressCB = Callable[[float, str, Optional[float]], None]
MEDIA = re.compile(r"\.(jpe?g|png|gif|bmp|tiff?|webp|heic|mp4|mov|avi|mkv|wmv)$", re.I)


def run(db: CaseDB, evidence_id: str, progress_cb: ProgressCB) -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, path, name, size FROM files WHERE evidence_id=? AND is_dir=0",
            (evidence_id,),
        ).fetchall()
    hits = 0
    for i, r in enumerate(rows):
        if MEDIA.search(r["name"] or ""):
            db.add_artifact(
                {
                    "evidence_id": evidence_id,
                    "file_id": r["id"],
                    "module": "exif_media",
                    "category": "media",
                    "label": "Media file",
                    "path": r["path"],
                    "detail": {"size": r["size"], "ext": (r["name"] or "").rsplit(".", 1)[-1].lower()},
                }
            )
            hits += 1
        if i % 400 == 0:
            progress_cb(min(0.99, (i + 1) / max(len(rows), 1)), f"{hits} media", None)
    progress_cb(1.0, f"{hits} media files", 0)
    return {"hits": hits}
