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
