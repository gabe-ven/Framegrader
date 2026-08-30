import logging
import os
import threading
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import limiter, rate_limit_exceeded_handler

logger = logging.getLogger(__name__)

# Ceiling on the auto-derived thread count. The work is CPU-bound, so more
# threads than cores buys nothing, and each in-flight analysis holds a 26MP
# image plus its intermediates — concurrency is bounded by memory well before
# it is bounded by CPU.
_MAX_AUTO_CONCURRENCY = 8


def _resolve_analysis_concurrency(configured: int) -> int:
    """Threads available to synchronous route handlers. 0 means auto."""
    if configured > 0:
        return configured
    return max(2, min(_MAX_AUTO_CONCURRENCY, os.cpu_count() or 4))


def _warm_models() -> None:
    """Load heavyweight models in a background thread at startup.

    Running this off the main thread means the server accepts requests
    immediately; the first request that actually needs the model will
    block briefly until it's ready, but typically the model finishes
    loading well before any user submits a photo.

    Warms the predictor too, not just the weights — see
    YOLOWorldSubjectLocator.warm_up.
    """
    try:
        from app.services.composition.subject_localization import (
            YOLOWorldSubjectLocator,
        )

        logger.info("Warming YOLO-World model in background…")
        YOLOWorldSubjectLocator.warm_up()
        # Report what actually happened. Logging "ready" unconditionally was
        # actively misleading on the lite build, which has no ultralytics at
        # all: the log said the detector was ready two lines after saying the
        # import failed.
        if YOLOWorldSubjectLocator._get_model() is not None:
            logger.info("YOLO-World model ready.")
        else:
            logger.info(
                "Detector tier unavailable; subject localization will use the "
                "VLM tier, falling back to the saliency centroid."
            )
    except Exception:
        logger.warning("Model warm-up failed; will retry on first request.", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The route handlers are synchronous, so Starlette runs them in anyio's
    # default threadpool. Its stock size is 40 — far more concurrent 26MP
    # analyses than this process has memory for. Capping it makes excess
    # requests queue inside anyio (cheap) rather than all decode at once.
    #
    # Safe only because /health is async and therefore never competes for a
    # thread; if it were sync, a full pool would stall it and undo the whole
    # point of running the handlers off the event loop.
    concurrency = _resolve_analysis_concurrency(get_settings().analysis_concurrency)
    to_thread.current_default_thread_limiter().total_tokens = concurrency
    logger.info("Analysis threadpool limited to %d concurrent requests.", concurrency)

    threading.Thread(target=_warm_models, daemon=True, name="model-warmup").start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    # Before anything else, so warnings raised during startup are visible.
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    # slowapi reads the limiter off app.state, and the handler turns its
    # RateLimitExceeded into the {"detail": ...} shape the frontend renders.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Deliberately async: this does no blocking work, so it belongs on the
    # event loop. As a sync handler it would need a thread from the capped
    # analysis pool and could queue behind in-flight analyses — exactly the
    # stall this whole design avoids, and the worst possible thing for a
    # health check to do.
    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    from app.api.routes import analysis

    app.include_router(analysis.router, prefix="/api")

    return app


app = create_app()
