#!/usr/bin/env bash
# One-shot install for Team Forensic Framework (TFF) after cloning from GitHub.
# - installs Python requirements (required)
# - optionally installs system packages
# - installs Electron desktop deps
# - registers "T Forensic" in the desktop application menu
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> TFF install from: $ROOT"

if [[ ! -f "$ROOT/requirements.txt" ]]; then
  echo "error: requirements.txt missing — clone the full repository." >&2
  exit 1
fi

# --- Python ---
echo "==> Python packages (requirements.txt)…"
python3 -m pip install --user -r "$ROOT/requirements.txt" || \
  python3 -m pip install -r "$ROOT/requirements.txt"

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${ROOT}/scripts:${PATH}"

# --- Optional system tools ---
if [[ "${TFF_SKIP_APT:-}" != "1" ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "==> System packages (Debian/Kali/Ubuntu)…"
    echo "    Set TFF_SKIP_APT=1 to skip this step."
    # shellcheck disable=SC2046
    sudo apt-get install -y $(grep -vE '^\s*(#|$)' "$ROOT/requirements-system.txt" | tr '\n' ' ') || {
      echo "warn: apt install had errors — continue; run: tforensic deps" >&2
    }
  else
    echo "==> Skipping apt (no apt-get). Install tools from requirements-system.txt manually."
  fi
else
  echo "==> Skipping apt (TFF_SKIP_APT=1)"
fi

# --- Desktop (Electron) ---
if command -v npm >/dev/null 2>&1; then
  echo "==> Desktop (Electron) npm install…"
  "$ROOT/scripts/desktop-npm-install.sh"
else
  echo "warn: npm not found — install Node.js to use the desktop app." >&2
  echo "      CLI/web still work:  tforensic serve" >&2
fi

# --- PATH helper (~/.local/bin) ---
BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
ln -sfn "$ROOT/scripts/tforensic" "$BIN_DIR/tforensic"
ln -sfn "$ROOT/scripts/run-desktop.sh" "$BIN_DIR/tforensic-desktop"
ln -sfn "$ROOT/update.sh" "$BIN_DIR/tforensic-update"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: add to PATH:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# --- Application menu launcher ---
echo "==> Registering desktop app (app list / start menu)…"
"$ROOT/scripts/install-desktop-launcher.sh"

echo ""
echo "Done."
echo "  Check deps:   tforensic deps"
echo "  Desktop app:  open “T Forensic” from your application menu"
echo "                or:  tforensic-desktop"
echo "  Web UI:       tforensic serve"
echo "  Later update: ./update.sh   (or: tforensic-update)"
echo ""
