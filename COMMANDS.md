# TFF — commands (copy/paste)

## First install (new machine)

```bash
git clone https://github.com/rahatsahriarrafi/T-Forensic.git
cd T-Forensic
./install.sh
```

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
