#!/usr/bin/env bash
# Launch Electron desktop shell (installs deps on first run if needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${ROOT}/scripts:${PATH}"

# Hard gate: requirements.txt must be installed before the app runs.
if ! python3 -c "
from tforensic.deps import ensure_requirements
import sys
ok, msg = ensure_requirements()
if not ok:
    print(msg, file=sys.stderr)
    sys.exit(3)
print('requirements.txt OK', flush=True)
"; then
  echo ""
  echo "Fix:  pip install -r \"${ROOT}/requirements.txt\""
  echo "Then: ./scripts/run-desktop.sh"
  exit 3
fi

cd "${ROOT}/desktop"
if [[ ! -d node_modules ]]; then
  echo "Installing desktop dependencies…"
  npm install
fi
exec npx electron .
