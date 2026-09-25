#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/nullx-a/Project_T-Forensic"
cd "$ROOT"
exec "$ROOT/scripts/run-desktop.sh" "$@"
