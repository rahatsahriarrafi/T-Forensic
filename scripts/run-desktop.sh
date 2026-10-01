#!/usr/bin/env bash
# Launch Electron desktop shell (installs deps on first run if needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${ROOT}/scripts:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

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
ELECTRON_BIN="${ROOT}/desktop/node_modules/.bin/electron"
if [[ ! -x "$ELECTRON_BIN" ]]; then
  echo "Installing desktop dependencies…"
  if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm/node not found — install Node.js, then re-run ./update.sh" >&2
    exit 4
  fi
  npm install
fi
if [[ ! -x "$ELECTRON_BIN" ]]; then
  echo "error: Electron binary missing after npm install: $ELECTRON_BIN" >&2
  exit 4
fi

# Prefer direct electron binary (more reliable than npx from app-menu PATH).
exec "$ELECTRON_BIN" "${ROOT}/desktop" "$@"
