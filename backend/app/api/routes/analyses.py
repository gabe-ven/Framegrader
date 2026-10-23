"""Persisted analyses: submit, watch, share, revisit.

``POST /api/analyses`` validates the upload, stores it, and enqueues an
``analyze`` job in one transaction, answering 202 in milliseconds. The client
then follows progress on ``GET /api/analyses/{id}/events`` (Server-Sent
Events) or by polling ``GET /api/analyses/{id}``. Both return the same
snapshot shape, so a client can switch between them freely.

Ownership without accounts: the browser sends a random ``X-Client-Id`` it keeps
in localStorage. Its sha256 is stored as the analysis owner. The owner can read
private analyses, list history, share, and delete; anyone can read an analysis
the owner made public (``/r/:id`` links), minus GPS.

Handlers are async and push every database call to their own small thread
limiter. They must not use Starlette's default threadpool: it is capped at
ANALYSIS_CONCURRENCY (1 on the free instance), so a status poll would otherwise
queue behind a 6-second synchronous /api/analyze.
"""

# NOTE: no `from __future__ import annotations` — see analysis.py; slowapi's
# decorator breaks FastAPI's annotation resolution under postponed evaluation.

import asyncio
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.core import signing
from app.core.config import Settings, get_settings
from app.core.observability import analysis_id_var, request_id_var
from app.core.rate_limit import limiter
from app.db import repository as repo
from app.db.engine import get_engine
from app.jobs import worker as job_worker
from app.jobs.progress import initial_stages
from app.schemas.jobs import (
    AnalysisSnapshot,
    CreatedAnalysis,
    HistoryItem,
    HistoryPage,
    JobView,
    VisibilityUpdate,
)
from app.services import image_io

router = APIRouter(tags=["analyses"])

_AI_RATE_LIMIT = get_settings().ai_rate_limit
_db_limiter = anyio.CapacityLimiter(16)
_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")

# SSE tuning. 0.5s polling of one indexed integer is negligible load and makes
# stage transitions feel immediate; the keep-alive comment stops proxies (and
# Render's 100s idle timeout) from closing a quiet stream mid-critique.
_SSE_POLL_S = 0.5
_SSE_KEEPALIVE_S = 15.0
_SSE_MAX_S = 600.0


async def _db(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=_db_limiter)


def _client_id(x_client_id: str | None = Header(default=None)) -> str | None:
    if x_client_id is None:
        return None
    if not _CLIENT_ID.match(x_client_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed X-Client-Id header.")
    return x_client_id


def _image_url(analysis_id: str, kind: str, public: bool) -> str:
    base = f"/api/analyses/{analysis_id}/{kind}"
    if public:
        return base  # cacheable by anyone; no signature needed
    expires, sig = signing.sign(analysis_id, kind)
    return f"{base}?exp={expires}&sig={sig}"


def _job_view(job: dict[str, Any], position: int | None = None) -> JobView:
    return JobView(
        id=job["id"],
        kind=job["kind"],
        status=job["status"],
        stage=job.get("stage"),
        progress=job.get("progress") or 0.0,
        stages=job.get("stages") or [],
        error=job.get("error"),
        queue_position=position if job["status"] == "queued" else None,
    )


def _strip_private(measurements: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a non-owner may see: everything except where the photo was taken."""
    if not measurements:
        return measurements
    exif = dict(measurements.get("exif") or {})
    exif["gps"] = None
    return {**measurements, "exif": exif}


def _build_snapshot(engine: Any, analysis_id: str, owner: str | None) -> AnalysisSnapshot | None:
    """Load an analysis as the caller is allowed to see it, or None if not."""
    row = repo.get_analysis(engine, analysis_id)
    if row is None:
        return None
    is_owner = owner is not None and row["owner_hash"] == owner
    if not (is_owner or row["is_public"]):
        return None  # indistinguishable from "does not exist", on purpose

    jobs = repo.jobs_for(engine, analysis_id)
    views = {}
    for kind, job in jobs.items():
        position = repo.queue_position(engine, job) if job["status"] == "queued" else None
        views[kind] = _job_view(job, position)

    has_image = row["measurements"] is not None
    public_urls = bool(row["is_public"])
    return AnalysisSnapshot(
        id=row["id"],
        filename=row["filename"],
        status=row["status"],
        created_at=row["created_at"],
        is_public=bool(row["is_public"]),
        is_owner=is_owner,
        version=row["version"],
        image_url=_image_url(analysis_id, "image", public_urls) if has_image else None,
        thumb_url=_image_url(analysis_id, "thumb", public_urls) if has_image else None,
        measurements=row["measurements"] if is_owner else _strip_private(row["measurements"]),
        ai=row["ai"],
        color_grade=row["color_grade"],
        jobs=views,
        error=row["error"],
    )


async def _snapshot_or_404(analysis_id: str, owner: str | None) -> AnalysisSnapshot:
    snap = await _db(_build_snapshot, get_engine(), analysis_id, owner)
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")
    return snap


def _is_settled(snap: AnalysisSnapshot) -> bool:
    return snap.status in repo.TERMINAL and all(
        j.status in repo.TERMINAL for j in snap.jobs.values()
    )


# ---------------------------------------------------------------------------


@router.post(
    "/analyses",
    response_model=CreatedAnalysis,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(_AI_RATE_LIMIT)
async def create_analysis(
    # Both required by slowapi (client address; X-RateLimit-* headers).
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    client_id: str | None = Depends(_client_id),
    settings: Settings = Depends(get_settings),
) -> CreatedAnalysis:
    """Queue a full analysis (measurements, scoring, AI critique) of one photo.

    Rate-limited like the AI endpoints, because every analysis ends in a paid
    critique call.
    """
    # Reject on the declared size before buffering 25MB+ into memory.
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Image exceeds the {settings.max_upload_mb}MB size limit.",
        )
    data = await file.read()
    try:
        image_io.validate_upload(data, file.content_type, max_bytes=settings.max_upload_bytes)
        await anyio.to_thread.run_sync(image_io.probe_image, data, limiter=_db_limiter)
    except image_io.ImageValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    minted = None
    if client_id is None:
        minted = client_id = str(uuid.uuid4())

    analysis_id, job_id = await _db(
        repo.create_analysis,
        get_engine(),
        owner=repo.owner_hash(client_id),
        filename=file.filename or "upload",
        original=data,
        content_type=file.content_type or "application/octet-stream",
        stages=initial_stages("analyze"),
        request_id=request_id_var.get(),
        max_attempts=settings.job_max_attempts,
    )
    analysis_id_var.set(analysis_id)
    job_worker.notify()
    response.headers["Location"] = f"/api/analyses/{analysis_id}"
    return CreatedAnalysis(
        id=analysis_id,
        job=JobView(
            id=job_id, kind="analyze", status="queued", progress=0.0,
            stages=initial_stages("analyze"),
        ),
        client_id=minted,
    )


@router.get("/analyses", response_model=HistoryPage)
async def list_history(
    limit: int = Query(default=24, ge=1, le=100),
    before: float | None = Query(default=None),
    client_id: str | None = Depends(_client_id),
) -> HistoryPage:
    """The caller's own analyses, newest first. Empty without an X-Client-Id."""
    if client_id is None:
        return HistoryPage(items=[])
    rows = await _db(
        repo.list_analyses, get_engine(), repo.owner_hash(client_id), limit=limit + 1, before=before
    )
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        m = row["measurements"] or {}
        score = (((m.get("scores") or {}).get("composition") or {}).get("score"))
        items.append(
            HistoryItem(
                id=row["id"],
                filename=row["filename"],
                status=row["status"],
                created_at=row["created_at"],
                is_public=bool(row["is_public"]),
                thumb_url=(
                    _image_url(row["id"], "thumb", bool(row["is_public"])) if row["measurements"] else None
                ),
                scene_summary=(((row["ai"] or {}).get("scene") or {}).get("summary")),
                composition_score=score,
            )
        )
    return HistoryPage(items=items, next_before=rows[-1]["created_at"] if more else None)


@router.get("/analyses/{analysis_id}", response_model=AnalysisSnapshot)
async def get_analysis(
    analysis_id: str, client_id: str | None = Depends(_client_id)
) -> AnalysisSnapshot:
    analysis_id_var.set(analysis_id)
    return await _snapshot_or_404(analysis_id, repo.owner_hash(client_id))


@router.get("/analyses/{analysis_id}/events")
async def stream_analysis(
    analysis_id: str, request: Request, client_id: str | None = Depends(_client_id)
) -> StreamingResponse:
    """Server-Sent Events: a ``snapshot`` event on every change, then ``end``.

    The first event is sent immediately, so a client that connects late (or
    reconnects) is caught up without a separate GET.
    """
    owner = repo.owner_hash(client_id)
    engine = get_engine()
    first = await _snapshot_or_404(analysis_id, owner)

    async def events() -> AsyncIterator[str]:
        snap = first
        started = last_sent = time.monotonic()
        yield _sse("snapshot", snap)
        while not _is_settled(snap) and time.monotonic() - started < _SSE_MAX_S:
            if await request.is_disconnected():
                return
            await asyncio.sleep(_SSE_POLL_S)
            version = await _db(repo.get_version, engine, analysis_id)
            if version is None:
                yield "event: gone\ndata: {}\n\n"
                return
            if version != snap.version:
                fresh = await _db(_build_snapshot, engine, analysis_id, owner)
                if fresh is None:
                    yield "event: gone\ndata: {}\n\n"
                    return
                snap = fresh
                last_sent = time.monotonic()
                yield _sse("snapshot", snap)
            elif time.monotonic() - last_sent > _SSE_KEEPALIVE_S:
                last_sent = time.monotonic()
                yield ": keep-alive\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, snap: AnalysisSnapshot) -> str:
    return f"event: {event}\ndata: {snap.model_dump_json()}\n\n"


@router.post(
    "/analyses/{analysis_id}/color-grade",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(_AI_RATE_LIMIT)
async def request_color_grade(
    request: Request,
    response: Response,
    analysis_id: str,
    client_id: str | None = Depends(_client_id),
    settings: Settings = Depends(get_settings),
) -> JobView:
    """Queue an AI color-grade suggestion. Idempotent: an existing result or
    an in-flight job is returned instead of starting another paid call."""
    snap = await _snapshot_or_404(analysis_id, repo.owner_hash(client_id))
    if snap.measurements is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The photo is still being measured.")
    existing = snap.jobs.get("color_grade")
    if snap.color_grade is not None and existing is not None:
        return existing
    job, created = await _db(
        repo.enqueue_job,
        get_engine(),
        analysis_id,
        "color_grade",
        stages=initial_stages("color_grade"),
        request_id=request_id_var.get(),
        max_attempts=settings.job_max_attempts,
    )
    if created:
        job_worker.notify()
    return _job_view(job)


@router.put("/analyses/{analysis_id}/visibility", response_model=AnalysisSnapshot)
async def set_visibility(
    analysis_id: str,
    body: VisibilityUpdate,
    client_id: str | None = Depends(_client_id),
) -> AnalysisSnapshot:
    owner = repo.owner_hash(client_id)
    snap = await _snapshot_or_404(analysis_id, owner)
    if not snap.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change sharing.")
    await _db(repo.update_analysis, get_engine(), analysis_id, is_public=body.public)
    return await _snapshot_or_404(analysis_id, owner)


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: str, client_id: str | None = Depends(_client_id)
) -> Response:
    snap = await _snapshot_or_404(analysis_id, repo.owner_hash(client_id))
    if not snap.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can delete this.")
    await _db(repo.delete_analysis, get_engine(), analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/analyses/{analysis_id}/{kind}", response_class=Response)
async def get_image(
    analysis_id: str,
    kind: str,
    exp: int | None = Query(default=None),
    sig: str | None = Query(default=None),
) -> Response:
    if kind not in ("image", "thumb"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    engine = get_engine()
    row = await _db(repo.get_analysis, engine, analysis_id)
    signed = signing.verify(analysis_id, kind, exp, sig)
    if row is None or not (row["is_public"] or signed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    blob = await _db(repo.get_blob, engine, analysis_id, kind)
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    # The bytes for (analysis, kind) never change once written, so the only
    # thing bounding the cache is access: private copies must not outlive
    # their signature in a shared cache.
    cache = "public, max-age=86400" if row["is_public"] and not signed else "private, max-age=3600"
    return Response(content=blob["data"], media_type=blob["content_type"], headers={"Cache-Control": cache})


