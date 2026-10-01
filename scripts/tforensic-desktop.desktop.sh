#!/usr/bin/env bash
# Launcher used by the .desktop entry (no hardcoded home paths).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec "$ROOT/scripts/run-desktop.sh" "$@"
