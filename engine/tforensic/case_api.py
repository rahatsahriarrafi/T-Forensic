"""HTTP handlers for persistent case API."""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import parse_qs

from tforensic.casedb import CaseDB, create_case, list_cases, open_case, resolve_case
from tforensic.estimate import estimate_open
from tforensic.ingest import MODULES, run_ingest
from tforensic.jobs import start_job

# Process-wide active case for the API server
ACTIVE: Optional[CaseDB] = None


def get_active(case_id: Optional[str] = None) -> CaseDB:
    global ACTIVE
    if case_id:
        ACTIVE = open_case(case_id)
        return ACTIVE
    if ACTIVE is not None:
        return ACTIVE
    ACTIVE = resolve_case(None)
    return ACTIVE


def handle_case_get(route: str, q: dict) -> tuple[int, Any]:
    global ACTIVE
    if route == "/api/case/list":
        return 200, {"cases": list_cases()}
    if route == "/api/case/modules":
        return 200, {"modules": list(MODULES.keys())}
    if route == "/api/case/info":
        db = get_active((q.get("id") or [None])[0])
        info = db.info().as_dict()
        info["stats"] = db.stats()
        info["evidence"] = db.list_evidence()
        info["jobs"] = db.list_jobs(20)
        return 200, info
    if route == "/api/case/evidence":
        db = get_active((q.get("id") or [None])[0])
        return 200, {"evidence": db.list_evidence()}
    if route == "/api/case/jobs":
        db = get_active((q.get("id") or [None])[0])
        jid = (q.get("job") or [None])[0]
        if jid:
            return 200, db.get_job(jid)
        return 200, {"jobs": db.list_jobs()}
    if route == "/api/case/files":
        db = get_active((q.get("id") or [None])[0])
        qq = (q.get("q") or [""])[0]
        limit = int((q.get("limit") or ["200"])[0])
        if qq:
            return 200, {"files": db.search_files(qq, limit=limit)}
        with db.connect() as c:
            rows = c.execute(
                "SELECT id, evidence_id, path, name, is_dir, size, deleted, hash_status FROM files ORDER BY path LIMIT ?",
                (limit,),
            ).fetchall()
        return 200, {"files": [dict(r) for r in rows]}
    if route == "/api/case/tags":
        db = get_active((q.get("id") or [None])[0])
        fid = (q.get("file_id") or [None])[0]
        return 200, {"tags": db.list_tags(int(fid) if fid else None)}
    if route == "/api/case/notes":
        db = get_active((q.get("id") or [None])[0])
        fid = (q.get("file_id") or [None])[0]
        return 200, {"notes": db.list_notes(int(fid) if fid else None)}
    if route == "/api/case/bookmarks":
        db = get_active((q.get("id") or [None])[0])
        return 200, {"bookmarks": db.list_bookmarks()}
    if route == "/api/case/timeline":
        db = get_active((q.get("id") or [None])[0])
        start = (q.get("start") or [None])[0]
        end = (q.get("end") or [None])[0]
        et = (q.get("type") or [None])[0]
        limit = int((q.get("limit") or ["300"])[0])
        return 200, {
            "events": db.query_timeline(
                start=float(start) if start else None,
                end=float(end) if end else None,
                event_type=et,
                limit=limit,
            )
        }
    if route == "/api/case/search":
        db = get_active((q.get("id") or [None])[0])
        qq = (q.get("q") or [""])[0]
        limit = int((q.get("limit") or ["200"])[0])
        return 200, {
            "files": db.search_files(qq, limit=limit),
            "keyword_hits": db.search_keyword(qq, limit=limit),
        }
    if route == "/api/case/artifacts":
        db = get_active((q.get("id") or [None])[0])
        module = (q.get("module") or [None])[0]
        return 200, {"artifacts": db.list_artifacts(module=module)}
    if route == "/api/case/hashsets":
        db = get_active((q.get("id") or [None])[0])
        return 200, {"hash_sets": db.list_hash_sets()}
    if route == "/api/case/custody":
        db = get_active((q.get("id") or [None])[0])
        return 200, {"entries": db.custody_entries()}
    if route == "/api/case/charts":
        db = get_active((q.get("id") or [None])[0])
        return 200, db.chart_data()
    if route == "/api/lab/status":
        from tforensic.framework.lab import LabWorkspace
        db = get_active((q.get("id") or [None])[0])
        return 200, LabWorkspace(db).status().as_dict()
    if route == "/api/plugin/list":
        from tforensic.framework.plugin import list_plugins
        return 200, {"plugins": list_plugins()}
    if route == "/api/playbook/list":
        from tforensic.framework.playbook import list_playbooks
        return 200, {"playbooks": list_playbooks()}
    return 404, {"error": "not found"}


def handle_case_post(route: str, body: dict) -> tuple[int, Any]:
    global ACTIVE
    if route == "/api/case/create":
        name = body.get("name") or "Untitled"
        db = create_case(
            name,
            examiner=body.get("examiner") or "",
            description=body.get("description") or "",
        )
        ACTIVE = db
        return 200, db.info().as_dict()
    if route == "/api/case/open":
        cid = body.get("id") or body.get("case_id")
        if not cid:
            return 400, {"error": "id required", "title": "Missing case", "suggestion": "Pass case id"}
        ACTIVE = open_case(cid)
        return 200, ACTIVE.info().as_dict()
    if route == "/api/case/add":
        db = get_active(body.get("case_id"))
        path = body.get("path") or body.get("image")
        if not path:
            return 400, {"error": "path required", "title": "Missing path", "suggestion": "Provide evidence path"}
        ev = db.add_evidence(path, name=body.get("name"))
        return 200, ev
    if route == "/api/case/ingest":
        db = get_active(body.get("case_id"))
        eid = body.get("evidence_id") or body.get("evidence")
        if not eid:
            return 400, {"error": "evidence_id required"}
        mods = body.get("modules")
        ev = db.get_evidence(eid)
        est = estimate_open(ev["path"])
        jid = db.create_job("ingest", eid, eta_seconds=est["seconds"])

        def job_fn(database, job_id, progress_cb):
            return run_ingest(database, eid, progress_cb, modules=mods)

        start_job(db, jid, job_fn)
        return 200, {"job_id": jid, "estimate": est}
    if route == "/api/case/tag":
        db = get_active(body.get("case_id"))
        db.add_tag(int(body["file_id"]), body["tag"])
        return 200, {"ok": True}
    if route == "/api/case/note":
        db = get_active(body.get("case_id"))
        nid = db.add_note(body["body"], file_id=body.get("file_id"), evidence_id=body.get("evidence_id"))
        return 200, {"id": nid}
    if route == "/api/case/bookmark":
        db = get_active(body.get("case_id"))
        db.add_bookmark(int(body["file_id"]), body.get("label") or "")
        return 200, {"ok": True}
    if route == "/api/case/hash-import":
        db = get_active(body.get("case_id"))
        hashes = body.get("hashes") or []
        if body.get("text"):
            for line in str(body["text"]).splitlines():
                part = line.strip().split(",")[0].strip().strip('"').lower()
                if part and all(c in "0123456789abcdef" for c in part) and len(part) in (32, 40, 64):
                    hashes.append(part)
        if not hashes:
            return 400, {"error": "no hashes", "suggestion": "Provide hashes[] or text with one hash per line"}
        algo = body.get("algo") or ("md5" if len(hashes[0]) == 32 else "sha1" if len(hashes[0]) == 40 else "sha256")
        res = db.import_hash_set(
            body.get("name") or "imported",
            hashes,
            kind=body.get("kind") or "notable",
            algo=algo,
        )
        res["files_marked"] = db.apply_hash_sets_to_files()
        return 200, res
    if route == "/api/case/report":
        from tforensic.report import generate_html_report

        db = get_active(body.get("case_id"))
        path = generate_html_report(db, out_path=body.get("output"))
        return 200, {"report": path}
    if route == "/api/case/verify":
        from tforensic.case_ops import verify_all, verify_evidence

        db = get_active(body.get("case_id"))
        eid = body.get("evidence_id")
        if eid:
            return 200, verify_evidence(db, eid)
        return 200, {"results": verify_all(db)}
    if route == "/api/case/export":
        from tforensic.case_ops import export_case_zip

        db = get_active(body.get("case_id"))
        path = export_case_zip(db, body.get("output"))
        return 200, {"export": path}
    if route == "/api/lab/enable":
        from tforensic.framework.lab import LabWorkspace

        db = get_active(body.get("case_id"))
        st = LabWorkspace(db).enable(virtual_write=bool(body.get("virtual_write")))
        return 200, st.as_dict()
    if route == "/api/lab/copy":
        from tforensic.framework.lab import LabWorkspace

        db = get_active(body.get("case_id"))
        lab = LabWorkspace(db)
        if not lab.status().enabled:
            lab.enable()
        return 200, lab.make_working_copy(body["path"], name=body.get("name"))
    if route == "/api/plugin/run":
        from tforensic.framework.plugin import run_plugin
        from tforensic.jobs import start_job

        db = get_active(body.get("case_id"))
        name = body.get("plugin") or body.get("name")
        if not name:
            return 400, {"error": "plugin name required"}
        sync = body.get("sync", True)
        if sync:
            res = run_plugin(
                name,
                db,
                evidence_id=body.get("evidence_id"),
                params=body.get("params") or {},
            )
            return 200, res.as_dict()
        jid = db.create_job("plugin", body.get("evidence_id"))

        def job_fn(database, job_id, progress_cb):
            r = run_plugin(
                name,
                database,
                evidence_id=body.get("evidence_id"),
                params=body.get("params") or {},
                progress=progress_cb,
            )
            return r.as_dict()

        start_job(db, jid, job_fn)
        return 200, {"job_id": jid}
    if route == "/api/playbook/run":
        from tforensic.framework.playbook import run_playbook
        from tforensic.jobs import start_job

        db = get_active(body.get("case_id"))
        name = body.get("playbook") or body.get("name")
        if not name:
            return 400, {"error": "playbook name required"}
        if body.get("sync", False):
            return 200, run_playbook(
                name, db, evidence_id=body.get("evidence_id")
            )
        jid = db.create_job("playbook", body.get("evidence_id"))

        def job_fn(database, job_id, progress_cb):
            return run_playbook(
                name,
                database,
                evidence_id=body.get("evidence_id"),
                progress=progress_cb,
            )

        start_job(db, jid, job_fn)
        return 200, {"job_id": jid}
    return 404, {"error": "not found"}
