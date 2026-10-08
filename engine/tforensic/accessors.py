"""Extension-based file accessors — open each file with the right viewer."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tforensic.preview import (
    HEX_PREVIEW_DEFAULT,
    TEXT_PREVIEW_MAX,
    detect_and_decode,
    hex_window,
    preview_to_dict,
)


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
# Video/audio + camcorder MPEG Program Stream (.mod/.tod - JVC, Canon, Panasonic, ...)
_reg(
    "media",
    "mp3", "mp4", "wav", "flac", "ogg", "webm", "avi", "mkv", "mov", "m4a",
    "m4v", "wmv", "mpg", "mpeg", "m2v", "m2t", "m2ts", "mts", "ts", "vob",
    "mod", "tod", "3gp", "3g2",
)
_reg("office", "doc", "xls", "ppt", "rtf")
_reg("hex", "bin", "dat", "img", "raw", "dump", "evtx", "lnk")
_reg("prefetch", "pf")
_reg(
    "pcap",
    "pcap", "pcapng", "cap", "dmp", "pkt", "snoop", "netmon", "ntar",
    "erf", "bfr", "rf5", "tpc", "fdc", "enc", "tr1", "5vw", "erp",
    "k12", "vwr", "mplog", "ipfix", "pklg",
)

# Help stdlib guess MIME for camcorder / MPEG-PS names
mimetypes.add_type("video/mpeg", ".mod")
mimetypes.add_type("video/mpeg", ".tod")
mimetypes.add_type("video/mpeg", ".mpg")
mimetypes.add_type("video/mpeg", ".mpeg")
mimetypes.add_type("video/mp2t", ".m2ts")
mimetypes.add_type("video/mp2t", ".mts")
mimetypes.add_type("video/mp2t", ".ts")


def _looks_like_mpeg_ps(data: bytes) -> bool:
    """JVC/Canon/Panasonic .MOD and similar MPEG-2 Program Streams."""
    if len(data) < 4:
        return False
    # Pack start: 00 00 01 BA
    if data[:4] == b"\x00\x00\x01\xba":
        return True
    # Sometimes leading zeros / system header before pack
    idx = data.find(b"\x00\x00\x01\xba")
    return 0 <= idx <= 64


def _looks_like_tracker_mod(data: bytes) -> bool:
    """Amiga/PC ProTracker-style music modules (also use .mod)."""
    if len(data) < 1084:
        return False
    tag = data[1080:1084]
    return tag in {
        b"M.K.", b"M!K!", b"FLT4", b"FLT8", b"4CHN", b"6CHN", b"8CHN",
        b"OKTA", b"CD81", b"2CHN",
    }


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
    offset: int = 0
    window: int = 0


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
    # .mod is overloaded: camcorder MPEG-PS (common in DFIR) vs tracker music.
    # Prefer magic when bytes are available.
    if ext == "mod" and data is not None:
        if _looks_like_mpeg_ps(data):
            return "media"
        if _looks_like_tracker_mod(data):
            return "hex"
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
        if _looks_like_mpeg_ps(data):
            return "media"
    return "auto"


def mime_for(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    ext = extension_of(path)
    if ext in {"mod", "tod", "mpg", "mpeg", "m2v"}:
        return "video/mpeg"
    if ext in {"m2ts", "mts", "ts"}:
        return "video/mp2t"
    return "application/octet-stream"


# Cap sample written to /tmp for probe + still (huge MOD/VOB stay on evidence).
_MEDIA_SAMPLE_MAX = 12 * 1024 * 1024
# How many bytes the API feeds the accessor for photos (phone JPEGs are often >2 MiB).
_IMAGE_SAMPLE_MAX = 16 * 1024 * 1024
# Max raw bytes embedded as a data URL; larger/incomplete images get an ffmpeg thumb.
_IMAGE_EMBED_MAX = 6 * 1024 * 1024
# Disk/icat inline window for generic files (text/logs/binaries). Hex can page beyond.
_DEFAULT_SAMPLE_MAX = 64 * 1024 * 1024


def preview_byte_cap(path: str) -> int:
    """How many bytes the API should pass into open_with_accessor for this name."""
    acc = EXT_MAP.get(extension_of(path))
    if acc == "media":
        return _MEDIA_SAMPLE_MAX
    if acc in {"exif", "image"}:
        return _IMAGE_SAMPLE_MAX
    return _DEFAULT_SAMPLE_MAX


def _image_bytes_complete(data: bytes, ext: str) -> bool:
    """True when bytes look like a whole image (truncation breaks browser <img>)."""
    if len(data) < 24:
        return False
    if data[:2] == b"\xff\xd8" or ext in {"jpg", "jpeg"}:
        if data[:2] != b"\xff\xd8":
            return False
        # EOI must be at the end (allow trailing NULs from padding)
        return data.rstrip(b"\x00")[-2:] == b"\xff\xd9"
    if data[:8] == b"\x89PNG\r\n\x1a\n" or ext == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n" and data[-8:] == b"IEND\xaeB`\x82"
    if data[:6] in (b"GIF87a", b"GIF89a") or ext == "gif":
        return data[:6] in (b"GIF87a", b"GIF89a") and data[-1:] == b"\x3b"
    if (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or ext == "webp":
        return len(data) >= 16 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return True


def _write_media_sample(data: bytes, ext: str) -> Optional[str]:
    if not data:
        return None
    suffix = f".{ext}" if ext else ".bin"
    fd, tmp = tempfile.mkstemp(prefix="tff-media-", suffix=suffix)
    try:
        os.close(fd)
        sample = data if len(data) <= _MEDIA_SAMPLE_MAX else data[:_MEDIA_SAMPLE_MAX]
        with open(tmp, "wb") as f:
            f.write(sample)
        return tmp
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None


def _ffprobe_summary_file(path: str) -> str:
    """Best-effort stream info for media previews (does not modify evidence)."""
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return ""
    try:
        raw = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries",
                "format=format_name,duration,size,bit_rate:stream=codec_type,codec_name,width,height",
                "-of", "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if raw.returncode != 0 or not raw.stdout.strip():
            return ""
        info = json.loads(raw.stdout)
        fmt = info.get("format") or {}
        parts = []
        if fmt.get("format_name"):
            parts.append(f"container={fmt['format_name']}")
        if fmt.get("duration"):
            try:
                parts.append(f"duration={float(fmt['duration']):.1f}s")
            except (TypeError, ValueError):
                pass
        for s in info.get("streams") or []:
            kind = s.get("codec_type") or "?"
            codec = s.get("codec_name") or "?"
            if kind == "video" and s.get("width") and s.get("height"):
                parts.append(f"{kind}:{codec} {s['width']}x{s['height']}")
            else:
                parts.append(f"{kind}:{codec}")
        return "ffprobe: " + ", ".join(parts) if parts else ""
    except Exception:
        return ""


def _ffmpeg_still_data_url(path: str) -> str:
    """First video frame as a JPEG data URL (empty if ffmpeg missing / audio-only)."""
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ""
    out: Optional[str] = None
    try:
        fd, out = tempfile.mkstemp(prefix="tff-still-", suffix=".jpg")
        os.close(fd)
        raw = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-probesize", "8M", "-analyzeduration", "8M",
                "-i", path,
                "-an", "-frames:v", "1",
                "-q:v", "4",
                "-y", out,
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if raw.returncode != 0:
            return ""
        jpg = Path(out).read_bytes()
        if len(jpg) < 32 or jpg[:2] != b"\xff\xd8":
            return ""
        # ponytail: one JPEG frame; if somehow huge, skip embedding
        if len(jpg) > 2 * 1024 * 1024:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")
    except Exception:
        return ""
    finally:
        if out:
            try:
                os.unlink(out)
            except OSError:
                pass


def _text_result(
    path: str,
    data: bytes,
    accessor: str,
    *,
    offset: int = 0,
    length: Optional[int] = None,
    force_hex: bool = False,
) -> AccessorResult:
    prev = detect_and_decode(data, force_hex=force_hex, offset=offset, length=length)
    note = prev.note or f"Opened with {ACCESSOR_LABELS.get(accessor, accessor)} accessor"
    if prev.truncated and prev.mode == "text":
        note = f"{note} · showing first {prev.window or len(prev.text)} of {prev.size} bytes"
    elif prev.mode == "hex" and prev.size > prev.window:
        end = prev.offset + prev.window
        note = f"{note} · hex bytes {prev.offset}-{end} of {prev.size}"
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
        note=note,
        offset=prev.offset,
        window=prev.window,
    )


def _image_thumb_data_url(data: bytes, ext: str) -> str:
    """Decode via ffmpeg into a small JPEG data URL (works on truncated phone JPEGs)."""
    sample = _write_media_sample(data, ext or "bin")
    if not sample:
        return ""
    try:
        return _ffmpeg_still_data_url(sample)
    finally:
        try:
            os.unlink(sample)
        except OSError:
            pass


def _image_result(path: str, data: bytes) -> AccessorResult:
    ext = extension_of(path)
    mime = mime_for(path)
    if mime == "application/octet-stream":
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "ico": "image/x-icon",
            "svg": "image/svg+xml",
            "tif": "image/tiff",
            "tiff": "image/tiff",
            "heic": "image/heic",
        }.get(ext, "image/jpeg" if ext in {"jpg", "jpeg"} else "image/png")
    note = f"{mime} · {len(data)} bytes"
    data_url = ""
    truncated = False
    complete = _image_bytes_complete(data, ext)
    if complete and len(data) <= _IMAGE_EMBED_MAX:
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    else:
        # Large or truncated JPEG/PNG: never embed a cut-off file (browser shows nothing).
        data_url = _image_thumb_data_url(data, ext)
        truncated = True
        if data_url:
            note += " · preview thumbnail"
        elif complete and len(data) <= _IMAGE_SAMPLE_MAX:
            # ffmpeg missing — last resort embed (may be heavy)
            data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            truncated = False
        elif not shutil.which("ffmpeg"):
            note += " · install ffmpeg for image preview: sudo apt install ffmpeg"
    return AccessorResult(
        accessor="image",
        label="Image",
        extension=ext,
        mime=mime,
        mode="image",
        data_url=data_url,
        size=len(data),
        truncated=truncated or (not complete),
        kind="image",
        note=note,
    )


def _json_result(path: str, data: bytes) -> AccessorResult:
    # Parse the full payload (up to text forensic cap) — never the old 64KiB slice.
    raw = data[:TEXT_PREVIEW_MAX]
    text = raw.decode("utf-8", "replace")
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
            truncated=len(data) > TEXT_PREVIEW_MAX,
            kind="json",
            note="pretty-printed JSON",
            window=len(raw),
        )
    except Exception as e:
        prev = detect_and_decode(data)
        return AccessorResult(
            accessor="json",
            label="JSON",
            extension=extension_of(path),
            mime="application/json",
            mode="text",
            encoding=prev.encoding,
            text=text if prev.mode != "text" else prev.text,
            size=len(data),
            truncated=len(data) > TEXT_PREVIEW_MAX or prev.truncated,
            kind="json-invalid",
            note=f"JSON parse failed: {e}",
            window=len(raw),
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
                infos = zf.infolist()
                for info in infos:
                    items.append({
                        "name": info.filename,
                        "size": info.file_size,
                        "compressed": info.compress_size,
                        "is_dir": info.is_dir(),
                    })
                note = f"{len(infos)} entries (ZIP-compatible)"
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
            offset=prev.offset,
            window=prev.window,
        )
    return AccessorResult(
        accessor="archive",
        label="Archive",
        extension=extension_of(path),
        mime=mime_for(path),
        mode="list",
        items=items,
        size=len(data),
        truncated=False,
        kind="zip",
        note=note,
    )


def _sqlite_result(path: str, data: bytes, wal: Optional[bytes] = None) -> AccessorResult:
    from tforensic.sqlite_view import browse_summary, materialize_sqlite

    try:
        mat = materialize_sqlite(path, data, wal=wal)
        summary = browse_summary(
            mat["path"],
            size=len(data),
            truncated=mat["truncated"],
            wal_merged=mat.get("wal_merged", False),
        )
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
    # Header hex sample only — full bytes stay available via Hex tab / Download.
    text, off, win, more = hex_window(data, offset=0, length=min(4096, HEX_PREVIEW_DEFAULT))
    return AccessorResult(
        accessor=accessor,
        label=ACCESSOR_LABELS.get(accessor, accessor),
        extension=extension_of(path),
        mime=mime_for(path),
        mode="info",
        text=text,
        size=len(data),
        truncated=more,
        kind=accessor,
        note=note,
        executable=data[:2] == b"MZ",
        offset=off,
        window=win,
    )


def open_with_accessor(
    path: str,
    data: bytes,
    force: Optional[str] = None,
    *,
    system_data: Optional[bytes] = None,
    wal_data: Optional[bytes] = None,
    offset: int = 0,
    length: Optional[int] = None,
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
        return _sqlite_result(path, data, wal=wal_data)
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
        r = _text_result(
            path, data, "pe", offset=offset, length=length, force_hex=True,
        )
        r.mode = "hex"
        r.executable = True
        r.note = r.note or "PE/MZ — hex accessor"
        return r
    if acc == "pdf":
        return _info_result(
            path, data, "pdf",
            "PDF detected — use Download/Export to open in an external PDF reader",
        )
    if acc == "media":
        ext = extension_of(path)
        mime = mime_for(path)
        if ext in {"mod", "tod"} or _looks_like_mpeg_ps(data):
            note = (
                f"Camcorder / MPEG Program Stream ({mime or 'video/mpeg'}). "
                "Still frame below when ffmpeg is available; export for full playback."
            )
            if _looks_like_mpeg_ps(data):
                note += " · MPEG pack header detected"
        else:
            note = f"Media file ({mime}) - still frame below when ffmpeg is available"
        still = ""
        probe = ""
        sample = _write_media_sample(data, ext or "bin")
        try:
            if sample:
                probe = _ffprobe_summary_file(sample)
                still = _ffmpeg_still_data_url(sample)
        finally:
            if sample:
                try:
                    os.unlink(sample)
                except OSError:
                    pass
        if probe:
            note = f"{note}\n{probe}"
        if still:
            note = f"{note}\nStill frame preview (ffmpeg)"
        elif not shutil.which("ffmpeg"):
            note = f"{note}\nInstall ffmpeg for inline still previews: sudo apt install ffmpeg"
        r = _info_result(path, data, "media", note)
        if still:
            r.data_url = still
        return r
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
        r = _text_result(
            path, data, "hex", offset=offset, length=length, force_hex=True,
        )
        r.mode = "hex"
        if extension_of(path) == "mod" and _looks_like_tracker_mod(data):
            r.note = (
                "Tracker music module (ProTracker-style), not camcorder MPEG. "
                "Shown as hex - export if you need a module player. "
                + (r.note or "")
            )
        return r
    if acc in ("text", "markup"):
        return _text_result(path, data, acc, offset=offset, length=length)
    # auto
    return _text_result(path, data, "auto", offset=offset, length=length)


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
        "offset": r.offset,
        "window": r.window,
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
