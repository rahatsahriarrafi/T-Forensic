"""Windows Prefetch (.pf) parser — human-readable execution evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _utc(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    try:
        if isinstance(dt, datetime):
            if dt.year <= 1601:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        # integer FILETIME-ish / epoch
        n = int(dt)
        if n <= 0:
            return None
        # pyscca get_last_run_time_as_integer may be FILETIME
        if n > 10_000_000_000_000:
            unix = (n / 10_000_000.0) - 11_644_473_600
        elif n > 1_000_000_000_000:
            unix = n / 1_000_000.0
        else:
            unix = float(n)
        if unix < 631_152_000:
            return None
        return datetime.fromtimestamp(unix, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return None


def parse_prefetch(data: bytes, name: str = "") -> Optional[dict[str, Any]]:
    """Parse Prefetch bytes via pyscca (handles Win10 MAM compression)."""
    if not data or len(data) < 16:
        return None
    try:
        import pyscca
    except ImportError:
        return {
            "error": "pyscca not installed (python3-libscca)",
            "hint": "sudo apt install python3-libscca",
            "raw_name": name,
        }

    import tempfile
    import os

    path = None
    try:
        # libscca wants a path; write a temp copy (evidence bytes already extracted)
        fd, path = tempfile.mkstemp(suffix=".pf", prefix="tff_pf_")
        os.write(fd, data)
        os.close(fd)
        f = pyscca.file()
        f.open(path)
        exec_name = f.executable_filename or ""
        run_count = int(f.run_count or 0)
        last_runs = []
        for i in range(8):
            try:
                t = f.get_last_run_time(i)
            except Exception:
                break
            u = _utc(t)
            if u:
                last_runs.append(u)
        filenames = []
        n = int(f.number_of_filenames or 0)
        for i in range(min(n, 200)):
            try:
                filenames.append(f.get_filename(i) or "")
            except Exception:
                break
        # Highlight interesting referenced paths for analyst questions
        def _notable(path: str) -> bool:
            u = path.upper().replace("/", "\\")
            keys = (
                "\\TORBROWSER", "TORBROWSER-", "TOR.EXE", "\\TOR\\",
                "FIREFOX", "MOZILLA", "CHROME", "\\EDGE\\", "OPERA",
                "BRAVE", "\\DOWNLOADS\\", "\\USERS\\",
            )
            return any(k in u for k in keys)

        interesting = [p for p in filenames if _notable(p)]
        is_installer = any(
            k in (exec_name or name).upper()
            for k in ("INSTALL", "SETUP", "UPDATE")
        )
        note = ""
        if is_installer:
            note = (
                "This is an INSTALLER prefetch. "
                "Installer .pf ≠ the app was used afterward. "
                "Look for a separate app .pf (e.g. firefox.exe / tor browser binary) for actual use."
            )
        return {
            "executable": exec_name,
            "run_count": run_count,
            "prefetch_hash": int(f.prefetch_hash or 0),
            "format_version": int(f.format_version or 0),
            "last_runs_utc": last_runs,
            "last_run_utc": last_runs[0] if last_runs else None,
            "filenames": filenames,
            "interesting_paths": interesting,
            "is_installer": is_installer,
            "note": note,
            "raw_name": name,
        }
    except Exception as e:
        return {"error": str(e), "raw_name": name}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def prefetch_summary_text(info: dict[str, Any]) -> str:
    if info.get("error") and not info.get("executable"):
        return f"Prefetch parse error: {info.get('error')}\n{info.get('hint') or ''}".strip()
    lines = [
        f"Executable : {info.get('executable') or '?'}",
        f"Run count  : {info.get('run_count', '?')}",
        f"Last run   : {info.get('last_run_utc') or '(none)'}",
    ]
    if info.get("last_runs_utc"):
        for i, t in enumerate(info["last_runs_utc"][:8]):
            lines.append(f"  run[{i}]   : {t}")
    if info.get("is_installer"):
        lines.append("")
        lines.append("⚠ INSTALLER prefetch — does not prove the app was launched later.")
    if info.get("note"):
        lines.append(info["note"])
    paths = info.get("interesting_paths") or []
    if paths:
        lines.append("")
        lines.append("Notable referenced paths:")
        for p in paths[:40]:
            lines.append(f"  {p}")
    elif info.get("filenames"):
        lines.append("")
        lines.append(f"Referenced files: {len(info['filenames'])} (see table)")
    return "\n".join(lines)
