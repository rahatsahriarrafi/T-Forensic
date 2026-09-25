"""CLI for lab / plugins / playbooks (framework mode)."""
from __future__ import annotations

import json
import sys
import time


def cmd_lab(args):
    action = args.lab_action
    if action == "enable":
        from tforensic.framework.lab import enable_lab

        st = enable_lab(args.case_id, virtual_write=bool(args.virtual_write))
        print(json.dumps(st.as_dict(), indent=2))
        print("\n# Evidence remains immutable. Writable sandbox:", st.path)
        if st.virtual_write:
            print(f"# xmount cache: {st.cache_file}")
        return 0
    if action == "status":
        from tforensic.framework.lab import lab_status

        print(json.dumps(lab_status(args.case_id).as_dict(), indent=2))
        return 0
    if action == "copy":
        from tforensic.casedb import resolve_case
        from tforensic.framework.lab import LabWorkspace

        db = resolve_case(args.case_id)
        lab = LabWorkspace(db)
        if not lab.status().enabled:
            lab.enable()
        rec = lab.make_working_copy(args.path, name=args.name)
        print(json.dumps(rec, indent=2))
        return 0
    print(f"unknown lab action: {action}", file=sys.stderr)
    return 1


def cmd_plugin(args):
    action = args.plugin_action
    if action == "list":
        from tforensic.framework.plugin import list_plugins

        for p in list_plugins():
            lab = " [lab]" if p["requires_lab"] else ""
            print(f"{p['name']:20} v{p['version']}{lab}  {p['description']}")
        return 0
    if action == "run":
        from tforensic.casedb import resolve_case
        from tforensic.framework.plugin import run_plugin

        db = resolve_case(args.case_id)
        params = {}
        if args.params:
            params = json.loads(args.params)

        def cb(p, m, e=None):
            print(f"\r{p*100:5.1f}%  {m[:70]}", end="", flush=True)

        res = run_plugin(
            args.name,
            db,
            evidence_id=args.evidence,
            params=params,
            progress=cb,
        )
        print()
        print(json.dumps(res.as_dict(), indent=2))
        return 0 if res.ok else 1
    print(f"unknown plugin action: {action}", file=sys.stderr)
    return 1


def cmd_playbook(args):
    action = args.playbook_action
    if action == "list":
        from tforensic.framework.playbook import list_playbooks

        for p in list_playbooks():
            if p.get("error"):
                print(f"{p.get('name')}  ERROR {p['error']}")
            else:
                print(f"{p['name']:20}  {p.get('description','')}")
        return 0
    if action == "run":
        from tforensic.casedb import resolve_case
        from tforensic.framework.playbook import run_playbook

        db = resolve_case(args.case_id)

        def cb(p, m, e=None):
            print(f"\r{p*100:5.1f}%  {m[:70]}", end="", flush=True)

        res = run_playbook(
            args.name,
            db,
            evidence_id=args.evidence,
            progress=cb,
        )
        print()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    print(f"unknown playbook action: {action}", file=sys.stderr)
    return 1


def register_framework_parsers(sub):
    def add_case(p):
        p.add_argument("--case", dest="case_id", default=None)

    sp = sub.add_parser("lab", help="writable lab sandbox (evidence stays immutable)")
    lab_sub = sp.add_subparsers(dest="lab_action", required=True)
    p = lab_sub.add_parser("enable", help="create case/lab/ sandbox")
    add_case(p)
    p.add_argument(
        "--virtual-write",
        action="store_true",
        help="prepare xmount --cache path for virtual writes",
    )
    p.set_defaults(func=cmd_lab)
    p = lab_sub.add_parser("status", help="show lab status")
    add_case(p)
    p.set_defaults(func=cmd_lab)
    p = lab_sub.add_parser("copy", help="copy a file into lab/working (mutable copy)")
    add_case(p)
    p.add_argument("path")
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_lab)

    sp = sub.add_parser("plugin", help="run / list analysis plugins")
    pl_sub = sp.add_subparsers(dest="plugin_action", required=True)
    p = pl_sub.add_parser("list")
    p.set_defaults(func=cmd_plugin, case_id=None, plugin_action="list")
    p = pl_sub.add_parser("run")
    add_case(p)
    p.add_argument("name")
    p.add_argument("--evidence", default=None)
    p.add_argument("--params", default=None, help="JSON object")
    p.set_defaults(func=cmd_plugin)

    sp = sub.add_parser("playbook", help="run analysis playbooks")
    pb_sub = sp.add_subparsers(dest="playbook_action", required=True)
    p = pb_sub.add_parser("list")
    p.set_defaults(func=cmd_playbook, case_id=None, playbook_action="list")
    p = pb_sub.add_parser("run")
    add_case(p)
    p.add_argument("name")
    p.add_argument("--evidence", default=None)
    p.set_defaults(func=cmd_playbook)
