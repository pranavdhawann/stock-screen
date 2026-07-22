from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
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


@dataclass
class _Bucket:
    """One (bucket, key) window's event timestamps plus its own TTL.

    The window is stored per-entry (not assumed global) so the round-robin
    sweep below can decide independently, for any key it happens to visit,
    whether that key's events have all aged out.
    """

    events: deque[datetime] = field(default_factory=deque)
    window_seconds: float = 0


# In-memory fallback store, keyed by (bucket, client_key). Entries are
# opportunistically evicted two ways: immediately, when the key being
# checked empties out (existing behavior), and via a small round-robin
# sweep on every call (see _sweep_expired_locked) so keys that stop being
# queried - e.g. a client IP that never comes back - don't linger forever.
_events: dict[tuple[str, str], _Bucket] = {}
_sweep_order: deque[tuple[str, str]] = deque()
_lock = RLock()

# Keep the per-call sweep cost O(small): a handful of keys per request,
# scaled up only if the map has grown past the threshold.
_SWEEP_BATCH_SIZE = 8
_SWEEP_SIZE_THRESHOLD = 500
_SWEEP_BATCH_SIZE_WHEN_LARGE = 32


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
    event_key = (bucket, key)

    with _lock:
        bucket_entry = _events.get(event_key)
        if bucket_entry is None:
            bucket_entry = _Bucket(window_seconds=window_seconds)
            _events[event_key] = bucket_entry
            _sweep_order.append(event_key)
        else:
            # Buckets are called with a fixed window per name in practice;
            # keep the stored window fresh in case a caller ever changes it.
            bucket_entry.window_seconds = window_seconds

        events = bucket_entry.events
        cutoff = now - timedelta(seconds=bucket_entry.window_seconds)
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

        _sweep_expired_locked(now)

        return RateLimitResult(allowed=allowed, remaining=remaining, reset_at=reset_at)


def _sweep_expired_locked(now: datetime) -> None:
    """Evict a small, bounded batch of fully-expired entries.

    Must be called with _lock held. Walks _sweep_order round-robin instead
    of scanning all of _events, so the per-request cost stays O(small)
    regardless of how many distinct keys have ever been seen. A key whose
    events haven't fully expired is pushed back to the end of the queue to
    be revisited later; a key already removed by the direct check above (or
    by an earlier sweep pass) is simply dropped from the queue.
    """
    batch_size = _SWEEP_BATCH_SIZE
    if len(_events) > _SWEEP_SIZE_THRESHOLD:
        batch_size = _SWEEP_BATCH_SIZE_WHEN_LARGE

    for _ in range(min(batch_size, len(_sweep_order))):
        try:
            candidate_key = _sweep_order.popleft()
        except IndexError:
            break

        bucket_entry = _events.get(candidate_key)
        if bucket_entry is None:
            continue

        cutoff = now - timedelta(seconds=bucket_entry.window_seconds)
        events = bucket_entry.events
        while events and events[0] <= cutoff:
            events.popleft()

        if events:
            _sweep_order.append(candidate_key)
        else:
            del _events[candidate_key]


def status(bucket: str, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    return check_limit(bucket, key, limit, window_seconds, consume=False)
