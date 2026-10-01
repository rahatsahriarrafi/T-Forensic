#!/usr/bin/env bash
# App-menu launcher. Never fails silently: logs + desktop error dialog.
set -u
_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")/.." && pwd)"
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tforensic"
LOG="$LOG_DIR/launch.log"
mkdir -p "$LOG_DIR"

# GUI sessions often have a tiny PATH (nvm / ~/.local/bin missing).
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
# Optional nvm node without sourcing full bashrc (safer from .desktop)
if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  . "${HOME}/.nvm/nvm.sh" >/dev/null 2>&1 || true
fi
if [[ -d "${HOME}/.local/share/fnm" ]] && command -v fnm >/dev/null 2>&1; then
  eval "$(fnm env)" >/dev/null 2>&1 || true
fi

cd "$ROOT" || {
  msg="T Forensic: repo folder missing:\n$ROOT\n\nRe-run: cd T-Forensic && ./update.sh"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="T Forensic" --width=420 --text="$msg" || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "T Forensic" "$msg" || true
  fi
  exit 1
}

{
  echo "======== $(date -Iseconds) ========"
  echo "ROOT=$ROOT"
  echo "PATH=$PATH"
  echo "DISPLAY=${DISPLAY:-}"
  echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}"
} >>"$LOG"

set +e
"$ROOT/scripts/run-desktop.sh" "$@" >>"$LOG" 2>&1
code=$?
set -e

if [[ "$code" -ne 0 ]]; then
  tail_txt="$(tail -n 40 "$LOG" 2>/dev/null || true)"
  msg="T Forensic failed to start (exit ${code}).

Log: ${LOG}

Last lines:
${tail_txt}

Fix: open a terminal and run:
  cd ${ROOT} && ./update.sh
  tforensic-desktop"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="T Forensic" --width=520 --text="$msg" || true
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --error "$msg" || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "T Forensic failed to start" "See $LOG — run ./update.sh" || true
  fi
  exit "$code"
fi
exit 0
