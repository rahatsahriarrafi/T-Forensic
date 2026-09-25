"""Lab workspace — writable forensic sandbox (evidence stays immutable).

Lab mode enables:
  - case/lab/ working directory for reconstructions, notes dumps, carved copies
  - optional xmount --cache virtual-write overlay (writes hit cache file only)
  - working copies of selected exports for tooling that needs a mutable file
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from tforensic.casedb import CaseDB, resolve_case
from tforensic.workspace import hash_file


@dataclass
class LabStatus:
    enabled: bool
    path: str
    virtual_write: bool
    cache_file: Optional[str]
    working_copies: int
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


class LabWorkspace:
    def __init__(self, case: CaseDB):
        self.case = case
        self.root = Path(case.info().path)
        self.lab = self.root / "lab"
        self.meta_path = self.lab / "lab.json"

    def enable(self, *, virtual_write: bool = False, cache_name: str = "virtual-write.cache") -> LabStatus:
        self.lab.mkdir(parents=True, exist_ok=True)
        (self.lab / "working").mkdir(exist_ok=True)
        (self.lab / "carve").mkdir(exist_ok=True)
        (self.lab / "scripts").mkdir(exist_ok=True)
        (self.lab / "out").mkdir(exist_ok=True)
        cache = None
        if virtual_write:
            cache = str((self.lab / cache_name).resolve())
        meta = {
            "enabled": True,
            "enabled_at": time.time(),
            "virtual_write": virtual_write,
            "cache_file": cache,
            "policy": "Original evidence is never modified. Writes go to lab/ or xmount cache only.",
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.case.set_meta("lab_enabled", "1")
        self.case.set_meta("lab_virtual_write", "1" if virtual_write else "0")
        if cache:
            self.case.set_meta("lab_cache", cache)
        self.case.log_custody(
            "lab_enable",
            f"lab={self.lab} virtual_write={virtual_write} cache={cache or '-'}",
        )
        return self.status()

    def status(self) -> LabStatus:
        enabled = self.lab.is_dir() and self.meta_path.is_file()
        meta = {}
        if self.meta_path.is_file():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        copies = 0
        working = self.lab / "working"
        if working.is_dir():
            copies = sum(1 for _ in working.rglob("*") if _.is_file())
        return LabStatus(
            enabled=bool(enabled or meta.get("enabled")),
            path=str(self.lab),
            virtual_write=bool(meta.get("virtual_write")),
            cache_file=meta.get("cache_file"),
            working_copies=copies,
            note=meta.get("policy")
            or "Evidence images stay immutable; lab/ is the writable sandbox.",
        )

    def make_working_copy(self, src: str | Path, name: Optional[str] = None) -> dict:
        """Copy a file into lab/working for tools that need a mutable path."""
        src = Path(src).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"not found: {src}")
        if not self.lab.is_dir():
            self.enable()
        dest_name = name or src.name
        dest = self.lab / "working" / dest_name
        # avoid clobber
        if dest.exists():
            dest = self.lab / "working" / f"{int(time.time())}_{dest_name}"
        shutil.copy2(src, dest)
        digest = hash_file(dest)
        rec = {
            "source": str(src),
            "working_copy": str(dest),
            "sha256": digest,
            "size": dest.stat().st_size,
            "created_at": time.time(),
        }
        manifest = self.lab / "working" / "copies.jsonl"
        with open(manifest, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self.case.log_custody("lab_working_copy", f"{src} → {dest}")
        return rec

    def virtual_write_mount_args(self) -> dict:
        """Args to pass to xmount mount for lab virtual-write."""
        st = self.status()
        if not st.virtual_write or not st.cache_file:
            return {}
        return {"cache": st.cache_file, "owcache": False}


def enable_lab(case_id: Optional[str] = None, *, virtual_write: bool = False) -> LabStatus:
    case = resolve_case(case_id)
    return LabWorkspace(case).enable(virtual_write=virtual_write)


def lab_status(case_id: Optional[str] = None) -> LabStatus:
    case = resolve_case(case_id)
    return LabWorkspace(case).status()
