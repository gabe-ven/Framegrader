"""Engine construction — one per database URL, created lazily."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from app.core.config import get_settings
from app.db.schema import metadata

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engines: dict[str, Engine] = {}


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        # WAL lets the SSE readers proceed while a worker writes progress;
        # the default rollback journal would make every reader wait.
        cur.execute("PRAGMA journal_mode=WAL")
        # Writers queue for up to 5s instead of failing with "database is
        # locked" when two threads commit at the same instant.
        cur.execute("PRAGMA busy_timeout=5000")
        # ON DELETE CASCADE (jobs, blobs) is a no-op unless enabled per
        # connection.
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().sqlalchemy_url
    with _lock:
        engine = _engines.get(url)
        if engine is not None:
            return engine

        if url.startswith("sqlite"):
            db_path = url.split("///", 1)[-1]
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(url, connect_args={"check_same_thread": False})
            _configure_sqlite(engine)
        else:
            # pre_ping: managed Postgres drops idle connections; without it the
            # first query after a quiet hour fails.
            engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)

        metadata.create_all(engine)
        logger.info("Database ready", extra={"dialect": engine.dialect.name})
        _engines[url] = engine
        return engine


def reset_engines() -> None:
    """Dispose every engine. Tests use this to switch databases."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
