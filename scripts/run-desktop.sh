#!/usr/bin/env bash
# Launch Electron desktop shell (installs deps on first run if needed).
set -euo pipefail
# Follow ~/.local/bin/tforensic-desktop → …/scripts/run-desktop.sh
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/scripts/tff-python-env.sh"
tff_python_env "$ROOT"

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${ROOT}/scripts:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
# Prefer venv python for the Electron-spawned engine
export TFOR_PYTHON
TFOR_PYTHON="$(tff_python)"
export TFOR_PYTHON

# Hard gate: requirements.txt must be installed before the app runs.
if ! "$TFOR_PYTHON" -c "
from tforensic.deps import ensure_requirements
import sys
ok, msg = ensure_requirements()
if not ok:
    print(msg, file=sys.stderr)
    sys.exit(3)
print('requirements.txt OK', flush=True)
"; then
  echo ""
  echo "Fix:  cd \"$ROOT\" && ./install.sh"
  echo "   or: \"$ROOT/scripts/install-python-reqs.sh\""
  echo "Then: tforensic-desktop"
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
  if [[ -x "${ROOT}/scripts/desktop-npm-install.sh" ]]; then
    "${ROOT}/scripts/desktop-npm-install.sh"
  else
    npm install
  fi
fi
if [[ ! -x "$ELECTRON_BIN" ]]; then
  echo "error: Electron binary missing after npm install: $ELECTRON_BIN" >&2
  exit 4
fi

exec "$ELECTRON_BIN" "${ROOT}/desktop" "$@"
