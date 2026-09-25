"""Playbooks — chain plugins + ingest steps like an analysis framework."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from tforensic.casedb import CaseDB
from tforensic.framework.lab import LabWorkspace
from tforensic.framework.plugin import ProgressCB, run_plugin
from tforensic.ingest.pipeline import run_ingest

BUILTIN_DIR = Path(__file__).resolve().parent / "playbooks"


@dataclass
class Playbook:
    name: str
    description: str = ""
    steps: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Playbook":
        return cls(
            name=data.get("name") or "unnamed",
            description=data.get("description") or "",
            steps=list(data.get("steps") or []),
        )

    def as_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "steps": self.steps}


def _load_playbook_file(path: Path) -> Playbook:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "name" not in data:
        data["name"] = path.stem
    return Playbook.from_dict(data)


def list_playbooks() -> list[dict]:
    out = []
    dirs = [BUILTIN_DIR, Path.home() / ".tforensic" / "playbooks"]
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                pb = _load_playbook_file(p)
                out.append({**pb.as_dict(), "path": str(p)})
            except Exception as e:
                out.append({"name": p.stem, "error": str(e), "path": str(p)})
    return out


def get_playbook(name: str) -> Playbook:
    for item in list_playbooks():
        if item.get("name") == name and not item.get("error"):
            return _load_playbook_file(Path(item["path"]))
    # try path
    p = Path(name)
    if p.is_file():
        return _load_playbook_file(p)
    raise FileNotFoundError(f"playbook not found: {name}")


def run_playbook(
    name: str,
    case: CaseDB,
    *,
    evidence_id: Optional[str] = None,
    progress: Optional[ProgressCB] = None,
) -> dict:
    pb = get_playbook(name)
    results = []
    n = max(len(pb.steps), 1)
    case.log_custody("playbook_start", f"{pb.name} steps={len(pb.steps)}")

    def report(i, frac, msg):
        if progress:
            progress((i + frac) / n, f"[{pb.name}] {msg}", None)

    for i, step in enumerate(pb.steps):
        kind = (step.get("type") or step.get("action") or "").lower()
        report(i, 0.05, f"step {i+1}: {kind}")
        try:
            if kind == "lab_enable":
                st = LabWorkspace(case).enable(virtual_write=bool(step.get("virtual_write")))
                results.append({"step": i, "type": kind, "ok": True, "result": st.as_dict()})
            elif kind == "ingest":
                eid = step.get("evidence_id") or evidence_id
                if not eid:
                    evs = case.list_evidence()
                    if not evs:
                        raise RuntimeError("no evidence for ingest step")
                    eid = evs[-1]["id"]
                mods = step.get("modules")

                def cb(p, m, e=None, _i=i):
                    report(_i, 0.1 + 0.8 * p, m)

                r = run_ingest(case, eid, cb, modules=mods)
                results.append({"step": i, "type": kind, "ok": True, "result": r})
            elif kind == "plugin":
                pname = step.get("plugin") or step.get("name")
                if not pname:
                    raise RuntimeError("plugin step needs plugin name")

                def cb(p, m, e=None, _i=i):
                    report(_i, 0.1 + 0.8 * p, m)

                r = run_plugin(
                    pname,
                    case,
                    evidence_id=step.get("evidence_id") or evidence_id,
                    params=step.get("params") or {},
                    progress=cb,
                )
                results.append({"step": i, "type": kind, "ok": r.ok, "result": r.as_dict()})
            elif kind == "note":
                case.add_note(step.get("body") or f"Playbook {pb.name} checkpoint")
                results.append({"step": i, "type": kind, "ok": True})
            else:
                results.append({"step": i, "type": kind, "ok": False, "error": f"unknown step type: {kind}"})
        except Exception as e:
            results.append({"step": i, "type": kind, "ok": False, "error": str(e)})
            if step.get("stop_on_error", True):
                break
        report(i, 1.0, f"step {i+1} done")

    ok = all(r.get("ok") for r in results) if results else False
    case.log_custody("playbook_done", f"{pb.name} ok={ok}")
    if progress:
        progress(1.0, f"playbook {pb.name} complete", 0)
    return {
        "playbook": pb.name,
        "ok": ok,
        "steps": results,
        "finished_at": time.time(),
    }
