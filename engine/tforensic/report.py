"""HTML case report generator."""
from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Optional

from tforensic.casedb import CaseDB


def generate_html_report(db: CaseDB, *, out_path: Optional[str | Path] = None) -> str:
    info = db.info()
    stats = db.stats()
    evidence = db.list_evidence()
    tagged = db.list_tags()
    bookmarks = db.list_bookmarks()
    artifacts = db.list_artifacts(limit=200)
    timeline = db.query_timeline(limit=100)
    custody = db.custody_entries(limit=50)
    hash_sets = db.list_hash_sets()

    notable = []
    with db.connect() as c:
        notable = [
            dict(r)
            for r in c.execute(
                "SELECT path, name, hash_status, md5, sha256 FROM files WHERE hash_status IS NOT NULL LIMIT 100"
            ).fetchall()
        ]

    def esc(x):
        return html.escape(str(x if x is not None else ""))

    rows_ev = "".join(
        f"<tr><td>{esc(e['id'])}</td><td>{esc(e['name'])}</td><td>{esc(e['kind'])}</td>"
        f"<td>{esc(e.get('sha256',''))}</td><td>{esc(e.get('status',''))}</td></tr>"
        for e in evidence
    )
    rows_art = "".join(
        f"<tr><td>{esc(a['module'])}</td><td>{esc(a['category'])}</td>"
        f"<td>{esc(a['label'])}</td><td>{esc(a.get('path',''))}</td></tr>"
        for a in artifacts
    )
    rows_tl = "".join(
        f"<tr><td>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(a['ts']))}</td>"
        f"<td>{esc(a['event_type'])}</td><td>{esc(a['description'])}</td>"
        f"<td>{esc(a.get('path',''))}</td></tr>"
        for a in timeline
    )
    rows_bm = "".join(
        f"<tr><td>{esc(b.get('label') or '')}</td><td>{esc(b.get('path',''))}</td></tr>"
        for b in bookmarks
    )
    rows_hash = "".join(
        f"<tr><td>{esc(n['hash_status'])}</td><td>{esc(n['name'])}</td>"
        f"<td>{esc(n['path'])}</td><td>{esc(n.get('md5') or n.get('sha256') or '')}</td></tr>"
        for n in notable
    )
    rows_cust = "".join(
        f"<tr><td>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(c['ts']))}</td>"
        f"<td>{esc(c['actor'])}</td><td>{esc(c['action'])}</td><td>{esc(c['detail'])}</td></tr>"
        for c in custody
    )

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>T Forensic Report — {esc(info.name)}</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #1a1510; background: #faf8f5; }}
h1 {{ color: #8a5a12; }} h2 {{ border-bottom: 1px solid #ccc; padding-bottom: .3rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f0e6d4; }} .meta {{ color: #666; }}
.tag {{ display: inline-block; background: #2a2216; color: #f0b35a; padding: 2px 8px; border-radius: 4px; margin: 2px; font-size: 12px; }}
</style></head><body>
<h1>T Forensic Case Report</h1>
<p class="meta">Generated {time.strftime('%Y-%m-%d %H:%M:%S')} · Team NullX</p>
<p><strong>Case:</strong> {esc(info.name)} (<code>{esc(info.id)}</code>)<br>
<strong>Examiner:</strong> {esc(info.examiner)}<br>
<strong>Description:</strong> {esc(info.description)}<br>
<strong>Path:</strong> {esc(info.path)}</p>
<h2>Summary</h2>
<ul>
<li>Evidence sources: {stats['evidence']}</li>
<li>Indexed files: {stats['files']}</li>
<li>Artifacts: {stats['artifacts']}</li>
<li>Timeline events: {stats['timeline']}</li>
<li>Tags: {stats['tags']} · Notes: {stats['notes']} · Bookmarks: {stats['bookmarks']}</li>
<li>Hash sets: {stats['hash_sets']}</li>
</ul>
<h2>Evidence</h2>
<table><tr><th>ID</th><th>Name</th><th>Kind</th><th>SHA-256</th><th>Status</th></tr>{rows_ev}</table>
<h2>Bookmarks</h2>
<table><tr><th>Label</th><th>Path</th></tr>{rows_bm or '<tr><td colspan=2>None</td></tr>'}</table>
<h2>Tags</h2>
<p>{''.join(f'<span class="tag">{esc(t["tag"])} → file {t["file_id"]}</span>' for t in tagged) or 'None'}</p>
<h2>Hash set matches</h2>
<table><tr><th>Status</th><th>Name</th><th>Path</th><th>Hash</th></tr>{rows_hash or '<tr><td colspan=4>None</td></tr>'}</table>
<h2>Artifacts (sample)</h2>
<table><tr><th>Module</th><th>Category</th><th>Label</th><th>Path</th></tr>{rows_art or '<tr><td colspan=4>None</td></tr>'}</table>
<h2>Timeline (recent)</h2>
<table><tr><th>When</th><th>Type</th><th>Description</th><th>Path</th></tr>{rows_tl or '<tr><td colspan=4>None</td></tr>'}</table>
<h2>Chain of custody</h2>
<table><tr><th>When</th><th>Actor</th><th>Action</th><th>Detail</th></tr>{rows_cust}</table>
<p class="meta">Hash sets loaded: {', '.join(esc(h['name']) for h in hash_sets) or 'none'}</p>
</body></html>"""

    dest = Path(out_path) if out_path else Path(info.path) / "reports" / f"report-{int(time.time())}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    db.log_custody("report_generate", f"HTML report {dest}")
    return str(dest)
