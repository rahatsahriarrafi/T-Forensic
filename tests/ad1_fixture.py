"""Build a minimal valid AD1 v4 logical image for tests."""
from __future__ import annotations

import struct
import zlib

BASE = 0x200


def build_sample_ad1(files):
    """One-level AD1: root 'SAMPLE' containing (name, payload_bytes) files."""
    buf = bytearray(0x8000)

    buf[0:16] = b"ADSEGMENTEDFILE\x00"
    struct.pack_into("<Q", buf, 0x28, BASE)

    buf[0x200:0x210] = b"ADLOGICALIMAGE\x00\x00"
    struct.pack_into("<I", buf, BASE + 0x18, 0x10000)
    path = b"SAMPLE"
    struct.pack_into("<I", buf, BASE + 0x2C, len(path))
    buf[BASE + 0x5C : BASE + 0x5C + len(path)] = path
    struct.pack_into("<I", buf, BASE + 0x24, 0x100)

    obj_abs = 0x300
    for i, (name, payload) in enumerate(files):
        nb = name.encode("utf-8")
        is_last = i == len(files) - 1
        next_abs = 0 if is_last else obj_abs + 0x400
        desc_abs = obj_abs + 0x80
        data_abs = obj_abs + 0xA0

        struct.pack_into("<Q", buf, obj_abs + 0x00, 0 if is_last else next_abs - BASE)
        struct.pack_into("<Q", buf, obj_abs + 0x08, 0)
        struct.pack_into("<Q", buf, obj_abs + 0x10, 0)
        struct.pack_into("<Q", buf, obj_abs + 0x18, desc_abs - BASE)
        struct.pack_into("<Q", buf, obj_abs + 0x20, len(payload))
        struct.pack_into("<I", buf, obj_abs + 0x2C, len(nb))
        buf[obj_abs + 0x30 : obj_abs + 0x30 + len(nb)] = nb

        comp = zlib.compress(payload)
        struct.pack_into("<Q", buf, desc_abs + 0x00, 1)
        struct.pack_into("<Q", buf, desc_abs + 0x08, data_abs - BASE)
        buf[data_abs : data_abs + len(comp)] = comp
        obj_abs += 0x400

    return bytes(buf)
