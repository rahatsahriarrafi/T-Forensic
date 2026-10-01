#!/usr/bin/env bash
# Install ALL TFF requirements (Python + system) — no manual downloads.
# Driven by:
#   requirements.txt          → pip (venv on Kali)
#   requirements-system.txt   → apt (xmount, sleuthkit, qemu-utils, nodejs, …)
set -euo pipefail
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
cd "$ROOT"

echo "==> TFF requirements (all)"
echo "    Python list: $ROOT/requirements.txt"
echo "    System list: $ROOT/requirements-system.txt"

"$ROOT/scripts/install-python-reqs.sh" "$ROOT/requirements.txt"
"$ROOT/scripts/install-system-reqs.sh" "$ROOT/requirements-system.txt"

echo "==> All requirements install finished"
echo "    Check:  tforensic deps"
echo "    Skip apt next time:  TFF_SKIP_APT=1 ./update.sh"
