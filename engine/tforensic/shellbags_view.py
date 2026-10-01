"""Windows ShellBags (BagMRU) from UsrClass.dat / NTUSER.DAT."""
from __future__ import annotations

import os
import tempfile
from typing import Any, Optional


def _utf16_names(data: bytes) -> list[str]:
    names: list[str] = []
    i = 0
    while i + 1 < len(data):
        if data[i + 1] == 0 and 32 <= data[i] < 127:
            chars: list[str] = []
            j = i
            while j + 1 < len(data) and data[j + 1] == 0 and 32 <= data[j] < 127:
                chars.append(chr(data[j]))
                j += 2
            if len(chars) >= 2:
                s = "".join(chars)
                if s.isprintable():
                    names.append(s)
            i = j
        else:
            i += 1
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _shell_item_label(data: bytes) -> str:
    """Best-effort folder/item name from a BagMRU shell-item blob."""
    try:
        import pyfwsi

        item_list = pyfwsi.item_list()
        item_list.copy_from_byte_stream(data)
        for i in range(item_list.get_number_of_items()):
            item = item_list.get_item(i)
            for attr in ("get_name", "get_long_name", "get_short_name"):
                if hasattr(item, attr):
                    try:
                        v = getattr(item, attr)()
                        if v and str(v).strip():
                            return str(v).strip()
                    except Exception:
                        pass
            # file_entry style
            if hasattr(item, "get_file_entry_extension_block"):
                try:
                    ext = item.get_file_entry_extension_block()
                    if ext and hasattr(ext, "get_long_name"):
                        v = ext.get_long_name()
                        if v:
                            return str(v).strip()
                except Exception:
                    pass
    except Exception:
        pass
    names = _utf16_names(data)
    # Prefer short folder-like tokens over GUID/path noise
    for n in names:
        u = n.upper()
        if u in {"DCIM", "CAMERA", "PICTURES", "CONTACT", "DOWNLOADS", "DESKTOP"}:
            return n
        if n.startswith("LG ") or n.startswith("\\\\?\\"):
            if n.startswith("LG "):
                return n
    for n in names:
        if 2 <= len(n) <= 64 and not n.startswith("{") and "http" not in n.lower():
            if not n.startswith("Microsoft.") and " " in n or n.isalnum() or n in names[:3]:
                return n
    return names[0] if names else ""


def _walk_bagmru(key, path_labels: list[str], rows: list[dict], depth: int = 0) -> None:
    label_here = path_labels[-1] if path_labels else "BagMRU"
    full = " / ".join(path_labels) if path_labels else "BagMRU"
    # Parse numeric / empty-named values as shell items
    child_labels: dict[str, str] = {}
    for vi in range(key.get_number_of_values()):
        val = key.get_value(vi)
        name = val.get_name() or ""
        if name in {"MRUListEx", "NodeSlot", "NodeSlots", "MRUList"}:
            continue
        try:
            data = val.get_data()
        except Exception:
            continue
        if not data or len(data) < 4:
            continue
        item_name = _shell_item_label(data)
        if not item_name:
            continue
        child_labels[name] = item_name
        rows.append(
            {
                "bag_path": full + (f" / [{name}]" if name else ""),
                "name": item_name,
                "key": name,
                "depth": depth,
            }
        )
    for i in range(key.get_number_of_sub_keys()):
        sk = key.get_sub_key(i)
        sk_name = sk.get_name() or ""
        # Subkey name is usually a digit matching a value
        folder = child_labels.get(sk_name) or sk_name
        _walk_bagmru(sk, path_labels + [folder], rows, depth + 1)


def parse_shellbags(data: bytes, name: str = "") -> dict[str, Any]:
    """Parse UsrClass.dat / NTUSER.DAT BagMRU into readable folder paths."""
    try:
        import pyregf
    except ImportError:
        return {
            "error": "pyregf not installed (python3-libregf)",
            "hint": "sudo apt install python3-libregf python3-libfwsi",
            "entries": [],
        }

    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".dat", prefix="tff_hive_")
        os.write(fd, data)
        os.close(fd)
        f = pyregf.file()
        f.open(path)
        root = f.get_root_key()

        # Find BagMRU under Local Settings\...\Shell\BagMRU (UsrClass)
        # or Software\Microsoft\Windows\Shell\BagMRU (NTUSER)
        candidates = [
            ["Local Settings", "Software", "Microsoft", "Windows", "Shell", "BagMRU"],
            ["Software", "Microsoft", "Windows", "Shell", "BagMRU"],
            ["Software", "Microsoft", "Windows", "ShellNoRoam", "BagMRU"],
        ]
        bag = None
        used = None
        for parts in candidates:
            k = root
            ok = True
            for p in parts:
                k = k.get_sub_key_by_name(p)
                if k is None:
                    ok = False
                    break
            if ok:
                bag = k
                used = "\\".join(parts)
                break
        if bag is None:
            # fallback: search
            def find_bag(key, depth=0):
                if (key.get_name() or "") == "BagMRU":
                    return key
                if depth > 10:
                    return None
                for i in range(key.get_number_of_sub_keys()):
                    hit = find_bag(key.get_sub_key(i), depth + 1)
                    if hit:
                        return hit
                return None

            bag = find_bag(root)
            used = "BagMRU (found)"

        entries: list[dict] = []
        if bag:
            _walk_bagmru(bag, ["BagMRU"], entries)

        # Build reconstructed paths where parent/child chain is meaningful
        paths: list[str] = []
        interesting: list[dict] = []
        keys_up = ("DCIM", "CAMERA", "LG", "Q7", "CONTACT", "PICTURES", "MTP", "PHONE")
        for e in entries:
            n = e.get("name") or ""
            u = n.upper()
            chain = e.get("bag_path") or ""
            if any(k in u for k in keys_up) or any(k in chain.upper() for k in keys_up):
                interesting.append(e)
            if u in {"DCIM", "CAMERA", "CONTACT", "PICTURES"} or n.startswith("LG "):
                paths.append(f"{chain} → {n}")

        # Prefer a compact phone path summary
        phone_paths = []
        for e in interesting:
            phone_paths.append(f"{e.get('bag_path')} → {e.get('name')}")

        note = (
            "ShellBags show folders the user browsed in Explorer "
            "(including phone / portable device paths)."
        )
        return {
            "hive": name,
            "bagmru_key": used,
            "entries": entries,
            "interesting": interesting,
            "phone_paths": phone_paths,
            "note": note,
            "count": len(entries),
        }
    except Exception as e:
        return {"error": str(e), "entries": [], "hive": name}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def shellbags_summary_text(info: dict[str, Any]) -> str:
    if info.get("error") and not info.get("entries"):
        return f"ShellBags parse error: {info.get('error')}\n{info.get('hint') or ''}".strip()
    lines = [
        f"Hive: {info.get('hive') or '?'}",
        f"BagMRU: {info.get('bagmru_key') or '?'}",
        f"Entries: {info.get('count', 0)}",
        "",
        info.get("note") or "",
        "",
    ]
    phone = info.get("phone_paths") or []
    if phone:
        lines.append("Phone / portable / notable paths:")
        for p in phone[:60]:
            lines.append(f"  {p}")
    else:
        lines.append("Notable folder names:")
        for e in (info.get("interesting") or info.get("entries") or [])[:40]:
            lines.append(f"  {e.get('bag_path')} → {e.get('name')}")
    # Highlight DCIM → Camera chain if present
    names = [e.get("name") for e in info.get("entries") or []]
    if "DCIM" in names and "Camera" in names:
        lines.append("")
        lines.append("Hint: under DCIM, browsed folder includes → Camera")
    return "\n".join(lines)
