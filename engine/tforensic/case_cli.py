"""CLI commands for persistent cases (Autopsy-class)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def cmd_case(args):
    action = args.case_action
    if action == "create":
        from tforensic.casedb import create_case

        db = create_case(
            args.name,
            examiner=args.examiner or "",
            description=args.description or "",
        )
        info = db.info()
        print(f"case:    {info.id}")
        print(f"name:    {info.name}")
        print(f"path:    {info.path}")
        print(f"\nexport TFOR_CASE={info.id}")
        return 0

    if action == "list":
        from tforensic.casedb import list_cases

        cases = list_cases()
        if not cases:
            print("no cases")
            return 0
        for c in cases:
            st = c.get("stats") or {}
            print(
                f"{c['id']}  {c['name']!r}  files={st.get('files',0)}  "
                f"evidence={st.get('evidence',0)}  {c['path']}"
            )
        return 0

    if action == "open":
        from tforensic.casedb import open_case

        db = open_case(args.case_id)
        info = db.info()
        print(f"opened:  {info.id}  {info.name}")
        print(f"path:    {info.path}")
        print(f"export TFOR_CASE={info.id}")
        return 0

    if action == "info":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        info = db.info().as_dict()
        info["stats"] = db.stats()
        info["evidence"] = db.list_evidence()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(json.dumps(info, indent=2))
        return 0

    if action == "add":
        from tforensic.casedb import resolve_case
        from tforensic.estimate import estimate_open

        db = resolve_case(args.case_id)
        est = estimate_open(args.image)
        print(f"estimate: {est['human']} ({est['kind']}, {est['size_human']})", flush=True)
        ev = db.add_evidence(args.image, name=args.name)
        print(f"evidence: {ev['id']}")
        print(f"kind:     {ev['kind']}")
        print(f"sha256:   {ev['sha256']}")
        if args.ingest:
            return _run_ingest(db, ev["id"], wait=True)
        print(f"# ingest: tforensic case ingest --evidence {ev['id']}")
        return 0

    if action == "ingest":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        eid = args.evidence
        if not eid:
            evs = db.list_evidence()
            if not evs:
                print("error: no evidence in case", file=sys.stderr)
                return 1
            eid = evs[-1]["id"]
        return _run_ingest(db, eid, wait=not args.async_, modules=args.modules)

    if action == "jobs":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        for j in db.list_jobs():
            print(
                f"{j['id']}  {j['status']:8}  {j['progress']*100:5.1f}%  "
                f"{j['kind']}  {j.get('message','')}"
            )
        return 0

    if action == "timeline":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        rows = db.query_timeline(limit=args.limit, event_type=args.type)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        for r in rows:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            print(f"{ts}  {r['event_type']:12}  {r['description'][:60]}  {r.get('path') or ''}")
        return 0

    if action == "search":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        files = db.search_files(args.q, limit=args.limit)
        kws = db.search_keyword(args.q, limit=args.limit)
        if args.json:
            print(json.dumps({"files": files, "keyword_hits": kws}, indent=2))
            return 0
        print(f"# files ({len(files)})")
        for f in files:
            print(f"  {f['path']}")
        print(f"# keyword hits ({len(kws)})")
        for h in kws:
            print(f"  [{h['keyword']}] {h['path']}")
        return 0

    if action == "tag":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        db.add_tag(args.file_id, args.tag)
        print("tagged")
        return 0

    if action == "note":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        nid = db.add_note(args.body, file_id=args.file_id)
        print(f"note: {nid}")
        return 0

    if action == "bookmark":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        db.add_bookmark(args.file_id, args.label or "")
        print("bookmarked")
        return 0

    if action == "hash-import":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        path = Path(args.file)
        hashes = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # NSRL-ish: hash may be first CSV field or bare hex
            part = line.split(",")[0].strip().strip('"').lower()
            if all(c in "0123456789abcdef" for c in part) and len(part) in (32, 40, 64):
                hashes.append(part)
        algo = args.algo or ("md5" if len(hashes[0]) == 32 else "sha1" if len(hashes[0]) == 40 else "sha256")
        res = db.import_hash_set(args.name, hashes, kind=args.kind, algo=algo)
        matched = db.apply_hash_sets_to_files()
        print(json.dumps({**res, "files_marked": matched}, indent=2))
        return 0

    if action == "report":
        from tforensic.casedb import resolve_case
        from tforensic.report import generate_html_report

        db = resolve_case(args.case_id)
        out = generate_html_report(db, out_path=args.output)
        print(out)
        return 0

    if action == "verify":
        from tforensic.casedb import resolve_case
        from tforensic.case_ops import verify_all, verify_evidence

        db = resolve_case(args.case_id)
        if args.evidence:
            print(json.dumps(verify_evidence(db, args.evidence), indent=2))
        else:
            print(json.dumps(verify_all(db), indent=2))
        return 0

    if action == "export":
        from tforensic.casedb import resolve_case
        from tforensic.case_ops import export_case_zip

        db = resolve_case(args.case_id)
        out = export_case_zip(db, args.output)
        print(out)
        return 0

    if action == "custody":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        for e in db.custody_entries(limit=args.limit):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"]))
            print(f"{ts}  {e['actor']:12}  {e['action']:16}  {e['detail']}")
        return 0

    if action == "artifacts":
        from tforensic.casedb import resolve_case

        db = resolve_case(args.case_id)
        arts = db.list_artifacts(module=args.module, limit=args.limit)
        if args.json:
            print(json.dumps(arts, indent=2))
            return 0
        for a in arts:
            print(f"[{a['module']}/{a['category']}] {a['label']}  {a.get('path') or ''}")
        return 0

    print(f"unknown case action: {action}", file=sys.stderr)
    return 1


def _run_ingest(db, evidence_id: str, *, wait: bool = True, modules=None):
    from tforensic.estimate import estimate_open
    from tforensic.ingest import run_ingest
    from tforensic.jobs import start_job

    ev = db.get_evidence(evidence_id)
    est = estimate_open(ev["path"])
    mods = None
    if modules:
        mods = [m.strip() for m in modules.split(",") if m.strip()]

    jid = db.create_job("ingest", evidence_id, eta_seconds=est["seconds"])
    print(f"job:      {jid}")
    print(f"estimate: {est['human']}", flush=True)

    def job_fn(database, job_id, progress_cb):
        return run_ingest(database, evidence_id, progress_cb, modules=mods)

    start_job(db, jid, job_fn)
    if not wait:
        print("started (async)")
        return 0
    # poll
    while True:
        j = db.get_job(jid)
        print(f"\r{j['status']:8} {j['progress']*100:5.1f}%  {j.get('message','')[:60]}", end="", flush=True)
        if j["status"] in ("done", "error"):
            print()
            if j["status"] == "error":
                print(j.get("error") or j.get("message"), file=sys.stderr)
                return 1
            print(json.dumps(j.get("result") or {}, indent=2))
            return 0
        time.sleep(0.5)


def register_case_parser(sub):
    sp = sub.add_parser("case", help="persistent case management (Autopsy-class)")
    case_sub = sp.add_subparsers(dest="case_action", required=True)

    def add_case_id(p):
        p.add_argument("--case", dest="case_id", default=None, help="case id (or TFOR_CASE / active)")

    p = case_sub.add_parser("create", help="create a new case")
    p.add_argument("name")
    p.add_argument("--examiner", default="")
    p.add_argument("--description", default="")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("list", help="list cases")
    p.set_defaults(func=cmd_case, case_id=None)

    p = case_sub.add_parser("open", help="set active case")
    p.add_argument("case_id")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("info", help="show case info")
    add_case_id(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("add", help="add evidence image to case")
    add_case_id(p)
    p.add_argument("image")
    p.add_argument("--name", default=None)
    p.add_argument("--ingest", action="store_true", help="run ingest after add")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("ingest", help="run ingest on evidence")
    add_case_id(p)
    p.add_argument("--evidence", default=None)
    p.add_argument("--modules", default=None, help="comma list: artifacts,web,registry,...")
    p.add_argument("--async", dest="async_", action="store_true")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("jobs", help="list ingest jobs")
    add_case_id(p)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("timeline", help="query timeline")
    add_case_id(p)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--type", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("search", help="search files + keyword index")
    add_case_id(p)
    p.add_argument("q")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("tag", help="tag a file id")
    add_case_id(p)
    p.add_argument("file_id", type=int)
    p.add_argument("tag")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("note", help="add a note")
    add_case_id(p)
    p.add_argument("body")
    p.add_argument("--file-id", type=int, default=None)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("bookmark", help="bookmark a file")
    add_case_id(p)
    p.add_argument("file_id", type=int)
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("hash-import", help="import hash set (NSRL/custom text)")
    add_case_id(p)
    p.add_argument("file", help="file with one hash per line (or CSV first column)")
    p.add_argument("--name", required=True)
    p.add_argument("--kind", default="notable", choices=["notable", "known"])
    p.add_argument("--algo", default=None)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("report", help="generate HTML case report")
    add_case_id(p)
    p.add_argument("-o", "--output", default=None)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("verify", help="re-hash evidence vs recorded sha256")
    add_case_id(p)
    p.add_argument("--evidence", default=None)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("export", help="export case zip (db+reports, not images)")
    add_case_id(p)
    p.add_argument("-o", "--output", default=None)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("custody", help="show chain-of-custody log")
    add_case_id(p)
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_case)

    p = case_sub.add_parser("artifacts", help="list ingest artifact hits")
    add_case_id(p)
    p.add_argument("--module", default=None)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_case)
