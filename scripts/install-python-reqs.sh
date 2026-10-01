#!/usr/bin/env bash
# Install Python requirements into the active environment (venv or user).
# Usage: install-python-reqs.sh /path/to/requirements.txt
set -euo pipefail
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
REQ="${1:?requirements.txt path required}"

if [[ ! -f "$REQ" ]]; then
  echo "error: missing $REQ" >&2
  exit 1
fi

# Prefer plain pip inside a virtualenv (--user is invalid there).
if [[ -n "${VIRTUAL_ENV:-}" ]] || python3 -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null; then
  echo "    (venv detected — installing into $VIRTUAL_ENV)"
  python3 -m pip install -r "$REQ"
  exit 0
fi

if python3 -m pip install --user -r "$REQ" 2>/dev/null; then
  exit 0
fi
python3 -m pip install -r "$REQ"
