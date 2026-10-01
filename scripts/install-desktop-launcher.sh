#!/usr/bin/env bash
# Install "T Forensic" into the desktop application menu + system icon theme.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
# Prefer ~/.icons — ~/.local/share/icons is sometimes root-owned on Kali/custom images.
ICON_BASE="${HOME}/.icons/hicolor"
PIXMAP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pixmaps"
ICON_SRC="$ROOT/desktop/assets/tforensic-app.png"
DESKTOP_DST="$APP_DIR/t-forensic.desktop"

mkdir -p "$APP_DIR" "$PIXMAP_DIR" "$ICON_BASE"

if [[ ! -f "$ICON_SRC" ]]; then
  echo "error: missing icon $ICON_SRC" >&2
  exit 1
fi

chmod +x \
  "$ROOT/scripts/run-desktop.sh" \
  "$ROOT/scripts/tforensic-desktop.desktop.sh" \
  "$ROOT/scripts/install-desktop-launcher.sh" \
  "$ROOT/install.sh" \
  "$ROOT/update.sh" 2>/dev/null || true

# --- Install branded icons into the freedesktop icon theme ---
# Absolute PNG paths in .desktop files are often ignored → generic/wrong logo.
install_size() {
  local size="$1" src="$2"
  local dir="$ICON_BASE/${size}x${size}/apps"
  mkdir -p "$dir"
  cp -f "$src" "$dir/tforensic.png"
}

for size in 16 24 32 48 64 128 256 512; do
  cand=""
  if [[ -f "$ROOT/desktop/assets/icon-${size}.png" ]]; then
    cand="$ROOT/desktop/assets/icon-${size}.png"
  elif [[ -f "$ROOT/desktop/assets/tff-icon-${size}.png" ]]; then
    cand="$ROOT/desktop/assets/tff-icon-${size}.png"
  else
    cand="$ICON_SRC"
  fi
  install_size "$size" "$cand"
done

# Canonical 256 app mark (TFF cyan ring)
install_size 256 "$ICON_SRC"
cp -f "$ICON_SRC" "$PIXMAP_DIR/tforensic.png"

if [[ -f "$ROOT/desktop/assets/tff-mark.svg" ]]; then
  mkdir -p "$ICON_BASE/scalable/apps"
  cp -f "$ROOT/desktop/assets/tff-mark.svg" "$ICON_BASE/scalable/apps/tforensic.svg"
fi

# Ensure index.theme exists so caches/tools recognize the tree
if [[ ! -f "$ICON_BASE/index.theme" ]]; then
  cat > "$ICON_BASE/index.theme" <<'EOF'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Directories=16x16/apps,24x24/apps,32x32/apps,48x48/apps,64x64/apps,128x128/apps,256x256/apps,512x512/apps,scalable/apps

[16x16/apps]
Size=16
Context=Applications
Type=Fixed

[24x24/apps]
Size=24
Context=Applications
Type=Fixed

[32x32/apps]
Size=32
Context=Applications
Type=Fixed

[48x48/apps]
Size=48
Context=Applications
Type=Fixed

[64x64/apps]
Size=64
Context=Applications
Type=Fixed

[128x128/apps]
Size=128
Context=Applications
Type=Fixed

[256x256/apps]
Size=256
Context=Applications
Type=Fixed

[512x512/apps]
Size=512
Context=Applications
Type=Fixed

[scalable/apps]
Size=128
MaxSize=512
Context=Applications
Type=Scalable
EOF
fi

# Also try XDG data icons dir when writable (some DEs prefer it)
XDG_ICON="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
if mkdir -p "$XDG_ICON/256x256/apps" 2>/dev/null; then
  for size in 16 24 32 48 64 128 256 512; do
    src="$ICON_BASE/${size}x${size}/apps/tforensic.png"
    if [[ -f "$src" ]]; then
      mkdir -p "$XDG_ICON/${size}x${size}/apps"
      cp -f "$src" "$XDG_ICON/${size}x${size}/apps/tforensic.png"
    fi
  done
  if [[ -f "$ICON_BASE/scalable/apps/tforensic.svg" ]]; then
    mkdir -p "$XDG_ICON/scalable/apps"
    cp -f "$ICON_BASE/scalable/apps/tforensic.svg" "$XDG_ICON/scalable/apps/tforensic.svg"
  fi
else
  echo "note: $XDG_ICON not writable — using $ICON_BASE (OK)."
fi

# Remove older/duplicate launchers so only one entry appears
rm -f \
  "$APP_DIR/tforensic.desktop" \
  "$APP_DIR/team-forensic-framework.desktop" \
  "$APP_DIR/Team Forensic Framework.desktop" \
  "$APP_DIR/team-forensic-framework.desktop" \
  "$APP_DIR/t-forensic.desktop"

# Absolute Icon= fallback path + theme name — some menus ignore Icon=tforensic until cache refresh
{
  echo "[Desktop Entry]"
  echo "Type=Application"
  echo "Version=1.0"
  echo "Name=T Forensic"
  echo "GenericName=Team Forensic Framework (TFF)"
  echo "Comment=Team NullX forensic analysis framework — AD1, disk, OVA, PCAP"
  echo "Exec=${ROOT}/scripts/tforensic-desktop.desktop.sh"
  echo "TryExec=${ROOT}/scripts/tforensic-desktop.desktop.sh"
  echo "Path=${ROOT}"
  echo "Icon=${PIXMAP_DIR}/tforensic.png"
  echo "Terminal=false"
  echo "Categories=Utility;"
  echo "Keywords=forensic;ad1;dfir;evidence;tff;nullx;pcap;"
  echo "StartupNotify=true"
  echo "StartupWMClass=Team Forensic Framework"
} > "$DESKTOP_DST"
chmod 644 "$DESKTOP_DST"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$DESKTOP_DST" 2>/dev/null || true
fi

update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
gtk-update-icon-cache -f -t "$XDG_ICON" 2>/dev/null || true
xdg-desktop-menu forceupdate 2>/dev/null || true

echo "Installed app menu entry: $DESKTOP_DST"
echo "Logo: ${PIXMAP_DIR}/tforensic.png  (+ theme icons in $ICON_BASE)"
echo "Name: T Forensic"
echo "Launch: application menu → T Forensic   or   $ROOT/scripts/run-desktop.sh"
echo "If the old icon still shows: log out/in once."
echo "If click does nothing: tforensic-desktop   or see ~/.cache/tforensic/launch.log"
