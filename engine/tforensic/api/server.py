"""Local loopback JSON API + static web UI for Team Forensic Framework."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from tforensic.accessors import (
    accessor_to_dict,
    list_accessors,
    open_with_accessor,
    preview_byte_cap,
)
from tforensic.analysis import classify_artifacts, hashes, is_executable
from tforensic.case import Case, load_case, tree_dict
from tforensic.evidence import DiskCase, PcapCase, accepted_formats, open_evidence
from tforensic.preview import (
    HEX_PREVIEW_MAX,
    detect_and_decode,
    hex_window,
    preview_to_dict,
)
from tforensic import xmount_wrap as xm
from dataclasses import asdict

CASE: Optional[object] = None  # Case | DiskCase | PcapCase
WEB_DIR: str = ""


def _uploads_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "tforensic-uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_byte_window(q) -> tuple[int, Optional[int]]:
    """offset / bytes query params for hex (and large-file) paging."""
    try:
        offset = max(0, int((q.get("offset") or ["0"])[0]))
    except (TypeError, ValueError):
        offset = 0
    raw = (q.get("bytes") or [None])[0]
    if raw in (None, ""):
        return offset, None
    try:
        length = max(1, min(int(raw), HEX_PREVIEW_MAX))
    except (TypeError, ValueError):
        length = None
    return offset, length


def _hex_payload(data: bytes, *, name: str = "", note: str = "", offset: int = 0, length: Optional[int] = None) -> dict:
    text, off, win, more = hex_window(data, offset=offset, length=length)
    ext = ""
    if name and "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
    end = off + win
    n = note or f"hex bytes {off}-{end} of {len(data)}"
    return {
        "accessor": "hex",
        "label": "Hex",
        "extension": ext,
        "mime": "application/octet-stream",
        "mode": "hex",
        "encoding": None,
        "text": text,
        "html": "",
        "data_url": "",
        "rows": None,
        "columns": None,
        "items": None,
        "truncated": more or off > 0,
        "size": len(data),
        "kind": "hex",
        "executable": is_executable(data),
        "note": n,
        "offset": off,
        "window": win,
    }


def _safe_upload_name(name: str) -> str:
    base = Path(name or "upload.bin").name
    base = re.sub(r"[^\w.\-+()\[\] ]+", "_", base).strip(" .") or "upload.bin"
    return base[:200]


def _unique_upload_path(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    n = 1
    while True:
        cand = dest_dir / f"{stem}_{n}{suf}"
        if not cand.exists():
            return cand
        n += 1


def _is_ad1_case(c) -> bool:
    return isinstance(c, Case)


def _is_disk_case(c) -> bool:
    return isinstance(c, DiskCase)


def _is_pcap_case(c) -> bool:
    return isinstance(c, PcapCase)


def default_web_dir() -> str:
    here = Path(__file__).resolve()
    repo_web = here.parents[3] / "web"
    if repo_web.is_dir():
        return str(repo_web)
    return str(here.parents[2] / "web")


class Handler(BaseHTTPRequestHandler):
    server_version = "TFF/0.3.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Filename, X-Open",
        )
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                return self._serve_static("index.html")
            if route.startswith("/static/"):
                return self._serve_static(route[len("/static/") :])
            if route == "/api/formats":
                return self._send(200, accepted_formats())
            if route == "/api/estimate":
                from tforensic.estimate import estimate_open
                p = (q.get("path") or [None])[0]
                if not p:
                    return self._send(400, {
                        "error": "path query required",
                        "title": "Missing path",
                        "suggestion": "Call /api/estimate?path=/path/to/image",
                    })
                itype = (q.get("input_type") or q.get("in") or [None])[0]
                return self._send(200, estimate_open(p, input_type=itype))
            if route == "/api/shell/context":
                return self._api_shell_context()
            if route.startswith("/api/case/") or route.startswith("/api/lab/") or route.startswith("/api/plugin/") or route.startswith("/api/playbook/"):
                from tforensic import case_api
                code, body = case_api.handle_case_get(route, q)
                return self._send(code, body)
            if route == "/api/info":
                if CASE is None:
                    from tforensic import case_api
                    try:
                        db = case_api.get_active()
                        info = db.info().as_dict()
                        info["kind"] = "case"
                        info["stats"] = db.stats()
                        return self._send(200, info)
                    except Exception as e:
                        return self._send(400, {
                            "error": str(e),
                            "title": "No case or triage image",
                            "suggestion": "Open an image or create a case from the Case tab.",
                        })
                return self._send(200, CASE.info())
            if route == "/api/tree":
                if CASE is None:
                    return self._send(200, {
                        "name": "/", "path": "/", "is_dir": True, "children": [],
                        "note": "case mode — use Case tab",
                    })
                if _is_pcap_case(CASE):
                    name = Path(CASE.pcap_path).name
                    return self._send(200, {
                        "name": name,
                        "path": CASE.pcap_path,
                        "is_dir": True,
                        "children": [{
                            "name": name,
                            "path": CASE.pcap_path,
                            "is_dir": False,
                            "size": CASE.meta.image_size,
                            "note": "Open Network tab for packet analysis",
                        }],
                        "kind": "pcap",
                        "note": "Packet capture — use Network tab",
                    })
                parent = (q.get("path") or [None])[0]
                if _is_disk_case(CASE):
                    if parent:
                        return self._send(200, self._disk_tree_children(parent))
                    return self._send(200, self._disk_tree())
                if parent:
                    node = CASE.get(parent)
                    if not node:
                        return self._send(404, {
                            "error": f"path not found: {parent}",
                            "title": "Not in tree",
                            "suggestion": "Expand the root folder and click a file from the list.",
                        })
                    return self._send(200, tree_dict(node))
                return self._send(200, tree_dict(CASE.img.root))
            if route == "/api/meta":
                if CASE is None or _is_disk_case(CASE) or _is_pcap_case(CASE):
                    return self._send(400, {
                        "error": "AD1-style metadata is not available in this mode.",
                        "title": "Wrong mode",
                        "suggestion": "For packet captures use the Network tab. For disk images use Disk → Partitions.",
                    })
                return self._api_meta(q)
            if route == "/api/hash":
                if CASE is None:
                    return self._send(400, {"error": "No image open", "title": "Nothing open", "suggestion": "Open an image first."})
                if _is_pcap_case(CASE):
                    return self._send(400, {
                        "error": "Use Network tab for captures, or Case hash tools.",
                        "title": "Hash not available here",
                        "suggestion": "Open AD1 for file hashes, or use Case → Verify for evidence hashes.",
                    })
                if _is_disk_case(CASE):
                    return self._api_disk_hash(q)
                return self._api_hash(q)
            if route == "/api/file":
                if CASE is None:
                    return self._send(400, {
                        "error": "No image open for preview.",
                        "title": "Nothing open",
                        "suggestion": "Open an AD1/disk image first.",
                    })
                if _is_pcap_case(CASE):
                    return self._send(400, {
                        "error": "Packet captures open in the Network tab.",
                        "title": "Use Network",
                        "suggestion": "Click Network → packet list / Stats.",
                    })
                if _is_disk_case(CASE):
                    return self._api_disk_file(q)
                return self._api_file(q)
            if route == "/api/sqlite/tables":
                return self._api_sqlite("tables", q)
            if route == "/api/sqlite/schema":
                return self._api_sqlite("schema", q)
            if route == "/api/sqlite/rows":
                return self._api_sqlite("rows", q)
            if route == "/api/sqlite/search":
                return self._api_sqlite("search", q)
            if route == "/api/download":
                if CASE is None or _is_disk_case(CASE):
                    return self._send(400, {
                        "error": "AD1 download is not used in this mode.",
                        "title": "Use Case / Disk tab",
                        "suggestion": "Export from Case or Disk tab.",
                    })
                return self._api_download(q)
            if route == "/api/search":
                return self._api_search(q)
            if route == "/api/grep":
                return self._api_grep(q)
            if route == "/api/accessors":
                return self._send(200, {"accessors": list_accessors()})
            if route == "/api/artifacts":
                if CASE is None or _is_disk_case(CASE):
                    return self._send(200, {"hits": []})
                return self._send(200, {"hits": classify_artifacts(CASE.files)})
            if route == "/api/health":
                from tforensic import APP_NAME, APP_SHORT, __version__
                from tforensic.deps import check_dependencies

                deps = check_dependencies()
                return self._send(200, {
                    "ok": True,
                    "name": APP_NAME,
                    "short": APP_SHORT,
                    "version": __version__,
                    "session": CASE.meta.id if CASE is not None else None,
                    "kind": getattr(CASE, "kind", "ad1") if CASE is not None else "case",
                    "deps": {
                        "complete": deps.get("complete"),
                        "missing": deps.get("counts", {}).get("missing", 0),
                        "summary": deps.get("summary"),
                    },
                })
            if route == "/api/deps":
                from tforensic.deps import check_dependencies

                return self._send(200, check_dependencies())
            if route == "/api/version":
                from tforensic import APP_NAME, APP_SHORT, __version__
                return self._send(200, {
                    "name": APP_NAME,
                    "short": APP_SHORT,
                    "version": __version__,
                    "product": f"{APP_SHORT} {__version__}",
                })
            # ---- xmount / disk ----
            if route == "/api/xmount/info":
                return self._send(200, xm.probe())
            if route == "/api/xmount/mounts":
                mounts = [asdict(m) for m in xm.list_active_mounts()]
                # ensure current disk case mount is listed
                if _is_disk_case(CASE):
                    cur = asdict(CASE.mount)
                    if not any(m.get("id") == cur.get("id") for m in mounts):
                        mounts.insert(0, cur)
                return self._send(200, {"mounts": mounts})
            if route == "/api/xmount/partitions":
                return self._api_xm_partitions(q)
            if route == "/api/xmount/fls":
                return self._api_xm_fls(q)
            # ---- PCAP / Network (Wireshark-style via tshark) ----
            if route == "/api/pcap/status":
                from tforensic import pcap_analysis as pa
                return self._send(200, {
                    "tshark": bool(pa.tshark_bin()),
                    "active": pa.active().as_dict() if pa.active() else None,
                })
            if route == "/api/pcap/summary":
                from tforensic import pcap_analysis as pa
                return self._send(200, pa.summary())
            if route == "/api/pcap/packets":
                from tforensic import pcap_analysis as pa
                if not pa.active():
                    return self._send(400, {
                        "error": "No PCAP open",
                        "title": "Open a capture",
                        "suggestion": "Network tab → enter .pcap/.pcapng path → Open",
                    })
                off = int((q.get("offset") or ["0"])[0])
                lim = int((q.get("limit") or ["200"])[0])
                yf = (q.get("filter") or [""])[0]
                return self._send(200, pa.packet_list(offset=off, limit=lim, display_filter=yf))
            if route == "/api/pcap/detail":
                from tforensic import pcap_analysis as pa
                if not pa.active():
                    return self._send(400, {"error": "No PCAP open"})
                no = int((q.get("no") or ["1"])[0])
                return self._send(200, pa.packet_detail(no))
            if route == "/api/pcap/protocols":
                from tforensic import pcap_analysis as pa
                return self._send(200, {"protocols": pa.protocol_stats()})
            if route == "/api/pcap/conversations":
                from tforensic import pcap_analysis as pa
                kind = (q.get("kind") or ["ip"])[0]
                return self._send(200, {"conversations": pa.conversations(kind=kind)})
            if route == "/api/pcap/dns":
                from tforensic import pcap_analysis as pa
                return self._send(200, {"queries": pa.dns_queries()})
            if route == "/api/pcap/http":
                from tforensic import pcap_analysis as pa
                return self._send(200, {"requests": pa.http_hosts()})
            return self._send(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:
            from tforensic.errors import explain_exception
            self._send(500, explain_exception(e).as_dict())

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        if parsed.path == "/api/open-upload":
            try:
                return self._api_open_upload(length)
            except Exception as e:
                from tforensic.errors import explain_exception
                return self._send(500, explain_exception(e, "open").as_dict())
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._send(400, {
                "error": "Invalid request body (expected JSON).",
                "title": "Bad request",
                "suggestion": "Retry the action from the UI, or check the API JSON payload.",
            })
        try:
            if parsed.path == "/api/open":
                return self._api_open(body)
            if parsed.path == "/api/export":
                if CASE is None:
                    return self._send(400, {"error": "no triage case", "suggestion": "Use Case tab export"})
                if _is_disk_case(CASE):
                    return self._send(400, {
                        "error": "AD1 export is not used in disk/OVA mode.",
                        "title": "Wrong mode",
                        "suggestion": "Use the Disk tab: click a file to extract with icat.",
                    })
                path = body.get("path")
                dest = body.get("dest")
                out = CASE.export_file(path, dest=dest)
                return self._send(200, {"exported": out})
            if parsed.path.startswith("/api/case/") or parsed.path.startswith("/api/lab/") or parsed.path.startswith("/api/plugin/") or parsed.path.startswith("/api/playbook/"):
                from tforensic import case_api
                code, resp = case_api.handle_case_post(parsed.path, body)
                return self._send(code, resp)
            if parsed.path == "/api/xmount/mount":
                return self._api_xm_mount(body)
            if parsed.path == "/api/xmount/umount":
                return self._api_xm_umount(body)
            if parsed.path == "/api/xmount/icat":
                return self._api_xm_icat(body)
            if parsed.path == "/api/pcap/open":
                from tforensic import pcap_analysis as pa
                path = body.get("path")
                if not path:
                    return self._send(400, {
                        "error": "path required",
                        "suggestion": "Pass {\"path\": \"/path/to/capture.pcap\"}",
                    })
                sess = pa.open_pcap(path)
                return self._send(200, sess.as_dict())
            if parsed.path == "/api/pcap/close":
                from tforensic import pcap_analysis as pa
                pa.close()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            from tforensic.errors import explain_exception
            self._send(500, explain_exception(e, "mount").as_dict())

    def _close_active_case(self):
        global CASE
        if CASE is None:
            return
        try:
            CASE.close()
        except Exception:
            pass
        CASE = None

    def _api_open(self, body):
        global CASE
        path = (body.get("path") or "").strip()
        if not path:
            return self._send(400, {
                "error": "path required",
                "title": "Missing path",
                "suggestion": "Pass {\"path\": \"/path/to/evidence.ad1\"} or use Open evidence…",
            })
        path = str(Path(path).expanduser())
        if not os.path.exists(path):
            return self._send(400, {
                "error": f"not found: {path}",
                "title": "Evidence not found",
                "suggestion": "Use Open evidence… to pick a file or folder, or enter a path that exists on this machine.",
            })
        self._close_active_case()
        CASE = open_evidence(
            path,
            input_type=body.get("input_type") or None,
            output_type=body.get("output_type") or "raw",
            morph=body.get("morph") or "combine",
            cache=body.get("cache") or None,
        )
        return self._send(200, CASE.info())

    def _api_open_upload(self, length: int):
        """Accept raw file body (browser File) and open it as evidence."""
        global CASE
        if length <= 0:
            return self._send(400, {
                "error": "empty upload",
                "title": "No file",
                "suggestion": "Choose an evidence file with Open evidence…",
            })
        # Cap extremely large uploads in-memory stream is fine for local loopback,
        # but refuse absurd Content-Lengths that are clearly mistakes.
        max_bytes = 64 * 1024 * 1024 * 1024  # 64 GiB hard ceiling
        if length > max_bytes:
            # Drain / reject without writing
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            return self._send(400, {
                "error": "upload too large",
                "title": "File too large",
                "suggestion": "For huge images, use Open by path… with a local filesystem path.",
            })
        fname = self.headers.get("X-Filename") or "upload.bin"
        dest = _unique_upload_path(_uploads_dir(), _safe_upload_name(fname))
        remaining = length
        chunk_size = 1024 * 1024
        try:
            with open(dest, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            if remaining > 0:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
                return self._send(400, {
                    "error": "incomplete upload",
                    "title": "Upload failed",
                    "suggestion": "Retry Open evidence… or use Open by path…",
                })
            open_it = (self.headers.get("X-Open") or "1").strip().lower() not in (
                "0", "false", "no",
            )
            if not open_it:
                return self._send(200, {
                    "ok": True,
                    "uploaded_path": str(dest),
                    "name": dest.name,
                    "size": dest.stat().st_size,
                })
            self._close_active_case()
            CASE = open_evidence(str(dest))
            info = CASE.info()
            info["uploaded_path"] = str(dest)
            return self._send(200, info)
        except Exception:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _disk_tree(self):
        """Synthetic tree for disk mode: partitions as expandable children."""
        name = Path(CASE.meta.image_path).name
        children = []
        try:
            parts = xm.mmls_partitions(CASE.mount.virtual_device)
            usable = [p for p in parts if int(p.get("length") or 0) > 0]
            if not usable:
                usable = parts
            for p in usable:
                children.append({
                    "name": f"{p.get('slot', '?')} {p.get('desc', 'part')} (start={p['start']})",
                    "path": f"part:{p['start']}",
                    "is_dir": True,
                    "size": int(p.get("length") or 0) * 512,
                    "children": [],
                    "lazy": True,
                })
            if not children:
                # whole-disk fallback
                children.append({
                    "name": "entire device (offset 0)",
                    "path": "part:0",
                    "is_dir": True,
                    "size": CASE.meta.image_size,
                    "children": [],
                    "lazy": True,
                })
        except Exception as e:
            children.append({
                "name": f"(mmls unavailable: {e})",
                "path": "part:0",
                "is_dir": True,
                "size": 0,
                "children": [],
                "lazy": True,
                "note": str(e),
            })
        return {
            "name": name,
            "path": "disk:",
            "is_dir": True,
            "size": CASE.meta.image_size,
            "children": children,
            "lazy": False,
        }

    def _disk_tree_children(self, path: str) -> dict:
        """List fls entries under part:OFFSET or inode:OFFSET:INODE."""
        device = CASE.mount.virtual_device
        offset = 0
        inode = None
        label = path
        if path.startswith("part:"):
            offset = int(path.split(":", 1)[1] or 0)
            label = f"partition @{offset}"
        elif path.startswith("inode:"):
            # inode:OFFSET:INODE[:name]
            parts = path.split(":")
            offset = int(parts[1] or 0)
            inode = parts[2] if len(parts) > 2 else None
            label = parts[3] if len(parts) > 3 else f"inode {inode}"
        else:
            return {
                "name": path,
                "path": path,
                "is_dir": True,
                "children": [],
                "error": "unknown disk tree path",
            }
        try:
            entries = xm.fls_list(
                device,
                offset_sectors=offset,
                inode=inode,
                recursive=False,
                limit=3000,
            )
        except Exception as e:
            from tforensic.errors import explain_exception
            err = explain_exception(e).as_dict()
            return {
                "name": label,
                "path": path,
                "is_dir": True,
                "children": [],
                "error": err.get("error"),
                "title": err.get("title"),
                "suggestion": err.get("suggestion"),
            }
        children = []
        for e in entries:
            name = e.get("name") or e.get("inode") or "?"
            # fls -p may return full paths; use basename for display
            disp = name.rstrip("/").split("/")[-1] or name
            if e.get("is_dir"):
                child_path = f"inode:{offset}:{e['inode']}:{disp}"
                children.append({
                    "name": disp + "/",
                    "path": child_path,
                    "is_dir": True,
                    "size": 0,
                    "children": [],
                    "lazy": True,
                    "deleted": bool(e.get("deleted")),
                    "inode": e.get("inode"),
                })
            else:
                child_path = f"inode:{offset}:{e['inode']}:{disp}"
                children.append({
                    "name": ("*" if e.get("deleted") else "") + disp,
                    "path": child_path,
                    "is_dir": False,
                    "size": 0,
                    "deleted": bool(e.get("deleted")),
                    "inode": e.get("inode"),
                    "offset": offset,
                })
        return {
            "name": label,
            "path": path,
            "is_dir": True,
            "children": children,
            "lazy": False,
        }

    def _parse_inode_path(self, path: str):
        # inode:OFFSET:INODE:name
        if not path or not path.startswith("inode:"):
            return None
        parts = path.split(":")
        if len(parts) < 3:
            return None
        return {
            "offset": int(parts[1] or 0),
            "inode": parts[2],
            "name": parts[3] if len(parts) > 3 else parts[2],
        }

    def _api_disk_file(self, q):
        path = (q.get("path") or [None])[0]
        parsed = self._parse_inode_path(path or "")
        if not parsed:
            return self._send(400, {
                "error": "Expand a partition in the Tree, then click a file.",
                "title": "Disk browse",
                "suggestion": "Tree → partition → folder → file. Or use the Disk tab.",
            })
        mode = (q.get("mode") or ["auto"])[0]
        dest = Path(CASE.meta.export_dir) / f"preview_{parsed['inode']}_{parsed['name']}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            out = xm.icat_extract(
                CASE.mount.virtual_device,
                str(parsed["inode"]),
                dest,
                offset_sectors=parsed["offset"],
            )
            data = Path(out).read_bytes()
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())
        # limit preview size (SQLite needs a fuller extract for browsing)
        from tforensic.sqlite_view import MAX_SQLITE_BYTES, looks_like_sqlite
        want_sqlite = looks_like_sqlite(b"", parsed["name"]) or (
            len(data) >= 16 and data[:15] == b"SQLite format 3"
        )
        # Re-read if we truncated a SQLite DB — icat already wrote full file to dest
        if want_sqlite:
            try:
                data = Path(out).read_bytes()[:MAX_SQLITE_BYTES]
            except Exception:
                pass
            preview = data
        else:
            # Prefer full extracted file; cap only for huge media/binaries
            cap = preview_byte_cap(parsed["name"])
            preview = data if len(data) <= cap else data[:cap]
        off, nbytes = _parse_byte_window(q)
        if mode == "hex":
            # Page hex across the full icat bytes (up to 256 MiB resident)
            hex_cap = 256 * 1024 * 1024
            src = data if len(data) <= hex_cap else data[:hex_cap]
            payload = _hex_payload(
                src,
                name=parsed["name"],
                note=f"icat inode {parsed['inode']} → {out}",
                offset=off,
                length=nbytes,
            )
            payload["size"] = len(data)
            if len(src) < len(data):
                payload["truncated"] = True
                payload["note"] += (
                    f" · inline window {len(src)} of {len(data)} bytes "
                    "(Export for remainder)"
                )
            return self._send(200, payload)
        acc = open_with_accessor(
            parsed["name"], preview, offset=off, length=nbytes,
        )
        d = accessor_to_dict(acc)
        d["size"] = len(data)
        d["note"] = (d.get("note") or "") + f" · icat inode {parsed['inode']}"
        if len(data) > len(preview):
            d["truncated"] = True
            d["note"] += (
                f" · loaded {len(preview)} of {len(data)} bytes "
                "(Export for full file)"
            )
        return self._send(200, d)

    def _api_disk_hash(self, q):
        path = (q.get("path") or [None])[0]
        parsed = self._parse_inode_path(path or "")
        if not parsed:
            return self._send(400, {
                "error": "Select a file from a partition in the Tree first.",
                "title": "No file",
                "suggestion": "Tree → partition → file, then Hashes.",
            })
        dest = Path(CASE.meta.export_dir) / f"hash_{parsed['inode']}_{parsed['name']}"
        try:
            out = xm.icat_extract(
                CASE.mount.virtual_device,
                str(parsed["inode"]),
                dest,
                offset_sectors=parsed["offset"],
            )
            data = Path(out).read_bytes()
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())
        result = hashes(data)
        result["executable"] = is_executable(data)
        result["exported"] = out
        return self._send(200, result)

    def _xm_device(self, q_or_body):
        if isinstance(q_or_body, dict) and not any(
            isinstance(v, list) for v in q_or_body.values()
        ):
            mid = q_or_body.get("id")
            image = q_or_body.get("image")
        else:
            mid = (q_or_body.get("id") or [None])[0]
            image = (q_or_body.get("image") or [None])[0]
        if image:
            return image
        # prefer active disk case
        if _is_disk_case(CASE) and (not mid or mid == CASE.mount.id):
            return CASE.mount.virtual_device
        rec = xm.find_mount(mid)
        return rec.virtual_device

    def _api_shell_context(self):
        from tforensic.shell_access import context_from_case_object, context_from_persistent_case

        try:
            if CASE is not None:
                ctx = context_from_case_object(CASE)
                return self._send(200, ctx)
            from tforensic import case_api
            try:
                db = case_api.get_active()
                ctx = context_from_persistent_case(db)
                return self._send(200, ctx)
            except Exception:
                return self._send(400, {
                    "error": "No open triage session or case.",
                    "title": "Nothing mounted",
                    "suggestion": "Open an image (File → Open) or create a case first.",
                })
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _serve_static(self, rel):
        rel = rel.lstrip("/")
        # AD1-viewer layout: /static/X -> WEB_DIR/X
        candidates = [
            os.path.normpath(os.path.join(WEB_DIR, rel)),
            os.path.normpath(os.path.join(WEB_DIR, "static", rel)),
        ]
        full = next((c for c in candidates if os.path.isfile(c)), None)
        root = os.path.abspath(WEB_DIR)
        if not full or not (
            full == root or full.startswith(root + os.sep)
        ):
            return self._send(404, {"error": "not found"})
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".json": "application/json",
            ".woff2": "font/woff2",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        extra = {"Access-Control-Allow-Origin": "*"}
        # Always revalidate UI assets so theme/font updates show after restart
        if os.path.splitext(full)[1].lower() in (".html", ".css", ".js", ".svg"):
            extra["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            extra["Pragma"] = "no-cache"
        return self._send(200, data, ctype, extra=extra)

    def do_HEAD(self):
        # Browsers / Electron may probe with HEAD; map to GET without body.
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route in ("/", "/index.html") or route.startswith("/static/"):
            # Reuse GET path logic lightly
            self.send_response(200)
            if route.endswith(".css"):
                self.send_header("Content-Type", "text/css")
            elif route.endswith(".js"):
                self.send_header("Content-Type", "application/javascript")
            elif route.endswith(".svg"):
                self.send_header("Content-Type", "image/svg+xml")
            else:
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def _node(self, q):
        path = q.get("path", [None])[0]
        return CASE.get(path) if path else None

    def _api_meta(self, q):
        node = self._node(q)
        if not node:
            return self._send(404, {"error": "path not found"})
        attrs = {str(k): v for k, v in CASE.img.metadata(node).items()}
        from tforensic.meta_format import format_attrs, parse_recycle_i

        rows = format_attrs(attrs)
        extra = {}
        name = (node.name or "").upper()
        if name.startswith("$I") and not node.is_dir:
            try:
                data = CASE.read(node.path)
                parsed = parse_recycle_i(data)
                if parsed:
                    extra["recycle"] = parsed
            except Exception:
                pass
        return self._send(200, {"path": node.path, "attrs": attrs, "rows": rows, **extra})

    def _api_hash(self, q):
        node = self._node(q)
        if not node or (node.is_dir and not (node.chunk_desc_rel and node.size)):
            return self._send(404, {"error": "file not found"})
        data = CASE.read(node.path)
        out = hashes(data)
        out["executable"] = is_executable(data)
        return self._send(200, out)

    def _read_evidence_bytes(self, path: str, max_bytes: int | None = None) -> tuple[bytes, str]:
        """Return (bytes, display_name) for AD1 path or inode: disk path."""
        from tforensic.sqlite_view import MAX_SQLITE_BYTES
        cap = max_bytes if max_bytes is not None else MAX_SQLITE_BYTES
        if path.startswith("inode:"):
            parsed = self._parse_inode_path(path)
            if not parsed:
                raise ValueError("Invalid disk inode path")
            dest = Path(CASE.meta.export_dir) / f"sqlite_{parsed['inode']}_{parsed['name']}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            out = xm.icat_extract(
                CASE.mount.virtual_device,
                str(parsed["inode"]),
                dest,
                offset_sectors=parsed["offset"],
            )
            data = Path(out).read_bytes()[:cap]
            return data, parsed["name"]
        if CASE is None:
            raise ValueError("No image open")
        if _is_disk_case(CASE) or _is_pcap_case(CASE):
            raise ValueError("Select a file from the Tree (AD1 path or disk inode)")
        node = CASE.get(path)
        if not node or (node.is_dir and not (node.chunk_desc_rel and node.size)):
            raise ValueError(f"File not found: {path}")
        data = CASE.read(node.path)[:cap]
        return data, node.name

    def _sqlite_wal(self, path: str) -> Optional[bytes]:
        """Sibling <db>-wal bytes for AD1/folder evidence, if present."""
        if CASE is None or path.startswith("inode:") or _is_disk_case(CASE) or _is_pcap_case(CASE):
            return None
        node = CASE.get(path)
        if not node:
            return None
        wal = CASE.path_index.get(f"{node.path}-wal")
        if not wal or wal.is_dir:
            return None
        try:
            return CASE.read(wal.path) or None
        except Exception:
            return None

    def _api_sqlite(self, action: str, q):
        from tforensic.sqlite_view import (
            list_tables,
            materialize_sqlite,
            table_rows,
            table_schema,
            table_search,
        )
        path = (q.get("path") or [None])[0]
        if not path:
            return self._send(400, {
                "error": "path required",
                "title": "Missing path",
                "suggestion": "Click a .sqlite / .db file in the Tree first.",
            })
        if CASE is None:
            return self._send(400, {
                "error": "No image open",
                "title": "Nothing open",
                "suggestion": "Open evidence, then select a SQLite file.",
            })
        try:
            data, name = self._read_evidence_bytes(path)
            cache_dir = str(Path(CASE.meta.export_dir) / "sqlite-cache")
            mat = materialize_sqlite(
                path, data, cache_dir=cache_dir, wal=self._sqlite_wal(path),
            )
            db_path = mat["path"]
            if action == "tables":
                tables = list_tables(db_path)
                return self._send(200, {
                    "path": path,
                    "name": name,
                    "size": mat["size"],
                    "truncated": mat["truncated"],
                    "tables": tables,
                })
            table = (q.get("table") or [None])[0]
            if not table:
                return self._send(400, {
                    "error": "table query required",
                    "title": "No table",
                    "suggestion": "Pick a table from the SQLite browser list.",
                })
            if action == "schema":
                return self._send(200, table_schema(db_path, table))
            if action == "rows":
                offset = int((q.get("offset") or ["0"])[0] or 0)
                limit = int((q.get("limit") or ["100"])[0] or 100)
                return self._send(200, table_rows(db_path, table, offset, limit))
            if action == "search":
                term = (q.get("q") or [""])[0] or ""
                limit = int((q.get("limit") or ["300"])[0] or 300)
                return self._send(200, table_search(db_path, table, term, limit))
            return self._send(404, {"error": f"unknown sqlite action: {action}"})
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _api_file(self, q):
        path = (q.get("path") or [None])[0]
        node = self._node(q)
        if not node or (node.is_dir and not (node.chunk_desc_rel and node.size)):
            return self._send(404, {
                "error": f"File not found in AD1 tree: {path}",
                "title": "File not found",
                "suggestion": "Expand the root folder in Tree and click a file (not a folder).",
            })
        mode = q.get("mode", ["auto"])[0]
        force = q.get("accessor", [None])[0]
        off, nbytes = _parse_byte_window(q)
        try:
            data = CASE.read(node.path)
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())
        if mode == "hex":
            return self._send(
                200,
                _hex_payload(data, name=node.name or "", offset=off, length=nbytes),
            )
        if mode == "force-hex":
            result = detect_and_decode(data, force_hex=True, offset=off, length=nbytes)
            out = preview_to_dict(result)
            out.update({
                "accessor": "hex", "label": "Hex", "extension": "", "mime": "",
                "html": "", "data_url": "", "rows": None, "columns": None, "items": None,
            })
            return self._send(200, out)
        # Extension-aware accessor (default Preview tab)
        try:
            system_data = None
            if (force or "").lower() == "sam" or (node.name or "").upper() == "SAM":
                from tforensic.sam_view import find_sibling_hive

                sys_path = find_sibling_hive(CASE.get, node.path, "SYSTEM")
                if sys_path:
                    try:
                        system_data = CASE.read(sys_path)
                    except Exception:
                        system_data = None
            wal_data = self._sqlite_wal(node.path) if data[:15] == b"SQLite format 3" else None
            acc = open_with_accessor(
                node.path,
                data,
                force=force,
                system_data=system_data,
                wal_data=wal_data,
                offset=off,
                length=nbytes,
            )
            return self._send(200, accessor_to_dict(acc))
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _api_download(self, q):
        node = self._node(q)
        if not node or (node.is_dir and not (node.chunk_desc_rel and node.size)):
            return self._send(404, {"error": "file not found"})
        data = CASE.read(node.path)
        fname = node.name.replace('"', "")
        return self._send(
            200,
            data,
            "application/octet-stream",
            {"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    def _api_search(self, q):
        term = (q.get("q", [""])[0] or "").lower()
        under = (q.get("under") or [None])[0]
        if not term:
            return self._send(200, {"results": [], "count": 0, "under": under})
        if CASE is None:
            return self._send(200, {"results": [], "count": 0, "under": under})
        # Disk inode trees: search via fls listing of parent when possible
        if _is_disk_case(CASE) and under and str(under).startswith(("part:", "inode:")):
            try:
                kids = self._disk_tree_children(under)
                children = kids.get("children") or []
                results = []
                for c in children:
                    name = (c.get("name") or "").lower()
                    path = c.get("path") or ""
                    if term in name or term in path.lower():
                        results.append({
                            "path": path,
                            "name": c.get("name"),
                            "size": c.get("size"),
                            "is_dir": bool(c.get("is_dir")),
                        })
                return self._send(200, {
                    "results": results[:500],
                    "count": len(results),
                    "under": under,
                    "scope": "folder",
                })
            except Exception as e:
                return self._send(400, {
                    "error": str(e),
                    "title": "Folder search failed",
                    "suggestion": "Try expanding the folder in Tree, then search again.",
                })
        files = getattr(CASE, "files", None) or []
        results = []
        for n in files:
            if under and not (n.path == under or n.path.startswith(under.rstrip("/") + "/")):
                continue
            if term in n.name.lower() or term in n.path.lower():
                results.append({
                    "path": n.path,
                    "name": n.name,
                    "size": n.size,
                    "is_dir": False,
                })
        return self._send(200, {
            "results": results[:500],
            "count": len(results),
            "under": under,
            "scope": "folder" if under else "image",
        })

    def _api_grep(self, q):
        """Grep-like filename + small-text content search under a folder."""
        term = (q.get("q", [""])[0] or "")
        under = (q.get("under") or [None])[0]
        if not term:
            return self._send(200, {"hits": [], "count": 0})
        if CASE is None or _is_pcap_case(CASE):
            return self._send(400, {
                "error": "Open an AD1/disk image first.",
                "title": "Nothing to search",
            })
        term_l = term.lower()
        hits = []
        # 1) filename hits (reuse search)
        sq = {"q": [term], "under": [under] if under else []}
        name_hits = self._api_search_collect(term_l, under)
        for r in name_hits[:200]:
            hits.append({**r, "kind": "name", "snippet": r.get("path")})

        # 2) content peek for AD1 text-ish files under folder (cap work)
        if not _is_disk_case(CASE) and hasattr(CASE, "files"):
            scanned = 0
            for n in CASE.files:
                if scanned >= 80 or len(hits) >= 300:
                    break
                if n.is_dir:
                    continue
                if under and not (n.path == under or n.path.startswith(under.rstrip("/") + "/")):
                    continue
                if n.size and n.size > 512_000:
                    continue
                ext = (n.name.rsplit(".", 1)[-1].lower() if "." in n.name else "")
                if ext in {"sqlite", "sqlite3", "db", "db3", "jpg", "png", "gif", "pdf", "exe", "dll", "zip"}:
                    continue
                try:
                    data = CASE.read(n.path)[:64_000]
                except Exception:
                    continue
                scanned += 1
                try:
                    text = data.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if term_l not in text.lower():
                    continue
                idx = text.lower().find(term_l)
                start = max(0, idx - 40)
                snippet = text[start : start + 120].replace("\n", " ")
                hits.append({
                    "path": n.path,
                    "name": n.name,
                    "size": n.size,
                    "kind": "content",
                    "snippet": snippet,
                })
        return self._send(200, {
            "hits": hits[:300],
            "count": len(hits),
            "under": under,
            "q": term,
        })

    def _api_search_collect(self, term_l: str, under: Optional[str]):
        if CASE is None:
            return []
        if _is_disk_case(CASE):
            return []
        out = []
        for n in getattr(CASE, "files", []) or []:
            if under and not (n.path == under or n.path.startswith(under.rstrip("/") + "/")):
                continue
            if term_l in n.name.lower() or term_l in n.path.lower():
                out.append({"path": n.path, "name": n.name, "size": n.size, "is_dir": False})
        return out

    def _api_xm_partitions(self, q):
        try:
            device = self._xm_device(q)
            return self._send(200, {"device": device, "partitions": xm.mmls_partitions(device)})
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _api_xm_fls(self, q):
        try:
            device = self._xm_device(q)
            offset = int((q.get("offset") or ["0"])[0])
            inode = (q.get("inode") or [None])[0]
            recursive = (q.get("r") or ["0"])[0] in ("1", "true", "yes")
            limit = int((q.get("limit") or ["2000"])[0])
            entries = xm.fls_list(
                device,
                offset_sectors=offset,
                inode=inode,
                recursive=recursive,
                limit=limit,
            )
            return self._send(200, {"device": device, "offset": offset, "entries": entries})
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _api_xm_mount(self, body):
        image = body.get("image")
        if not image:
            return self._send(400, {
                "error": "No image path was provided.",
                "title": "Missing path",
                "suggestion": "Enter a full path like /home/you/evidence.E01",
            })
        try:
            rec = xm.mount_image(
                image,
                input_type=body.get("input_type") or body.get("in"),
                output_type=body.get("output_type") or body.get("out") or "raw",
                morph=body.get("morph") or "combine",
                cache=body.get("cache"),
                owcache=bool(body.get("owcache")),
                offset=int(body.get("offset") or 0),
                sizelimit=body.get("sizelimit"),
                mount_dir=body.get("mount_dir"),
            )
            return self._send(200, asdict(rec))
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e, "mount").as_dict())

    def _api_xm_umount(self, body):
        # prevent umounting the primary disk case mount via UI accidentally without close
        try:
            if body.get("dir"):
                xm.umount(body["dir"])
            else:
                mid = body.get("id")
                if _is_disk_case(CASE) and mid == CASE.mount.id:
                    return self._send(400, {
                        "error": "This mount belongs to the open case.",
                        "title": "Cannot unmount yet",
                        "suggestion": "Close the case or quit the app to unmount safely.",
                    })
                rec = xm.find_mount(mid)
                xm.umount(rec.mount_dir)
            return self._send(200, {"ok": True})
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())

    def _api_xm_icat(self, body):
        try:
            device = self._xm_device(body)
            inode = body.get("inode")
            if not inode:
                return self._send(400, {
                    "error": "No inode was selected.",
                    "title": "Missing file",
                    "suggestion": "Click a file row in the Disk tab listing.",
                })
            dest = body.get("dest")
            if not dest:
                from tforensic.workspace import default_sessions_root
                if CASE:
                    dest = str(Path(CASE.meta.export_dir) / f"inode_{inode}.bin")
                else:
                    dest = str(default_sessions_root() / f"icat_{inode}.bin")
            out = xm.icat_extract(
                device,
                str(inode),
                dest,
                offset_sectors=int(body.get("offset") or 0),
            )
            return self._send(200, {"exported": out})
        except Exception as e:
            from tforensic.errors import explain_exception
            return self._send(400, explain_exception(e).as_dict())


def serve(
    image: Optional[str] = None,
    session: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 0,
    web_dir: Optional[str] = None,
    input_type: Optional[str] = None,
    output_type: str = "raw",
    morph: str = "combine",
    cache: Optional[str] = None,
) -> int:
    global CASE, WEB_DIR
    from tforensic.deps import ensure_requirements

    ok, msg = ensure_requirements()
    if not ok:
        print(msg, file=sys.stderr)
        return 3

    WEB_DIR = os.path.abspath(web_dir or default_web_dir())
    if not os.path.isdir(WEB_DIR):
        print(f"error: web dir not found: {WEB_DIR}", file=sys.stderr)
        return 1

    if image:
        from tforensic.estimate import estimate_open, print_eta_lines, print_progress

        ext = Path(image).suffix.lower()
        print(f"Opening {image} …", flush=True)
        print_progress(0.05, "starting")
        try:
            est = estimate_open(image, input_type=input_type)
            print_eta_lines(est)
            print(
                f"  estimate: {est['human']} "
                f"(typical {est['human_range']}, {est['size_human']})",
                flush=True,
            )
            print_progress(0.10, "estimate ready")
        except Exception:
            pass
        if os.path.isdir(image):
            print("  step: indexing folder (read-only) …", flush=True)
            print_progress(0.35, "index folder")
        elif ext == ".ova":
            print("  step: extract OVA (this can take a while for large appliances) …", flush=True)
            print_progress(0.20, "extract OVA")
            print("  step: convert disk if needed (qemu-img) …", flush=True)
            print_progress(0.45, "convert disk")
        elif ext in (".pcap", ".pcapng", ".cap", ".dmp", ".pkt", ".snoop", ".erf", ".ntar", ".pklg"):
            print("  step: opening packet capture (tshark) …", flush=True)
            print_progress(0.35, "open PCAP")
        elif ext in (".e01", ".ex01", ".ewf", ".s01", ".dd", ".raw", ".vdi", ".qcow2", ".vmdk"):
            print("  step: mounting with xmount …", flush=True)
            print_progress(0.35, "mounting with xmount")
        else:
            print("  step: parsing evidence …", flush=True)
            print_progress(0.40, "parsing evidence")
        try:
            CASE = open_evidence(
                image,
                input_type=input_type,
                output_type=output_type,
                morph=morph,
                cache=cache,
            )
        except Exception as e:
            from tforensic.errors import format_cli_error
            print(format_cli_error(e, "open"), file=sys.stderr, flush=True)
            return 1
        print_progress(0.90, "evidence open")
        print("  step: ready.", flush=True)
        print_progress(0.98, "starting UI")
    elif session:
        print(f"Loading session {session} …", flush=True)
        CASE = load_case(session)
    else:
        CASE = None
        print("Case / triage mode (no image) — use Case tab or open an image.", flush=True)

    if CASE is not None:
        info = CASE.info()
        kind = info.get("kind", "ad1")
        sid = info.get("session_id", "none")
        try:
            from tforensic.shell_access import context_from_case_object
            ctx = context_from_case_object(CASE)
            print(ctx["banner"], flush=True)
            print(f"  shell env: source {ctx['rc_file']}", flush=True)
        except Exception as e:
            print(f"  shell workspace note: {e}", flush=True)
        if kind in ("disk", "ova"):
            xm_info = info.get("xmount") or {}
            print(
                f"  {kind} session {sid}: "
                f"{xm_info.get('input_type')}→{xm_info.get('output_type')} "
                f"device={xm_info.get('virtual_device')}",
                flush=True,
            )
        else:
            print(
                f"  session {sid}: {info.get('dirs',0)} dirs, {info.get('files',0)} files",
                flush=True,
            )
    else:
        sid = "case"
        info = {"session_id": sid}

    httpd = ThreadingHTTPServer((host, port), Handler)
    bound_host, bound_port = httpd.server_address[:2]
    print(
        f"TFOR_READY http://{bound_host}:{bound_port}/ session={sid}",
        flush=True,
    )
    print(f"  Team Forensic Framework ready → http://{bound_host}:{bound_port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down…")
    finally:
        try:
            CASE.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(serve(sys.argv[1] if len(sys.argv) > 1 else None))
