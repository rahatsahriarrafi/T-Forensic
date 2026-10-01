"""Extension-based file accessors — open each file with the right viewer."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tforensic.preview import PREVIEW_CAP, detect_and_decode, hexdump, preview_to_dict


# accessor id → human label
ACCESSOR_LABELS = {
    "text": "Text",
    "image": "Image",
    "json": "JSON",
    "markup": "Markup",
    "archive": "Archive",
    "sqlite": "SQLite",
    "pe": "PE / Executable",
    "hex": "Hex",
    "pdf": "PDF",
    "media": "Media",
    "office": "Office",
    "pcap": "PCAP / Network",
    "recycle": "Recycle Bin $I",
    "prefetch": "Prefetch",
    "shellbags": "ShellBags",
    "exif": "EXIF / Metadata",
    "sam": "SAM / NTLM",
    "auto": "Auto",
}

# extension (lowercase, no dot) → accessor
EXT_MAP: dict[str, str] = {}

def _reg(accessor: str, *exts: str) -> None:
    for e in exts:
        EXT_MAP[e.lower().lstrip(".")] = accessor


_reg("text",
     "txt", "log", "md", "markdown", "csv", "tsv", "ini", "cfg", "conf", "config",
     "bat", "cmd", "ps1", "psm1", "vbs", "vbe", "wsf", "sh", "bash", "zsh",
     "py", "pyw", "rb", "pl", "php", "c", "h", "cpp", "hpp", "cs", "java",
     "go", "rs", "swift", "kt", "sql", "yml", "yaml", "toml", "env", "properties",
     "reg", "inf", "url", "desktop", "service", "gitignore", "dockerfile")
_reg("json", "json", "jsonl", "geojson", "webmanifest")
_reg("markup", "html", "htm", "xhtml", "xml", "svg", "xsl", "xslt", "plist")
_reg("image", "gif", "bmp", "ico")
_reg("exif", "jpg", "jpeg", "tif", "tiff", "heic", "png", "webp")
_reg("archive", "zip", "jar", "apk", "whl", "docx", "xlsx", "pptx", "odt", "ods")
_reg("sqlite", "sqlite", "sqlite3", "db", "db3")
_reg("pe", "exe", "dll", "sys", "scr", "com", "cpl", "ocx", "mui", "drv")
_reg("pdf", "pdf")
_reg("media", "mp3", "mp4", "wav", "flac", "ogg", "webm", "avi", "mkv", "mov", "m4a")
_reg("office", "doc", "xls", "ppt", "rtf")
_reg("hex", "bin", "dat", "img", "raw", "dump", "evtx", "lnk")
_reg("prefetch", "pf")
_reg(
    "pcap",
    "pcap", "pcapng", "cap", "dmp", "pkt", "snoop", "netmon", "ntar",
    "erf", "bfr", "rf5", "tpc", "fdc", "enc", "tr1", "5vw", "erp",
    "k12", "vwr", "mplog", "ipfix", "pklg",
)


@dataclass
class AccessorResult:
    accessor: str
    label: str
    extension: str
    mime: str
    mode: str  # text | hex | image | json | table | list | info
    encoding: Optional[str] = None
    text: str = ""
    html: str = ""
    data_url: str = ""
    rows: Optional[list] = None
    columns: Optional[list] = None
    items: Optional[list] = None
    size: int = 0
    truncated: bool = False
    kind: str = ""
    executable: bool = False
    note: str = ""


def extension_of(path: str) -> str:
    name = Path(path).name
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def accessor_for(path: str, data: bytes | None = None) -> str:
    name = Path(path).name
    uname = name.upper()
    # Windows Recycle Bin $I* (not NTFS $I30 index)
    if uname.startswith("$I") and not uname.startswith("$I30") and len(uname) > 2:
        if data is None:
            return "recycle"
        from tforensic.meta_format import parse_recycle_i
        if parse_recycle_i(data):
            return "recycle"
    # ShellBags hives
    if uname in {"USRCLASS.DAT", "NTUSER.DAT"} or uname.endswith("USRCLASS.DAT"):
        return "shellbags"
    # Local SAM (needs sibling SYSTEM for boot key — handled in API)
    if uname == "SAM":
        return "sam"
    ext = extension_of(path)
    if ext in EXT_MAP:
        return EXT_MAP[ext]
    if data is not None:
        if data[:2] == b"MZ":
            return "pe"
        if data[:8] == b"SQLite f":
            return "sqlite"
        if data[:2] == b"PK":
            return "archive"
        if data[:3] == b"\xff\xd8\xff":
            return "exif"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image"
    return "auto"


def mime_for(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _text_result(path: str, data: bytes, accessor: str) -> AccessorResult:
    prev = detect_and_decode(data)
    return AccessorResult(
        accessor=accessor,
        label=ACCESSOR_LABELS.get(accessor, accessor),
        extension=extension_of(path),
        mime=mime_for(path),
        mode=prev.mode if prev.mode != "binary" else "hex",
        encoding=prev.encoding,
        text=prev.text,
        size=prev.size,
        truncated=prev.truncated,
        kind=prev.kind,
        executable=prev.executable,
        note=prev.note or f"Opened with {ACCESSOR_LABELS.get(accessor, accessor)} accessor",
    )


def _image_result(path: str, data: bytes) -> AccessorResult:
    mime = mime_for(path)
    if mime == "application/octet-stream":
        ext = extension_of(path)
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "ico": "image/x-icon",
            "svg": "image/svg+xml",
        }.get(ext, "image/png")
    # Cap embedded preview size (~4 MiB)
    preview = data[: 4 * 1024 * 1024]
    b64 = base64.b64encode(preview).decode("ascii")
    return AccessorResult(
        accessor="image",
        label="Image",
        extension=extension_of(path),
        mime=mime,
        mode="image",
        data_url=f"data:{mime};base64,{b64}",
        size=len(data),
        truncated=len(data) > len(preview),
        kind="image",
        note=f"{mime} · {len(data)} bytes",
    )


def _json_result(path: str, data: bytes) -> AccessorResult:
    prev = detect_and_decode(data)
    text = prev.text if prev.mode == "text" else data[:PREVIEW_CAP].decode("utf-8", "replace")
    try:
        obj = json.loads(text)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        return AccessorResult(
            accessor="json",
            label="JSON",
            extension=extension_of(path),
            mime="application/json",
            mode="json",
            encoding="utf-8",
            text=pretty,
            size=len(data),
            truncated=len(data) > PREVIEW_CAP,
            kind="json",
            note="pretty-printed JSON",
        )
    except Exception as e:
        return AccessorResult(
            accessor="json",
            label="JSON",
            extension=extension_of(path),
            mime="application/json",
            mode="text",
            encoding=prev.encoding,
            text=text,
            size=len(data),
            truncated=prev.truncated,
            kind="json-invalid",
            note=f"JSON parse failed: {e}",
        )


def _archive_result(path: str, data: bytes) -> AccessorResult:
    items = []
    note = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for info in zf.infolist()[:500]:
                    items.append({
                        "name": info.filename,
                        "size": info.file_size,
                        "compressed": info.compress_size,
                        "is_dir": info.is_dir(),
                    })
                note = f"{len(zf.infolist())} entries (ZIP-compatible)"
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        note = f"Not a readable ZIP container: {e}"
        prev = detect_and_decode(data, force_hex=True)
        return AccessorResult(
            accessor="archive",
            label="Archive",
            extension=extension_of(path),
            mime=mime_for(path),
            mode="hex",
            text=prev.text,
            size=len(data),
            truncated=prev.truncated,
            kind="archive",
            note=note,
        )
    return AccessorResult(
        accessor="archive",
        label="Archive",
        extension=extension_of(path),
        mime=mime_for(path),
        mode="list",
        items=items,
        size=len(data),
        truncated=len(items) >= 500,
        kind="zip",
        note=note,
    )


def _sqlite_result(path: str, data: bytes) -> AccessorResult:
    from tforensic.sqlite_view import browse_summary, materialize_sqlite

    try:
        mat = materialize_sqlite(path, data)
        summary = browse_summary(mat["path"], size=len(data), truncated=mat["truncated"])
        return AccessorResult(
            accessor="sqlite",
            label="SQLite",
            extension=extension_of(path),
            mime="application/x-sqlite3",
            mode="sqlite-browser",
            rows=summary.get("rows"),
            columns=summary.get("columns"),
            items=summary.get("items"),
            size=len(data),
            truncated=mat["truncated"],
            kind="sqlite",
            note=summary.get("note") or "",
        )
    except Exception as e:
        prev = detect_and_decode(data, force_hex=True)
        return AccessorResult(
            accessor="sqlite",
            label="SQLite",
            extension=extension_of(path),
            mime="application/x-sqlite3",
            mode="hex",
            text=prev.text,
            size=len(data),
            truncated=prev.truncated,
            kind="sqlite",
            note=f"SQLite open failed: {e}",
        )


def _shellbags_result(path: str, data: bytes) -> AccessorResult:
    from tforensic.shellbags_view import parse_shellbags, shellbags_summary_text

    info = parse_shellbags(data, name=Path(path).name)
    rows = [
        ["Hive", info.get("hive") or Path(path).name],
        ["BagMRU key", info.get("bagmru_key") or "?"],
        ["Entries", str(info.get("count", 0))],
    ]
    for p in (info.get("phone_paths") or [])[:40]:
        rows.append(["Path", p])
    if not info.get("phone_paths"):
        for e in (info.get("interesting") or [])[:40]:
            rows.append(["Folder", f"{e.get('bag_path')} → {e.get('name')}"])
    if info.get("error"):
        rows.append(["Error", str(info["error"])])
    # Q9-style hint
    names = {(e.get("name") or "") for e in (info.get("entries") or [])}
    if "DCIM" in names and "Camera" in names:
        rows.insert(3, ["Hint (phone photos)", "DCIM → Camera (parent folder under DCIM)"])
    return AccessorResult(
        accessor="shellbags",
        label="ShellBags",
        extension=extension_of(path) or "dat",
        mime="application/x-windows-registry",
        mode="table",
        columns=["Field", "Value"],
        rows=rows,
        size=len(data),
        kind="shellbags",
        note=info.get("note") or "ShellBags / BagMRU",
        text=shellbags_summary_text(info),
        items=[e.get("name") for e in (info.get("entries") or []) if e.get("name")],
    )


def _sam_result(path: str, data: bytes, system_data: bytes | None = None) -> AccessorResult:
    from tforensic.sam_view import dump_sam_hashes, sam_summary_text

    if system_data is None:
        rows = [
            ["SAM", Path(path).name],
            ["Size", str(len(data))],
            ["Header", data[:4].decode("ascii", "replace") if data[:4] == b"regf" else "not regf"],
            ["Error", "SYSTEM hive required (same folder) to decrypt NTLM hashes"],
            ["Hint", "Open Windows\\System32\\config\\SAM — TFF loads sibling SYSTEM automatically"],
        ]
        return AccessorResult(
            accessor="sam",
            label="SAM / NTLM",
            extension="",
            mime="application/x-windows-registry",
            mode="table",
            columns=["Field", "Value"],
            rows=rows,
            size=len(data),
            kind="sam",
            note="SAM hive — need SYSTEM for boot key",
            text="Export SAM + SYSTEM, then: secretsdump.py -sam SAM -system SYSTEM LOCAL",
        )

    info = dump_sam_hashes(data, system_data)
    crack = info.get("crack") or {}
    rows: list[list[str]] = [
        ["SAM", Path(path).name],
        ["Method", str(info.get("method") or "?")],
        ["Boot key", str(info.get("boot_key") or "?")],
        ["Accounts", str(info.get("count", 0))],
        [
            "Auto-crack",
            (
                f"{crack.get('tool') or 'unavailable'} · "
                f"{crack.get('cracked', 0)}/{crack.get('attempted', 0)} cracked"
                if crack.get("tool")
                else (crack.get("note") or "hashcat/john not found")
            ),
        ],
    ]
    if info.get("error"):
        rows.append(["Error", str(info["error"])])
    for u in info.get("users") or []:
        flag = []
        if u.get("disabled"):
            flag.append("disabled")
        if u.get("empty_password"):
            pw = "(empty)"
            flag.append("empty")
        elif u.get("password") is not None:
            pw = str(u["password"])
            flag.append("CRACKED")
        else:
            pw = "(not cracked)"
        suf = f" · {', '.join(flag)}" if flag else ""
        rows.append(
            [
                f"{u['username']} (RID {u['rid']})",
                f"{pw}  |  NTLM {u['nt_hash']}{suf}",
            ]
        )
    return AccessorResult(
        accessor="sam",
        label="SAM / NTLM",
        extension="",
        mime="application/x-windows-registry",
        mode="table",
        columns=["Field", "Value"],
        rows=rows,
        size=len(data),
        kind="sam",
        note=info.get("note") or "Local SAM NTLM hashes",
        text=sam_summary_text(info),
        items=[u.get("pwdump") for u in (info.get("users") or [])],
    )


def _exif_result(path: str, data: bytes) -> AccessorResult:
    """JPEG/TIFF EXIF via exiftool when available (phone make/model for Q9)."""
    import shutil
    import subprocess

    rows: list[list[str]] = []
    text = ""
    note = "Image EXIF"
    if shutil.which("exiftool"):
        import tempfile
        import os

        fd, tmp = tempfile.mkstemp(suffix="." + (extension_of(path) or "jpg"))
        try:
            os.write(fd, data)
            os.close(fd)
            proc = subprocess.run(
                ["exiftool", "-s", "-Make", "-Model", "-CreateDate", "-DateTimeOriginal",
                 "-ModifyDate", "-Software", "-GPSPosition", "-LensModel", "-ImageSize", tmp],
                capture_output=True, text=True, timeout=20,
            )
            text = (proc.stdout or "") + (proc.stderr or "")
            for line in (proc.stdout or "").splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    rows.append([k.strip(), v.strip()])
            make = next((v for k, v in rows if k.lower() == "make"), "")
            model = next((v for k, v in rows if k.lower() == "model"), "")
            if make or model:
                note = f"Camera: {make} {model}".strip()
                rows.insert(0, ["Hint", "Phone/camera EXIF — check ShellBags (UsrClass.dat) for DCIM\\Camera"])
        except Exception as e:
            rows.append(["exiftool", str(e)])
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    else:
        # fall back to image preview
        return _image_result(path, data)
    # still show the image
    img = _image_result(path, data)
    return AccessorResult(
        accessor="exif",
        label="EXIF / Image",
        extension=extension_of(path),
        mime=mime_for(path),
        mode="table",
        columns=["Field", "Value"],
        rows=rows or [["Note", "No EXIF tags parsed"]],
        size=len(data),
        kind="exif",
        note=note,
        text=text or note,
        data_url=img.data_url,
    )


def _prefetch_result(path: str, data: bytes) -> AccessorResult:
    from tforensic.prefetch_view import parse_prefetch, prefetch_summary_text

    info = parse_prefetch(data, name=Path(path).name) or {}
    rows = [
        ["Executable", info.get("executable") or "?"],
        ["Run count", str(info.get("run_count", "?"))],
        ["Last run (UTC)", info.get("last_run_utc") or "(none)"],
        ["Format version", str(info.get("format_version", ""))],
        ["Prefetch hash", hex(info.get("prefetch_hash") or 0)],
        ["Installer?", "YES — installer ≠ app was used" if info.get("is_installer") else "no"],
    ]
    for i, t in enumerate((info.get("last_runs_utc") or [])[:8]):
        rows.append([f"Run time [{i}] UTC", t])
    for p in (info.get("interesting_paths") or [])[:30]:
        rows.append(["Referenced (notable)", p])
    if info.get("error"):
        rows.append(["Parse note", str(info.get("error"))])
    note = info.get("note") or "Windows Prefetch — execution evidence"
    return AccessorResult(
        accessor="prefetch",
        label="Prefetch",
        extension=extension_of(path) or "pf",
        mime="application/x-windows-prefetch",
        mode="table",
        columns=["Field", "Value"],
        rows=rows,
        size=len(data),
        kind="prefetch",
        note=note,
        text=prefetch_summary_text(info),
        items=info.get("filenames") or [],
    )


def _recycle_result(path: str, data: bytes) -> AccessorResult:
    from tforensic.meta_format import parse_recycle_i

    parsed = parse_recycle_i(data)
    if not parsed:
        return _text_result(path, data, "hex")
    rows = [
        ["Deleted (UTC)", parsed.get("deleted_utc") or "?"],
        ["Original path", parsed.get("original_path") or "?"],
        ["Original size", str(parsed.get("original_size"))],
        ["$I version", str(parsed.get("version"))],
        ["FILETIME raw", str(parsed.get("deleted_filetime"))],
    ]
    note = (
        f"Recycle Bin delete record — {parsed.get('deleted_utc') or 'time unknown'}"
    )
    return AccessorResult(
        accessor="recycle",
        label="Recycle Bin $I",
        extension=extension_of(path),
        mime="application/x-recycle-i",
        mode="table",
        columns=["Field", "Value"],
        rows=rows,
        size=len(data),
        kind="recycle",
        note=note,
        text=(
            f"Deleted: {parsed.get('deleted_utc')}\n"
            f"Original: {parsed.get('original_path')}\n"
            f"Size: {parsed.get('original_size')}"
        ),
    )


def _info_result(path: str, data: bytes, accessor: str, note: str) -> AccessorResult:
    prev = detect_and_decode(data, force_hex=True)
    return AccessorResult(
        accessor=accessor,
        label=ACCESSOR_LABELS.get(accessor, accessor),
        extension=extension_of(path),
        mime=mime_for(path),
        mode="info",
        text=prev.text[:4096],
        size=len(data),
        truncated=True,
        kind=accessor,
        note=note,
        executable=data[:2] == b"MZ",
    )


def open_with_accessor(
    path: str,
    data: bytes,
    force: Optional[str] = None,
    *,
    system_data: Optional[bytes] = None,
) -> AccessorResult:
    """Open file bytes with the accessor for its extension (or forced accessor)."""
    acc = force or accessor_for(path, data)

    if acc == "image":
        return _image_result(path, data)
    if acc == "json":
        return _json_result(path, data)
    if acc == "archive":
        return _archive_result(path, data)
    if acc == "sqlite":
        return _sqlite_result(path, data)
    if acc == "recycle":
        return _recycle_result(path, data)
    if acc == "prefetch":
        return _prefetch_result(path, data)
    if acc == "shellbags":
        return _shellbags_result(path, data)
    if acc == "sam":
        return _sam_result(path, data, system_data)
    if acc == "exif":
        return _exif_result(path, data)
    if acc == "pe":
        r = _text_result(path, data, "pe")
        r.mode = "hex"
        r.text = hexdump(data)
        r.executable = True
        r.note = "PE/MZ — hex accessor"
        return r
    if acc == "pdf":
        return _info_result(
            path, data, "pdf",
            "PDF detected — use Download/Export to open in an external PDF reader",
        )
    if acc == "media":
        return _info_result(
            path, data, "media",
            f"Media file ({mime_for(path)}) — export to play with a media player",
        )
    if acc == "office":
        return _info_result(
            path, data, "office",
            "Legacy Office binary — export to open with LibreOffice/Office",
        )
    if acc == "pcap":
        return _info_result(
            path, data, "pcap",
            "Network capture — open this path in the Network tab (Wireshark/tshark packet list, filters, conversations)",
        )
    if acc == "hex":
        r = _text_result(path, data, "hex")
        r.mode = "hex"
        r.text = hexdump(data)
        return r
    if acc in ("text", "markup"):
        return _text_result(path, data, acc)
    # auto
    return _text_result(path, data, "auto")


def accessor_to_dict(r: AccessorResult) -> dict:
    d = {
        "accessor": r.accessor,
        "label": r.label,
        "extension": r.extension,
        "mime": r.mime,
        "mode": r.mode,
        "encoding": r.encoding,
        "text": r.text,
        "html": r.html,
        "data_url": r.data_url,
        "rows": r.rows,
        "columns": r.columns,
        "items": r.items,
        "size": r.size,
        "truncated": r.truncated,
        "kind": r.kind,
        "executable": r.executable,
        "note": r.note,
    }
    if r.mode == "sqlite-browser" or r.kind == "sqlite":
        d["browser"] = True
        d["tables"] = r.items
    return d


def list_accessors() -> list[dict]:
    by_acc: dict[str, list[str]] = {}
    for ext, acc in sorted(EXT_MAP.items()):
        by_acc.setdefault(acc, []).append(ext)
    return [
        {"accessor": a, "label": ACCESSOR_LABELS.get(a, a), "extensions": exts}
        for a, exts in sorted(by_acc.items())
    ]
