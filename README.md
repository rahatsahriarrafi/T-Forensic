# Team Forensic Framework (TFF)

AD1-first forensic **analysis framework** by **Team NullX**: CLI + web UI + Electron desktop,
with Autopsy-class cases, plugins, playbooks, Network/PCAP, and a writable **lab** sandbox.

**Evidence images stay immutable.** Analysis writes go to `case/lab/`, xmount
virtual-write cache, exports, and reports — never the source image.

**Why TFF:** Autopsy-depth casework, AD1/OVA-first, scriptable Linux framework.

See [docs/FRAMEWORK.md](docs/FRAMEWORK.md) for plugins / lab / playbooks.

## Persistent cases (Autopsy-class)

```bash
tforensic case create "Matter-42" --examiner "A. Analyst"
export TFOR_CASE=<id>   # or: tforensic case open <id>
tforensic case add /path/to/evidence.ad1 --ingest
tforensic case timeline
tforensic case search password
tforensic case hash-import hashes.txt --name nsrl-subset --kind known
tforensic case report
tforensic case verify
tforensic case export
tforensic case custody
```

UI tabs: **Case**, **Charts**, **Timeline**, **Search**, **Disk**, **Network** (plus Tree / Formats).

Ingest modules: `artifacts`, `web`, `registry`, `lnk_prefetch`, `email`, `exif_media`, `carve`, `keyword`.

## Network / PCAP (Wireshark-style)

Requires system `tshark` (Wireshark CLI) for full features; classic `.pcap` works with a built-in fallback.

```bash
# UI: Network tab → path to .pcap/.pcapng → Open
# Display filters: http || dns || tcp.port==443
```

API: `/api/pcap/open`, `/packets`, `/detail`, `/summary`, `/dns`, `/http`, `/conversations`.

See [docs/PACKAGING.md](docs/PACKAGING.md) for deps and packaging.

## Disk images (xmount)

Requires system `xmount` (+ optional sleuthkit `mmls` / `fls` / `icat`).

```bash
tforensic xmount-info
tforensic mount evidence.E01 --in ewf --out raw
tforensic partitions --id <mount_id>
tforensic fls --id <mount_id> -o <start_sector>
tforensic icat <inode> -o <start_sector> -O /tmp/out.bin --id <mount_id>
tforensic umount --id <mount_id>
```

In the web/desktop UI, open the **Disk** tab to mount E01/raw/VDI/…, list partitions, browse with `fls`, and extract with `icat`.

## Features (MVP)

- Open AccessData **AD1** logical images
- **CLI** (`tree`, `cat`, `hex`, `export`, `hash`, `find`, `artifacts`, `meta`)
- **Smart preview** (UTF-8 / UTF-16 LE·BE / latin-1; PE → hex — no garbage text dumps)
- **Local web UI** (tree, findings, preview, hex, metadata, hashes, export)
- **Electron shell** auto-starts the Python engine on loopback, embeds the UI, and offers an in-app terminal
- Session temp under `/tmp/tforensic-sessions/<id>/` (override with `TFOR_SESSION_ROOT`)

## Quick start (CLI / web — no Electron)

**TFF will not start until `requirements.txt` is installed.**

```bash
cd Project_T-Forensic
python3 -m pip install -r requirements.txt   # REQUIRED — app refuses to run without this
# optional system tools (disk/PCAP/SAM/prefetch/…):
#   sudo apt install $(grep -v '^#' requirements-system.txt | tr '\n' ' ')

export PYTHONPATH="$PWD/engine"
export PATH="$PWD/scripts:$PATH"

# See what’s missing (always works — even before pip install)
tforensic deps

# AD1 logical image
tforensic open /path/to/evidence.ad1

# Disk image (same as xmount — E01/raw/VDI/qcow2/…)
tforensic open /path/to/disk.E01
tforensic serve /path/to/disk.dd --port 8000
```

The web UI also shows a **continuous missing-tools banner** (`/api/deps`) that
refreshes every ~45s until optional system packages are installed.

Optional install as a package:

```bash
pip install -e ./engine
```

## Desktop (Electron)

```bash
./scripts/run-desktop.sh
# File → Open AD1…  (or: npx electron . /path/to/evidence.ad1 from desktop/)
```

First run runs `npm install` in `desktop/` (needs Node.js). The app:

1. Spawns `python3 -m tforensic serve` on an ephemeral loopback port
2. Loads the UI in an iframe
3. Can open an embedded terminal (`node-pty` + xterm) with `scripts/tforensic` on `PATH`

### Linux package (optional)

```bash
cd desktop && npm install && npm run pack
# artifacts under desktop/dist/
```

## Tests

```bash
cd Project_T-Forensic
PYTHONPATH=engine python3 -m unittest discover -s tests -v
```

No real evidence files are required; tests build synthetic AD1 images in memory.

## Layout

```
engine/tforensic/   Python engine (parser, preview, workspace, CLI, API)
web/                Browser UI served by the API
desktop/            Electron shell + terminal
scripts/            run-web / run-desktop / tforensic wrapper
tests/              unit tests
```

## Evidence safety

- Source `.ad1` is opened read-only (`mmap` ACCESS_READ)
- Exports go to `<session>/export/` (or `-o` path you choose)
- `tforensic close` deletes the session temp (use `--keep-export` to retain exports)

## Phase 2 (not in MVP)

- Deep browser / mail decoders beyond artifact locate + export
- Full Autopsy-style timeline UI

## License

MIT
