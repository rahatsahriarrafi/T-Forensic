# Packaging T Forensic (Linux)

## Runtime dependencies

```bash
sudo apt install python3 xmount sleuthkit qemu-utils fuse
# optional deep carve
sudo apt install testdisk   # provides photorec
```

Ensure `/etc/fuse.conf` has `user_allow_other` uncommented if xmount requires it.

## CLI / engine

```bash
cd Project_T-Forensic
export PYTHONPATH="$PWD/engine"
export PATH="$PWD/scripts:$PATH"
pip install -e ./engine   # optional
```

## Desktop (Electron)

```bash
./scripts/run-desktop.sh
# or
cd desktop && npm install && npm run pack
# artifacts under desktop/dist/
```

## Persistent cases

Cases live under `~/.tforensic/cases/<id>/` (override with `TFOR_CASE_ROOT`).

```bash
tforensic case create "Matter-42" --examiner "A. Analyst"
tforensic case add /path/to/evidence.ad1 --ingest
tforensic case report
tforensic case export
tforensic case verify
```

## Headless API (case mode, no image)

```bash
tforensic serve --port 8000
# open http://127.0.0.1:8000/ → Case tab
```
