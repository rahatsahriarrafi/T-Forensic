"""Rough open/mount time estimates so the UI can show ETA without panicking users.

These are heuristics for local SSD/HDD — not promises. Network paths and busy
disks will be slower; estimates are intentionally a bit generous.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


# Effective throughput (bytes/sec) for local disk — conservative.
_RATES = {
    "ad1_parse": 80 * 1024 * 1024,  # AD1 index/parse
    "ewf_mount": 120 * 1024 * 1024,  # xmount ewf startup work (amortized)
    "raw_mount": 200 * 1024 * 1024,  # mostly fixed; size soft factor
    "ova_extract": 40 * 1024 * 1024,  # tar extract
    "qemu_convert": 35 * 1024 * 1024,  # qemu-img convert to raw
    "vdi_qcow_mount": 80 * 1024 * 1024,
}

_FIXED = {
    "ad1": 3,
    "ewf": 8,
    "raw": 4,
    "ova_extract": 5,
    "qemu_convert": 10,
    "xmount": 6,
    "vdi": 6,
}


def format_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"~{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"~{m}m {sec:02d}s" if sec else f"~{m}m"
    h, m = divmod(m, 60)
    return f"~{h}h {m:02d}m"


def format_size(n: int) -> str:
    n = max(0, int(n))
    for unit, div in (("T", 1024**4), ("G", 1024**3), ("M", 1024**2), ("K", 1024)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n}B"


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _stage(name: str, seconds: float, detail: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "seconds": round(seconds, 1),
        "human": format_duration(seconds),
        "detail": detail,
    }


def classify_for_estimate(path: str | Path) -> str:
    if Path(path).is_dir():
        return "folder"
    ext = Path(path).suffix.lower()
    if ext == ".ad1":
        return "ad1"
    if ext == ".ova":
        return "ova"
    if ext in (
        ".pcap", ".pcapng", ".cap", ".dmp", ".pkt", ".snoop", ".erf",
        ".ntar", ".pklg", ".ipfix", ".bfr", ".rf5", ".k12", ".vwr",
    ):
        return "pcap"
    if ext in (".e01", ".ex01", ".ewf", ".s01"):
        return "ewf"
    if ext in (".vmdk", ".vhd", ".vhdx"):
        return "vmdk"
    if ext in (".vdi",):
        return "vdi"
    if ext in (".qcow", ".qcow2"):
        return "qcow"
    if ext in (".dd", ".raw", ".img", ".bin", ".001"):
        return "raw"
    if ext in (".aff", ".aaff", ".afd"):
        return "aff"
    return "unknown"


def estimate_open(path: str | Path, *, input_type: Optional[str] = None) -> dict[str, Any]:
    """Estimate time to open/mount evidence for analysis."""
    path = Path(path)
    size = _size(path) if path.is_file() else 0
    kind = classify_for_estimate(path)
    if input_type:
        it = input_type.lower()
        if it in ("ewf", "aewf"):
            kind = "ewf"
        elif it in ("raw", "dd"):
            kind = "raw"
        elif it in ("vdi",):
            kind = "vdi"
        elif it in ("qcow", "qcow2", "qemu"):
            kind = "qcow"

    stages: list[dict[str, Any]] = []

    if kind == "folder":
        stages.append(_stage("Index folder", 5, "Walk directory tree (read-only)"))
    elif kind == "ad1":
        sec = _FIXED["ad1"] + size / _RATES["ad1_parse"]
        stages.append(_stage("Parse AD1", sec, "Build session tree"))
    elif kind == "pcap":
        sec = 2 + min(30, size / (80 * 1024 * 1024))
        stages.append(_stage("Open capture", sec, "tshark / PCAP index"))
    elif kind == "ova":
        ex = _FIXED["ova_extract"] + size / _RATES["ova_extract"]
        stages.append(_stage("Extract OVA", ex, "Unpack tar appliance"))
        disk_guess = max(size * 0.7, size * 0.5)
        cv = _FIXED["qemu_convert"] + disk_guess / _RATES["qemu_convert"]
        stages.append(_stage("Convert disk", cv, "qemu-img → raw (if needed)"))
        mt = _FIXED["xmount"] + disk_guess / _RATES["raw_mount"] * 0.05
        stages.append(_stage("Mount", mt, "xmount FUSE"))
    elif kind == "vmdk":
        cv = _FIXED["qemu_convert"] + size / _RATES["qemu_convert"]
        stages.append(_stage("Convert disk", cv, "qemu-img → raw"))
        mt = _FIXED["xmount"] + 3
        stages.append(_stage("Mount", mt, "xmount FUSE"))
    elif kind == "ewf":
        sec = _FIXED["ewf"] + size / _RATES["ewf_mount"] * 0.15
        stages.append(_stage("Mount EWF", sec, "xmount --in ewf"))
    elif kind in ("vdi", "qcow"):
        sec = _FIXED["vdi"] + size / _RATES["vdi_qcow_mount"] * 0.1
        stages.append(_stage("Mount virtual disk", sec, f"xmount --in {kind}"))
    elif kind == "aff":
        sec = _FIXED["ewf"] + size / _RATES["ewf_mount"] * 0.2
        stages.append(_stage("Mount AFF", sec, "xmount --in aff"))
    elif kind == "raw":
        sec = _FIXED["raw"] + min(20, size / _RATES["raw_mount"] * 0.02)
        stages.append(_stage("Mount raw", sec, "xmount --in raw"))
    else:
        sec = 15 + size / (50 * 1024 * 1024)
        stages.append(_stage("Open evidence", sec, "Unknown type — rough guess"))

    total = sum(s["seconds"] for s in stages)
    total = max(2.0, min(total, 6 * 3600))
    low = max(1.0, total * 0.6)
    high = min(6 * 3600, total * 1.6)

    return {
        "path": str(path),
        "exists": path.exists(),
        "size": size,
        "size_human": format_size(size),
        "kind": kind,
        "seconds": round(total, 1),
        "seconds_low": round(low, 1),
        "seconds_high": round(high, 1),
        "human": format_duration(total),
        "human_range": f"{format_duration(low)} – {format_duration(high)}",
        "stages": stages,
        "note": "Estimate only (local disk). Network / busy disks / huge OVAs can take longer.",
    }


def print_eta_lines(est: dict[str, Any]) -> None:
    """Machine-friendly lines for the desktop shell to parse."""
    print(
        f"ETA: {est['human']} (range {est['human_range']}) "
        f"size={est['size_human']} kind={est['kind']}",
        flush=True,
    )
    print(f"ETA_SECONDS: {est['seconds']}", flush=True)
    for s in est.get("stages") or []:
        print(f"ETA_STAGE: {s['name']}|{s['seconds']}|{s.get('detail') or ''}", flush=True)


def print_progress(fraction: float, message: str = "") -> None:
    """Emit machine-readable load progress (0.0–1.0) for UI progress bars."""
    p = max(0.0, min(1.0, float(fraction)))
    msg = (message or "").replace("\n", " ").strip()
    print(f"PROGRESS: {p:.4f}" + (f" | {msg}" if msg else ""), flush=True)
    pct = int(round(p * 100))
    if msg:
        print(f"  loaded: {pct}% — {msg}", flush=True)
    else:
        print(f"  loaded: {pct}%", flush=True)
