"""Built-in framework plugins — active analysis beyond browse/read."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from tforensic.framework.plugin import Plugin, PluginContext, PluginResult


class HashSweepPlugin(Plugin):
    name = "hash_sweep"
    version = "1.0"
    description = "Hash indexed files (sample) and match against case hash sets"
    requires_lab = False

    def run(self, ctx: PluginContext) -> PluginResult:
        limit = int(ctx.params.get("limit") or 50)
        with ctx.case.connect() as c:
            rows = c.execute(
                "SELECT id, path, name, size FROM files WHERE is_dir=0 ORDER BY size DESC LIMIT ?",
                (limit,),
            ).fetchall()
        matched = 0
        scanned = 0
        for i, r in enumerate(rows):
            ctx.report((i + 1) / max(len(rows), 1), f"hash {r['name']}", None)
            with ctx.case.connect() as c:
                row = c.execute(
                    "SELECT md5, sha1, sha256 FROM files WHERE id=?", (r["id"],)
                ).fetchone()
            digest = ""
            if row:
                digest = row["sha256"] or row["md5"] or row["sha1"] or ""
            if digest and ctx.case.match_hash(digest):
                matched += 1
            scanned += 1
        marked = ctx.case.apply_hash_sets_to_files()
        return PluginResult(
            ok=True,
            plugin=self.name,
            summary=f"scanned {scanned} file records, hash-set marks={marked}, prior matches={matched}",
            data={"scanned": scanned, "marked": marked, "matched": matched},
        )


class StringsHuntPlugin(Plugin):
    name = "strings_hunt"
    version = "1.0"
    description = "Hunt suspicious keywords in indexed filenames; write hit list to lab/"
    requires_lab = True

    DEFAULT = [
        r"password",
        r"secret",
        r"wallet",
        r"ransom",
        r"bitcoin",
        r"\.onion",
        r"credential",
        r"private.?key",
    ]

    def run(self, ctx: PluginContext) -> PluginResult:
        patterns = ctx.params.get("patterns") or self.DEFAULT
        compiled = [re.compile(p, re.I) for p in patterns]
        with ctx.case.connect() as c:
            rows = c.execute(
                "SELECT id, path, name FROM files WHERE is_dir=0"
            ).fetchall()
        hits = []
        for i, r in enumerate(rows):
            blob = f"{r['name']} {r['path']}"
            for rx in compiled:
                if rx.search(blob):
                    hits.append({"file_id": r["id"], "path": r["path"], "pattern": rx.pattern})
                    ctx.add_artifact("hunt", f"Pattern {rx.pattern}", r["path"], {"pattern": rx.pattern})
                    break
            if i % 200 == 0:
                ctx.report(min(0.99, (i + 1) / max(len(rows), 1)), f"{len(hits)} hits", None)
        out = ctx.write_lab(
            "out/strings_hunt.json",
            __import__("json").dumps({"hits": hits, "count": len(hits)}, indent=2),
        )
        return PluginResult(
            ok=True,
            plugin=self.name,
            summary=f"{len(hits)} suspicious path hits → {out}",
            artifacts=hits[:50],
            files_written=[str(out)],
            data={"count": len(hits)},
        )


class TimelineExportPlugin(Plugin):
    name = "timeline_export"
    version = "1.0"
    description = "Export case timeline to lab/out/timeline.csv"
    requires_lab = True

    def run(self, ctx: PluginContext) -> PluginResult:
        events = ctx.case.query_timeline(limit=int(ctx.params.get("limit") or 5000))
        lines = ["ts,iso,event_type,source,description,path"]
        for e in events:
            iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(e["ts"]))
            desc = (e.get("description") or "").replace(",", " ")
            path = (e.get("path") or "").replace(",", " ")
            lines.append(
                f"{e['ts']},{iso},{e.get('event_type')},{e.get('source')},{desc},{path}"
            )
        out = ctx.write_lab("out/timeline.csv", "\n".join(lines) + "\n")
        return PluginResult(
            ok=True,
            plugin=self.name,
            summary=f"exported {len(events)} events → {out}",
            files_written=[str(out)],
            data={"events": len(events)},
        )


class CorrelationPlugin(Plugin):
    name = "correlate"
    version = "1.0"
    description = "Correlate tags, bookmarks, artifacts, and hash hits into a lab brief"
    requires_lab = True

    def run(self, ctx: PluginContext) -> PluginResult:
        stats = ctx.case.stats()
        tags = ctx.case.list_tags()
        bms = ctx.case.list_bookmarks()
        arts = ctx.case.list_artifacts(limit=100)
        notable = []
        with ctx.case.connect() as c:
            notable = [
                dict(r)
                for r in c.execute(
                    "SELECT path, name, hash_status FROM files WHERE hash_status='notable' LIMIT 50"
                ).fetchall()
            ]
        brief = {
            "generated_at": time.time(),
            "stats": stats,
            "tags": tags[:50],
            "bookmarks": bms,
            "artifacts_sample": arts[:40],
            "notable_hashes": notable,
            "policy": "Evidence immutable — this brief is analysis product only.",
        }
        out = ctx.write_lab(
            "out/correlation_brief.json",
            __import__("json").dumps(brief, indent=2),
        )
        md = [
            "# T Forensic correlation brief",
            "",
            f"- Files: {stats.get('files')}",
            f"- Artifacts: {stats.get('artifacts')}",
            f"- Tags: {stats.get('tags')}",
            f"- Notable hash hits: {len(notable)}",
            "",
            "## Bookmarks",
        ]
        for b in bms:
            md.append(f"- {b.get('label') or ''} `{b.get('path')}`")
        md_path = ctx.write_lab("out/correlation_brief.md", "\n".join(md) + "\n")
        return PluginResult(
            ok=True,
            plugin=self.name,
            summary=f"brief → {out}",
            files_written=[str(out), str(md_path)],
            data=brief,
        )
