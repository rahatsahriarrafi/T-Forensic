"""Unified evidence opener — AD1 logical images or xmount disk images."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from tforensic.ad1.parser import AD1, AD1Error
from tforensic.case import Case, open_case
from tforensic.workspace import SessionMeta, create_session
from tforensic.xmount_wrap import (
    MountRecord,
    guess_input_type,
    mount_image,
    probe,
)

# Extensions treated as disk images (xmount), not AD1
DISK_EXTENSIONS = {
    "e01", "ex01", "ewf", "s01", "l01",
    "raw", "dd", "img", "bin", "001",
    "aff", "afd", "afm", "aaff",
    "vdi", "qcow", "qcow2",
    "vmdk", "vhd", "vhdx",
    "ova",
}

# Human-facing catalog for UI / CLI
FORMAT_CATALOG = [
    {
        "group": "AD1 logical",
        "engine": "ad1",
        "extensions": [".ad1"],
        "notes": "AccessData/FTK logical images — tree, preview, export",
    },
    {
        "group": "EWF / Expert Witness",
        "engine": "xmount",
        "extensions": [".E01", ".Ex01", ".ewf", ".s01", ".L01"],
        "notes": "xmount --in ewf (or aewf)",
    },
    {
        "group": "Raw / DD",
        "engine": "xmount",
        "extensions": [".dd", ".raw", ".img", ".bin", ".001"],
        "notes": "xmount --in raw|dd",
    },
    {
        "group": "AFF",
        "engine": "xmount",
        "extensions": [".aff", ".afd", ".afm", ".aaff"],
        "notes": "xmount --in aff|aaff",
    },
    {
        "group": "Virtual disks",
        "engine": "xmount",
        "extensions": [".vdi", ".qcow", ".qcow2", ".vmdk", ".vhd", ".vhdx"],
        "notes": "xmount --in vdi|qcow2; VMDK/VHD converted via qemu-img",
    },
    {
        "group": "OVA appliance",
        "engine": "ova+xmount",
        "extensions": [".ova"],
        "notes": "Extract OVF/VMDK from tar, convert if needed, mount with xmount",
    },
    {
        "group": "Network capture",
        "engine": "tshark/pcap",
        "extensions": [
            ".pcap", ".pcapng", ".cap", ".dmp", ".pkt",
            ".snoop", ".erf", ".ntar", ".pklg", ".ipfix",
        ],
        "notes": "Network tab — all common packet captures via tshark (Wireshark). Also .bfr .rf5 .k12 .vwr …",
    },
    {
        "group": "Folder / phone extraction",
        "engine": "folder (read-only)",
        "extensions": [],
        "notes": "Open a directory: Android/iOS file-system dumps, logical copies, unpacked archives",
    },
]


def accepted_formats() -> dict:
    """List of evidence formats Team Forensic Framework can open for analysis."""
    from tforensic.xmount_wrap import probe
    from tforensic.pcap_analysis import packet_extensions, tshark_bin

    p = probe()
    return {
        "catalog": FORMAT_CATALOG,
        "extensions_flat": sorted(
            {e.lower() for g in FORMAT_CATALOG for e in g["extensions"]}
            | {f".{x}" for x in packet_extensions()}
        ),
        "packet_extensions": packet_extensions(),
        "tshark": bool(tshark_bin()),
        "xmount": {
            "available": bool(p.get("xmount")),
            "inputs": p.get("inputs") or [],
            "outputs": p.get("outputs") or [],
            "morphs": p.get("morphs") or [],
        },
        "sleuthkit": {
            "mmls": bool(p.get("mmls")),
            "fls": bool(p.get("fls")),
        },
    }


def is_ad1_file(path: str | Path) -> bool:
    path = Path(path)
    if path.suffix.lower() == ".ad1":
        return True
    try:
        with open(path, "rb") as f:
            sig = f.read(16)
        return sig.startswith(b"ADSEGMENTEDFILE")
    except OSError:
        return False


def is_disk_image(path: str | Path) -> bool:
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    if ext in DISK_EXTENSIONS:
        return True
    # split E01 series: .E01 already covered; also .e02 etc. treated as ewf segments
    if len(ext) == 3 and ext[0] in "eEsS" and ext[1:].isdigit():
        return True
    return False


def classify_evidence(path: str | Path) -> str:
    """Return 'folder' | 'ad1' | 'ova' | 'disk' | 'pcap' | 'unknown'."""
    path = Path(path)
    if path.is_dir():
        return "folder"
    if not path.is_file():
        raise FileNotFoundError(f"not found: {path}")
    from tforensic.pcap_analysis import is_pcap_file

    if is_pcap_file(path):
        return "pcap"
    if is_ad1_file(path):
        return "ad1"
    if path.suffix.lower() == ".ova":
        from tforensic.ova import is_ova_file

        if is_ova_file(path):
            return "ova"
        raise RuntimeError(f"file has .ova extension but is not a valid tar/OVA: {path}")
    if is_disk_image(path):
        return "disk"
    # sniff: EWF often starts with EVF\t or similar; raw has no signature
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"EVF\x09") or head.startswith(b"EVF2"):
        return "disk"
    if head.startswith(b"ADSEGMENTEDFILE"):
        return "ad1"
    # Only treat as disk when extension/signature says so — not every file when xmount exists
    return "unknown"


class DiskCase:
    """Session for an xmount-backed disk image (no AD1 tree)."""

    def __init__(self, meta: SessionMeta, mount: MountRecord, ova: Optional[dict] = None):
        self.meta = meta
        self.mount = mount
        self.ova = ova
        self.kind = "disk"

    def info(self) -> dict:
        out = {
            "kind": "disk",
            "session_id": self.meta.id,
            "image": Path(self.meta.image_path).name,
            "image_path": self.meta.image_path,
            "image_sha256": self.meta.image_sha256,
            "image_size": self.meta.image_size,
            "temp_dir": self.meta.temp_dir,
            "export_dir": self.meta.export_dir,
            "root": self.mount.virtual_device or "",
            "dirs": 0,
            "files": 0,
            "xmount": {
                "id": self.mount.id,
                "input_type": self.mount.input_type,
                "output_type": self.mount.output_type,
                "morph": self.mount.morph,
                "mount_dir": self.mount.mount_dir,
                "virtual_device": self.mount.virtual_device,
                "cache_file": self.mount.cache_file,
            },
        }
        if self.ova:
            out["kind"] = "ova"
            out["ova"] = {
                "primary_disk": self.ova.get("primary_disk"),
                "mount_path": self.ova.get("mount_path"),
                "disks": (self.ova.get("ova_meta") or {}).get("disks"),
            }
        return out

    def close(self) -> None:
        try:
            from tforensic.xmount_wrap import umount

            umount(self.mount.mount_dir)
        except Exception:
            pass


def open_disk(
    image_path: str,
    *,
    input_type: Optional[str] = None,
    output_type: str = "raw",
    morph: str = "combine",
    cache: Optional[str] = None,
    ova_info: Optional[dict] = None,
    mount_source: Optional[str] = None,
) -> DiskCase:
    meta = create_session(image_path)
    source = mount_source or image_path
    itype = input_type or guess_input_type(source)
    mount_dir = str(Path(meta.temp_dir) / "xmount")
    mount = mount_image(
        source,
        input_type=itype,
        output_type=output_type,
        morph=morph,
        cache=cache,
        mount_dir=mount_dir,
    )
    note = Path(meta.temp_dir) / "disk.json"
    import json
    from dataclasses import asdict

    payload = {"kind": "ova" if ova_info else "disk", "mount": asdict(mount)}
    if ova_info:
        payload["ova"] = ova_info
    note.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return DiskCase(meta, mount, ova=ova_info)


def open_ova(
    image_path: str,
    *,
    output_type: str = "raw",
    morph: str = "combine",
    cache: Optional[str] = None,
) -> DiskCase:
    from tforensic.ova import open_ova_to_mountable

    if not probe().get("xmount"):
        raise RuntimeError("OVA requires xmount on PATH (apt install xmount)")
    # session first so we have temp space for extract/convert
    meta = create_session(image_path)
    prepared = open_ova_to_mountable(image_path, meta.temp_dir)
    mount_dir = str(Path(meta.temp_dir) / "xmount")
    mount = mount_image(
        prepared["mount_path"],
        input_type=prepared["input_type"],
        output_type=output_type,
        morph=morph,
        cache=cache,
        mount_dir=mount_dir,
    )
    import json
    from dataclasses import asdict

    note = Path(meta.temp_dir) / "disk.json"
    note.write_text(
        json.dumps({"kind": "ova", "mount": asdict(mount), "ova": prepared}, indent=2),
        encoding="utf-8",
    )
    return DiskCase(meta, mount, ova=prepared)


class PcapCase:
    """Session for a network packet capture (PCAP/PCAPNG/…)."""

    def __init__(self, meta: SessionMeta, pcap_path: str):
        self.meta = meta
        self.pcap_path = pcap_path
        self.kind = "pcap"

    def info(self) -> dict:
        from tforensic import pcap_analysis as pa
        sess = pa.active()
        return {
            "kind": "pcap",
            "session_id": self.meta.id,
            "image": Path(self.pcap_path).name,
            "image_path": self.pcap_path,
            "pcap_path": self.pcap_path,
            "image_sha256": self.meta.image_sha256,
            "image_size": self.meta.image_size,
            "temp_dir": self.meta.temp_dir,
            "export_dir": self.meta.export_dir,
            "root": self.pcap_path,
            "dirs": 0,
            "files": 0,
            "pcap": sess.as_dict() if sess else {"path": self.pcap_path},
            "tshark": bool(pa.tshark_bin()),
        }

    def close(self) -> None:
        try:
            from tforensic import pcap_analysis as pa
            pa.close()
        except Exception:
            pass


def open_pcap_case(image_path: str) -> PcapCase:
    from tforensic import pcap_analysis as pa

    meta = create_session(image_path)
    pa.open_pcap(image_path)
    return PcapCase(meta, str(Path(image_path).expanduser().resolve()))


def open_evidence(
    image_path: str,
    *,
    input_type: Optional[str] = None,
    output_type: str = "raw",
    morph: str = "combine",
    cache: Optional[str] = None,
) -> Union[Case, DiskCase, "PcapCase"]:
    kind = classify_evidence(image_path)
    if kind == "pcap":
        return open_pcap_case(image_path)
    if kind == "folder":
        return open_case(image_path)
    if kind == "ad1":
        case = open_case(image_path)
        case.kind = "ad1"  # type: ignore[attr-defined]
        return case
    if kind == "ova":
        return open_ova(
            image_path,
            output_type=output_type,
            morph=morph,
            cache=cache,
        )
    if kind == "disk":
        if not probe().get("xmount"):
            raise RuntimeError(
                "disk image requires xmount on PATH (apt install xmount)"
            )
        # standalone VMDK/VHD also need convert
        ext = Path(image_path).suffix.lower()
        if ext in (".vmdk", ".vhd", ".vhdx"):
            from tforensic.ova import prepare_disk_for_xmount

            meta = create_session(image_path)
            mount_path, itype = prepare_disk_for_xmount(
                image_path, Path(meta.temp_dir) / "convert"
            )
            mount_dir = str(Path(meta.temp_dir) / "xmount")
            mount = mount_image(
                mount_path,
                input_type=input_type or itype,
                output_type=output_type,
                morph=morph,
                cache=cache,
                mount_dir=mount_dir,
            )
            import json
            from dataclasses import asdict

            (Path(meta.temp_dir) / "disk.json").write_text(
                json.dumps({"kind": "disk", "mount": asdict(mount)}, indent=2),
                encoding="utf-8",
            )
            return DiskCase(meta, mount)
        return open_disk(
            image_path,
            input_type=input_type,
            output_type=output_type,
            morph=morph,
            cache=cache,
        )
    raise RuntimeError(
        f"unsupported evidence format: {image_path} "
        f"(expected AD1, OVA, xmount disk image, network PCAP/PCAPNG, or a folder)"
    )
