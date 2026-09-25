#!/usr/bin/env bash
# Launch Electron desktop shell (installs deps on first run if needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}/desktop"
if [[ ! -d node_modules ]]; then
  echo "Installing desktop dependencies…"
  npm install
fi
export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${ROOT}/scripts:${PATH}"
exec npx electron .
