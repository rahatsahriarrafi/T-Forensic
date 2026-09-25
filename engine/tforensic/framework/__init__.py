"""T Forensic Framework — extensible analysis beyond read-only triage.

Design rules (non-negotiable):
  - Original evidence files are NEVER modified.
  - Writable work happens in: case lab/, xmount --cache overlays, exports/.
  - Plugins and playbooks operate on CaseDB + lab paths, not source images.
"""
from __future__ import annotations

from tforensic.framework.plugin import (
    Plugin,
    PluginContext,
    PluginResult,
    discover_plugins,
    get_plugin,
    list_plugins,
    run_plugin,
)
from tforensic.framework.lab import LabWorkspace, enable_lab, lab_status
from tforensic.framework.playbook import Playbook, list_playbooks, run_playbook

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginResult",
    "discover_plugins",
    "get_plugin",
    "list_plugins",
    "run_plugin",
    "LabWorkspace",
    "enable_lab",
    "lab_status",
    "Playbook",
    "list_playbooks",
    "run_playbook",
]
