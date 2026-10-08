"""Session temp workspace — never mutate source evidence."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


SESSION_ENV = "TFOR_SESSION"
SESSION_ROOT_ENV = "TFOR_SESSION_ROOT"


def default_sessions_root() -> Path:
    override = os.environ.get(SESSION_ROOT_ENV)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "tforensic-sessions"


@dataclass
class SessionMeta:
    id: str
    image_path: str
    image_sha256: str
    image_size: int
    temp_dir: str
    export_dir: str
    created_at: float = field(default_factory=time.time)

    def save(self) -> None:
        path = Path(self.temp_dir) / "session.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, temp_dir: str | Path) -> "SessionMeta":
        data = json.loads(Path(temp_dir).joinpath("session.json").read_text(encoding="utf-8"))
        return cls(**data)


def hash_file(path: str | Path, algo: str = "sha256", chunk: int = 1 << 20) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def create_session(image_path: str | Path, sessions_root: Optional[Path] = None) -> SessionMeta:
    image_path = Path(image_path).resolve()
    if image_path.is_dir():
        from tforensic.folder_image import folder_manifest

        digest, size, _ = folder_manifest(image_path)
    elif image_path.is_file():
        digest, size = hash_file(image_path), image_path.stat().st_size
    else:
        raise FileNotFoundError(f"image not found: {image_path}")

    root = sessions_root or default_sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    temp_dir = root / sid
    export_dir = temp_dir / "export"
    cache_dir = temp_dir / "cache"
    export_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)

    meta = SessionMeta(
        id=sid,
        image_path=str(image_path),
        image_sha256=digest,
        image_size=size,
        temp_dir=str(temp_dir),
        export_dir=str(export_dir),
    )
    meta.save()
    return meta


def resolve_session(session_id: Optional[str] = None) -> SessionMeta:
    """Resolve session from arg, TFOR_SESSION env, or newest under sessions root."""
    sid = session_id or os.environ.get(SESSION_ENV)
    root = default_sessions_root()
    if sid:
        temp = root / sid
        if not (temp / "session.json").is_file():
            raise FileNotFoundError(f"session not found: {sid}")
        return SessionMeta.load(temp)

    if not root.is_dir():
        raise FileNotFoundError("no active session; run: tforensic open <image.ad1>")
    candidates = sorted(
        (p for p in root.iterdir() if (p / "session.json").is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("no active session; run: tforensic open <image.ad1>")
    return SessionMeta.load(candidates[0])


def cleanup_session(session_id: Optional[str] = None, keep_export: bool = False) -> str:
    meta = resolve_session(session_id)
    temp = Path(meta.temp_dir)
    if keep_export:
        export = Path(meta.export_dir)
        if export.is_dir():
            kept = Path(tempfile.gettempdir()) / f"tforensic-export-{meta.id}"
            if kept.exists():
                shutil.rmtree(kept)
            shutil.move(str(export), str(kept))
            shutil.rmtree(temp, ignore_errors=True)
            return str(kept)
    shutil.rmtree(temp, ignore_errors=True)
    return ""


def safe_export_path(export_dir: Path, logical_path: str, name: str) -> Path:
    """Map a logical AD1 path into export_dir without escaping."""
    # Keep basename primarily; nest under hashed parent for collisions.
    safe_name = name.replace("/", "_").replace("\\", "_") or "unnamed"
    parent_key = hashlib.sha1(logical_path.encode("utf-8", "replace")).hexdigest()[:8]
    dest_dir = export_dir / parent_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / safe_name
