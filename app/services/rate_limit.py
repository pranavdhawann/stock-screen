from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: datetime


_events: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
_lock = RLock()


def _get_supabase_client():
    try:
        from app.services import supabase_client

        return supabase_client
    except Exception as exc:
        logger.warning("Supabase rate-limit backend unavailable: %s", exc)
        return None


def _hash_key(bucket: str, key: str) -> str:
    salt = os.environ.get("RATE_LIMIT_KEY_SALT") or os.environ.get("SECRET_KEY") or "stock-screen-rate-limit"
    material = f"{salt}:{bucket}:{key}".encode()
    return hashlib.sha256(material).hexdigest()


def _parse_reset_at(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _check_supabase_limit(
    bucket: str,
    key: str,
    limit: int,
    window_seconds: int,
    *,
    consume: bool,
) -> RateLimitResult | None:
    supabase_client = _get_supabase_client()
    if not supabase_client:
        return None
    if hasattr(supabase_client, "is_available") and not supabase_client.is_available():
        return None
    try:
        payload = supabase_client.consume_rate_limit(
            bucket=bucket,
            key=_hash_key(bucket, key),
            limit=limit,
            window_seconds=window_seconds,
            consume=consume,
        )
        if not payload:
            return None
        return RateLimitResult(
            allowed=bool(payload["allowed"]),
            remaining=max(0, int(payload["remaining"])),
            reset_at=_parse_reset_at(payload["reset_at"]),
        )
    except Exception as exc:
        logger.warning("Supabase rate-limit check failed for %s: %s", bucket, exc)
        return None


def check_limit(
    bucket: str,
    key: str,
    limit: int,
    window_seconds: int,
    *,
    consume: bool = True,
    distributed: bool = True,
) -> RateLimitResult:
    """Check a rate limit.

    distributed=True routes through the Supabase RPC so the limit holds
    across instances and restarts (use for quotas that must be durable:
    forecasts, contact form, AI buckets). distributed=False stays in-memory
    only - right for cheap anti-burst buckets where a network round-trip
    per request costs more than the protection is worth.
    """
    if distributed:
        supabase_result = _check_supabase_limit(bucket, key, limit, window_seconds, consume=consume)
        if supabase_result is not None:
            return supabase_result

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)
    event_key = (bucket, key)

    with _lock:
        events = _events[event_key]
        while events and events[0] <= cutoff:
            events.popleft()

        allowed = len(events) < limit
        if allowed and consume:
            events.append(now)

        reset_at = events[0] + timedelta(seconds=window_seconds) if events else now + timedelta(seconds=window_seconds)
        remaining = max(0, limit - len(events))
        if not events:
            # Drop empty entries so the map doesn't grow forever with one
            # deque per client IP that ever made a request.
            del _events[event_key]
        return RateLimitResult(allowed=allowed, remaining=remaining, reset_at=reset_at)


def status(bucket: str, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    return check_limit(bucket, key, limit, window_seconds, consume=False)
