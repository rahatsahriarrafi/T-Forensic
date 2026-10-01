"""Pure-stdlib parser for AccessData AD1 logical images (v4).

Read-only: never mutates the source image. Offsets are little-endian;
relative offsets are against BASE (0x200).
"""
from __future__ import annotations

import mmap
import struct
import zlib
from dataclasses import dataclass, field

BASE = 0x200
DEFAULT_CHUNK = 0x10000
_CHUNK_WINDOW = 0x12000

KEY_NAME = 0xA028
KEY_CREATED = 0xA01C
KEY_MODIFIED = 0xA01D
KEY_ACCESSED = 0xA01E


class AD1Error(Exception):
    pass


@dataclass
class Node:
    name: str
    is_dir: bool
    size: int
    offset: int
    meta_rel: int = 0
    chunk_desc_rel: int = 0
    path: str = ""
    children: list["Node"] = field(default_factory=list)

    @property
    def is_file(self) -> bool:
        return not self.is_dir


class AD1:
    def __init__(self, path: str):
        self.path = path
        self._f = open(path, "rb")
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self._validate()
        self.chunk_size = self._u32(BASE + 0x18) or DEFAULT_CHUNK
        self.root = self._build_tree()

    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self._mm, off)[0]

    def _u64(self, off: int) -> int:
        return struct.unpack_from("<Q", self._mm, off)[0]

    def _bytes(self, off: int, n: int) -> bytes:
        return self._mm[off : off + n]

    def _validate(self) -> None:
        if self._mm[0:15] != b"ADSEGMENTEDFILE":
            raise AD1Error("not an AD1 file (missing ADSEGMENTEDFILE signature)")
        logical = self._u64(0x28)
        if logical != BASE or self._mm[BASE : BASE + 14] != b"ADLOGICALIMAGE":
            raise AD1Error("unexpected logical-image header location/signature")

    def _build_tree(self) -> Node:
        path_len = self._u32(BASE + 0x2C)
        root_path = self._bytes(BASE + 0x5C, path_len).decode("utf-8", "replace")
        root = Node(
            name=root_path,
            is_dir=True,
            size=0,
            offset=BASE,
            meta_rel=0x80,
            path=root_path,
        )
        first_child_rel = self._u32(BASE + 0x24)
        if first_child_rel:
            visited: set[int] = set()
            root.children = self._walk_siblings(
                BASE + first_child_rel, root_path, visited
            )
        return root

    def _walk_siblings(self, off: int, parent_path: str, visited: set) -> list:
        nodes = []
        guard = 0
        while off and off + 0x30 <= len(self._mm):
            if off in visited:
                break
            visited.add(off)
            guard += 1
            if guard > 1_000_000:
                raise AD1Error("sibling list too long (corrupt?)")

            next_rel = self._u64(off + 0x00)
            child_rel = self._u64(off + 0x08)
            meta_rel = self._u64(off + 0x10)
            chunk_desc_rel = self._u64(off + 0x18)
            size = self._u64(off + 0x20)
            name_len = self._u32(off + 0x2C)
            name = self._bytes(off + 0x30, name_len).decode("utf-8", "replace")

            is_dir = child_rel != 0
            node = Node(
                name=name,
                is_dir=is_dir,
                size=size,
                offset=off,
                meta_rel=meta_rel,
                chunk_desc_rel=chunk_desc_rel,
                path=parent_path + "/" + name,
            )
            if child_rel:
                node.children = self._walk_siblings(
                    BASE + child_rel, node.path, visited
                )
            # FTK custom-content often stores real files (SAM/SYSTEM/…) as
            # folders with a single $DSC sidecar while chunk data holds the
            # hive bytes. Treat those as files so export/read work.
            if (
                node.chunk_desc_rel
                and node.size > 0
                and node.children
                and all(c.name == "$DSC" for c in node.children)
            ):
                node.is_dir = False
            nodes.append(node)
            off = BASE + next_rel if next_rel else 0
        return nodes

    def read_file(self, node: Node) -> bytes:
        # Chunk payload may exist even when AD1 attached sidecar children.
        if not node.chunk_desc_rel:
            return b""
        if node.is_dir and not node.size:
            return b""
        desc = BASE + node.chunk_desc_rel
        num = self._u64(desc)
        out = bytearray()
        for i in range(num):
            chunk_rel = self._u64(desc + 8 + i * 8)
            chunk_off = BASE + chunk_rel
            window = self._mm[chunk_off : chunk_off + _CHUNK_WINDOW]
            out += zlib.decompressobj().decompress(window)
        return bytes(out)

    def metadata(self, node: Node) -> dict:
        attrs: dict[int, str] = {}
        if not node.meta_rel:
            return attrs
        off = BASE + node.meta_rel
        seen: set[int] = set()
        while off and off + 20 <= len(self._mm) and off not in seen:
            seen.add(off)
            next_rel = self._u64(off + 0x00)
            key = self._u32(off + 0x0C)
            vlen = self._u32(off + 0x10)
            if vlen > 1 << 20:
                break
            val = self._bytes(off + 0x14, vlen).decode("utf-8", "replace")
            attrs[key] = val
            off = BASE + next_rel if next_rel else 0
        return attrs

    def close(self) -> None:
        self._mm.close()
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
