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
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"

# Chatty third parties. They stay at WARNING regardless of our level, so
# turning the app up to DEBUG does not drown the output in library noise.
_NOISY_LOGGERS = ("PIL", "matplotlib", "httpx", "httpcore", "urllib3")


def configure_logging(level: str = "INFO") -> None:
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
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    handler._framegrader = True  # type: ignore[attr-defined]

    root.addHandler(handler)
    root.setLevel(resolved)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(resolved, logging.WARNING))
