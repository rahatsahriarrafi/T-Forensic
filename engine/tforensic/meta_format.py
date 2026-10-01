"""Human-readable AD1 / NTFS metadata formatting."""
from __future__ import annotations

import re
import struct
from datetime import datetime, timezone
from typing import Any, Optional

# AccessData FTK Imager AD1 attribute IDs → friendly labels
AD1_ATTR_NAMES: dict[int, str] = {
    2: "Item type",
    3: "Logical size",
    4: "Physical size",
    7: "Accessed",
    8: "Modified",
    9: "Created",
    13: "Compressed",
    14: "Encrypted",
    30: "Has integrity hash",
    4097: "DOS 8.3 name",
    4098: "Is directory",
    4099: "Is deleted",
    4100: "Is unused",
    4101: "Is allocated",
    20481: "MD5",
    20482: "SHA-1",
    40961: "MFT entry",
    40962: "MFT modified",
    40963: "NTFS in use",
    40964: "NTFS directory",
    40965: "NTFS deleted flag",
    40966: "NTFS unused flag",
    40967: "Owner SID",
    40968: "Owner name",
    40969: "Group SID",
    40970: "Group name",
    40988: "SI Created",
    40989: "SI Modified",
    40990: "SI MFT changed",
    40991: "SI Accessed",
    40992: "USN low",
    40993: "USN high",
    40994: "FN flags A",
    40995: "FN flags B",
    40996: "FN Created (alt)",
    40997: "FN Modified (alt)",
    40998: "FN MFT changed (alt)",
    40999: "FN Accessed (alt)",
    41000: "File name",
    41001: "FN logical size",
    41002: "FN physical size",
    41003: "FN Created",
    41004: "FN Modified",
    41005: "FN MFT changed",
    41006: "FN Accessed",
    41007: "FN DOS name",
    41008: "FN DOS logical size",
    41009: "FN DOS physical size",
    41010: "FN DOS Created",
    41011: "FN DOS Modified",
    41012: "FN DOS MFT changed",
    41013: "FN DOS Accessed",
}

# ACE field offsets within each 0x1000-spaced ACL slot (AccessData)
_ACE_FIELD = {
    0: "ACE flags / mask id",
    4: "ACE SID",
    5: "ACE account",
    6: "ACE access mask",
    7: "ACE: read",
    8: "ACE: write",
    9: "ACE: execute",
    10: "ACE: delete",
    16: "ACE: read ctrl",
    17: "ACE: write dac",
    18: "ACE: write owner",
    19: "ACE: sync",
}

_AD1_TS = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(?:\.(\d+))?$")


def format_ad1_timestamp(value: str) -> Optional[str]:
    """20210429T182217.599865 → 2021-04-29 18:22:17 UTC."""
    m = _AD1_TS.match((value or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    try:
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _ace_label(key: int) -> Optional[str]:
    if key < 0x01000000:
        return None
    slot = (key - 0x01000000) // 0x1000
    field = (key - 0x01000000) % 0x1000
    base = _ACE_FIELD.get(field)
    if not base:
        return f"ACL[{slot}] field {field}"
    return f"ACL[{slot}] {base}"


def attr_label(key: int | str) -> str:
    try:
        k = int(key)
    except (TypeError, ValueError):
        return str(key)
    if k in AD1_ATTR_NAMES:
        return AD1_ATTR_NAMES[k]
    ace = _ace_label(k)
    if ace:
        return ace
    return f"Attribute {k}"


def format_attr_value(key: int | str, value: Any) -> dict[str, str]:
    """Return {label, raw, display, kind}."""
    label = attr_label(key)
    raw = "" if value is None else str(value)
    display = raw
    kind = "text"
    ts = format_ad1_timestamp(raw)
    if ts:
        display = f"{ts}  |  {raw}"
        kind = "time"
    elif raw.lower() in ("true", "false"):
        kind = "bool"
    elif re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        kind = "hash"
        label = label if "MD5" in label or "SHA" in label else f"{label} (MD5?)"
    elif re.fullmatch(r"[0-9a-fA-F]{40}", raw):
        kind = "hash"
    elif raw.startswith("S-1-"):
        kind = "sid"
    return {"key": str(key), "label": label, "raw": raw, "display": display, "kind": kind}


def format_attrs(attrs: dict) -> list[dict[str, str]]:
    rows = []
    for k, v in attrs.items():
        try:
            ki = int(k)
        except (TypeError, ValueError):
            ki = k
        rows.append(format_attr_value(ki, v))
    # Put times + identity first for quick reading
    priority = {
        "time": 0,
        "sid": 1,
        "hash": 2,
        "bool": 4,
        "text": 3,
    }
    rows.sort(key=lambda r: (priority.get(r["kind"], 9), r["label"]))
    return rows


def parse_recycle_i(data: bytes) -> Optional[dict[str, Any]]:
    """Parse Windows Recycle Bin $I* header (Vista+)."""
    if len(data) < 28:
        return None
    ver = struct.unpack_from("<Q", data, 0)[0]
    if ver not in (1, 2):
        return None
    size = struct.unpack_from("<Q", data, 8)[0]
    ft = struct.unpack_from("<Q", data, 16)[0]
    unix = (ft / 10_000_000.0) - 11_644_473_600
    try:
        dt = datetime.fromtimestamp(unix, tz=timezone.utc)
        deleted = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        deleted = None
    if ver >= 2:
        plen = struct.unpack_from("<I", data, 24)[0]
        path = data[28 : 28 + plen * 2].decode("utf-16-le", "replace").rstrip("\x00")
    else:
        path = data[24:].decode("utf-16-le", "replace").rstrip("\x00")
    return {
        "version": ver,
        "original_size": size,
        "deleted_filetime": ft,
        "deleted_utc": deleted,
        "original_path": path,
    }
