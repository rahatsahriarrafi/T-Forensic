#!/usr/bin/env bash
# Run T Forensic web UI against an AD1 or disk image (E01/raw/VDI/…).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="${1:?usage: $0 <image.ad1|E01|dd|…> [port]}"
PORT="${2:-0}"
export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m tforensic serve "$IMG" --host 127.0.0.1 --port "$PORT" --web "${ROOT}/web"
