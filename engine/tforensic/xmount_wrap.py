"""xmount integration — mount forensic disk images via the system xmount tool.

Supports the same input/output/morph options as xmount v1.x, plus
sleuthkit helpers (mmls / fls) for partition and filesystem browsing.
Evidence files are never modified; virtual-write uses an explicit cache file.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from tforensic.workspace import default_sessions_root, hash_file

INPUT_TYPES = ("aaff", "aff", "aff3", "raw", "dd", "vdi", "qcow", "qcow2", "qemu", "ewf", "aewf")
OUTPUT_TYPES = ("raw", "dmg", "vdi", "vhd", "vmdk", "vmdks")
MORPH_TYPES = ("combine", "unallocated", "raid0")

MOUNT_STATE_NAME = "xmount.json"


def state_path_for(mount_dir: Path) -> Path:
    """State file lives next to the FUSE mount, not inside it."""
    return Path(str(mount_dir) + ".state.json")


class XMountError(Exception):
    pass


def which_xmount() -> Optional[str]:
    return shutil.which("xmount")


def which_tool(name: str) -> Optional[str]:
    return shutil.which(name)


def probe() -> dict:
    """Return installed xmount / sleuthkit capabilities."""
    xm = which_xmount()
    info = {
        "xmount": xm is not None,
        "xmount_path": xm,
        "version": None,
        "inputs": list(INPUT_TYPES),
        "outputs": list(OUTPUT_TYPES),
        "morphs": list(MORPH_TYPES),
        "mmls": which_tool("mmls") is not None,
        "fls": which_tool("fls") is not None,
        "ewfmount": which_tool("ewfmount") is not None,
    }
    if xm:
        try:
            out = subprocess.check_output([xm], stderr=subprocess.STDOUT, text=True, timeout=5)
        except subprocess.CalledProcessError as e:
            out = e.output or ""
        except Exception:
            out = ""
        m = re.search(r"xmount v([\d.]+)", out)
        if m:
            info["version"] = m.group(1)
        # Prefer live library list from --info when possible
        try:
            info_out = subprocess.check_output(
                [xm, "--info"], stderr=subprocess.STDOUT, text=True, timeout=5
            )
        except subprocess.CalledProcessError as e:
            info_out = e.output or ""
        except Exception:
            info_out = ""
        inputs = re.findall(r'supporting "([^"]+)"(?:, "([^"]+)")?(?:, "([^"]+)")?', info_out)
        if inputs:
            flat = []
            for tup in inputs:
                for x in tup:
                    if x:
                        flat.append(x)
            # Keep only known input tokens from first library block lines containing input_
            in_libs = []
            for line in info_out.splitlines():
                if "libxmount_input_" in line and "supporting" in line:
                    in_libs.extend(re.findall(r'"([^"]+)"', line))
            if in_libs:
                info["inputs"] = in_libs
            morphs = []
            for line in info_out.splitlines():
                if "libxmount_morphing_" in line and "supporting" in line:
                    morphs.extend(re.findall(r'"([^"]+)"', line))
            if morphs:
                info["morphs"] = morphs
    return info


def guess_input_type(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    mapping = {
        "e01": "ewf",
        "ex01": "ewf",
        "ewf": "ewf",
        "s01": "ewf",
        "aff": "aff",
        "afd": "aff",
        "afm": "aff",
        "aaff": "aaff",
        "raw": "raw",
        "dd": "dd",
        "img": "raw",
        "bin": "raw",
        "vdi": "vdi",
        "qcow": "qcow",
        "qcow2": "qcow2",
        "vmdk": "raw",  # xmount may not take vmdk as input; treat as raw if dd-like
        "001": "raw",
    }
    return mapping.get(ext, "raw")


@dataclass
class MountRecord:
    id: str
    image_path: str
    image_sha256: str
    input_type: str
    output_type: str
    morph: str
    mount_dir: str
    cache_file: Optional[str]
    offset: int
    sizelimit: Optional[int]
    virtual_device: Optional[str]
    created_at: float = field(default_factory=time.time)
    pid: Optional[int] = None

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "MountRecord":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def _find_virtual_device(mount_dir: Path, output_type: str) -> Optional[str]:
    """Locate the emulated image file xmount created under mount_dir."""
    if not mount_dir.is_dir():
        return None
    prefer = {
        "raw": (".dd", ".raw", ".img"),
        "vdi": (".vdi",),
        "vhd": (".vhd",),
        "vmdk": (".vmdk",),
        "vmdks": (".vmdk",),
        "dmg": (".dmg",),
    }.get(output_type, ())
    files = [p for p in mount_dir.iterdir() if p.is_file()]
    for p in files:
        if p.suffix.lower() in prefer:
            return str(p)
    # fallback: largest file
    if files:
        return str(max(files, key=lambda p: p.stat().st_size))
    # sometimes xmount exposes only dirs first — wait briefly
    return None


def mount_image(
    image: str | Path,
    *,
    input_type: Optional[str] = None,
    output_type: str = "raw",
    morph: str = "combine",
    cache: Optional[str] = None,
    owcache: bool = False,
    offset: int = 0,
    sizelimit: Optional[int] = None,
    mount_dir: Optional[str | Path] = None,
    extra_in: Optional[list[tuple[str, str]]] = None,
) -> MountRecord:
    """Mount a forensic image with xmount into a session temp directory."""
    xm = which_xmount()
    if not xm:
        raise XMountError("xmount not found on PATH — install xmount")

    image = Path(image).resolve()
    if not image.is_file():
        raise FileNotFoundError(f"image not found: {image}")

    itype = (input_type or guess_input_type(str(image))).lower()
    otype = output_type.lower()
    mtype = morph.lower()
    if itype not in INPUT_TYPES and itype not in probe().get("inputs", []):
        # still allow — xmount will reject if unknown
        pass
    if otype not in OUTPUT_TYPES:
        raise XMountError(f"unsupported output type: {otype}")
    if mtype not in MORPH_TYPES:
        raise XMountError(f"unsupported morph: {mtype}")

    root = default_sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    mid = f"xm{int(time.time()) % 10_000_000:07d}"
    if mount_dir:
        mdir = Path(mount_dir)
        mdir.mkdir(parents=True, exist_ok=True)
    else:
        mdir = root / f"xmount-{mid}"
        mdir.mkdir(parents=True, exist_ok=True)

    cmd = [xm, "--in", itype, str(image)]
    if extra_in:
        for it, ip in extra_in:
            cmd += ["--in", it, str(Path(ip).resolve())]
    if mtype and mtype != "combine":
        cmd += ["--morph", mtype]
    if offset:
        cmd += ["--offset", str(offset)]
    if sizelimit is not None:
        cmd += ["--sizelimit", str(sizelimit)]
    if cache:
        cpath = Path(cache).resolve()
        cpath.parent.mkdir(parents=True, exist_ok=True)
        flag = "--owcache" if owcache else "--cache"
        cmd += [flag, str(cpath)]
    cmd += ["--out", otype, str(mdir)]

    # xmount stays in foreground unless we background it
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    # Wait until virtual device appears.
    # Note: some xmount builds fork/daemonize so the parent may exit 0 quickly.
    virtual = None
    err = ""
    for _ in range(80):
        virtual = _find_virtual_device(mdir, otype)
        if virtual:
            break
        rc = proc.poll()
        if rc is not None and rc != 0:
            try:
                err = proc.stderr.read() if proc.stderr else ""
            except Exception:
                err = ""
            raise XMountError(
                f"xmount exited early (code {rc}): {(err or '').strip()}"
            )
        # parent exited 0 — keep waiting briefly for FUSE files to appear
        time.sleep(0.1)
    if not virtual:
        try:
            if proc.poll() is None:
                os.killpg(proc.pid, 15)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            if proc.stderr:
                err = proc.stderr.read()
        except Exception:
            pass
        # leftover empty dir cleanup attempt
        raise XMountError(
            f"xmount started but no virtual device in {mdir}: {(err or '').strip()}"
        )

    try:
        if proc.stderr:
            proc.stderr.close()
    except Exception:
        pass

    rec = MountRecord(
        id=mid,
        image_path=str(image),
        image_sha256=hash_file(image),
        input_type=itype,
        output_type=otype,
        morph=mtype,
        mount_dir=str(mdir),
        cache_file=str(Path(cache).resolve()) if cache else None,
        offset=offset,
        sizelimit=sizelimit,
        virtual_device=virtual,
        pid=proc.pid if proc.poll() is None else None,
    )
    rec.save(state_path_for(mdir))
    return rec


def umount(mount_dir: str | Path, timeout: float = 10.0) -> None:
    mdir = Path(mount_dir)
    state_path = state_path_for(mdir)
    rec = MountRecord.load(state_path) if state_path.is_file() else None

    # fusermount / umount
    fusermount = which_tool("fusermount") or which_tool("fusermount3")
    cmds = []
    if fusermount:
        cmds.append([fusermount, "-u", str(mdir)])
        cmds.append([fusermount, "-uz", str(mdir)])
    cmds.append(["umount", str(mdir)])

    last_err = ""
    for cmd in cmds:
        try:
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
            break
        except Exception as e:
            last_err = str(e)
    else:
        # try killing xmount pid
        if rec and rec.pid:
            try:
                os.kill(rec.pid, 15)
                time.sleep(0.5)
            except ProcessLookupError:
                pass
        if fusermount:
            try:
                subprocess.check_call(
                    [fusermount, "-uz", str(mdir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                )
            except Exception as e:
                raise XMountError(f"umount failed: {last_err or e}") from e

    # cleanup state file if empty dir remnants
    if state_path.is_file():
        try:
            state_path.unlink()
        except OSError:
            pass


def list_active_mounts(root: Optional[Path] = None) -> list[MountRecord]:
    root = root or default_sessions_root()
    if not root.is_dir():
        return []
    out = []
    for p in root.glob("xmount-*.state.json"):
        try:
            out.append(MountRecord.load(p))
        except Exception:
            continue
    # also accept legacy/custom dirs referenced by any *.state.json
    for p in root.glob("*.state.json"):
        if p.name.startswith("xmount-"):
            continue
        try:
            rec = MountRecord.load(p)
            if rec not in out:
                out.append(rec)
        except Exception:
            continue
    return out


def find_mount(mount_id: Optional[str] = None) -> MountRecord:
    mounts = list_active_mounts()
    if not mounts:
        raise FileNotFoundError("no active xmount sessions")
    if mount_id:
        for m in mounts:
            if m.id == mount_id or m.mount_dir.endswith(mount_id):
                return m
        raise FileNotFoundError(f"mount not found: {mount_id}")
    return sorted(mounts, key=lambda m: m.created_at, reverse=True)[0]


def mmls_partitions(image_or_device: str) -> list[dict]:
    """Parse `mmls` partition table from a raw/E01-compatible path."""
    mmls = which_tool("mmls")
    if not mmls:
        raise XMountError("mmls (sleuthkit) not found on PATH")
    try:
        out = subprocess.check_output(
            [mmls, "-B", image_or_device],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        # retry without -B
        try:
            out = subprocess.check_output(
                [mmls, image_or_device],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as e2:
            raise XMountError((e2.output or str(e2)).strip()) from e2

    parts = []
    # Typical: "002:  0000002048   0002050047   0002048000   Win95 FAT32 (0x0B)"
    for line in out.splitlines():
        m = re.match(
            r"^\s*(\d\d\d):\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)$",
            line,
        )
        if not m:
            continue
        slot, start, end, length, desc = m.groups()
        parts.append({
            "slot": slot,
            "start": int(start),
            "end": int(end),
            "length": int(length),
            "desc": desc.strip(),
            "byte_offset": int(start) * 512,
        })
    return parts


def fls_list(image_or_device: str, *, offset_sectors: int = 0, inode: Optional[str] = None,
             recursive: bool = False, limit: int = 2000) -> list[dict]:
    """List filesystem entries with sleuthkit `fls`."""
    fls = which_tool("fls")
    if not fls:
        raise XMountError("fls (sleuthkit) not found on PATH")
    cmd = [fls, "-p"]
    if recursive:
        cmd.append("-r")
    if offset_sectors:
        cmd += ["-o", str(offset_sectors)]
    cmd.append(image_or_device)
    if inode:
        cmd.append(str(inode))
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=120)
    except subprocess.CalledProcessError as e:
        raise XMountError((e.output or str(e)).strip()) from e

    entries = []
    # d/d 123: path  or  r/r 456: file
    for line in out.splitlines():
        m = re.match(r"^([a-zA-Z-+]+)\s+(\*?)\s*(\d+)(?:-(\d+)-(\d+))?:\s+(.*)$", line)
        if not m:
            m = re.match(r"^([a-zA-Z/+]+)\s+(\d+):\s+(.*)$", line)
            if not m:
                continue
            ftype, inum, name = m.group(1), m.group(2), m.group(3)
            deleted = False
        else:
            ftype, star, inum, _a, _b, name = m.groups()
            deleted = star == "*"
        is_dir = ftype.startswith("d") or "/d" in ftype
        entries.append({
            "type": ftype,
            "inode": inum,
            "name": name,
            "is_dir": is_dir,
            "deleted": deleted,
        })
        if len(entries) >= limit:
            break
    return entries


def icat_extract(image_or_device: str, inode: str, dest: str | Path,
                 *, offset_sectors: int = 0) -> str:
    """Extract a file by inode with `icat` into dest path."""
    icat = which_tool("icat")
    if not icat:
        raise XMountError("icat (sleuthkit) not found on PATH")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [icat]
    if offset_sectors:
        cmd += ["-o", str(offset_sectors)]
    cmd += [image_or_device, str(inode)]
    with open(dest, "wb") as out:
        try:
            subprocess.check_call(cmd, stdout=out, stderr=subprocess.PIPE, timeout=300)
        except subprocess.CalledProcessError as e:
            raise XMountError(f"icat failed: {e}") from e
    return str(dest.resolve())
