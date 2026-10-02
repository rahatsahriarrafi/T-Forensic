# TFF desktop (Electron) - supported platforms and build notes

## Is Linux x86_64 supported?

**Yes.** Kali / Debian / Ubuntu **x86_64** is the primary target for the source-tree desktop app (`./install.sh`, app-menu **T Forensic**, `tforensic-desktop`).

The UI and Python engine do **not** depend on `node-pty`. Only the **embedded terminal panel** inside Electron uses it.

## Recommended versions (tested workflow)

| Component | Recommended | Notes |
|-----------|-------------|--------|
| **OS** | Kali / Debian / Ubuntu **amd64** | Other Linux amd64 distros usually work |
| **Node.js** | **20.x LTS** or **22.x LTS** | Avoid **Node 24+** for `npm install` in `desktop/` until you use the optional native rebuild flow below |
| **npm** | **10+** (bundled with Node 20/22) | npm 12 on Node 24 is what many users hit when builds fail |
| **Python (TFF engine)** | **3.11 – 3.12** (3.13+ often OK) | `pip install -r requirements.txt` - this is separate from `node-gyp` |
| **Python (node-gyp only)** | **3.11 or 3.12** + **setuptools** | Python **3.12+** removed stdlib `distutils`; old **node-gyp 9** still imports it unless setuptools is installed or you point npm at another Python |
| **Electron** | **33.x** (see `desktop/package.json`) | Installed locally under `desktop/node_modules` |

We develop and smoke-test on **Kali amd64** with **Node 20/22** and **Python 3.11+** for the engine. Your stack (**Node 24.19 + Python 3.14.7**) is ahead of that curve: Electron and `node-pty` often fall back to **node-gyp**, which then breaks on **missing distutils** under Python 3.14.

## What `node-pty` / `node-gyp` are for

- **`node-pty`** - native addon for the in-app terminal.
- **`node-gyp`** - compiles that addon when no matching **prebuild** exists (common on **Node 24** or very new Python).

If `node-pty` is not built, the desktop app **still runs** (open evidence, tree, disk, PCAP, etc.). The terminal shows a message and you can use a normal shell: `tforensic`, `tforensic serve`, `tforensic-desktop` from a terminal.

As of **v0.3.3**, `node-pty` is an **optional** npm dependency so `npm install` in `desktop/` can succeed even when the native build fails.

## Kali Linux - install desktop (recommended)

From the repo root:

```bash
./install.sh
# or after clone: ./update.sh
```

Then: application menu → **T Forensic**, or `tforensic-desktop`.

Use **Node 20 or 22** if you can (nvm/fnm or `nodejs` from Debian/Kali repos):

```bash
node -v   # prefer v20.x or v22.x
cd T-Forensic/desktop && npm install
```

## If you need the embedded terminal (`node-pty`)

Install build tools and setuptools (fixes many `distutils` errors on Python 3.12+):

```bash
sudo apt install build-essential python3-dev python3-setuptools
```

If the default `python3` is **3.13/3.14**, point **node-gyp** at an older interpreter for the native build only:

```bash
sudo apt install python3.12 python3.12-dev   # if available
cd T-Forensic/desktop
npm config set python /usr/bin/python3.12
npm install
npm run rebuild-native
```

`rebuild-native` runs **electron-rebuild** so `node-pty` matches **Electron 33**, not only your system Node version.

## Pinning Node with nvm (example)

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
# new shell, then:
nvm install 22
nvm use 22
cd T-Forensic && ./update.sh
```

## Versions we do **not** recommend changing blindly

- **`electron`** - keep aligned with `desktop/package.json` (^33.x).
- **`node-pty`** - keep ^1.0.0; use **electron-rebuild**, do not randomly downgrade Electron.

## Quick answers (for GitHub issues)

1. **Official Linux x64 desktop?** Yes (source install + app menu).
2. **Recommended Node?** **20 LTS or 22 LTS** for smoothest `npm install`.
3. **Recommended Python?** **3.11–3.12** for the **forensic engine**; for **node-gyp**, same or setuptools + optional `npm config set python`.
4. **Recommended node-gyp?** Whatever **npm** pulls in; fix the environment (Node version, `build-essential`, `python3-setuptools`, `electron-rebuild`) rather than pinning node-gyp in this repo.
5. **`npm install` failed on node-pty?** Upgrade to **v0.3.3+**, re-run `./update.sh` - app should work without terminal; then follow **embedded terminal** steps above if needed.

## Logs

Desktop menu launch: `~/.cache/tforensic/launch.log`
