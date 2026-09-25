#!/usr/bin/env bash
# Packaged resource name used by Electron extraResources
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m tforensic "$@"
