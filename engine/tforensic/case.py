"""Active case session: AD1 image + path index + temp workspace."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from tforensic.ad1.parser import AD1, Node
from tforensic.workspace import SessionMeta, create_session, resolve_session, safe_export_path


class Case:
    def __init__(self, meta: SessionMeta, img: AD1):
        self.meta = meta
        self.img = img
        self.path_index: dict[str, Node] = {}
        self.files: list[Node] = []
        self._index(img.root)

    def _index(self, node: Node) -> None:
        self.path_index[node.path] = node
        if node.is_file:
            self.files.append(node)
        for c in node.children:
            self._index(c)

    def get(self, path: str) -> Optional[Node]:
        if not path:
            return None
        if path in self.path_index:
            return self.path_index[path]
        # tolerate leading/trailing slashes and backslashes
        alt = path.strip().replace("\\", "/").strip("/")
        if alt in self.path_index:
            return self.path_index[alt]
        # match by suffix (UI sometimes drops root prefix)
        for p, node in self.path_index.items():
            if p.endswith("/" + alt) or p == alt or p.endswith(alt):
                return node
        return None

    def _readable(self, node: Optional[Node]) -> bool:
        if node is None:
            return False
        if not node.is_dir:
            return True
        # Fallback: dir-flagged node that still carries file chunks
        return bool(node.chunk_desc_rel and node.size > 0)

    def read(self, path: str) -> bytes:
        node = self.get(path)
        if not self._readable(node):
            raise FileNotFoundError(f"file not found: {path}")
        return self._cached_read(node.path)

    @lru_cache(maxsize=256)
    def _cached_read(self, path: str) -> bytes:
        node = self.path_index[path]
        return self.img.read_file(node)

    def export_file(self, path: str, dest: Optional[str] = None) -> str:
        node = self.get(path)
        if not self._readable(node):
            raise FileNotFoundError(f"file not found: {path}")
        data = self.read(path)
        if dest:
            out = Path(dest)
            if out.is_dir():
                out = out / node.name
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = safe_export_path(Path(self.meta.export_dir), path, node.name)
        out.write_bytes(data)
        resolved = str(out.resolve())
        try:
            last = Path(self.meta.export_dir) / ".tff_last_export"
            last.write_text(resolved + "\n", encoding="utf-8")
        except OSError:
            pass
        return resolved

    def close(self) -> None:
        self._cached_read.cache_clear()
        self.img.close()

    def info(self) -> dict:
        return {
            "kind": "ad1",
            "session_id": self.meta.id,
            "image": Path(self.meta.image_path).name,
            "image_path": self.meta.image_path,
            "image_sha256": self.meta.image_sha256,
            "image_size": self.meta.image_size,
            "temp_dir": self.meta.temp_dir,
            "export_dir": self.meta.export_dir,
            "root": self.img.root.path,
            "dirs": sum(1 for n in self.path_index.values() if n.is_dir),
            "files": len(self.files),
        }


def open_case(image_path: str) -> Case:
    meta = create_session(image_path)
    img = AD1(meta.image_path)
    return Case(meta, img)


def load_case(session_id: Optional[str] = None) -> Case:
    meta = resolve_session(session_id)
    img = AD1(meta.image_path)
    return Case(meta, img)


def tree_dict(node: Node) -> dict:
    d = {
        "name": node.name,
        "path": node.path,
        "is_dir": node.is_dir,
        "size": node.size,
    }
    if node.is_dir:
        d["children"] = [
            tree_dict(c)
            for c in sorted(node.children, key=lambda n: (not n.is_dir, n.name.lower()))
        ]
    return d


def print_tree(node: Node, prefix: str = "", path_filter: Optional[str] = None) -> None:
    if path_filter:
        # Print subtree rooted at path_filter if under node.
        target = None

        def find(n: Node):
            nonlocal target
            if n.path == path_filter or n.path.endswith("/" + path_filter.lstrip("/")):
                target = n
                return
            for c in n.children:
                find(c)

        find(node)
        if target is None:
            raise FileNotFoundError(f"path not found: {path_filter}")
        node = target
        prefix = ""

    mark = "/" if node.is_dir else ""
    size = f" ({node.size})" if node.is_file else ""
    print(f"{prefix}{node.name}{mark}{size}")
    if not node.is_dir:
        return
    kids = sorted(node.children, key=lambda n: (not n.is_dir, n.name.lower()))
    for i, c in enumerate(kids):
        last = i == len(kids) - 1
        branch = "└── " if last else "├── "
        cont = "    " if last else "│   "
        _print_child(c, prefix + branch, prefix + cont)


def _print_child(node: Node, line_prefix: str, child_prefix: str) -> None:
    mark = "/" if node.is_dir else ""
    size = f" ({node.size})" if node.is_file else ""
    print(f"{line_prefix}{node.name}{mark}{size}")
    if not node.is_dir:
        return
    kids = sorted(node.children, key=lambda n: (not n.is_dir, n.name.lower()))
    for i, c in enumerate(kids):
        last = i == len(kids) - 1
        branch = "└── " if last else "├── "
        cont = "    " if last else "│   "
        _print_child(c, child_prefix + branch, child_prefix + cont)
