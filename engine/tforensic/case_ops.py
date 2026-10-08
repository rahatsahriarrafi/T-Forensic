"""Evidence verification + case export (zip) for LE hardening."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

from tforensic.casedb import CaseDB
from tforensic.workspace import hash_file


def verify_evidence(db: CaseDB, evidence_id: str) -> dict:
    """Re-hash evidence file and compare to recorded sha256."""
    ev = db.get_evidence(evidence_id)
    path = Path(ev["path"])
    if not path.exists():
        result = {
            "ok": False,
            "evidence_id": evidence_id,
            "error": "file missing",
            "path": str(path),
        }
        db.log_custody("verify_fail", json.dumps(result))
        return result
    if path.is_dir():
        from tforensic.folder_image import folder_manifest

        digest, size, _ = folder_manifest(path)
    else:
        digest, size = hash_file(path), path.stat().st_size
    expected = (ev.get("sha256") or "").lower()
    ok = digest.lower() == expected if expected else True
    result = {
        "ok": ok,
        "evidence_id": evidence_id,
        "path": str(path),
        "recorded_sha256": expected,
        "current_sha256": digest,
        "size": size,
        "verified_at": time.time(),
    }
    db.log_custody(
        "verify_ok" if ok else "verify_mismatch",
        f"{evidence_id} ok={ok} sha256={digest}",
    )
    return result


def verify_all(db: CaseDB) -> list[dict]:
    return [verify_evidence(db, e["id"]) for e in db.list_evidence()]


def export_case_zip(db: CaseDB, dest: Optional[str | Path] = None, *, include_evidence_links: bool = True) -> str:
    """Zip case.db, reports, exports, custody — not full disk images."""
    info = db.info()
    case_dir = Path(info.path)
    out = Path(dest) if dest else case_dir / "exports" / f"case-{info.id}-{int(time.time())}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(case_dir / "case.db", arcname="case.db")
        for sub in ("reports", "exports", "index"):
            d = case_dir / sub
            if not d.is_dir():
                continue
            for f in d.rglob("*"):
                if f.is_file() and f != out:
                    zf.write(f, arcname=str(f.relative_to(case_dir)))
        # evidence path manifest (not the images themselves)
        manifest = {
            "case": info.as_dict(),
            "exported_at": time.time(),
            "evidence": db.list_evidence(),
            "stats": db.stats(),
            "custody": db.custody_entries(limit=1000),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        if include_evidence_links:
            ev_dir = case_dir / "evidence"
            if ev_dir.is_dir():
                for f in ev_dir.iterdir():
                    if f.is_symlink() or f.suffix == ".path" or f.is_file():
                        try:
                            zf.write(f, arcname=f"evidence/{f.name}")
                        except OSError:
                            pass
    db.log_custody("case_export", f"zip={out}")
    return str(out)
