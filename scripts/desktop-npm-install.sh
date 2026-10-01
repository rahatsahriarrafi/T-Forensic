#!/usr/bin/env bash
# Install desktop npm deps; node-pty is optional (embedded terminal only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/desktop"

if ! command -v npm >/dev/null 2>&1; then
  echo "error: npm not found — install Node.js 20 or 22 LTS (see docs/DESKTOP.md)" >&2
  exit 1
fi

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)"
if [[ "$NODE_MAJOR" -ge 24 ]]; then
  echo "warn: Node $(node -v) is newer than tested (20/22 LTS)." >&2
  echo "      npm install may skip node-pty; app still runs. See docs/DESKTOP.md" >&2
fi

cd "$DESKTOP"
if npm install; then
  :
else
  echo "warn: npm install reported errors — retrying without optional deps…" >&2
  npm install --no-optional || {
    echo "error: desktop npm install failed. See docs/DESKTOP.md" >&2
    exit 1
  }
fi

if [[ -d node_modules/electron ]]; then
  echo "Desktop: Electron OK ($(node -p "require('./package.json').devDependencies.electron" 2>/dev/null || echo '?'))"
else
  echo "error: Electron not installed under desktop/node_modules" >&2
  exit 1
fi

if node -e "require('node-pty')" 2>/dev/null; then
  echo "Desktop: node-pty OK (embedded terminal available)"
else
  echo "note: node-pty not built — embedded terminal disabled; rest of TFF desktop works."
  echo "      To enable: docs/DESKTOP.md (build-essential, python3-setuptools, npm run rebuild-native)"
fi
