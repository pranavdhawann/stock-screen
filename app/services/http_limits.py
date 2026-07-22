"""Request-scoped rate limiting for HTTP handlers.

Wraps app.services.rate_limit with the two things a Flask view needs: how
to derive the caller's identity from the request, and how to turn a
denied check into a 429 response. This used to live as private helpers in
app/routes/api.py, which meant app/routes/account.py had to import
`_consume_limit` out of another blueprint's private namespace.
"""

import logging

from flask import jsonify, request

from app.config import TRUST_PROXY_HEADERS, TRUSTED_PROXY_HOPS
from app.services.rate_limit import check_limit

logger = logging.getLogger(__name__)


def client_key():
    """Derive the rate-limit identity for the current request.

    Cloud Run appends the *real* client IP as the last entry of
    X-Forwarded-For; every entry to its left is client-supplied and can be
    forged. TRUSTED_PROXY_HOPS is how many trusted proxy hops sit between
    the client and this app (Cloud Run alone = 1), so we index from the
    right, not the left. Any missing/malformed/out-of-range header falls
    back to remote_addr (the immediate peer, i.e. the proxy itself when
    TRUST_PROXY_HEADERS is off).
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            index = len(hops) - TRUSTED_PROXY_HOPS
            if 0 <= index < len(hops):
                return hops[index]
    return request.remote_addr or "unknown"


def rate_limit_payload(result):
    return {
        "error": "Rate limit exceeded. Please try again later.",
        "remaining": result.remaining,
        "reset_at": result.reset_at.isoformat(),
    }


def consume_limit(bucket, limit, window_seconds, *, distributed=True):
    """Consume one unit of a bucket; returns a 429 response tuple or None."""
    result = check_limit(bucket, client_key(), limit, window_seconds, distributed=distributed)
    if not result.allowed:
        return jsonify(rate_limit_payload(result)), 429
    return None
