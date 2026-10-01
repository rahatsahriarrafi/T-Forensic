#!/usr/bin/env bash
# Install "T Forensic" into the desktop application menu (~/.local/share/applications).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_SRC="$ROOT/desktop/assets/tforensic-app.png"
DESKTOP_SRC="$ROOT/desktop/tforensic.desktop"
DESKTOP_DST="$APP_DIR/t-forensic.desktop"

mkdir -p "$APP_DIR"
if [[ ! -f "$ICON_SRC" ]]; then
  echo "error: missing icon $ICON_SRC" >&2
  exit 1
fi
if [[ ! -x "$ROOT/scripts/run-desktop.sh" ]]; then
  chmod +x "$ROOT/scripts/run-desktop.sh" "$ROOT/scripts/tforensic-desktop.desktop.sh" || true
fi

# Remove older duplicate launchers so only one entry appears
rm -f \
  "$APP_DIR/tforensic.desktop" \
  "$APP_DIR/team-forensic-framework.desktop" \
  "$APP_DIR/Team Forensic Framework.desktop" \
  "$APP_DIR/team-forensic-framework.desktop"

# Rewrite template with absolute paths for this clone
sed \
  -e "s|@ROOT@|$ROOT|g" \
  -e "s|^Exec=.*|Exec=$ROOT/scripts/tforensic-desktop.desktop.sh|" \
  -e "s|^Icon=.*|Icon=$ICON_SRC|" \
  "$DESKTOP_SRC" > "$DESKTOP_DST"
chmod 644 "$DESKTOP_DST"
chmod +x "$ROOT/scripts/tforensic-desktop.desktop.sh" "$ROOT/scripts/run-desktop.sh" "$ROOT/install.sh" 2>/dev/null || true

update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons" 2>/dev/null || true

echo "Installed app menu entry: $DESKTOP_DST"
echo "Name: T Forensic"
echo "Launch: application menu → T Forensic   or   $ROOT/scripts/run-desktop.sh"
