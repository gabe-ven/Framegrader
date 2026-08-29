"""Per-IP rate limiting for the endpoints that spend money.

`/ai-analysis` and `/color-grade` each make a paid Anthropic call and accept a
25MB upload, with no auth in front of them. Without a limit, anyone who finds
the URL can drain the API key — and because the handlers do their work on the
event loop, a burst is a denial of service as well as a cost attack.

The limiter is deliberately kept out of `main.py` so the app factory stays a
wiring layer: this module owns the policy (key function, limit, 429 shape) and
`main.py` just registers it.

Two operational caveats:

- Storage is in-memory and per-process, so N uvicorn workers means N buckets
  and an effective limit of N x the configured value. Point slowapi at Redis
  (`storage_uri`) if the service is ever scaled past one worker.
- `get_remote_address` reads `request.client.host`. Behind a reverse proxy that
  is the *proxy's* address, which would put every user in one shared bucket.
  Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so
  `X-Forwarded-For` is resolved before it reaches here.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# headers_enabled adds Retry-After and the X-RateLimit-* family to throttled
# responses, so a client can back off intelligently instead of hammering.
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a 429 the frontend can actually display.

    slowapi's built-in handler responds with ``{"error": ...}``, but the
    frontend's `postForm` reads ``detail`` (the shape FastAPI's HTTPException
    produces). Using the default would surface a bare "Request failed (429)."
    to the user instead of the reason, so we mirror the app's error contract.
    """
    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": (
                f"Too many requests — this endpoint allows {exc.detail} per IP "
                "address. Please try again later."
            )
        },
    )
    # Re-uses slowapi's own header injection so Retry-After stays accurate.
    return limiter._inject_headers(response, request.state.view_rate_limit)
