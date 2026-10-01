# Packaging / install — Team Forensic Framework (TFF)

## Fast path (GitHub clone → same desktop app)

```bash
git clone https://github.com/rahatsahriarrafi/T-Forensic.git
cd T-Forensic
./install.sh
```

This will:

1. `pip install -r requirements.txt` (**required** — TFF will not start without it)
2. `sudo apt install …` packages from `requirements-system.txt` (skip with `TFF_SKIP_APT=1`)
3. `npm install` in `desktop/` (via `scripts/desktop-npm-install.sh`; see [DESKTOP.md](DESKTOP.md))
4. Register **T Forensic** in your application menu (`~/.local/share/applications/`)
5. Symlink `tforensic` / `tforensic-desktop` into `~/.local/bin`

Then open **T Forensic** from the app list (or run `tforensic-desktop`).

## Update (one command)

```bash
cd T-Forensic
./update.sh
# or: tforensic-update
```

Pulls latest `main` from GitHub, reinstalls `requirements.txt`, refreshes Electron deps, and rewrites the app-menu launcher.

Re-install / refresh the menu entry only:

```bash
./scripts/install-desktop-launcher.sh
```

## Runtime dependencies

Python:

```bash
pip install -r requirements.txt
```

System (Debian/Kali/Ubuntu):

```bash
sudo apt install $(grep -vE '^\s*(#|$)' requirements-system.txt | tr '\n' ' ')
```

Check what’s missing:

```bash
export PYTHONPATH="$PWD/engine" PATH="$PWD/scripts:$PATH"
tforensic deps
```

Ensure `/etc/fuse.conf` has `user_allow_other` uncommented if xmount needs it.

## Packaged AppImage (optional)

```bash
cd desktop && npm install && npm run pack
# artifacts: desktop/dist/*.AppImage
# Make executable and run, or install the .desktop from install.sh for the source tree.
```

## CLI / web only

```bash
export PYTHONPATH="$PWD/engine" PATH="$PWD/scripts:$PATH"
tforensic serve
# http://127.0.0.1:<port>/
```

## Persistent cases

Cases live under `~/.tforensic/cases/<id>/` (override with `TFOR_CASE_ROOT`).
