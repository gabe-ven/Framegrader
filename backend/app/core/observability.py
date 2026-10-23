"""Request IDs, per-stage timings, and the one-line-per-request access log.

Three pieces, all built on ``contextvars`` so they follow the work wherever it
runs — the event loop, Starlette's threadpool (``run_in_threadpool`` copies the
context), or a background job worker that re-binds the context explicitly:

- ``request_id`` / ``job_id`` / ``analysis_id`` context variables. The logging
  filter in app/core/logging.py stamps them onto every record, so a warning
  raised three modules deep in the VLM locator is attributable to the request
  (or job) that caused it without threading an ID through every signature.
- ``stage(name)``: a context manager that times one pipeline stage, logs it, and
  accumulates it into the current timing bucket. The request middleware reports
  the bucket as a ``Server-Timing`` header and in its summary line; the job
  worker persists it on the job row.
- ``RequestContextMiddleware``: assigns or accepts an ``X-Request-ID``, echoes it
  on the response, and writes one structured summary line per request.

The middleware is pure ASGI rather than ``BaseHTTPMiddleware`` on purpose: the
latter buffers streaming responses and runs the endpoint in a separate task,
which both breaks the SSE progress stream and drops context changes made inside
the endpoint.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("app.request")
_stage_logger = logging.getLogger("app.stage")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
analysis_id_var: ContextVar[str | None] = ContextVar("analysis_id", default=None)
# Ordered (name, duration_ms) pairs for the current request or job. A list, not
# a dict: the same stage can legitimately run twice (e.g. a retried decode),
# and the order is part of what makes a slow request readable.
_timings_var: ContextVar[list[tuple[str, float]] | None] = ContextVar(
    "stage_timings", default=None
)

REQUEST_ID_HEADER = "x-request-id"
# Accept a caller-supplied ID only if it is short and boring. It is echoed into
# a response header and every log line, so anything else (newlines, quotes,
# kilobytes of text) is a header-injection or log-forging vector.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def new_request_id() -> str:
    return uuid.uuid4().hex


def current_timings() -> list[tuple[str, float]]:
    """Stage timings recorded so far in this context (empty if none)."""
    return list(_timings_var.get() or [])


@contextlib.contextmanager
def timing_scope() -> Iterator[list[tuple[str, float]]]:
    """Start a fresh timing bucket; yields the list stages append into."""
    bucket: list[tuple[str, float]] = []
    token = _timings_var.set(bucket)
    try:
        yield bucket
    finally:
        _timings_var.reset(token)


@contextlib.contextmanager
def stage(name: str, **fields: Any) -> Iterator[None]:
    """Time one pipeline stage.

    Logs ``stage`` at INFO with ``stage`` and ``duration_ms`` as structured
    fields (plus ``failed`` when the block raised), and appends to the active
    timing bucket if there is one. Never swallows the exception.
    """
    start = time.perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        bucket = _timings_var.get()
        if bucket is not None:
            bucket.append((name, duration_ms))
        extra = {"stage": name, "duration_ms": duration_ms, **fields}
        if failed:
            extra["failed"] = True
        _stage_logger.info("stage %s %.1fms", name, duration_ms, extra=extra)


@contextlib.contextmanager
def bind(**values: str | None) -> Iterator[None]:
    """Bind request_id / job_id / analysis_id for the duration of a block.

    Used by the job worker, whose threads do not inherit any request context:
    it re-binds the enqueuing request's ID so a job's log lines join up with the
    request that created it.
    """
    vars_ = {"request_id": request_id_var, "job_id": job_id_var, "analysis_id": analysis_id_var}
    tokens = [(vars_[k], vars_[k].set(v)) for k, v in values.items() if k in vars_]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def _server_timing(timings: list[tuple[str, float]]) -> str:
    # Server-Timing metric names are HTTP tokens; our stage names already are,
    # but sanitise anyway so a future "subject (vlm)" can't corrupt the header.
    parts = []
    for i, (name, ms) in enumerate(timings):
        token = re.sub(r"[^A-Za-z0-9_-]", "_", name) or f"s{i}"
        parts.append(f"{token};dur={ms}")
    return ", ".join(parts)


class RequestContextMiddleware:
    """Pure-ASGI middleware: request ID, Server-Timing, and an access log line."""

    # Health checks fire every few seconds from the platform; logging each one
    # buries the real traffic. They still get a request ID.
    _QUIET_PATHS = frozenset({"/health"})

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = None
        for key, value in scope.get("headers", []):
            if key == b"x-request-id":
                supplied = value.decode("latin-1")
                break
        request_id = supplied if supplied and _SAFE_REQUEST_ID.match(supplied) else new_request_id()

        rid_token = request_id_var.set(request_id)
        bucket: list[tuple[str, float]] = []
        timings_token = _timings_var.set(bucket)
        start = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                # The handler has finished by the time a non-streaming response
                # starts, so every stage it ran is already in the bucket.
                if bucket:
                    headers.append((b"server-timing", _server_timing(bucket).encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_holder.setdefault("status", 500)
            logger.exception("unhandled error", extra={"path": scope.get("path")})
            raise
        finally:
            path = scope.get("path", "")
            if path not in self._QUIET_PATHS:
                duration_ms = round((time.perf_counter() - start) * 1000, 1)
                client = scope.get("client")
                logger.info(
                    "%s %s %s %.1fms",
                    scope.get("method"),
                    path,
                    status_holder.get("status", 0),
                    duration_ms,
                    extra={
                        "event": "request",
                        "method": scope.get("method"),
                        "path": path,
                        "status": status_holder.get("status", 0),
                        "duration_ms": duration_ms,
                        "client": client[0] if client else None,
                        "stages": {name: ms for name, ms in bucket} or None,
                    },
                )
            _timings_var.reset(timings_token)
            request_id_var.reset(rid_token)
