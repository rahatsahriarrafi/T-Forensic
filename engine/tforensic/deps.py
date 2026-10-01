"""Runtime dependency probe — report missing tools with install suggestions."""
from __future__ import annotations

import os
import re
import shutil
import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

# PyPI name → import module (requirements.txt uses PyPI names)
_PIP_IMPORT = {
    "impacket": "impacket",
}


@dataclass
class Dep:
    id: str
    name: str
    kind: str  # required | feature | optional
    feature: str
    ok: bool
    check: str
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


def requirements_txt_path() -> Path:
    """Repo-root requirements.txt (engine/tforensic/deps.py → repo root)."""
    return Path(__file__).resolve().parents[2] / "requirements.txt"


def _parse_requirement_name(line: str) -> Optional[str]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    line = line.split(";", 1)[0].strip()
    m = re.match(r"^([A-Za-z0-9_.-]+)", line)
    return m.group(1).lower().replace("_", "-") if m else None


def check_requirements_txt() -> dict[str, Any]:
    """Verify every package in requirements.txt is importable. Hard gate for startup."""
    path = requirements_txt_path()
    missing: list[dict[str, str]] = []
    packages: list[dict[str, Any]] = []

    if not path.is_file():
        return {
            "ok": False,
            "path": str(path),
            "packages": [],
            "missing": [
                {
                    "name": "requirements.txt",
                    "suggestion": f"Missing {path} — clone the full repo or restore requirements.txt",
                }
            ],
            "install": "./install.sh   # or: scripts/install-python-reqs.sh (creates .venv on Kali)",
            "message": f"requirements.txt not found at {path}",
        }

    for raw in path.read_text(encoding="utf-8").splitlines():
        name = _parse_requirement_name(raw)
        if not name:
            continue
        mod = _PIP_IMPORT.get(name, name.replace("-", "_"))
        ok = _has_mod(mod)
        packages.append({"name": name, "module": mod, "ok": ok, "spec": raw.strip()})
        if not ok:
            missing.append(
                {
                    "name": name,
                    "module": mod,
                    "suggestion": f"./install.sh   # or: scripts/install-python-reqs.sh  (needs: {name})",
                }
            )

    ok = len(missing) == 0
    return {
        "ok": ok,
        "path": str(path),
        "packages": packages,
        "missing": missing,
        "install": "./install.sh   # creates .venv on Kali/Debian (PEP 668)",
        "message": (
            "requirements.txt satisfied."
            if ok
            else "TFF will not start until requirements.txt is installed (./install.sh)."
        ),
    }


def format_requirements_block(req: Optional[dict[str, Any]] = None) -> str:
    req = req or check_requirements_txt()
    lines = [
        "REQUIREMENTS BLOCKED — install Python packages first:",
        f"  {req.get('install') or 'pip install -r requirements.txt'}",
        f"  (file: {req.get('path')})",
        "",
    ]
    for m in req.get("missing") or []:
        lines.append(f"  missing: {m.get('name')}")
        if m.get("suggestion"):
            lines.append(f"    → {m['suggestion']}")
    lines.append("")
    lines.append("Then re-run. Check status:  tforensic deps")
    return "\n".join(lines)


def ensure_requirements() -> tuple[bool, str]:
    """Return (ok, message). TFOR_SKIP_REQ=1 bypasses (emergency only)."""
    if os.environ.get("TFOR_SKIP_REQ", "").strip().lower() in ("1", "true", "yes"):
        return True, "TFOR_SKIP_REQ set — skipping requirements.txt gate"
    req = check_requirements_txt()
    if req["ok"]:
        return True, req["message"]
    return False, format_requirements_block(req)


def check_dependencies() -> dict[str, Any]:
    """Return full dependency report with missing items + install lines."""
    req = check_requirements_txt()
    deps: list[Dep] = [
        Dep(
            id="python3",
            name="Python 3.9+",
            kind="required",
            feature="Engine / CLI / API",
            ok=True,
            check="runtime",
            suggestion="Already running under this interpreter.",
        ),
        Dep(
            id="requirements.txt",
            name="requirements.txt (pip)",
            kind="required",
            feature="Must be installed before TFF will start",
            ok=req["ok"],
            check=str(req.get("path") or "requirements.txt"),
            suggestion=req.get("install") or "pip install -r requirements.txt",
            pip="see requirements.txt",
        ),
        Dep(
            id="impacket",
            name="impacket",
            kind="required",
            feature="Listed in requirements.txt (SAM / NTLM)",
            ok=_has_mod("impacket"),
            check="import impacket",
            suggestion="pip install -r requirements.txt",
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
    missing_required = [d for d in missing if d.kind == "required"]
    missing_feature = [d for d in missing if d.kind == "feature"]
    missing_optional = [d for d in missing if d.kind == "optional"]

    apt_pkgs: list[str] = []
    pip_pkgs: list[str] = []
    for d in missing:
        for p in (d.apt or "").split():
            if p and p not in apt_pkgs:
                apt_pkgs.append(p)
        if d.pip and d.pip not in pip_pkgs and d.pip != "see requirements.txt":
            pip_pkgs.append(d.pip)

    install_lines: list[str] = []
    if not req["ok"] or pip_pkgs:
        install_lines.append("pip install -r requirements.txt")
    if pip_pkgs:
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

    return {
        "ok": req["ok"] and len(missing_required) == 0,
        "requirements_ok": req["ok"],
        "requirements": req,
        "complete": len(missing) == 0,
        "summary": (
            "All recommended tools present."
            if not missing
            else (
                "BLOCKED: install requirements.txt before TFF will start."
                if not req["ok"]
                else f"{len(missing)} missing — install to unlock full features."
            )
        ),
        "counts": {
            "total": len(deps),
            "ok": sum(1 for d in deps if d.ok),
            "missing": len(missing),
            "missing_required": len(missing_required),
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
            "REQUIRED first: ./install.sh (creates .venv on Kali). "
            "Then: ./update.sh installs system tools from requirements-system.txt "
            "(xmount, sleuthkit, qemu-utils, …). Check: tforensic deps"
        ),
    }


def format_deps_text(report: Optional[dict[str, Any]] = None) -> str:
    report = report or check_dependencies()
    lines = [
        f"TFF dependencies: {report['counts']['ok']}/{report['counts']['total']} OK",
        report["summary"],
        "",
    ]
    if not report.get("requirements_ok", True):
        lines.append(format_requirements_block(report.get("requirements")))
        lines.append("")
    for d in report["deps"]:
        mark = "OK " if d["ok"] else ("REQ" if d["kind"] == "required" else "MISS")
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
    hint = report.get("hint") or ""
    if isinstance(hint, (tuple, list)):
        hint = " ".join(str(x) for x in hint)
    lines.append(str(hint))
    return "\n".join(str(x) for x in lines)
