"""Friendly terminal access to session mounts / exports (never mutates evidence)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def _link(src: Optional[str | Path], dest: Path, name: str) -> Optional[str]:
    if not src:
        return None
    src = Path(src)
    if not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass
    try:
        dest.symlink_to(src)
        return str(dest)
    except OSError:
        # fallback pointer file
        dest.with_suffix(dest.suffix + ".path").write_text(str(src), encoding="utf-8")
        return str(src)


def build_shell_context(
    *,
    temp_dir: Optional[str] = None,
    export_dir: Optional[str] = None,
    mount_dir: Optional[str] = None,
    virtual_device: Optional[str] = None,
    image_path: Optional[str] = None,
    session_id: Optional[str] = None,
    kind: str = "unknown",
    lab_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Create shell/ with friendly symlinks and return env + banner."""
    if not temp_dir:
        raise ValueError("temp_dir required")
    root = Path(temp_dir)
    shell_dir = root / "shell"
    shell_dir.mkdir(parents=True, exist_ok=True)

    links = {}
    links["mount"] = _link(mount_dir, shell_dir / "mount", "mount")
    links["device"] = _link(virtual_device, shell_dir / "device", "device")
    links["export"] = _link(export_dir or (root / "export"), shell_dir / "export", "export")
    links["lab"] = _link(lab_dir, shell_dir / "lab", "lab") if lab_dir else None
    links["image"] = _link(image_path, shell_dir / "image", "image") if image_path else None

    # README for humans
    readme = shell_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
        "Team Forensic Framework — friendly shell workspace",
                "====================================",
                "Evidence images are never modified.",
                "",
                "Shortcuts in this folder:",
                "  mount/   → xmount FUSE dir (virtual disk file lives here)",
                "  device   → symlink to the virtual disk (use with mmls/fls/icat)",
                "  export/  → session exports",
                "  lab/     → writable lab sandbox (if enabled)",
                "  image    → original evidence path (read-only reference)",
                "",
                "Quick commands:",
                "  cd $TFOR_SHELL",
                "  ls -la",
                "  tfor-parts          # mmls on $TFOR_DEVICE",
                "  tfor-fls -o <start> # fls listing",
                "  tfor-here           # print all paths",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = {
        "TFOR_SESSION": session_id or "",
        "TFOR_KIND": kind,
        "TFOR_TEMP": str(root),
        "TFOR_SHELL": str(shell_dir),
        "TFOR_MOUNT": str(mount_dir or ""),
        "TFOR_DEVICE": str(virtual_device or ""),
        "TFOR_EXPORT": str(export_dir or root / "export"),
        "TFOR_IMAGE": str(image_path or ""),
        "TFOR_LAB": str(lab_dir or ""),
    }

    # Persist for external terminals
    (shell_dir / "env.sh").write_text(_env_sh(env, links), encoding="utf-8")
    (shell_dir / "context.json").write_text(
        json.dumps(
            {
                "env": env,
                "links": links,
                "shell_dir": str(shell_dir),
                "cwd": str(shell_dir),
                "rc_file": str(shell_dir / "env.sh"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    banner_lines = [
        "Team Forensic Framework shell — mounted evidence access",
        f"  session: {session_id or '-'}  kind: {kind}",
        f"  shell:   {shell_dir}",
    ]
    if mount_dir:
        banner_lines.append(f"  mount:   {mount_dir}")
    if virtual_device:
        banner_lines.append(f"  device:  {virtual_device}")
    banner_lines.append(f"  export:  {env['TFOR_EXPORT']}")
    banner_lines.append("  tip:     cd $TFOR_SHELL && ls -la   |   tfor-here   |   tfor-parts")
    banner = "\n".join(banner_lines)

    return {
        "shell_dir": str(shell_dir),
        "cwd": str(shell_dir),
        "env": env,
        "links": {k: v for k, v in links.items() if v},
        "banner": banner,
        "rc_file": str(shell_dir / "env.sh"),
    }


def context_from_case_object(case_obj) -> dict[str, Any]:
    """Build shell context from triage Case / DiskCase."""
    info = case_obj.info()
    xm = info.get("xmount") or {}
    return build_shell_context(
        temp_dir=info.get("temp_dir"),
        export_dir=info.get("export_dir"),
        mount_dir=xm.get("mount_dir"),
        virtual_device=xm.get("virtual_device"),
        image_path=info.get("image_path"),
        session_id=info.get("session_id"),
        kind=info.get("kind") or "ad1",
    )


def context_from_persistent_case(case_db) -> dict[str, Any]:
    """Best-effort shell context for persistent CaseDB (lab + evidence paths)."""
    info = case_db.info()
    case_dir = Path(info.path)
    lab = case_dir / "lab"
    # point shell at case dir
    evs = case_db.list_evidence()
    image = evs[-1]["path"] if evs else None
    return build_shell_context(
        temp_dir=str(case_dir),
        export_dir=str(case_dir / "exports"),
        mount_dir=None,
        virtual_device=None,
        image_path=image,
        session_id=info.id,
        kind="case",
        lab_dir=str(lab) if lab.is_dir() else None,
    )


def _env_sh(env: dict[str, str], links: dict) -> str:
    lines = [
        "# Auto-generated by Team Forensic Framework — source this in your shell",
        "#   source \"$TFOR_SHELL/env.sh\"   or:  . ./env.sh",
        "export TFOR_FRIENDLY=1",
    ]
    for k, v in env.items():
        if v is None:
            continue
        # shell-escape single quotes
        esc = str(v).replace("'", "'\"'\"'")
        lines.append(f"export {k}='{esc}'")
    lines += [
        "",
        "tfor-here() {",
        "  echo \"TFOR_SHELL=$TFOR_SHELL\"",
        "  echo \"TFOR_MOUNT=$TFOR_MOUNT\"",
        "  echo \"TFOR_DEVICE=$TFOR_DEVICE\"",
        "  echo \"TFOR_EXPORT=$TFOR_EXPORT\"",
        "  echo \"TFOR_LAB=$TFOR_LAB\"",
        "  echo \"TFOR_IMAGE=$TFOR_IMAGE\"",
        "  ls -la \"${TFOR_SHELL:-.}\" 2>/dev/null || true",
        "}",
        "",
        "tfor-parts() {",
        "  if [ -z \"${TFOR_DEVICE}\" ]; then echo 'no TFOR_DEVICE (open a disk/OVA image)'; return 1; fi",
        "  mmls \"$TFOR_DEVICE\" \"$@\"",
        "}",
        "",
        "tfor-fls() {",
        "  if [ -z \"${TFOR_DEVICE}\" ]; then echo 'no TFOR_DEVICE'; return 1; fi",
        "  fls \"$TFOR_DEVICE\" \"$@\"",
        "}",
        "",
        "tfor-icat() {",
        "  if [ -z \"${TFOR_DEVICE}\" ]; then echo 'no TFOR_DEVICE'; return 1; fi",
        "  icat \"$TFOR_DEVICE\" \"$@\"",
        "}",
        "",
        "tfor-cd-mount() { cd \"${TFOR_MOUNT:-$TFOR_SHELL/mount}\" 2>/dev/null || cd \"$TFOR_SHELL\"; }",
        "tfor-cd-export() { cd \"${TFOR_EXPORT:-$TFOR_SHELL/export}\" 2>/dev/null || true; }",
        "",
        "alias cdmount='tfor-cd-mount'",
        "alias cdexport='tfor-cd-export'",
        "",
        "if [ -n \"${TFOR_SHELL}\" ] && [ -d \"${TFOR_SHELL}\" ]; then",
        "  cd \"$TFOR_SHELL\"",
        "fi",
        "",
    ]
    return "\n".join(lines) + "\n"
