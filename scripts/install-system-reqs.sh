#!/usr/bin/env bash
# Install OS packages from requirements-system.txt (Debian/Kali/Ubuntu).
# Used by ./install.sh and ./update.sh so users get xmount/sleuthkit/… on update.
set -euo pipefail
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
LIST="${1:-$ROOT/requirements-system.txt}"

if [[ "${TFF_SKIP_APT:-}" == "1" ]]; then
  echo "    Skipping system packages (TFF_SKIP_APT=1)"
  exit 0
fi

if [[ ! -f "$LIST" ]]; then
  echo "warn: missing $LIST" >&2
  exit 0
fi

mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$LIST" | tr -d '\r' | awk 'NF')
if [[ "${#PKGS[@]}" -eq 0 ]]; then
  echo "    (no system packages listed)"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "warn: apt-get not found — install manually: ${PKGS[*]}" >&2
  exit 0
fi

echo "    Packages: ${PKGS[*]}"
echo "    (sudo may prompt for your password)"
if sudo apt-get install -y "${PKGS[@]}"; then
  echo "    System packages OK"
else
  echo "warn: apt install had errors — continue; run: tforensic deps" >&2
  exit 0
fi
