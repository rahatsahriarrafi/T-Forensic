#!/usr/bin/env bash
# Install Python requirements for TFF.
# On Kali/Debian (PEP 668), creates repo/.venv automatically — no
# --break-system-packages needed for a normal install.
# Usage: install-python-reqs.sh [/path/to/requirements.txt]
set -euo pipefail
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
REQ="${1:-$ROOT/requirements.txt}"

if [[ ! -f "$REQ" ]]; then
  echo "error: missing $REQ" >&2
  exit 1
fi

# shellcheck source=/dev/null
. "$ROOT/scripts/tff-python-env.sh"

in_venv() {
  [[ -n "${VIRTUAL_ENV:-}" ]] && return 0
  python3 -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null
}

ensure_project_venv() {
  local venv="$ROOT/.venv"
  if [[ -x "$venv/bin/python3" ]]; then
    # Apt Python bindings (pyscca/pyregf/pyfwsi) live on system Python —
    # enable system-site-packages so the project venv can import them.
    if [[ -f "$venv/pyvenv.cfg" ]]; then
      if grep -q '^include-system-site-packages = false' "$venv/pyvenv.cfg"; then
        echo "    Enabling system-site-packages in $venv (for python3-libscca / libregf / libfwsi)"
        sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' "$venv/pyvenv.cfg"
      fi
    fi
    return 0
  fi
  echo "    Creating project venv: $venv"
  echo "    (Kali/Debian PEP 668 — venv with system-site-packages for apt Python bindings)"
  # --system-site-packages: see python3-libscca / python3-libregf / python3-libfwsi
  if ! python3 -m venv --system-site-packages "$venv"; then
    echo "error: could not create venv. On Kali/Debian run:" >&2
    echo "  sudo apt install python3-venv python3-full" >&2
    exit 1
  fi
  "$venv/bin/python3" -m ensurepip --upgrade 2>/dev/null || true
  "$venv/bin/python3" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
}

pip_ok() {
  local py="$1"
  "$py" -m pip install -r "$REQ"
}

# 1) Active venv (user already activated something)
if in_venv; then
  # If it's our project .venv, ensure system-site-packages for apt bindings
  if [[ "${VIRTUAL_ENV:-}" == "$ROOT/.venv" ]] || [[ "$(readlink -f "${VIRTUAL_ENV:-}")" == "$ROOT/.venv" ]]; then
    ensure_project_venv
  fi
  echo "    (venv detected — installing into ${VIRTUAL_ENV:-active env})"
  pip_ok python3
  exit 0
fi

# 2) Existing project .venv
if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  ensure_project_venv   # also flips system-site-packages if needed
  echo "    (using $ROOT/.venv)"
  pip_ok "$ROOT/.venv/bin/python3"
  tff_python_env "$ROOT"
  exit 0
fi

# 3) Try pip --user (older setups); capture PEP 668 failures
USER_LOG="$(mktemp)"
if python3 -m pip install --user -r "$REQ" >"$USER_LOG" 2>&1; then
  echo "    (installed with pip --user)"
  rm -f "$USER_LOG"
  exit 0
fi

if grep -qiE 'externally-managed-environment|PEP 668|break-system-packages' "$USER_LOG"; then
  echo "    System Python is externally managed (PEP 668) — using project .venv"
else
  echo "    pip --user failed — falling back to project .venv"
  sed -n '1,8p' "$USER_LOG" >&2 || true
fi
rm -f "$USER_LOG"

# 4) Kali / modern Debian: project venv
ensure_project_venv
pip_ok "$ROOT/.venv/bin/python3"
tff_python_env "$ROOT"
echo "    Python deps OK in $ROOT/.venv"
echo "    Launchers will use this venv automatically (no need to activate)."
