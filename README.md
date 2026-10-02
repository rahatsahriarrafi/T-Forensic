# Team Forensic Framework (TFF)

AD1-first forensic **analysis framework** by **Team NullX**: CLI + web UI + Electron desktop,
with Autopsy-class cases, plugins, playbooks, Network/PCAP, and a writable **lab** sandbox.

**Evidence images stay immutable.** Analysis writes go to `case/lab/`, xmount
virtual-write cache, exports, and reports — never the source image.

**Owner:** [rahatsahriarrafi](https://github.com/rahatsahriarrafi) · **Team NullX**

---

## Commands (install / update)

| What | Command |
|------|---------|
| **Install** (first time) | `git clone https://github.com/rahatsahriarrafi/T-Forensic.git && cd T-Forensic && ./install.sh` |
| **Update** (already cloned) | `cd T-Forensic && ./update.sh` |
| **Install all requirements only** | `./scripts/install-all-reqs.sh` · or `tforensic deps --install` |
| **Desktop app** | Application menu → **T Forensic** · or `tforensic-desktop` |
| **Check tools** | `tforensic deps` |
| **Web UI** | `tforensic serve` |

Full copy-paste list: **[COMMANDS.md](COMMANDS.md)** · packaging notes: [docs/PACKAGING.md](docs/PACKAGING.md)

```bash
# first time
git clone https://github.com/rahatsahriarrafi/T-Forensic.git
cd T-Forensic
./install.sh

# later — one command to newest version
./update.sh
```

After install, open **T Forensic** from your app list (same desktop experience).

---

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

## More install detail

See the [Commands table at the top](#commands-install--update) and **[COMMANDS.md](COMMANDS.md)**.

**TFF will not start until `requirements.txt` is installed** (`./install.sh` / `./update.sh` do this).

## Quick start (CLI / web — no Electron)

```bash
cd T-Forensic
python3 -m pip install -r requirements.txt   # REQUIRED (or ./install.sh — creates .venv on Kali)
# optional: sudo apt install $(grep -vE '^\s*(#|$)' requirements-system.txt | tr '\n' ' ')

export PYTHONPATH="$PWD/engine"
export PATH="$PWD/scripts:$PATH"

tforensic deps
tforensic open /path/to/evidence.ad1
tforensic serve /path/to/disk.dd --port 8000
```

The web UI shows a **continuous missing-tools banner** (`/api/deps`) until optional system packages are installed.

Optional: `pip install -e ./engine`

## Desktop (Electron)

```bash
./install.sh                 # recommended — menu entry + deps
# or just:
./scripts/run-desktop.sh
```

First run runs `npm install` in `desktop/` (needs **Node.js 20 or 22 LTS** recommended). The app:

1. Spawns `python3 -m tforensic serve` on an ephemeral loopback port
2. Loads the UI in an iframe
3. Can open an embedded terminal (`node-pty` + xterm) with `scripts/tforensic` on `PATH` — optional; see [docs/DESKTOP.md](docs/DESKTOP.md) for Kali / Node 24 / Python 3.14 build notes

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

**MIT** — see [LICENSE](LICENSE).

**Team Forensic Framework (TFF)** is an official **Team NullX** product,
created and maintained by **[rahatsahriarrafi](https://github.com/rahatsahriarrafi)**.
