"""Request-scoped rate limiting for HTTP handlers.

Wraps app.services.rate_limit with the two things a Flask view needs: how
to derive the caller's identity from the request, and how to turn a
denied check into a 429 response. This used to live as private helpers in
app/routes/api.py, which meant app/routes/account.py had to import
`_consume_limit` out of another blueprint's private namespace.
"""

import logging

from flask import jsonify, request, session

from app.config import TRUST_PROXY_HEADERS, TRUSTED_PROXY_HOPS
from app.services.rate_limit import check_limit

logger = logging.getLogger(__name__)

# Plans that are exempt from request quotas. Membership is decided server-side
# and stored in public.app_users.plan; the session copy is signed with the
# app SECRET_KEY, so a client cannot promote itself by editing its cookie.
UNLIMITED_PLANS = frozenset({"pro"})


def has_unlimited_access():
    """True when the signed-in account's plan lifts request quotas.

    Anonymous callers and unknown plans always fall through to the limits -
    an entitlement check that fails open would be a hole, not a convenience.
    """
    try:
        return session.get("plan") in UNLIMITED_PLANS
    except RuntimeError:
        # No request/session context (background work, tests calling directly).
        return False


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
    if has_unlimited_access():
        return None
    result = check_limit(bucket, client_key(), limit, window_seconds, distributed=distributed)
    if not result.allowed:
        return jsonify(rate_limit_payload(result)), 429
    return None


def consume_tiered_limit(
    bucket,
    *,
    burst_limit,
    burst_window_seconds,
    quota_limit,
    quota_window_seconds,
):
    """Cheap per-instance burst guard in front of a durable shared quota.

    An in-memory-only limit is per *container*: once Cloud Run scales to N
    instances the effective ceiling becomes N x the configured number, because
    each instance counts independently. That is fine for anti-hammering but
    wrong for anything meant to be a real quota.

    Making every bucket distributed instead would put a Supabase round-trip in
    front of responses that otherwise serve straight out of the in-memory
    cache. So both run, cheapest first: the local burst window rejects
    hammering with no network at all, and only requests that clear it spend a
    round-trip on the durable quota.

    A request that passes the burst check but fails the quota still consumes a
    burst token. That is deliberate - it makes repeatedly probing a
    quota-exhausted endpoint get *more* expensive, not less.

    Pro accounts skip both tiers, including the burst guard: the guard exists
    to stop anonymous hammering, and an authenticated paid account is already
    attributable.
    """
    if has_unlimited_access():
        return None

    key = client_key()

    burst = check_limit(
        f"{bucket}_burst", key, burst_limit, burst_window_seconds, distributed=False
    )
    if not burst.allowed:
        return jsonify(rate_limit_payload(burst)), 429

    quota = check_limit(
        bucket, key, quota_limit, quota_window_seconds, distributed=True
    )
    if not quota.allowed:
        return jsonify(rate_limit_payload(quota)), 429

    return None
