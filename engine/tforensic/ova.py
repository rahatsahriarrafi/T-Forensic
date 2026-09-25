"""OVA (Open Virtualization Appliance) support.

OVA is a tar archive of OVF + one or more virtual disks (usually VMDK).
xmount cannot open .ova directly — we extract, pick the primary disk,
convert to raw via qemu-img when needed, then mount with xmount.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Optional

DISK_MEMBERS = (
    ".vmdk",
    ".vdi",
    ".qcow2",
    ".qcow",
    ".img",
    ".raw",
    ".vhd",
    ".vhdx",
)


class OVAError(Exception):
    pass


def is_ova_file(path: str | Path) -> bool:
    path = Path(path)
    if path.suffix.lower() != ".ova":
        return False
    try:
        return tarfile.is_tarfile(path)
    except OSError:
        return False


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest) + "/") and target != dest:
            raise OVAError(f"refusing unsafe path in OVA: {member.name}")
    tar.extractall(dest, filter="data")


def extract_ova(ova_path: str | Path, dest_dir: str | Path) -> dict:
    """Extract OVA into dest_dir. Returns metadata + chosen disk path."""
    ova_path = Path(ova_path).resolve()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not tarfile.is_tarfile(ova_path):
        raise OVAError(f"not a valid OVA/tar: {ova_path}")

    with tarfile.open(ova_path, "r:*") as tar:
        members = [m.name for m in tar.getmembers() if m.isfile()]
        _safe_extract(tar, dest_dir)

    disks = []
    for p in dest_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DISK_MEMBERS:
            disks.append(p)

    if not disks:
        raise OVAError(
            "no virtual disk found inside OVA "
            f"(looked for {', '.join(DISK_MEMBERS)}); members={members[:20]}"
        )

    # Prefer largest disk (main volume); skip tiny descriptor-like vmdks when possible
    disks.sort(key=lambda p: p.stat().st_size, reverse=True)
    primary = disks[0]

    ovf = next((p for p in dest_dir.rglob("*.ovf")), None)
    mf = next((p for p in dest_dir.rglob("*.mf")), None)

    meta = {
        "ova": str(ova_path),
        "extract_dir": str(dest_dir),
        "members": members,
        "disks": [str(d) for d in disks],
        "primary_disk": str(primary),
        "ovf": str(ovf) if ovf else None,
        "manifest": str(mf) if mf else None,
    }
    (dest_dir / "ova_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def prepare_disk_for_xmount(disk_path: str | Path, work_dir: str | Path) -> tuple[str, str]:
    """Return (path, xmount_input_type), converting via qemu-img when needed.

    xmount supports: raw/dd, vdi, qcow/qcow2 — not VMDK/VHD directly.
    """
    disk_path = Path(disk_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    ext = disk_path.suffix.lower()

    if ext in (".vdi",):
        return str(disk_path), "vdi"
    if ext in (".qcow", ".qcow2"):
        return str(disk_path), "qcow2" if ext == ".qcow2" else "qcow"
    if ext in (".raw", ".img", ".dd"):
        return str(disk_path), "raw"

    # VMDK / VHD / unknown → convert to raw with qemu-img
    qemu = shutil.which("qemu-img")
    if not qemu:
        raise OVAError(
            f"cannot mount {ext} without qemu-img (apt install qemu-utils)"
        )
    out = work_dir / (disk_path.stem + ".raw")
    if not out.is_file() or out.stat().st_size == 0:
        try:
            subprocess.check_call(
                [qemu, "convert", "-O", "raw", str(disk_path), str(out)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=3600,
            )
        except subprocess.CalledProcessError as e:
            err = ""
            if e.stderr:
                err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else str(e.stderr)
            raise OVAError(f"qemu-img convert failed: {err or e}") from e
    return str(out), "raw"


def open_ova_to_mountable(
    ova_path: str | Path,
    session_temp: str | Path,
) -> dict:
    """Extract OVA and prepare a disk path suitable for xmount.

    Returns dict with keys: primary_disk, mount_path, input_type, ova_meta
    """
    extract_dir = Path(session_temp) / "ova_extract"
    meta = extract_ova(ova_path, extract_dir)
    convert_dir = Path(session_temp) / "ova_convert"
    mount_path, itype = prepare_disk_for_xmount(meta["primary_disk"], convert_dir)
    return {
        "ova_meta": meta,
        "primary_disk": meta["primary_disk"],
        "mount_path": mount_path,
        "input_type": itype,
    }
