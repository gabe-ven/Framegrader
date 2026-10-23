"""Short-lived signed URLs for stored images.

The owner of a private analysis proves ownership with the ``X-Client-Id``
header, but an ``<img src>`` request can't carry custom headers. So the
snapshot hands out image URLs with an expiry and an HMAC over
``analysis:kind:expiry``; the image route accepts either a valid signature or
a public analysis.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from functools import lru_cache

from app.core.config import get_settings

URL_TTL_SECONDS = 6 * 3600


@lru_cache
def _key() -> bytes:
    configured = get_settings().secret_key
    return configured.encode() if configured else secrets.token_bytes(32)


def _mac(analysis_id: str, kind: str, expires: int) -> str:
    msg = f"{analysis_id}:{kind}:{expires}".encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:32]


def sign(analysis_id: str, kind: str, ttl: int = URL_TTL_SECONDS) -> tuple[int, str]:
    # Round the expiry to the hour so repeated snapshots produce identical
    # URLs and the browser cache actually hits.
    expires = (int(time.time()) // 3600 + 1) * 3600 + ttl
    return expires, _mac(analysis_id, kind, expires)


def verify(analysis_id: str, kind: str, expires: int | None, sig: str | None) -> bool:
    if not expires or not sig or expires < time.time():
        return False
    return hmac.compare_digest(_mac(analysis_id, kind, expires), sig)
