"""Runtime dependency probe — report missing tools with install suggestions."""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class Dep:
    id: str
    name: str
    kind: str  # core | feature | optional
    feature: str
    ok: bool
    check: str  # how we probed
    suggestion: str
    apt: str = ""
    pip: str = ""


def _has_mod(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _bin(name: str) -> bool:
    return bool(shutil.which(name))


def check_dependencies() -> dict[str, Any]:
    """Return full dependency report with missing items + install lines."""
    deps: list[Dep] = [
        Dep(
            id="python3",
            name="Python 3.9+",
            kind="core",
            feature="Engine / CLI / API",
            ok=True,  # if we are running, python works
            check="runtime",
            suggestion="Already running under this interpreter.",
        ),
        Dep(
            id="impacket",
            name="impacket",
            kind="feature",
            feature="SAM / NTLM dump + password crack helper",
            ok=_has_mod("impacket"),
            check="import impacket",
            suggestion="pip install -r requirements.txt   # or: pip install impacket",
            pip="impacket>=0.11.0",
        ),
        Dep(
            id="pyscca",
            name="pyscca (libscca)",
            kind="feature",
            feature="Windows Prefetch viewer",
            ok=_has_mod("pyscca"),
            check="import pyscca",
            suggestion="sudo apt install python3-libscca",
            apt="python3-libscca",
        ),
        Dep(
            id="pyregf",
            name="pyregf (libregf)",
            kind="feature",
            feature="ShellBags / registry hive browse",
            ok=_has_mod("pyregf"),
            check="import pyregf",
            suggestion="sudo apt install python3-libregf python3-libfwsi",
            apt="python3-libregf python3-libfwsi",
        ),
        Dep(
            id="pyfwsi",
            name="pyfwsi (libfwsi)",
            kind="feature",
            feature="ShellBags shell-item names",
            ok=_has_mod("pyfwsi"),
            check="import pyfwsi",
            suggestion="sudo apt install python3-libfwsi",
            apt="python3-libfwsi",
        ),
        Dep(
            id="xmount",
            name="xmount",
            kind="feature",
            feature="Disk / E01 / VDI / OVA mount",
            ok=_bin("xmount"),
            check="which xmount",
            suggestion="sudo apt install xmount",
            apt="xmount",
        ),
        Dep(
            id="sleuthkit",
            name="Sleuth Kit (mmls/fls/icat)",
            kind="feature",
            feature="Partition browse + file extract",
            ok=_bin("mmls") and _bin("fls") and _bin("icat"),
            check="which mmls fls icat",
            suggestion="sudo apt install sleuthkit",
            apt="sleuthkit",
        ),
        Dep(
            id="qemu-img",
            name="qemu-img",
            kind="feature",
            feature="OVA / VMDK / VHD convert",
            ok=_bin("qemu-img"),
            check="which qemu-img",
            suggestion="sudo apt install qemu-utils",
            apt="qemu-utils",
        ),
        Dep(
            id="fusermount",
            name="FUSE (fusermount)",
            kind="feature",
            feature="xmount FUSE mounts",
            ok=_bin("fusermount") or _bin("fusermount3"),
            check="which fusermount",
            suggestion="sudo apt install fuse3   # and enable user_allow_other in /etc/fuse.conf",
            apt="fuse3",
        ),
        Dep(
            id="tshark",
            name="tshark",
            kind="feature",
            feature="Network / PCAP analysis",
            ok=_bin("tshark"),
            check="which tshark",
            suggestion="sudo apt install tshark",
            apt="tshark",
        ),
        Dep(
            id="exiftool",
            name="exiftool",
            kind="feature",
            feature="JPEG/TIFF EXIF (phone make/model)",
            ok=_bin("exiftool"),
            check="which exiftool",
            suggestion="sudo apt install libimage-exiftool-perl",
            apt="libimage-exiftool-perl",
        ),
        Dep(
            id="john",
            name="John the Ripper",
            kind="feature",
            feature="Auto-crack SAM NTLM hashes",
            ok=_bin("john"),
            check="which john",
            suggestion="sudo apt install john",
            apt="john",
        ),
        Dep(
            id="hashcat",
            name="hashcat",
            kind="optional",
            feature="NTLM crack fallback (GPU/CPU)",
            ok=_bin("hashcat"),
            check="which hashcat",
            suggestion="sudo apt install hashcat",
            apt="hashcat",
        ),
        Dep(
            id="samdump2",
            name="samdump2",
            kind="optional",
            feature="SAM dump fallback if impacket fails",
            ok=_bin("samdump2"),
            check="which samdump2",
            suggestion="sudo apt install samdump2",
            apt="samdump2",
        ),
        Dep(
            id="photorec",
            name="photorec",
            kind="optional",
            feature="Deep file carve during ingest",
            ok=_bin("photorec"),
            check="which photorec",
            suggestion="sudo apt install testdisk",
            apt="testdisk",
        ),
    ]

    missing = [d for d in deps if not d.ok]
    missing_core = [d for d in missing if d.kind == "core"]
    missing_feature = [d for d in missing if d.kind == "feature"]
    missing_optional = [d for d in missing if d.kind == "optional"]

    apt_pkgs: list[str] = []
    pip_pkgs: list[str] = []
    for d in missing:
        for p in (d.apt or "").split():
            if p and p not in apt_pkgs:
                apt_pkgs.append(p)
        if d.pip and d.pip not in pip_pkgs:
            pip_pkgs.append(d.pip)

    install_lines: list[str] = []
    if pip_pkgs:
        install_lines.append("pip install -r requirements.txt")
        install_lines.append("pip install " + " ".join(pip_pkgs))
    if apt_pkgs:
        install_lines.append("sudo apt install " + " ".join(apt_pkgs))

    suggestions = [
        {
            "id": d.id,
            "name": d.name,
            "feature": d.feature,
            "kind": d.kind,
            "suggestion": d.suggestion,
            "apt": d.apt,
            "pip": d.pip,
        }
        for d in missing
    ]

    ready = len(missing_core) == 0  # core always ok today; AD1 works without extras
    return {
        "ok": ready,
        "complete": len(missing) == 0,
        "summary": (
            "All recommended tools present."
            if not missing
            else f"{len(missing)} missing — install to unlock full features."
        ),
        "counts": {
            "total": len(deps),
            "ok": sum(1 for d in deps if d.ok),
            "missing": len(missing),
            "missing_feature": len(missing_feature),
            "missing_optional": len(missing_optional),
        },
        "deps": [asdict(d) for d in deps],
        "missing": suggestions,
        "install": {
            "pip": pip_pkgs,
            "apt": apt_pkgs,
            "commands": install_lines,
        },
        "hint": (
            "Run: tforensic deps   ·   or open Formats / status banner in the UI. "
            "Re-check anytime — suggestions stay until packages are installed."
        ),
    }


def format_deps_text(report: Optional[dict[str, Any]] = None) -> str:
    report = report or check_dependencies()
    lines = [
        f"TFF dependencies: {report['counts']['ok']}/{report['counts']['total']} OK",
        report["summary"],
        "",
    ]
    for d in report["deps"]:
        mark = "OK " if d["ok"] else "MISS"
        lines.append(f"  [{mark}] {d['name']:28} · {d['feature']}")
        if not d["ok"]:
            lines.append(f"         → {d['suggestion']}")
    cmds = (report.get("install") or {}).get("commands") or []
    if cmds:
        lines.append("")
        lines.append("Quick install:")
        for c in cmds:
            lines.append(f"  {c}")
    lines.append("")
    lines.append(report.get("hint") or "")
    return "\n".join(lines)
