#!/usr/bin/env bash
# Prefer repo .venv on Kali/Debian (PEP 668 externally-managed Python).
# Source from other scripts after ROOT is set:
#   # shellcheck source=/dev/null
#   . "$ROOT/scripts/tff-python-env.sh"
tff_python_env() {
  local root="${1:-${ROOT:-}}"
  if [[ -z "$root" ]]; then
    echo "tff_python_env: ROOT required" >&2
    return 1
  fi
  if [[ -x "$root/.venv/bin/python3" ]]; then
    export VIRTUAL_ENV="$root/.venv"
    export PATH="$root/.venv/bin:${PATH:-}"
    export TFOR_PYTHON="$root/.venv/bin/python3"
    return 0
  fi
  if [[ -n "${TFOR_PYTHON:-}" && -x "${TFOR_PYTHON}" ]]; then
    return 0
  fi
  export TFOR_PYTHON="${TFOR_PYTHON:-python3}"
}

tff_python() {
  if [[ -n "${TFOR_PYTHON:-}" ]]; then
    if [[ -x "${TFOR_PYTHON}" ]]; then
      echo "$TFOR_PYTHON"
      return 0
    fi
    # bare name like python3
    if command -v "${TFOR_PYTHON}" >/dev/null 2>&1; then
      command -v "${TFOR_PYTHON}"
      return 0
    fi
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo "python3"
  fi
}
