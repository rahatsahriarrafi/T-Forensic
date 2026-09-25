#!/usr/bin/env bash
# Install a single T Forensic launcher into the desktop application menu.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
PIXMAP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pixmaps"
ICON_SRC="$ROOT/desktop/assets/tforensic-app.png"
DESKTOP_SRC="$ROOT/desktop/tforensic.desktop"
DESKTOP_DST="$APP_DIR/tforensic.desktop"

mkdir -p "$APP_DIR" "$PIXMAP_DIR"
if [[ ! -f "$ICON_SRC" ]]; then
  echo "error: missing icon $ICON_SRC" >&2
  exit 1
fi

# Drop older duplicate launchers so only one entry appears
rm -f \
  "$APP_DIR/team-forensic-framework.desktop" \
  "$APP_DIR/Team Forensic Framework.desktop" \
  "$PIXMAP_DIR/team-forensic-framework.png"

cp "$ICON_SRC" "$PIXMAP_DIR/tforensic.png"

# Rewrite desktop entry with absolute paths for this machine
sed \
  -e "s|^Exec=.*|Exec=$ROOT/scripts/tforensic-desktop.desktop.sh|" \
  -e "s|^Icon=.*|Icon=$ICON_SRC|" \
  -e "s|^Name=.*|Name=T Forensic|" \
  "$DESKTOP_SRC" > "$DESKTOP_DST"
chmod 644 "$DESKTOP_DST"

update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons" 2>/dev/null || true
echo "Installed launcher: $DESKTOP_DST"
echo "Icon: $ICON_SRC"
echo "App menu name: T Forensic"
