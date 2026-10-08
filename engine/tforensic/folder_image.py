"""Read-only folder evidence (phone extractions, logical copies, unpacked dumps).

Exposes the same surface as the AD1 parser (root Node tree, read_file, metadata,
close) so Case, the tree, preview, hex, hashes, export and ingest work unchanged.
Never writes to the source folder and never follows directory symlinks.
"""
from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from tforensic.ad1.parser import Node


def _walk(root: Path):
    """Yield (DirEntry, parent_rel) depth-first without following symlinks."""
    stack = [(root, "")]
    while stack:
        d, rel = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            yield e, rel
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append((Path(e.path), f"{rel}/{e.name}" if rel else e.name))
            except OSError:
                pass


def folder_manifest(root: str | Path) -> tuple[str, int, int]:
    """
    SHA-256 over the sorted listing (relative path, type, size, mtime_ns).
    Detects added/removed/changed files without reading every byte.
    Returns (sha256, total_regular_bytes, file_count).
    """
    root = Path(root)
    rows = []
    total = 0
    files = 0
    for e, rel in _walk(root):
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        kind = "l" if stat.S_ISLNK(st.st_mode) else "d" if stat.S_ISDIR(st.st_mode) else "f"
        if kind == "f":
            total += st.st_size
            files += 1
        rows.append(f"{rel}/{e.name}\0{kind}\0{st.st_size}\0{st.st_mtime_ns}")
    h = hashlib.sha256()
    for r in sorted(rows):
        h.update(r.encode("utf-8", "surrogateescape") + b"\n")
    return h.hexdigest(), total, files


def _ts(epoch: float) -> str:
    # AD1-style stamp so meta_format renders it as a UTC time
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%dT%H%M%S.%f")


class FolderImage:
    def __init__(self, path: str | Path):
        self.path = str(Path(path).resolve())
        base = Path(self.path)
        if not base.is_dir():
            raise NotADirectoryError(f"not a folder: {self.path}")
        name = base.name or self.path
        self.root = Node(name=name, is_dir=True, size=0, offset=0, path=name)
        self._real: dict[str, str] = {name: self.path}
        dirs: dict[str, Node] = {"": self.root}
        for e, rel in _walk(base):
            parent = dirs.get(rel)
            if parent is None:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                size = 0 if is_dir else e.stat(follow_symlinks=False).st_size
            except OSError:
                is_dir, size = False, 0
            node = Node(
                name=e.name,
                is_dir=is_dir,
                size=size,
                offset=0,
                path=f"{parent.path}/{e.name}",
            )
            parent.children.append(node)
            self._real[node.path] = e.path
            if is_dir:
                dirs[f"{rel}/{e.name}" if rel else e.name] = node

    def real_path(self, node: Node) -> str:
        return self._real[node.path]

    def read_file(self, node: Node) -> bytes:
        p = self._real.get(node.path)
        if not p or node.is_dir:
            return b""
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode):
            return f"symlink -> {os.readlink(p)}".encode("utf-8", "surrogateescape")
        if not stat.S_ISREG(st.st_mode):
            return b""
        # O_NOATIME keeps access times intact where the kernel allows it
        flags = os.O_RDONLY | getattr(os, "O_NOATIME", 0)
        try:
            fd = os.open(p, flags)
        except PermissionError:
            fd = os.open(p, os.O_RDONLY)
        with os.fdopen(fd, "rb") as f:
            return f.read()

    def metadata(self, node: Node) -> dict:
        p = self._real.get(node.path)
        if not p:
            return {}
        try:
            st = os.lstat(p)
        except OSError as e:
            return {"Error": str(e)}
        attrs: dict = {
            3: str(st.st_size),
            8: _ts(st.st_mtime),
            7: _ts(st.st_atime),
            "Changed (ctime)": _ts(st.st_ctime),
            "Mode": stat.filemode(st.st_mode),
            "Owner UID": str(st.st_uid),
            "Group GID": str(st.st_gid),
            "Inode": str(st.st_ino),
            "Hard links": str(st.st_nlink),
            "Source path": p,
        }
        birth = getattr(st, "st_birthtime", None)
        if birth:
            attrs[9] = _ts(birth)
        if stat.S_ISLNK(st.st_mode):
            try:
                attrs["Symlink target"] = os.readlink(p)
            except OSError:
                pass
        return attrs

    def close(self) -> None:
        pass
