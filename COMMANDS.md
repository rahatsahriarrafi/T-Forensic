# TFF — commands (copy/paste)

## First install (new machine)

```bash
git clone https://github.com/rahatsahriarrafi/T-Forensic.git
cd T-Forensic
./install.sh
```

On **Kali/Debian**, `./install.sh` creates a project `.venv` automatically (PEP 668 — system `pip` is blocked). You do **not** need `--break-system-packages`.

Then open **T Forensic** from your application menu, or:

```bash
tforensic-desktop
```

## Update (already cloned — one command)

```bash
cd T-Forensic
./update.sh
```

Or:

```bash
tforensic-update
tforensic update
```

After update: open **T Forensic** from the app menu (TFF logo).  
`./update.sh` also installs **system tools** from `requirements-system.txt` (`xmount`, `sleuthkit`, `qemu-utils`, …) so disk/OVA open works.  
Skip apt with `TFF_SKIP_APT=1 ./update.sh` if needed.

## Check missing tools

```bash
tforensic deps
```

## Web UI only

```bash
export PYTHONPATH="$PWD/engine" PATH="$PWD/scripts:$PATH"
tforensic serve
```

## App menu launcher only

```bash
./scripts/install-desktop-launcher.sh
```

More detail: [docs/PACKAGING.md](docs/PACKAGING.md)
