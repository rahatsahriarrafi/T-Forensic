#!/usr/bin/env bash
# One-command update: pull latest from GitHub and refresh deps / desktop launcher.
# Usage (from anywhere if installed):  tforensic-update
#        (from repo root):             ./update.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "error: this folder is not a git clone." >&2
  echo "Clone once:  git clone https://github.com/rahatsahriarrafi/T-Forensic.git" >&2
  echo "Then later:  cd T-Forensic && ./update.sh" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${ROOT}/scripts:${PATH}"

OLD_VER="?"
if [[ -f "$ROOT/engine/tforensic/__init__.py" ]]; then
  OLD_VER=$(python3 -c "import tforensic; print(tforensic.__version__)" 2>/dev/null || echo "?")
fi
echo "==> TFF update  (current: v${OLD_VER})"
echo "    repo: $ROOT"

# Prefer origin/main; fall back to current upstream
BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "origin/main")

echo "==> Fetching ${REMOTE}…"
git fetch --prune origin

BEFORE=$(git rev-parse HEAD)
if ! git merge-base --is-ancestor HEAD "$REMOTE" 2>/dev/null && \
   ! git merge-base --is-ancestor "$REMOTE" HEAD 2>/dev/null; then
  echo "warn: local history diverged from $REMOTE." >&2
  echo "      Resolve manually, or:  git reset --hard $REMOTE" >&2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "warn: you have local changes — stashing before pull…"
  git stash push -u -m "tff-update-$(date +%Y%m%d%H%M%S)" || true
  STASHED=1
else
  STASHED=0
fi

echo "==> Pulling latest…"
if git pull --ff-only origin "$BRANCH" 2>/dev/null; then
  :
elif git pull --ff-only origin main 2>/dev/null; then
  :
else
  echo "error: could not fast-forward. Try:" >&2
  echo "  git status" >&2
  echo "  git pull origin main" >&2
  exit 1
fi
AFTER=$(git rev-parse HEAD)

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "==> Already up to date ($BEFORE)."
else
  echo "==> Updated $BEFORE → $AFTER"
fi

echo "==> Refreshing Python requirements…"
python3 -m pip install --user -r "$ROOT/requirements.txt" || \
  python3 -m pip install -r "$ROOT/requirements.txt"

if command -v npm >/dev/null 2>&1 && [[ -f "$ROOT/desktop/package.json" ]]; then
  echo "==> Refreshing desktop npm deps…"
  "$ROOT/scripts/desktop-npm-install.sh"
fi

# Re-register app menu (paths may be unchanged, but safe)
if [[ -x "$ROOT/scripts/install-desktop-launcher.sh" ]]; then
  echo "==> Refreshing application menu entry…"
  "$ROOT/scripts/install-desktop-launcher.sh"
fi

# Keep CLI helper links fresh
BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
ln -sfn "$ROOT/scripts/tforensic" "$BIN_DIR/tforensic"
ln -sfn "$ROOT/scripts/run-desktop.sh" "$BIN_DIR/tforensic-desktop"
ln -sfn "$ROOT/update.sh" "$BIN_DIR/tforensic-update"

NEW_VER=$(python3 -c "import tforensic; print(tforensic.__version__)" 2>/dev/null || echo "?")
echo ""
echo "Done.  TFF v${OLD_VER} → v${NEW_VER}"
if [[ "$STASHED" == "1" ]]; then
  echo "note: local changes were stashed — run:  git stash list"
fi
echo "  Desktop:  application menu → T Forensic   (TFF logo)"
echo "  Or:       tforensic-desktop"
echo "  Deps:     tforensic deps"
echo ""
echo "If the menu icon looks wrong: log out and back in (icon cache)."
echo "If click does nothing: run  tforensic-desktop  in a terminal, or see"
echo "  ~/.cache/tforensic/launch.log"
echo ""
