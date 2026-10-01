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
If the old icon still shows, log out/in once.  
If a click does nothing, run `tforensic-desktop` in a terminal or check `~/.cache/tforensic/launch.log`.

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
