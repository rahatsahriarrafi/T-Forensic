"""tforensic CLI — open | tree | cat | hex | export | hash | find | close | serve."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from tforensic import __version__
from tforensic.analysis import classify_artifacts, hashes, is_executable
from tforensic.case import load_case, open_case, print_tree, tree_dict
from tforensic.accessors import open_with_accessor
from tforensic.preview import detect_and_decode, hexdump
from tforensic.workspace import cleanup_session


def _case(args):
    return load_case(getattr(args, "session", None))


def cmd_open(args):
    from tforensic.evidence import open_evidence
    from tforensic.estimate import estimate_open

    try:
        est = estimate_open(args.image, input_type=getattr(args, "input_type", None))
        print(
            f"estimate: {est['human']} (typical {est['human_range']}, "
            f"{est['size_human']}, {est['kind']})",
            flush=True,
        )
    except Exception:
        pass

    case = open_evidence(
        args.image,
        input_type=getattr(args, "input_type", None),
        output_type=getattr(args, "output_type", None) or "raw",
        morph=getattr(args, "morph", None) or "combine",
        cache=getattr(args, "cache", None),
    )
    info = case.info()
    print(f"session: {info['session_id']}")
    print(f"kind:    {info.get('kind', 'ad1')}")
    print(f"image:   {info['image_path']}")
    print(f"sha256:  {info['image_sha256']}")
    print(f"temp:    {info['temp_dir']}")
    if info.get("kind") == "disk":
        xmi = info.get("xmount") or {}
        print(f"xmount:  {xmi.get('input_type')}→{xmi.get('output_type')}")
        print(f"device:  {xmi.get('virtual_device')}")
        print(f"mount:   {xmi.get('id')}")
        print(f"\nexport TFOR_SESSION={info['session_id']}")
        print(f"# tforensic partitions --id {xmi.get('id')}")
        print(f"# tforensic fls --id {xmi.get('id')} -o <start_sector>")
        print(f"# keep mount alive; umount with: tforensic umount --id {xmi.get('id')}")
        # do not close — that would umount
    else:
        print(f"export:  {info['export_dir']}")
        print(f"tree:    {info['dirs']} dirs, {info['files']} files")
        print(f"\nexport TFOR_SESSION={info['session_id']}")
        print(f"# or: tforensic tree --session {info['session_id']}")
        case.close()
    return 0


def cmd_info(args):
    case = _case(args)
    try:
        print(json.dumps(case.info(), indent=2))
    finally:
        case.close()
    return 0


def cmd_tree(args):
    case = _case(args)
    try:
        if args.json:
            print(json.dumps(tree_dict(case.img.root), indent=2))
        else:
            print_tree(case.img.root, path_filter=args.path)
    finally:
        case.close()
    return 0


def cmd_cat(args):
    case = _case(args)
    try:
        data = case.read(args.path)
        result = open_with_accessor(args.path, data, force=args.accessor)
        print(f"# accessor: {result.label} ({result.accessor})", file=sys.stderr)
        if result.note:
            print(f"# note: {result.note}", file=sys.stderr)
        if result.mode in ("text", "json", "hex"):
            sys.stdout.write(result.text)
            if result.text and not result.text.endswith("\n"):
                sys.stdout.write("\n")
            return 0
        if result.mode == "list" and result.items:
            for it in result.items:
                if isinstance(it, dict):
                    print(f"{it.get('size', ''):>10}  {it.get('name', '')}")
                else:
                    print(it)
            return 0
        if result.mode == "table":
            if result.items:
                for t in result.items:
                    print(f"[{t.get('type')}] {t.get('name')}")
            if result.columns:
                print(" | ".join(result.columns))
                print("-" * 40)
                for row in result.rows or []:
                    print(" | ".join(row))
            return 0
        if result.mode == "image":
            print(f"# image {result.mime} ({result.size} bytes) — use: tforensic export {args.path!r}", file=sys.stderr)
            return 0
        print(result.note or result.text, file=sys.stderr)
        return 0
    finally:
        case.close()


def cmd_accessors(args):
    from tforensic.accessors import list_accessors
    for a in list_accessors():
        print(f"{a['accessor']:10}  {a['label']:16}  {', '.join(a['extensions'][:12])}"
              + (" …" if len(a["extensions"]) > 12 else ""))
    return 0


def cmd_hex(args):
    case = _case(args)
    try:
        data = case.read(args.path)
        limit = args.bytes
        print(hexdump(data, limit=limit))
        if len(data) > limit:
            print(f"\n… truncated ({len(data)} bytes total)", file=sys.stderr)
    finally:
        case.close()
    return 0


def cmd_export(args):
    case = _case(args)
    try:
        out = case.export_file(args.path, dest=args.output)
        print(out)
    finally:
        case.close()
    return 0


def cmd_hash(args):
    case = _case(args)
    try:
        data = case.read(args.path)
        out = hashes(data)
        out["executable"] = is_executable(data)
        out["path"] = args.path
        print(json.dumps(out, indent=2))
    finally:
        case.close()
    return 0


def cmd_find(args):
    case = _case(args)
    try:
        if not args.name and not args.q:
            print("error: provide --name and/or --q", file=sys.stderr)
            return 1
        uniq = []
        for n in case.files:
            if args.name and not fnmatch.fnmatch(n.name.lower(), args.name.lower()):
                continue
            if args.q and args.q.lower() not in n.name.lower():
                continue
            uniq.append(n)
        for n in uniq[: args.limit]:
            print(f"{n.size:>10}  {n.path}")
        if len(uniq) > args.limit:
            print(f"# … {len(uniq) - args.limit} more", file=sys.stderr)
    finally:
        case.close()
    return 0


def cmd_artifacts(args):
    case = _case(args)
    try:
        hits = classify_artifacts(case.files)
        print(json.dumps({"hits": hits}, indent=2))
    finally:
        case.close()
    return 0


def cmd_meta(args):
    case = _case(args)
    try:
        node = case.get(args.path)
        if not node:
            print(f"path not found: {args.path}", file=sys.stderr)
            return 1
        attrs = {hex(k): v for k, v in case.img.metadata(node).items()}
        print(json.dumps({"path": node.path, "attrs": attrs}, indent=2))
    finally:
        case.close()
    return 0


def cmd_close(args):
    kept = cleanup_session(args.session, keep_export=args.keep_export)
    if kept:
        print(f"session closed; export kept at {kept}")
    else:
        print("session closed; temp workspace removed")
    return 0


def cmd_serve(args):
    from tforensic.api.server import serve
    from tforensic.deps import check_dependencies, ensure_requirements, format_deps_text

    ok, msg = ensure_requirements()
    if not ok:
        print(msg, file=sys.stderr)
        return 3

    report = check_dependencies()
    if report["counts"]["missing"]:
        print(format_deps_text(report), file=sys.stderr)
        print("", file=sys.stderr)
    else:
        print("deps: all recommended tools present", file=sys.stderr)

    return serve(
        image=args.image,
        session=args.session,
        host=args.host,
        port=args.port,
        web_dir=args.web,
        input_type=getattr(args, "input_type", None),
        output_type=getattr(args, "output_type", None) or "raw",
        morph=getattr(args, "morph", None) or "combine",
        cache=getattr(args, "cache", None),
    )


def cmd_deps(args):
    from tforensic.deps import check_dependencies, format_deps_text

    report = check_dependencies()
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print(format_deps_text(report))
    return 0 if report.get("complete") else 2


def cmd_xmount_info(args):
    from tforensic.xmount_wrap import probe

    print(json.dumps(probe(), indent=2))
    return 0


def cmd_mount(args):
    from tforensic.xmount_wrap import mount_image

    rec = mount_image(
        args.image,
        input_type=args.input_type,
        output_type=args.output_type,
        morph=args.morph,
        cache=args.cache,
        owcache=args.owcache,
        offset=args.offset,
        sizelimit=args.sizelimit,
        mount_dir=args.mount_dir,
    )
    print(f"mount id:  {rec.id}")
    print(f"image:     {rec.image_path}")
    print(f"in/out:    {rec.input_type} → {rec.output_type} (morph={rec.morph})")
    print(f"mount dir: {rec.mount_dir}")
    print(f"device:    {rec.virtual_device}")
    if rec.cache_file:
        print(f"cache:     {rec.cache_file}")
    print(f"\n# next: tforensic partitions --id {rec.id}")
    print(f"#       tforensic fls --id {rec.id} -o <start_sector>")
    print(f"#       tforensic umount --id {rec.id}")
    return 0


def cmd_umount(args):
    from tforensic.xmount_wrap import find_mount, umount

    if args.mount_dir:
        umount(args.mount_dir)
    else:
        rec = find_mount(args.mount_id)
        umount(rec.mount_dir)
    print("unmounted")
    return 0


def cmd_mounts(args):
    from tforensic.xmount_wrap import list_active_mounts

    mounts = list_active_mounts()
    if not mounts:
        print("no active mounts")
        return 0
    for m in mounts:
        print(f"{m.id}  {m.input_type}->{m.output_type}  {m.image_path}")
        print(f"       device={m.virtual_device}")
        print(f"       dir={m.mount_dir}")
    return 0


def _resolve_disk_image(args):
    from tforensic.xmount_wrap import find_mount

    if getattr(args, "image", None):
        return args.image
    rec = find_mount(getattr(args, "mount_id", None))
    if not rec.virtual_device:
        raise FileNotFoundError("mount has no virtual device")
    return rec.virtual_device


def cmd_partitions(args):
    from tforensic.xmount_wrap import mmls_partitions

    img = _resolve_disk_image(args)
    parts = mmls_partitions(img)
    print(f"# {img}")
    print(f"{'slot':<5} {'start':>12} {'length':>12} {'byte_off':>14}  desc")
    for p in parts:
        print(
            f"{p['slot']:<5} {p['start']:>12} {p['length']:>12} {p['byte_offset']:>14}  {p['desc']}"
        )
    return 0


def cmd_fls(args):
    from tforensic.xmount_wrap import fls_list

    img = _resolve_disk_image(args)
    entries = fls_list(
        img,
        offset_sectors=args.offset,
        inode=args.inode,
        recursive=args.recursive,
        limit=args.limit,
    )
    for e in entries:
        mark = "d" if e["is_dir"] else "r"
        del_ = "*" if e["deleted"] else " "
        print(f"{mark}{del_} {e['inode']:>8}  {e['name']}")
    return 0


def cmd_icat(args):
    from tforensic.xmount_wrap import icat_extract

    img = _resolve_disk_image(args)
    out = icat_extract(img, args.inode, args.output, offset_sectors=args.offset)
    print(out)
    return 0


def cmd_formats(args):
    from tforensic.evidence import accepted_formats
    data = accepted_formats()
    print("Accepted evidence formats for analysis\n")
    for g in data["catalog"]:
        print(f"[{g['engine']}] {g['group']}")
        print(f"  {', '.join(g['extensions'])}")
        print(f"  {g['notes']}\n")
    xm = data.get("xmount") or {}
    print(f"xmount available: {xm.get('available')}")
    if xm.get("inputs"):
        print(f"xmount inputs:    {', '.join(xm['inputs'])}")
    return 0


def cmd_estimate(args):
    from tforensic.estimate import estimate_open
    import json

    est = estimate_open(args.image, input_type=getattr(args, "input_type", None))
    if getattr(args, "json", False):
        print(json.dumps(est, indent=2))
        return 0
    if not est["exists"]:
        print(f"warning: path not found or unreadable: {est['path']}", file=sys.stderr)
    print(f"path:     {est['path']}")
    print(f"size:     {est['size_human']} ({est['size']} bytes)")
    print(f"kind:     {est['kind']}")
    print(f"estimate: {est['human']}  (typical {est['human_range']})")
    print(f"note:     {est['note']}")
    if est.get("stages"):
        print("stages:")
        for s in est["stages"]:
            print(f"  - {s['name']}: {s['human']}" + (f"  ({s['detail']})" if s.get("detail") else ""))
    return 0


def cmd_shell(args):
    """Friendly terminal access to mounts."""
    from tforensic.shell_access import (
        context_from_case_object,
        context_from_persistent_case,
        build_shell_context,
    )

    # triage session
    try:
        from tforensic.case import load_case
        from tforensic.evidence import DiskCase

        # load_case is AD1; try session folder disk.json
        sess = getattr(args, "session", None)
        if sess or os.environ.get("TFOR_SESSION"):
            from tforensic.workspace import resolve_session
            meta = resolve_session(sess)
            disk_json = Path(meta.temp_dir) / "disk.json"
            if disk_json.is_file():
                data = json.loads(disk_json.read_text(encoding="utf-8"))
                m = data.get("mount") or {}
                ctx = build_shell_context(
                    temp_dir=meta.temp_dir,
                    export_dir=meta.export_dir,
                    mount_dir=m.get("mount_dir"),
                    virtual_device=m.get("virtual_device"),
                    image_path=meta.image_path,
                    session_id=meta.id,
                    kind=data.get("kind") or "disk",
                )
            else:
                case = load_case(sess)
                ctx = context_from_case_object(case)
            if args.env:
                print(ctx["rc_file"])
                return 0
            print(ctx["banner"])
            print(f"\n# source {ctx['rc_file']}")
            print(f"# or: cd {ctx['cwd']} && ls -la")
            return 0
    except Exception:
        pass

    try:
        from tforensic.casedb import resolve_case
        db = resolve_case(getattr(args, "case_id", None))
        ctx = context_from_persistent_case(db)
        if args.env:
            print(ctx["rc_file"])
            return 0
        print(ctx["banner"])
        print(f"\n# source {ctx['rc_file']}")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        print("hint:  open an image (tforensic open/serve) or set TFOR_SESSION / TFOR_CASE", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tforensic",
        description="Team Forensic Framework (TFF) — AD1 + xmount disk-image toolkit (CLI + API)",
    )
    p.add_argument("--version", action="version", version=f"Team Forensic Framework (TFF) {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_session(sp):
        sp.add_argument("--session", "-S", help="session id (or set TFOR_SESSION)")

    sp = sub.add_parser("open", help="open AD1 or disk image (E01/raw/VDI/…) into a session")
    sp.add_argument("image", help="path to .ad1 / .E01 / .dd / .raw / .vdi / .qcow2 / …")
    sp.add_argument("--in", dest="input_type", default=None, help="xmount input type (auto if omitted)")
    sp.add_argument("--out", dest="output_type", default="raw", help="xmount output type")
    sp.add_argument("--morph", default="combine")
    sp.add_argument("--cache", help="xmount virtual-write cache")
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("info", help="show active session info")
    add_session(sp)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("tree", help="print logical file tree")
    add_session(sp)
    sp.add_argument("--path", help="subtree path")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("cat", help="open file with extension-based accessor")
    add_session(sp)
    sp.add_argument("path")
    sp.add_argument(
        "--accessor",
        help="force accessor: text|image|json|markup|archive|sqlite|pe|hex|pdf|media|office|auto",
    )
    sp.set_defaults(func=cmd_cat)

    sp = sub.add_parser("accessors", help="list extension → accessor mappings")
    sp.set_defaults(func=cmd_accessors)

    sp = sub.add_parser("formats", help="list accepted evidence formats for analysis")
    sp.set_defaults(func=cmd_formats)

    sp = sub.add_parser("estimate", help="estimate time to open/mount an image")
    sp.add_argument("image", help="path to evidence file")
    sp.add_argument("--in", dest="input_type", default=None, help="xmount input type hint")
    sp.add_argument("--json", action="store_true", help="print JSON")
    sp.set_defaults(func=cmd_estimate)

    from tforensic.case_cli import register_case_parser
    register_case_parser(sub)

    from tforensic.framework_cli import register_framework_parsers
    register_framework_parsers(sub)

    sp = sub.add_parser("shell", help="print friendly mount paths / shell env for terminal")
    sp.add_argument("--session", "-S", default=None)
    sp.add_argument("--case", dest="case_id", default=None)
    sp.add_argument("--env", action="store_true", help="print sourceable env.sh path only")
    sp.set_defaults(func=cmd_shell)

    sp = sub.add_parser("hex", help="hex dump a file")
    add_session(sp)
    sp.add_argument("path")
    sp.add_argument("--bytes", type=int, default=65536)
    sp.set_defaults(func=cmd_hex)

    sp = sub.add_parser("export", help="export decompressed file into session temp/export")
    add_session(sp)
    sp.add_argument("path")
    sp.add_argument("-o", "--output", help="output file or directory")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("hash", help="MD5/SHA-1/SHA-256 of a file")
    add_session(sp)
    sp.add_argument("path")
    sp.set_defaults(func=cmd_hash)

    sp = sub.add_parser("find", help="find files by name pattern")
    add_session(sp)
    sp.add_argument("--name", help="glob pattern, e.g. '*.ps1'")
    sp.add_argument("--q", help="substring match on filename")
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("artifacts", help="list known forensic artifact hits")
    add_session(sp)
    sp.set_defaults(func=cmd_artifacts)

    sp = sub.add_parser("meta", help="show AD1 attribute metadata for a path")
    add_session(sp)
    sp.add_argument("path")
    sp.set_defaults(func=cmd_meta)

    sp = sub.add_parser("close", help="delete session temp workspace")
    add_session(sp)
    sp.add_argument("--keep-export", action="store_true")
    sp.set_defaults(func=cmd_close)

    sp = sub.add_parser("serve", help="start local JSON API + web UI (loopback)")
    sp.add_argument("image", nargs="?", help="AD1 or disk image (E01/raw/VDI/…)")
    add_session(sp)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=0, help="0 = ephemeral port")
    sp.add_argument("--web", default=None, help="path to web/ directory")
    sp.add_argument("--in", dest="input_type", default=None)
    sp.add_argument("--out", dest="output_type", default="raw")
    sp.add_argument("--morph", default="combine")
    sp.add_argument("--cache", default=None)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("deps", help="check runtime tools and print install suggestions")
    sp.add_argument("--json", action="store_true", help="machine-readable report")
    sp.set_defaults(func=cmd_deps)

    # ---- xmount / disk images ----
    sp = sub.add_parser("xmount-info", help="show xmount / sleuthkit availability")
    sp.set_defaults(func=cmd_xmount_info)

    sp = sub.add_parser("mount", help="mount disk image with xmount (E01/raw/VDI/…)")
    sp.add_argument("image", help="path to disk image")
    sp.add_argument("--in", dest="input_type", default=None,
                    help="input type (ewf, raw, dd, vdi, qcow2, aff, …); auto-guessed if omitted")
    sp.add_argument("--out", dest="output_type", default="raw",
                    help="output type: raw|dmg|vdi|vhd|vmdk|vmdks")
    sp.add_argument("--morph", default="combine", help="combine|unallocated|raid0")
    sp.add_argument("--cache", help="virtual-write cache file")
    sp.add_argument("--owcache", action="store_true", help="overwrite existing cache")
    sp.add_argument("--offset", type=int, default=0, help="byte offset into input")
    sp.add_argument("--sizelimit", type=int, default=None, help="limit output size in bytes")
    sp.add_argument("--mount-dir", help="custom mount directory")
    sp.set_defaults(func=cmd_mount)

    sp = sub.add_parser("umount", help="unmount an xmount session")
    sp.add_argument("--id", dest="mount_id", help="mount id (default: latest)")
    sp.add_argument("--dir", dest="mount_dir", help="mount directory")
    sp.set_defaults(func=cmd_umount)

    sp = sub.add_parser("mounts", help="list active xmount sessions")
    sp.set_defaults(func=cmd_mounts)

    sp = sub.add_parser("partitions", help="list partitions (mmls) on mounted/raw image")
    sp.add_argument("image", nargs="?", help="image/device path (default: latest xmount virtual device)")
    sp.add_argument("--id", dest="mount_id", help="use virtual device from this mount id")
    sp.set_defaults(func=cmd_partitions)

    sp = sub.add_parser("fls", help="list filesystem entries (sleuthkit fls)")
    sp.add_argument("image", nargs="?", help="image/device (default: latest xmount device)")
    sp.add_argument("--id", dest="mount_id")
    sp.add_argument("-o", "--offset", type=int, default=0, help="partition start sector")
    sp.add_argument("--inode", help="directory inode")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.add_argument("--limit", type=int, default=2000)
    sp.set_defaults(func=cmd_fls)

    sp = sub.add_parser("icat", help="extract file by inode (sleuthkit icat)")
    sp.add_argument("inode")
    sp.add_argument("-o", "--offset", type=int, default=0, help="partition start sector")
    sp.add_argument("--id", dest="mount_id")
    sp.add_argument("image", nargs="?", help="image/device (default: latest xmount device)")
    sp.add_argument("-O", "--output", required=True, help="output file path")
    sp.set_defaults(func=cmd_icat)

    return p


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # Allow `deps` / `deps --json` without requirements so users can discover the fix.
    cmd = next((a for a in argv if not a.startswith("-")), None)
    if cmd not in (None, "deps"):
        from tforensic.deps import ensure_requirements

        ok, msg = ensure_requirements()
        if not ok:
            print(msg, file=sys.stderr)
            return 3

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as e:
        from tforensic.errors import format_cli_error

        ctx = getattr(args, "cmd", "") or ""
        print(format_cli_error(e, ctx), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
