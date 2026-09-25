"""Ingest analysis modules (Autopsy-style)."""
from tforensic.ingest.modules import (
    artifacts,
    web,
    registry,
    lnk_prefetch,
    email_mod,
    exif_media,
    carve,
    keyword,
)

__all__ = [
    "artifacts",
    "web",
    "registry",
    "lnk_prefetch",
    "email_mod",
    "exif_media",
    "carve",
    "keyword",
]
