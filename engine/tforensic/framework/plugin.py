"""Plugin SDK — drop-in analysis modules for the T Forensic framework."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from tforensic.casedb import CaseDB, default_cases_root


ProgressCB = Callable[[float, str, Optional[float]], None]


@dataclass
class PluginResult:
    ok: bool
    plugin: str
    summary: str = ""
    artifacts: list[dict] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PluginContext:
    """Runtime context passed to every plugin."""

    case: CaseDB
    evidence_id: Optional[str] = None
    lab_dir: Optional[Path] = None
    params: dict = field(default_factory=dict)
    progress: Optional[ProgressCB] = None

    def report(self, fraction: float, message: str, eta: Optional[float] = None) -> None:
        if self.progress:
            self.progress(fraction, message, eta)

    def write_lab(self, relative: str, data: bytes | str) -> Path:
        """Write into the case lab/ sandbox (never into evidence)."""
        if not self.lab_dir:
            raise RuntimeError("lab not enabled — run: tforensic lab enable")
        dest = (self.lab_dir / relative).resolve()
        if not str(dest).startswith(str(self.lab_dir.resolve())):
            raise RuntimeError("refusing path escape from lab/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            dest.write_text(data, encoding="utf-8")
        else:
            dest.write_bytes(data)
        return dest

    def add_artifact(self, category: str, label: str, path: str = "", detail: Optional[dict] = None) -> None:
        if not self.evidence_id:
            # attach to first evidence if any
            evs = self.case.list_evidence()
            eid = evs[0]["id"] if evs else "lab"
        else:
            eid = self.evidence_id
        self.case.add_artifact(
            {
                "evidence_id": eid,
                "module": "plugin",
                "category": category,
                "label": label,
                "path": path or None,
                "detail": detail or {},
            }
        )


class Plugin(ABC):
    """Subclass this in ~/.tforensic/plugins/my_plugin.py"""

    name: str = "unnamed"
    version: str = "0.1"
    description: str = ""
    # requires_lab: True means plugin may write reconstructed/working files
    requires_lab: bool = False

    @abstractmethod
    def run(self, ctx: PluginContext) -> PluginResult:
        ...


_REGISTRY: dict[str, Plugin] = {}
_LOADED = False


def _builtin_plugins() -> list[Plugin]:
    from tforensic.framework.builtins import (
        HashSweepPlugin,
        StringsHuntPlugin,
        TimelineExportPlugin,
        CorrelationPlugin,
    )

    return [
        HashSweepPlugin(),
        StringsHuntPlugin(),
        TimelineExportPlugin(),
        CorrelationPlugin(),
    ]


def _load_dir(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"tfor_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            continue
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (
                isinstance(obj, type)
                and issubclass(obj, Plugin)
                and obj is not Plugin
            ):
                try:
                    inst = obj()
                    _REGISTRY[inst.name] = inst
                except Exception:
                    continue


def discover_plugins(extra_dirs: Optional[list[Path]] = None) -> dict[str, Plugin]:
    global _LOADED
    _REGISTRY.clear()
    for p in _builtin_plugins():
        _REGISTRY[p.name] = p
    # bundled examples
    here = Path(__file__).resolve().parent / "plugins"
    _load_dir(here)
    # user plugins
    user = Path.home() / ".tforensic" / "plugins"
    _load_dir(user)
    if extra_dirs:
        for d in extra_dirs:
            _load_dir(Path(d))
    _LOADED = True
    return dict(_REGISTRY)


def list_plugins() -> list[dict]:
    if not _LOADED:
        discover_plugins()
    return [
        {
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "requires_lab": p.requires_lab,
        }
        for p in sorted(_REGISTRY.values(), key=lambda x: x.name)
    ]


def get_plugin(name: str) -> Plugin:
    if not _LOADED:
        discover_plugins()
    if name not in _REGISTRY:
        raise KeyError(f"plugin not found: {name}. Available: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]


def run_plugin(
    name: str,
    case: CaseDB,
    *,
    evidence_id: Optional[str] = None,
    params: Optional[dict] = None,
    progress: Optional[ProgressCB] = None,
) -> PluginResult:
    plugin = get_plugin(name)
    lab = Path(case.info().path) / "lab"
    if plugin.requires_lab and not lab.is_dir():
        lab.mkdir(parents=True, exist_ok=True)
        case.log_custody("lab_auto_enable", f"plugin {name} required lab/")
    ctx = PluginContext(
        case=case,
        evidence_id=evidence_id,
        lab_dir=lab if lab.is_dir() else None,
        params=params or {},
        progress=progress,
    )
    t0 = time.time()
    try:
        result = plugin.run(ctx)
        case.log_custody(
            "plugin_run",
            f"{name} ok={result.ok} {result.summary} ({time.time()-t0:.1f}s)",
        )
        return result
    except Exception as e:
        err = traceback.format_exc()
        case.log_custody("plugin_error", f"{name}: {e}")
        return PluginResult(ok=False, plugin=name, error=err, summary=str(e))
