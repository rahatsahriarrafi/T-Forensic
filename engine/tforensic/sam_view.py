"""Local SAM + SYSTEM hive → Windows account NTLM hashes + optional crack."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

_EMPTY_NT = "31d6cfe0d16ae931b73c59d7e0c089c0"

# pwdump: name:rid:lmhash:nthash:::
_LINE_RE = re.compile(
    r"^(?:\*disabled\*\s*)?([^:]+):(\d+):([0-9a-fA-F]{32}):([0-9a-fA-F]{32}):"
)

# Fast CTF / lab-oriented masks. Avoid huge keyspaces (e.g. 8×?l) so the UI
# stays responsive when a long machine hash remains uncracked.
_DEFAULT_MASKS = (
    "?l?l?l?d?d?d?d",       # abc1234 / ctf2021  (~1.8e8)
    "?u?l?l?l?d?d?d?d",     # Abcd1234
    "?l?l?l?l?d?d?d",       # abcd123
    "?d?d?d?d?d?d?d?d",     # 8 digits
)

_CRACK_TIMEOUT_S = 45
_MASK_TIMEOUT_S = 12


def _write_temp(data: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="tff_hive_")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _parse_pwdump_lines(text: str) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        name, rid, lm, nt = m.group(1), int(m.group(2)), m.group(3).lower(), m.group(4).lower()
        disabled = "*disabled*" in raw.lower()
        users.append(
            {
                "username": name,
                "rid": rid,
                "lm_hash": lm,
                "nt_hash": nt,
                "disabled": disabled,
                "empty_password": nt == _EMPTY_NT,
                "password": "" if nt == _EMPTY_NT else None,
                "pwdump": f"{name}:{rid}:{lm}:{nt}:::",
            }
        )
    users.sort(key=lambda u: (u["rid"], u["username"].lower()))
    return users


def _dump_impacket(sam_path: str, system_path: str) -> tuple[list[dict[str, Any]], str]:
    from impacket.examples.secretsdump import LocalOperations, SAMHashes
    import sys
    from io import StringIO

    ops = LocalOperations(system_path)
    boot_key = ops.getBootKey()
    boot_hex = boot_key.hex() if isinstance(boot_key, (bytes, bytearray)) else str(boot_key)

    buf = StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        sam = SAMHashes(sam_path, boot_key, isRemote=False)
        try:
            sam.dump()
        finally:
            sam.finish()
    finally:
        sys.stdout = old
    return _parse_pwdump_lines(buf.getvalue()), boot_hex


def _dump_samdump2(sam_path: str, system_path: str) -> list[dict[str, Any]]:
    exe = shutil.which("samdump2")
    if not exe:
        raise RuntimeError("samdump2 not found")
    proc = subprocess.run(
        [exe, system_path, sam_path],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0 and ":" not in text:
        raise RuntimeError(f"samdump2 failed: {text.strip()[:200]}")
    return _parse_pwdump_lines(text)


def _parse_hash_password_lines(text: str) -> dict[str, str]:
    """Parse hashcat/john 'hash:password' (or hash:plain) lines."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        # hashcat may prefix with status noise; take last 32hex:rest
        m = re.search(r"\b([0-9a-fA-F]{32}):(.+)$", line)
        if not m:
            continue
        h, pw = m.group(1).lower(), m.group(2)
        if pw.startswith("$HEX["):
            # hashcat hex encoding of non-ascii
            continue
        found[h] = pw
    return found


def crack_ntlm_hashes(
    hashes: list[str],
    *,
    masks: tuple[str, ...] | None = None,
    timeout_s: int = _CRACK_TIMEOUT_S,
) -> dict[str, Any]:
    """Crack NTLM hashes with john (fast masks) or hashcat. Returns {hash: password}."""
    import time

    unique = sorted({(h or "").lower() for h in hashes if h and h != _EMPTY_NT})
    if not unique:
        return {"passwords": {}, "tool": None, "note": "no crackable hashes"}

    masks = masks or _DEFAULT_MASKS
    hashcat = shutil.which("hashcat")
    john = shutil.which("john")
    cracked: dict[str, str] = {}
    tool = None
    notes: list[str] = []
    deadline = time.monotonic() + max(5, timeout_s)

    # --- john first (cold-start ~<1s for small masks) ---
    if john:
        tool = "john"
        # Label each hash so --show maps password → hash
        labeled = [f"h{i}:{h}" for i, h in enumerate(unique)]
        label_to_hash = {f"h{i}": h for i, h in enumerate(unique)}
        hash_file = _write_temp("\n".join(labeled).encode() + b"\n", ".ntlm")
        pot = hash_file + ".pot"
        try:
            remaining = set(unique)
            for mask in masks:
                if not remaining:
                    break
                left = int(deadline - time.monotonic())
                if left <= 1:
                    notes.append("timeout")
                    break
                per = min(left, _MASK_TIMEOUT_S)
                try:
                    subprocess.run(
                        [
                            john,
                            "--format=nt",
                            f"--mask={mask}",
                            f"--pot={pot}",
                            f"--session=tff{os.getpid()}{abs(hash(mask)) % 100000}",
                            hash_file,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=per,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    notes.append(f"john timeout on {mask}")
                    # still collect whatever landed in the pot
                    pass
                show = subprocess.run(
                    [john, "--show", "--format=nt", f"--pot={pot}", hash_file],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                for raw in (show.stdout or "").splitlines():
                    # h0:password   or  h0:password:extra...
                    if ":" not in raw or raw.startswith("0 password"):
                        continue
                    name, pw, *_rest = raw.split(":")
                    h = label_to_hash.get(name)
                    if h and pw:
                        cracked[h] = pw
                        remaining.discard(h)
            notes.append(f"masks={len(masks)}")
        finally:
            for p in (hash_file, pot):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        if cracked or not hashcat:
            return {
                "passwords": cracked,
                "tool": tool,
                "note": "; ".join(notes) if notes else tool,
                "cracked": len(cracked),
                "attempted": len(unique),
            }

    # --- hashcat fallback (CPU device; slower init) ---
    if hashcat:
        tool = "hashcat"
        remaining = set(unique) - set(cracked)
        hash_file = _write_temp("\n".join(sorted(remaining)).encode() + b"\n", ".ntlm")
        try:
            for mask in masks:
                if not remaining:
                    break
                left = int(deadline - time.monotonic())
                if left <= 1:
                    notes.append("timeout")
                    break
                per = min(left, _MASK_TIMEOUT_S)
                session = f"tff{os.getpid()}{abs(hash(mask)) % 10000}"
                cmd = [
                    hashcat,
                    "-m", "1000",
                    hash_file,
                    "-a", "3",
                    mask,
                    "-D", "1",
                    "--force",
                    "--quiet",
                    "--potfile-disable",
                    "--logfile-disable",
                    "-O",
                    "--session", session,
                ]
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=per,
                        check=False,
                    )
                    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                except subprocess.TimeoutExpired as e:
                    out = ""
                    if e.stdout:
                        out = e.stdout if isinstance(e.stdout, str) else e.stdout.decode(
                            "utf-8", "replace"
                        )
                    notes.append(f"hashcat timeout on {mask}")
                got = _parse_hash_password_lines(out)
                cracked.update(got)
                remaining -= set(got)
            notes.append(f"masks={len(masks)}")
        finally:
            try:
                os.unlink(hash_file)
            except OSError:
                pass
        return {
            "passwords": cracked,
            "tool": tool,
            "note": "; ".join(notes) if notes else tool,
            "cracked": len(cracked),
            "attempted": len(unique),
        }

    return {
        "passwords": {},
        "tool": None,
        "note": "hashcat/john not installed",
        "cracked": 0,
        "attempted": len(unique),
    }


def dump_sam_hashes(
    sam_data: bytes,
    system_data: bytes,
    *,
    crack: bool = True,
) -> dict[str, Any]:
    """Decrypt SAM using SYSTEM boot key; optionally crack NTLM with hashcat."""
    if not sam_data.startswith(b"regf"):
        return {
            "error": "SAM does not look like a registry hive (missing regf header)",
            "users": [],
            "boot_key": None,
            "method": None,
        }
    if not system_data.startswith(b"regf"):
        return {
            "error": "SYSTEM does not look like a registry hive (missing regf header)",
            "users": [],
            "boot_key": None,
            "method": None,
        }

    sam_path = _write_temp(sam_data, ".sam")
    sys_path = _write_temp(system_data, ".system")
    try:
        users: list[dict[str, Any]] = []
        boot_key: Optional[str] = None
        method = None
        err: Optional[str] = None

        try:
            users, boot_key = _dump_impacket(sam_path, sys_path)
            method = "impacket"
        except Exception as e:
            err = f"impacket: {e}"
            try:
                users = _dump_samdump2(sam_path, sys_path)
                method = "samdump2"
                err = None
            except Exception as e2:
                err = f"{err}; samdump2: {e2}"

        if not users and err:
            return {
                "error": err,
                "users": [],
                "boot_key": boot_key,
                "method": method,
            }

        crack_info: dict[str, Any] = {"passwords": {}, "tool": None, "note": "skipped"}
        if crack:
            # Crack interactive user accounts only (RID >= 1000). Skipping
            # built-in/machine hashes keeps mask attacks fast for the UI.
            targets = [
                u["nt_hash"]
                for u in users
                if not u.get("empty_password") and u.get("rid", 0) >= 1000
            ]
            if not targets:
                targets = [
                    u["nt_hash"] for u in users if not u.get("empty_password")
                ]
            crack_info = crack_ntlm_hashes(targets)
            pw_map = crack_info.get("passwords") or {}
            for u in users:
                if u.get("password") is not None:
                    continue
                pw = pw_map.get(u["nt_hash"])
                if pw is not None:
                    u["password"] = pw

        cracked_n = sum(1 for u in users if u.get("password") is not None and not u.get("empty_password"))
        empty_n = sum(1 for u in users if u.get("empty_password"))
        tool = crack_info.get("tool")
        note = (
            f"NTLM from local SAM (boot key via SYSTEM). "
            f"Auto-crack: {tool or 'unavailable'} "
            f"({cracked_n} cracked, {empty_n} empty)."
        )
        if crack_info.get("note") and tool:
            note += f" [{crack_info['note']}]"
        if not tool and crack:
            note += " Install hashcat (or john) for automatic cracking."

        return {
            "error": None,
            "users": users,
            "boot_key": boot_key,
            "method": method,
            "count": len(users),
            "crack": crack_info,
            "note": note,
        }
    finally:
        for p in (sam_path, sys_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def sam_summary_text(info: dict[str, Any]) -> str:
    lines = [
        f"Method: {info.get('method') or '?'}",
        f"Boot key: {info.get('boot_key') or '?'}",
        f"Accounts: {info.get('count', len(info.get('users') or []))}",
    ]
    crack = info.get("crack") or {}
    if crack.get("tool"):
        lines.append(f"Crack tool: {crack['tool']} ({crack.get('cracked', 0)}/{crack.get('attempted', '?')})")
    if info.get("error"):
        lines.append(f"Error: {info['error']}")
    for u in info.get("users") or []:
        mark = " (disabled)" if u.get("disabled") else ""
        if u.get("empty_password"):
            pw = "(empty)"
        elif u.get("password") is not None:
            pw = repr(u["password"])
        else:
            pw = "(not cracked)"
        lines.append(f"{u['username']}:{u['rid']}:{u['nt_hash']} → {pw}{mark}")
    return "\n".join(lines)


def find_sibling_hive(case_get, sam_path: str, name: str = "SYSTEM") -> Optional[str]:
    """Locate SYSTEM (or other) hive next to SAM in the AD1 tree."""
    parent = str(Path(sam_path).parent).replace("\\", "/")
    for cand in (
        f"{parent}/{name}",
        f"{parent}/{name.upper()}",
        f"{parent}/{name.lower()}",
        f"{parent}/{name.capitalize()}",
    ):
        node = case_get(cand)
        if node is not None:
            return node.path
    node = case_get(f"Windows/System32/config/{name}")
    if node is not None:
        return node.path
    return None
