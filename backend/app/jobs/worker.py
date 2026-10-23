"""The job worker: claim, run, record, repeat.

Runs either embedded in the API process (``EMBEDDED_WORKERS`` threads, the
default — one process is all a 512MB instance can afford) or standalone via
``python -m app.worker`` when the API and the workers should scale separately.
Both modes run this same class against the same tables, so moving between them
is a configuration change, not a code change.

Idle workers poll every ``poll_interval`` seconds. In embedded mode the enqueue
path also calls ``notify()``, so a job submitted to this process starts
immediately instead of up to one poll interval later.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Any

from sqlalchemy import Engine

from app.core.config import Settings, get_settings
from app.core.observability import bind, timing_scope
from app.db import repository as repo
from app.db.engine import get_engine
from app.jobs.handlers import HANDLERS, JobFailed
from app.jobs.progress import ProgressTracker

logger = logging.getLogger(__name__)

_wake = threading.Event()

_MAINTENANCE_INTERVAL_S = 30.0
_PURGE_INTERVAL_S = 3600.0


def notify() -> None:
    """Wake idle in-process workers: a job was just enqueued."""
    _wake.set()


class Worker:
    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
        threads: int = 1,
        poll_interval: float = 0.5,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self.threads = threads
        self.poll_interval = poll_interval
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_purge = 0.0

    @property
    def engine(self) -> Engine:
        return self._engine or get_engine()

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        for i in range(self.threads):
            t = threading.Thread(target=self._loop, name=f"job-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        m = threading.Thread(target=self._maintenance_loop, name="job-maintenance", daemon=True)
        m.start()
        self._threads.append(m)
        logger.info("Job workers started", extra={"threads": self.threads, "worker_id": self.worker_id})

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        _wake.set()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))
        self._threads.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ran = self.run_once()
            except Exception:  # noqa: BLE001 - a DB hiccup must not kill the thread
                logger.exception("Job worker loop error")
                ran = False
            if not ran:
                _wake.wait(self.poll_interval)
                _wake.clear()

    def _maintenance_loop(self) -> None:
        while not self._stop.wait(_MAINTENANCE_INTERVAL_S):
            try:
                self.maintain()
            except Exception:  # noqa: BLE001
                logger.exception("Job maintenance error")

    # -- units of work (also called directly by tests) -----------------------

    def maintain(self) -> None:
        requeued, failed = repo.requeue_stale(self.engine, self.settings.job_stale_seconds)
        if requeued or failed:
            logger.warning(
                "Recovered stale jobs", extra={"requeued": requeued, "failed": failed}
            )
            if requeued:
                notify()
        days = self.settings.retention_days
        now = time.time()
        if days > 0 and now - self._last_purge > _PURGE_INTERVAL_S:
            self._last_purge = now
            purged = repo.purge_older_than(self.engine, now - days * 86400)
            if purged:
                logger.info("Purged expired analyses", extra={"count": purged})

    def run_once(self) -> bool:
        """Claim and run one job. Returns False when the queue was empty."""
        job = repo.claim_job(self.engine, self.worker_id)
        if job is None:
            return False
        self._execute(job)
        return True

    def drain(self, max_jobs: int = 100) -> int:
        """Run jobs until the queue is empty. For tests and the CLI's --once."""
        count = 0
        while count < max_jobs and self.run_once():
            count += 1
        return count

    def _execute(self, job: dict[str, Any]) -> None:
        engine = self.engine
        job_id, analysis_id, kind = job["id"], job["analysis_id"], job["kind"]

        def persist(stage: str | None, progress: float, stages: list[dict[str, Any]]) -> None:
            repo.update_job_progress(
                engine, job_id, analysis_id, stage=stage, progress=progress, stages=stages
            )

        tracker = ProgressTracker(kind, persist)
        handler = HANDLERS.get(kind)

        with bind(request_id=job["request_id"], job_id=job_id, analysis_id=analysis_id), \
                timing_scope() as timings:
            queued_ms = round(((job["started_at"] or time.time()) - job["created_at"]) * 1000, 1)
            logger.info(
                "Job started",
                extra={"kind": kind, "attempt": job["attempts"], "queued_ms": queued_ms},
            )
            start = time.perf_counter()
            status, error = "succeeded", None
            try:
                if handler is None:
                    raise JobFailed(f"Unknown job kind: {kind}")
                handler(engine, job, tracker, self.settings)
                stages = tracker.finish()
            except JobFailed as exc:
                status, error, stages = "failed", str(exc), tracker.fail()
            except Exception:  # noqa: BLE001 - record, never crash the worker
                logger.exception("Job raised")
                status = "failed"
                error = "Something went wrong while processing this photo."
                stages = tracker.fail()

            repo.finish_job(engine, job_id, analysis_id, status=status, error=error, stages=stages)
            if status == "failed" and kind == "analyze":
                repo.update_analysis(engine, analysis_id, status="failed", error=error)

            logger.info(
                "Job %s", status,
                extra={
                    "kind": kind,
                    "status": status,
                    "error": error,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "stages": {name: ms for name, ms in timings},
                },
            )
