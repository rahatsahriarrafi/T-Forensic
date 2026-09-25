"""Extension-based file accessors — open each file with the right viewer."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sqlite3
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
_reg("image", "png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "tif", "tiff")
_reg("archive", "zip", "jar", "apk", "whl", "docx", "xlsx", "pptx", "odt", "ods")
_reg("sqlite", "sqlite", "sqlite3", "db", "db3")
_reg("pe", "exe", "dll", "sys", "scr", "com", "cpl", "ocx", "mui", "drv")
_reg("pdf", "pdf")
_reg("media", "mp3", "mp4", "wav", "flac", "ogg", "webm", "avi", "mkv", "mov", "m4a")
_reg("office", "doc", "xls", "ppt", "rtf")
_reg("hex", "bin", "dat", "img", "raw", "dump", "evtx", "pf", "lnk")
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
            return "image"
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
    if data[:15] != b"SQLite format 3":
        # still try — some DBs are valid
        pass
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        con = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        try:
            cur = con.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            )
            tables = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
            sample_rows = []
            columns = []
            if tables:
                tname = tables[0]["name"]
                # quote identifier safely
                safe = tname.replace('"', '""')
                colcur = con.execute(f'SELECT * FROM "{safe}" LIMIT 50')
                columns = [d[0] for d in colcur.description] if colcur.description else []
                sample_rows = [list(map(str, row)) for row in colcur.fetchall()]
            return AccessorResult(
                accessor="sqlite",
                label="SQLite",
                extension=extension_of(path),
                mime="application/x-sqlite3",
                mode="table",
                rows=sample_rows,
                columns=columns,
                items=tables,
                size=len(data),
                kind="sqlite",
                note=f"{len(tables)} tables/views"
                + (f"; sample from `{tables[0]['name']}`" if tables else ""),
            )
        finally:
            con.close()
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
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            os.unlink(tmp_path)


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


def open_with_accessor(path: str, data: bytes, force: Optional[str] = None) -> AccessorResult:
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
    return {
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


def list_accessors() -> list[dict]:
    by_acc: dict[str, list[str]] = {}
    for ext, acc in sorted(EXT_MAP.items()):
        by_acc.setdefault(acc, []).append(ext)
    return [
        {"accessor": a, "label": ACCESSOR_LABELS.get(a, a), "extensions": exts}
        for a, exts in sorted(by_acc.items())
    ]
