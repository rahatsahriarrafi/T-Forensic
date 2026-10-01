#!/usr/bin/env bash
# Run T Forensic web UI against an AD1 or disk image (E01/raw/VDI/…).
set -euo pipefail
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/scripts/tff-python-env.sh"
tff_python_env "$ROOT"
IMG="${1:?usage: $0 <image.ad1|E01|dd|…> [port]}"
PORT="${2:-0}"
export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
exec "$(tff_python)" -m tforensic serve "$IMG" --host 127.0.0.1 --port "$PORT" --web "${ROOT}/web"
