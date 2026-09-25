"""Lightweight hashing and artifact locator."""
from __future__ import annotations

import hashlib
import re

ARTIFACT_RULES = [
    ("Chrome/Edge history DB", "browser", r"^history$"),
    ("Chrome/Edge downloads/web data", "browser", r"^web data$"),
    ("IE/Edge WebCache", "browser", r"^webcachev?\d*\.dat$"),
    ("Firefox places DB", "browser", r"^places\.sqlite$"),
    ("Firefox downloads", "browser", r"^downloads\.sqlite$"),
    ("Windows Mail store (HxStore)", "mail", r"^hxstore\.hxd$"),
    ("Windows Mail Unistore DB", "mail", r"^store\.vol$"),
    ("Outlook data file", "mail", r"\.(pst|ost)$"),
    ("Prefetch", "execution", r"\.pf$"),
    ("Windows Registry hive", "registry", r"^(ntuser\.dat|usrclass\.dat|sam|system|software|security)$"),
    ("Jump list (automatic)", "execution", r"\.automaticdestinations-ms$"),
    ("LNK shortcut", "execution", r"\.lnk$"),
    ("PowerShell script", "script", r"\.ps1$"),
    ("Batch/script", "script", r"\.(bat|cmd|vbs|js|hta)$"),
    ("Executable", "executable", r"\.(exe|dll|scr|com|msi)$"),
]
_COMPILED = [(label, cat, re.compile(rx, re.IGNORECASE)) for label, cat, rx in ARTIFACT_RULES]


def hashes(data: bytes) -> dict:
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def is_executable(data: bytes) -> bool:
    return data[:2] == b"MZ" if len(data) >= 2 else False


def classify_artifacts(nodes) -> list:
    hits = []
    for n in nodes:
        if getattr(n, "is_dir", False):
            continue
        for label, cat, rx in _COMPILED:
            if rx.search(n.name):
                hits.append(
                    {
                        "label": label,
                        "category": cat,
                        "path": n.path,
                        "name": n.name,
                        "size": n.size,
                    }
                )
                break
    return hits
