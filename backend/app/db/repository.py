"""Every read and write the app makes against the database.

Plain functions over an Engine; callers get dicts back, never Row objects, so
nothing outside this module depends on SQLAlchemy.

The job-queue half (enqueue/claim/heartbeat/finish/requeue) is what makes a
table behave like a queue:

- **claim** atomically flips the oldest ``queued`` job to ``running`` and
  returns it. On Postgres the inner SELECT takes ``FOR UPDATE SKIP LOCKED``, so
  concurrent workers each get a different job and never block on one another.
  SQLite has no row locks (SQLAlchemy omits the clause for that dialect) but
  serialises writers, and the outer ``status = 'queued'`` predicate means a
  second claimant of the same row updates zero rows rather than double-running
  it.
- **heartbeat** is written with every progress update. A job whose heartbeat
  goes stale belonged to a worker that died mid-job (deploy, OOM-kill); it is
  requeued if it has attempts left, failed otherwise. That is the whole
  at-least-once story, and it is why every job handler is idempotent.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from sqlalchemy import Engine, and_, delete, func, insert, select, update

from app.db.schema import analyses, blobs, jobs

TERMINAL = ("succeeded", "failed")


def new_id() -> str:
    return secrets.token_urlsafe(16)


def owner_hash(client_id: str | None) -> str | None:
    if not client_id:
        return None
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def create_analysis(
    engine: Engine,
    *,
    owner: str | None,
    filename: str,
    original: bytes,
    content_type: str,
    stages: list[dict[str, Any]],
    request_id: str | None,
    max_attempts: int,
) -> tuple[str, str]:
    """Insert an analysis, its original upload, and its analyze job — atomically."""
    now = time.time()
    analysis_id, job_id = new_id(), new_id()
    with engine.begin() as conn:
        conn.execute(
            insert(analyses).values(
                id=analysis_id,
                owner_hash=owner,
                filename=filename[:255],
                status="queued",
                is_public=False,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        conn.execute(
            insert(blobs).values(
                analysis_id=analysis_id,
                kind="original",
                content_type=content_type,
                data=original,
                created_at=now,
            )
        )
        conn.execute(
            insert(jobs).values(
                id=job_id,
                analysis_id=analysis_id,
                kind="analyze",
                status="queued",
                progress=0.0,
                stages=stages,
                attempts=0,
                max_attempts=max_attempts,
                request_id=request_id,
                created_at=now,
            )
        )
    return analysis_id, job_id


def get_analysis(engine: Engine, analysis_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return _row(conn.execute(select(analyses).where(analyses.c.id == analysis_id)).first())


def get_version(engine: Engine, analysis_id: str) -> int | None:
    with engine.connect() as conn:
        return conn.execute(
            select(analyses.c.version).where(analyses.c.id == analysis_id)
        ).scalar_one_or_none()


def update_analysis(engine: Engine, analysis_id: str, **values: Any) -> None:
    values["updated_at"] = time.time()
    with engine.begin() as conn:
        conn.execute(
            update(analyses)
            .where(analyses.c.id == analysis_id)
            .values(**values, version=analyses.c.version + 1)
        )


def list_analyses(
    engine: Engine, owner: str, *, limit: int, before: float | None = None
) -> list[dict[str, Any]]:
    cond = analyses.c.owner_hash == owner
    if before is not None:
        cond = and_(cond, analyses.c.created_at < before)
    # Deliberately not selecting the big JSON columns wholesale — history
    # pages render a handful of fields per row.
    cols = [
        analyses.c.id,
        analyses.c.filename,
        analyses.c.status,
        analyses.c.is_public,
        analyses.c.created_at,
        analyses.c.measurements,
        analyses.c.ai,
    ]
    with engine.connect() as conn:
        rows = conn.execute(
            select(*cols).where(cond).order_by(analyses.c.created_at.desc()).limit(limit)
        ).all()
    return [dict(r._mapping) for r in rows]


def delete_analysis(engine: Engine, analysis_id: str) -> None:
    # Explicit child deletes: cascades need PRAGMA foreign_keys on SQLite, and
    # being explicit keeps this correct even on a connection without it.
    with engine.begin() as conn:
        conn.execute(delete(blobs).where(blobs.c.analysis_id == analysis_id))
        conn.execute(delete(jobs).where(jobs.c.analysis_id == analysis_id))
        conn.execute(delete(analyses).where(analyses.c.id == analysis_id))


def purge_older_than(engine: Engine, cutoff: float) -> int:
    with engine.connect() as conn:
        ids = conn.execute(
            select(analyses.c.id).where(analyses.c.created_at < cutoff)
        ).scalars().all()
    for analysis_id in ids:
        delete_analysis(engine, analysis_id)
    return len(ids)


# ---------------------------------------------------------------------------
# Blobs
# ---------------------------------------------------------------------------


def put_blob(
    engine: Engine,
    analysis_id: str,
    kind: str,
    data: bytes,
    content_type: str,
    size: tuple[int, int] | None = None,
) -> None:
    width, height = size or (None, None)
    with engine.begin() as conn:
        conn.execute(
            delete(blobs).where(and_(blobs.c.analysis_id == analysis_id, blobs.c.kind == kind))
        )
        conn.execute(
            insert(blobs).values(
                analysis_id=analysis_id,
                kind=kind,
                content_type=content_type,
                data=data,
                width=width,
                height=height,
                created_at=time.time(),
            )
        )


def get_blob(engine: Engine, analysis_id: str, kind: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return _row(
            conn.execute(
                select(blobs).where(and_(blobs.c.analysis_id == analysis_id, blobs.c.kind == kind))
            ).first()
        )


def delete_blob(engine: Engine, analysis_id: str, kind: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            delete(blobs).where(and_(blobs.c.analysis_id == analysis_id, blobs.c.kind == kind))
        )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def enqueue_job(
    engine: Engine,
    analysis_id: str,
    kind: str,
    *,
    stages: list[dict[str, Any]],
    request_id: str | None,
    max_attempts: int,
) -> tuple[dict[str, Any], bool]:
    """Enqueue ``kind`` for an analysis unless one is already pending/running.

    Returns ``(job, created)``. Deduplication is what makes a double-clicked
    "AI suggestion" button (or two viewers of a shared link) cost one Claude
    call instead of two.
    """
    with engine.begin() as conn:
        existing = conn.execute(
            select(jobs).where(
                and_(
                    jobs.c.analysis_id == analysis_id,
                    jobs.c.kind == kind,
                    jobs.c.status.in_(("queued", "running")),
                )
            )
        ).first()
        if existing is not None:
            return dict(existing._mapping), False
        job = {
            "id": new_id(),
            "analysis_id": analysis_id,
            "kind": kind,
            "status": "queued",
            "progress": 0.0,
            "stages": stages,
            "attempts": 0,
            "max_attempts": max_attempts,
            "request_id": request_id,
            "created_at": time.time(),
        }
        conn.execute(insert(jobs).values(**job))
        conn.execute(
            update(analyses)
            .where(analyses.c.id == analysis_id)
            .values(version=analyses.c.version + 1, updated_at=time.time())
        )
    return {**job, "stage": None, "error": None}, True


def claim_job(engine: Engine, worker_id: str) -> dict[str, Any] | None:
    now = time.time()
    oldest_queued = (
        select(jobs.c.id)
        .where(jobs.c.status == "queued")
        .order_by(jobs.c.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(jobs)
        .where(and_(jobs.c.id == oldest_queued, jobs.c.status == "queued"))
        .values(
            status="running",
            worker_id=worker_id,
            started_at=now,
            heartbeat_at=now,
            attempts=jobs.c.attempts + 1,
            error=None,
        )
        .returning(*jobs.c)
    )
    with engine.begin() as conn:
        return _row(conn.execute(stmt).first())


def update_job_progress(
    engine: Engine,
    job_id: str,
    analysis_id: str,
    *,
    stage: str | None,
    progress: float,
    stages: list[dict[str, Any]],
) -> None:
    now = time.time()
    with engine.begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(stage=stage, progress=progress, stages=stages, heartbeat_at=now)
        )
        conn.execute(
            update(analyses)
            .where(analyses.c.id == analysis_id)
            .values(version=analyses.c.version + 1, updated_at=now)
        )


def finish_job(
    engine: Engine,
    job_id: str,
    analysis_id: str,
    *,
    status: str,
    error: str | None = None,
    stages: list[dict[str, Any]] | None = None,
) -> None:
    now = time.time()
    values: dict[str, Any] = {
        "status": status,
        "error": error,
        "finished_at": now,
        "heartbeat_at": now,
        "stage": None,
    }
    if status == "succeeded":
        values["progress"] = 1.0
    if stages is not None:
        values["stages"] = stages
    with engine.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))
        conn.execute(
            update(analyses)
            .where(analyses.c.id == analysis_id)
            .values(version=analyses.c.version + 1, updated_at=now)
        )


def jobs_for(engine: Engine, analysis_id: str) -> dict[str, dict[str, Any]]:
    """Most recent job of each kind for an analysis."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(jobs).where(jobs.c.analysis_id == analysis_id).order_by(jobs.c.created_at)
        ).all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row.kind] = dict(row._mapping)
    return latest


def requeue_stale(engine: Engine, stale_seconds: float) -> tuple[list[str], list[str]]:
    """Recover jobs whose worker vanished. Returns (requeued_ids, failed_ids)."""
    cutoff = time.time() - stale_seconds
    with engine.begin() as conn:
        stale = conn.execute(
            select(jobs.c.id, jobs.c.analysis_id, jobs.c.attempts, jobs.c.max_attempts).where(
                and_(jobs.c.status == "running", jobs.c.heartbeat_at < cutoff)
            )
        ).all()
        requeued, failed = [], []
        for job in stale:
            if job.attempts < job.max_attempts:
                conn.execute(
                    update(jobs)
                    .where(and_(jobs.c.id == job.id, jobs.c.status == "running"))
                    .values(status="queued", worker_id=None, stage=None)
                )
                requeued.append(job.id)
            else:
                conn.execute(
                    update(jobs)
                    .where(and_(jobs.c.id == job.id, jobs.c.status == "running"))
                    .values(
                        status="failed",
                        error="The worker processing this job stopped responding.",
                        finished_at=time.time(),
                    )
                )
                conn.execute(
                    update(analyses)
                    .where(and_(analyses.c.id == job.analysis_id, analyses.c.status != "succeeded"))
                    .values(
                        status="failed",
                        error="Analysis was interrupted. Please try again.",
                        version=analyses.c.version + 1,
                    )
                )
                failed.append(job.id)
    return requeued, failed


def queue_depth(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(jobs).where(jobs.c.status == "queued")
        ).scalar_one()


def queue_position(engine: Engine, job: dict[str, Any]) -> int:
    """How many queued jobs were enqueued before this one."""
    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(jobs)
            .where(and_(jobs.c.status == "queued", jobs.c.created_at < job["created_at"]))
        ).scalar_one()
