"""Encoding / type-aware preview — avoid garbage text dumps."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


PREVIEW_CAP = 65536


@dataclass
class PreviewResult:
    mode: str  # text | hex | binary
    encoding: Optional[str]
    text: str
    size: int
    truncated: bool
    kind: str  # utf8 | utf16le | utf16be | latin1 | pe | binary | empty
    executable: bool = False
    note: str = ""


def is_executable(data: bytes) -> bool:
    return len(data) >= 2 and data[:2] == b"MZ"


def _nul_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return data.count(0) / len(data)


def _looks_utf16_le(data: bytes) -> bool:
    if len(data) < 4:
        return False
    if data.startswith(b"\xff\xfe"):
        return True
    # Many Windows text files are UTF-16LE without BOM: ASCII interleaved with NULs.
    sample = data[: min(len(data), 512)]
    if len(sample) < 8:
        return False
    even = sample[0::2]
    odd = sample[1::2]
    if not odd:
        return False
    # High NUL density on odd bytes, printable-ish on even.
    odd_nul = sum(1 for b in odd if b == 0) / len(odd)
    even_print = sum(1 for b in even if 9 <= b < 127 or b in (10, 13)) / len(even)
    return odd_nul > 0.6 and even_print > 0.5


def _looks_utf16_be(data: bytes) -> bool:
    if data.startswith(b"\xfe\xff"):
        return True
    sample = data[: min(len(data), 512)]
    if len(sample) < 8:
        return False
    even = sample[0::2]
    odd = sample[1::2]
    if not even:
        return False
    even_nul = sum(1 for b in even if b == 0) / len(even)
    odd_print = sum(1 for b in odd if 9 <= b < 127 or b in (10, 13)) / len(odd)
    return even_nul > 0.6 and odd_print > 0.5


def _control_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = 0
    for ch in text:
        o = ord(ch)
        if ch in "\t\n\r":
            continue
        if o < 32 or o == 0xFFFD:
            bad += 1
    return bad / len(text)


def hexdump(data: bytes, limit: int = PREVIEW_CAP) -> str:
    preview = data[:limit]
    lines = []
    for i in range(0, len(preview), 16):
        chunk = preview[i : i + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hexs:<47}  {asc}")
    return "\n".join(lines)


def detect_and_decode(data: bytes, force_hex: bool = False) -> PreviewResult:
    size = len(data)
    truncated = size > PREVIEW_CAP
    preview = data[:PREVIEW_CAP]
    exe = is_executable(data)

    if not preview:
        return PreviewResult(
            mode="text",
            encoding=None,
            text="",
            size=0,
            truncated=False,
            kind="empty",
            note="empty file",
        )

    if force_hex or exe:
        return PreviewResult(
            mode="hex",
            encoding=None,
            text=hexdump(preview),
            size=size,
            truncated=truncated,
            kind="pe" if exe else "binary",
            executable=exe,
            note="PE/MZ executable" if exe else "hex view",
        )

    # Prefer UTF-16 when NUL pattern matches (fixes AD1 Viewer garbage previews).
    if _looks_utf16_le(preview):
        try:
            text = preview.decode("utf-16-le")
            if _control_ratio(text) < 0.15:
                return PreviewResult(
                    mode="text",
                    encoding="utf-16-le",
                    text=text,
                    size=size,
                    truncated=truncated,
                    kind="utf16le",
                )
        except UnicodeDecodeError:
            pass

    if _looks_utf16_be(preview):
        try:
            text = preview.decode("utf-16-be")
            if _control_ratio(text) < 0.15:
                return PreviewResult(
                    mode="text",
                    encoding="utf-16-be",
                    text=text,
                    size=size,
                    truncated=truncated,
                    kind="utf16be",
                )
        except UnicodeDecodeError:
            pass

    # UTF-8 strict, then replace if mostly printable.
    try:
        text = preview.decode("utf-8")
        if _control_ratio(text) < 0.1 and _nul_ratio(preview) < 0.05:
            return PreviewResult(
                mode="text",
                encoding="utf-8",
                text=text,
                size=size,
                truncated=truncated,
                kind="utf8",
            )
    except UnicodeDecodeError:
        pass

    # latin-1 always succeeds; only accept if printable enough.
    text = preview.decode("latin-1")
    if _control_ratio(text) < 0.08 and _nul_ratio(preview) < 0.02:
        return PreviewResult(
            mode="text",
            encoding="latin-1",
            text=text,
            size=size,
            truncated=truncated,
            kind="latin1",
        )

    return PreviewResult(
        mode="hex",
        encoding=None,
        text=hexdump(preview),
        size=size,
        truncated=truncated,
        kind="binary",
        note="binary or undecodable as text — showing hex",
    )


def preview_to_dict(result: PreviewResult) -> dict:
    return {
        "mode": result.mode,
        "encoding": result.encoding,
        "text": result.text,
        "size": result.size,
        "truncated": result.truncated,
        "kind": result.kind,
        "executable": result.executable,
        "note": result.note,
    }
