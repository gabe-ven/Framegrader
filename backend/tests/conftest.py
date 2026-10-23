"""Shared pytest fixtures.

The rate limiter is process-wide and its in-memory storage persists for the
whole session, so leaving it armed would make the suite order-dependent: the
11th test to POST /api/ai-analysis would start getting 429s that have nothing
to do with what it was asserting. Every test therefore runs with limiting off
unless it explicitly opts back in via the `rate_limited` fixture below.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.core.rate_limit import limiter


@pytest.fixture(autouse=True)
def _disable_rate_limiting() -> Iterator[None]:
    """Turn the limiter off for every test, and clear its buckets afterwards."""
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous
    limiter.reset()


@pytest.fixture
def rate_limited() -> Iterator[None]:
    """Opt back in, for the tests that assert on limiting itself.

    Storage is reset on both sides so these tests neither inherit counts from
    earlier requests nor leak their own into whatever runs next.
    """
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


@pytest.fixture(autouse=True)
def _unpaused_ai(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every test against a live (mocked) AI path, not a paused one.

    AI_ANALYSIS_PAUSED is read from backend/.env, so whether it is on depends
    on the machine the suite happens to run on. Pinning it off here keeps the
    suite hermetic; the tests that cover paused mode set it back on themselves.
    """
    monkeypatch.setenv("AI_ANALYSIS_PAUSED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty database and no embedded workers.

    SQLite by default: a fresh file per test. Set TEST_DATABASE_URL to run the
    suite against Postgres instead (CI does), where the job queue takes its
    FOR UPDATE SKIP LOCKED path; the tables are dropped and recreated around
    each test so nothing leaks between them.

    The engine is created lazily, so tests that never touch persistence pay
    nothing. Workers are off so a test decides exactly when jobs run (see
    `run_jobs` in test_jobs.py) instead of racing a background thread.
    """
    import os

    from app.db.engine import get_engine, reset_engines
    from app.db.schema import metadata

    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("EMBEDDED_WORKERS", "0")
    get_settings.cache_clear()
    reset_engines()
    if not url.startswith("sqlite"):
        metadata.drop_all(get_engine())
        metadata.create_all(get_engine())
    yield
    reset_engines()
