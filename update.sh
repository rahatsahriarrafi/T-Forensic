#!/usr/bin/env bash
# One-command update: pull latest from GitHub and refresh deps / desktop launcher.
# Usage (from anywhere if installed):  tforensic-update
#        (from repo root):             ./update.sh
set -euo pipefail

_SCRIPT="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "$_SCRIPT")" && pwd)"
cd "$ROOT"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "error: this folder is not a git clone." >&2
  echo "Clone once:  git clone https://github.com/rahatsahriarrafi/T-Forensic.git" >&2
  echo "Then later:  cd T-Forensic && ./update.sh" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${ROOT}/scripts:${PATH}"

# --- Post-pull phase (always uses the *pulled* update.sh via re-exec) ---
tff_post_pull() {
  local OLD_VER="${1:-?}"
  local STASHED="${2:-0}"

  echo "==> Refreshing Python requirements…"
  if [[ -x "$ROOT/scripts/install-python-reqs.sh" ]]; then
    "$ROOT/scripts/install-python-reqs.sh" "$ROOT/requirements.txt"
  else
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
      python3 -m pip install -r "$ROOT/requirements.txt"
    else
      python3 -m pip install --user -r "$ROOT/requirements.txt" || \
        python3 -m pip install -r "$ROOT/requirements.txt"
    fi
  fi

  echo "==> Refreshing system packages (requirements-system.txt)…"
  echo "    Ensures xmount / sleuthkit / qemu-utils for opening images."
  if [[ -x "$ROOT/scripts/install-system-reqs.sh" ]]; then
    "$ROOT/scripts/install-system-reqs.sh" "$ROOT/requirements-system.txt"
  elif command -v apt-get >/dev/null 2>&1 && [[ "${TFF_SKIP_APT:-}" != "1" ]]; then
    # shellcheck disable=SC2046
    sudo apt-get install -y $(grep -vE '^\s*(#|$)' "$ROOT/requirements-system.txt" | tr '\n' ' ') || true
  fi

  if command -v npm >/dev/null 2>&1 && [[ -f "$ROOT/desktop/package.json" ]]; then
    echo "==> Refreshing desktop npm deps…"
    if [[ -x "$ROOT/scripts/desktop-npm-install.sh" ]]; then
      "$ROOT/scripts/desktop-npm-install.sh"
    else
      (cd "$ROOT/desktop" && npm install)
    fi
  fi

  if [[ -x "$ROOT/scripts/install-desktop-launcher.sh" ]]; then
    echo "==> Refreshing application menu entry…"
    "$ROOT/scripts/install-desktop-launcher.sh"
  fi

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
}

if [[ "${TFF_UPDATE_POST_PULL:-}" == "1" ]]; then
  tff_post_pull "${TFF_UPDATE_OLD_VER:-?}" "${TFF_UPDATE_STASHED:-0}"
  exit 0
fi

OLD_VER="?"
if [[ -f "$ROOT/engine/tforensic/__init__.py" ]]; then
  OLD_VER=$(python3 -c "import tforensic; print(tforensic.__version__)" 2>/dev/null || echo "?")
fi
echo "==> TFF update  (current: v${OLD_VER})"
echo "    repo: $ROOT"

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

STASHED=0
if [[ -n "$(git status --porcelain)" ]]; then
  echo "warn: you have local changes — stashing before pull…"
  git stash push -u -m "tff-update-$(date +%Y%m%d%H%M%S)" || true
  STASHED=1
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
  echo "==> Already up to date ($AFTER)."
else
  echo "==> Updated $BEFORE → $AFTER"
fi

# Re-exec so the *new* update.sh runs post-pull steps (venv pip, desktop-npm-install, …).
export TFF_UPDATE_POST_PULL=1
export TFF_UPDATE_OLD_VER="$OLD_VER"
export TFF_UPDATE_STASHED="$STASHED"
exec "$ROOT/update.sh"
