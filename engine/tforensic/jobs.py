"""Background ingest job runner (thread-based for local desktop/API)."""
from __future__ import annotations

import threading
import traceback
from typing import Callable, Optional

from tforensic.casedb import CaseDB

_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}


def start_job(
    db: CaseDB,
    job_id: str,
    fn: Callable[[CaseDB, str, Callable], dict],
) -> None:
    """Run fn(db, job_id, progress_cb) in a daemon thread."""

    def progress_cb(progress: float, message: str, eta: Optional[float] = None):
        db.update_job(
            job_id,
            status="running",
            progress=max(0.0, min(1.0, progress)),
            message=message,
            eta_seconds=eta,
        )

    def runner():
        try:
            db.update_job(job_id, status="running", progress=0.01, message="starting")
            result = fn(db, job_id, progress_cb) or {}
            db.update_job(
                job_id,
                status="done",
                progress=1.0,
                message="complete",
                result=result,
                eta_seconds=0,
            )
        except Exception as e:
            db.update_job(
                job_id,
                status="error",
                message=str(e),
                error=traceback.format_exc(),
            )
        finally:
            with _lock:
                _running.pop(job_id, None)

    t = threading.Thread(target=runner, name=f"tfor-job-{job_id}", daemon=True)
    with _lock:
        _running[job_id] = t
    t.start()


def is_running(job_id: str) -> bool:
    with _lock:
        t = _running.get(job_id)
        return bool(t and t.is_alive())
