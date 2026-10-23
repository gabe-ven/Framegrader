"""Application logging setup.

Without this, nothing under ``app.*`` is ever seen. uvicorn configures handlers
for its own loggers (``uvicorn``, ``uvicorn.access``) and leaves the root logger
bare, so every ``logger.warning`` this codebase carefully emits — the VLM
falling back, GrabCut refusing to refine, an AI response that would not parse,
YOLO-World failing to load — was written to a logger with no handler and
discarded. In production that is the difference between a diagnosable incident
and a shrug.

Deliberately configures the *root* logger rather than an ``app`` logger, so
warnings from dependencies (ultralytics, PIL, httpx) surface too.

Two output formats, chosen by LOG_FORMAT:

- ``json`` (production): one JSON object per line. Log collectors (Render,
  Cloud Run, Datadog, Loki) index the fields, so "every request slower than
  10s" or "every line for job X" is a query rather than a grep.
- ``text`` (local development): the classic human-readable line, with the same
  structured fields appended as ``key=value`` pairs.

Either way every record carries ``request_id`` / ``job_id`` / ``analysis_id``
when one is bound (see app/core/observability.py), plus whatever a call site
passed in ``extra=``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.observability import analysis_id_var, job_id_var, request_id_var

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"

# Chatty third parties. They stay at WARNING regardless of our level, so
# turning the app up to DEBUG does not drown the output in library noise.
_NOISY_LOGGERS = ("PIL", "matplotlib", "httpx", "httpcore", "urllib3")

# uvicorn's own access log duplicates RequestContextMiddleware's summary line
# minus the request ID and timings, so it is silenced in favour of ours.
_REPLACED_LOGGERS = ("uvicorn.access",)

_CONTEXT_FIELDS = ("request_id", "job_id", "analysis_id")

# Attributes every LogRecord has. Anything else on a record arrived via
# `extra=` and is a structured field worth emitting.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName", *_CONTEXT_FIELDS}


class ContextFilter(logging.Filter):
    """Stamp the bound request/job/analysis IDs onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.job_id = job_id_var.get()
        record.analysis_id = analysis_id_var.get()
        return True


def _extra_fields(record: logging.LogRecord) -> dict:
    return {
        k: v for k, v in vars(record).items()
        if k not in _STANDARD_ATTRS and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # default=str: an `extra` value that isn't JSON-native (a Path, a numpy
        # float) must degrade to its repr, never raise inside the logger.
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(_FORMAT, datefmt=_DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = {f: getattr(record, f, None) for f in _CONTEXT_FIELDS}
        fields.update(_extra_fields(record))
        # The request summary's message already says method/path/status/ms.
        pairs = " ".join(
            f"{k}={v}" for k, v in fields.items()
            if v is not None and k not in ("method", "path", "status", "event")
        )
        if not pairs:
            return line
        # Keep a traceback (appended by the base class) at the end.
        head, sep, tail = line.partition("\n")
        return f"{head} [{pairs}]{sep}{tail}"


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Attach a stdout handler to the root logger. Idempotent.

    stdout (not stderr) because container runtimes and platform log collectors
    treat it as the normal application stream; stderr tends to be flagged as
    error output regardless of the record's level.
    """
    resolved = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()

    # create_app() can run more than once (tests, ASGI reloaders). Replace our
    # own handler rather than stacking duplicates that double every line.
    for existing in list(root.handlers):
        if getattr(existing, "_framegrader", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt.lower() == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    handler._framegrader = True  # type: ignore[attr-defined]

    root.addHandler(handler)
    root.setLevel(resolved)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(resolved, logging.WARNING))
    for name in _REPLACED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
