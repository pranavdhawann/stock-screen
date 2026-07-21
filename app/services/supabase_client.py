from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

_client = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    try:
        from supabase import create_client

        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        return _client
    except Exception as exc:
        logger.warning("Supabase client unavailable: %s", exc)
        return None


def is_available() -> bool:
    return _get_client() is not None


def _get_cache(table: str, key_column: str, key: str, payload_column: str, include_metadata: bool = False):
    client = _get_client()
    if not client:
        return None
    try:
        result = (
            client.table(table)
            .select(f"{payload_column},fetched_at,expires_at")
            .eq(key_column, key)
            .maybe_single()
            .execute()
        )
        row = getattr(result, "data", None)
        if not row:
            return None
        expires_raw = row.get("expires_at")
        if expires_raw:
            expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
            if expires_at <= _utc_now():
                return None
        payload = row.get(payload_column)
        if include_metadata:
            return {
                payload_column: payload,
                "fetched_at": row.get("fetched_at"),
                "expires_at": row.get("expires_at"),
            }
        if isinstance(payload, dict):
            payload.setdefault("fetched_at", row.get("fetched_at"))
        return payload
    except Exception as exc:
        logger.warning("Supabase cache read failed for %s/%s: %s", table, key, exc)
        return None


def _set_cache(table: str, key_column: str, key: str, payload_column: str, value: Any, ttl_seconds: int):
    client = _get_client()
    if not client:
        return False
    now = _utc_now()
    try:
        # Expired persistent cache rows are pruned by the public.cleanup_expired_cache() RPC.
        client.table(table).upsert(
            {
                key_column: key,
                payload_column: value,
                "fetched_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=ttl_seconds)),
            },
            on_conflict=key_column,
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Supabase cache write failed for %s/%s: %s", table, key, exc)
        return False


def get_stock_data_cache(key: str):
    return _get_cache("stock_data_cache", "cache_key", key, "data")


def set_stock_data_cache(key: str, value: Any):
    return _set_cache("stock_data_cache", "cache_key", key, "data", value, 300)


def get_aggregated_news_cache(key: str):
    return _get_cache("aggregated_news_cache", "symbol", key, "news_items")


def set_aggregated_news_cache(key: str, value: Any):
    return _set_cache("aggregated_news_cache", "symbol", key, "news_items", value, 600)


def get_sentiment_cache(key: str):
    return _get_cache("sentiment_cache", "symbol", key, "result")


def set_sentiment_cache(key: str, value: Any):
    return _set_cache("sentiment_cache", "symbol", key, "result", value, 900)


def get_sec_filings_cache(key: str):
    return _get_cache("sec_filings_cache", "cache_key", key, "data")


def set_sec_filings_cache(key: str, value: Any):
    return _set_cache("sec_filings_cache", "cache_key", key, "data", value, 1800)


def get_currents_cache():
    return _get_cache("currents_news_cache", "cache_key", "latest", "news_items", include_metadata=True)


def set_currents_cache(news_items):
    return _set_cache("currents_news_cache", "cache_key", "latest", "news_items", news_items, 8640)


def get_finnhub_cache(symbol: str):
    return _get_cache("finnhub_news_cache", "symbol", symbol.upper(), "news_items", include_metadata=True)


def set_finnhub_cache(symbol: str, news_items):
    return _set_cache("finnhub_news_cache", "symbol", symbol.upper(), "news_items", news_items, 3600)


def record_sentiment_snapshot(
    *,
    symbol: str,
    day: str,
    score: float,
    label: str,
    confidence: float,
    news_count: int,
) -> bool:
    """Upsert today's aggregated sentiment so past days remain displayable."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("sentiment_history").upsert(
            {
                "symbol": symbol.upper(),
                "day": day,
                "score": round(float(score), 4),
                "label": label,
                "confidence": round(float(confidence), 3),
                "news_count": int(news_count),
                "updated_at": _iso(_utc_now()),
            },
            on_conflict="symbol,day",
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Sentiment history write failed for %s: %s", symbol, exc)
        return False


def get_sentiment_history(symbol: str, days: int = 30) -> list:
    """Daily sentiment snapshots for a symbol, oldest first."""
    client = _get_client()
    if not client:
        return []
    try:
        cutoff = (_utc_now() - timedelta(days=days)).date().isoformat()
        result = (
            client.table("sentiment_history")
            .select("day,score,label,confidence,news_count")
            .eq("symbol", symbol.upper())
            .gte("day", cutoff)
            .order("day")
            .execute()
        )
        return getattr(result, "data", None) or []
    except Exception as exc:
        logger.warning("Sentiment history read failed for %s: %s", symbol, exc)
        return []


def get_user_by_email(email: str):
    """Fetch an account row by (lowercased) email, or None."""
    client = _get_client()
    if not client:
        return None
    try:
        result = (
            client.table("app_users")
            .select("id,email,password_hash")
            .eq("email", email.strip().lower())
            .maybe_single()
            .execute()
        )
        return getattr(result, "data", None) or None
    except Exception as exc:
        logger.warning("User lookup failed: %s", exc)
        return None


def create_user(email: str, password_hash: str):
    """Insert a new account; returns the created row or None (e.g. duplicate)."""
    client = _get_client()
    if not client:
        return None
    try:
        result = (
            client.table("app_users")
            .insert({"email": email.strip().lower(), "password_hash": password_hash})
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("User creation failed: %s", exc)
        return None


def touch_user_login(user_id: str) -> None:
    client = _get_client()
    if not client:
        return
    try:
        client.table("app_users").update({"last_login_at": _iso(_utc_now())}).eq("id", user_id).execute()
    except Exception as exc:
        logger.warning("Login timestamp update failed: %s", exc)


def get_watchlist(user_id: str) -> list:
    """Watchlist symbols for a user, oldest first."""
    client = _get_client()
    if not client:
        return []
    try:
        result = (
            client.table("watchlist_items")
            .select("symbol,added_at")
            .eq("user_id", user_id)
            .order("added_at")
            .execute()
        )
        return getattr(result, "data", None) or []
    except Exception as exc:
        logger.warning("Watchlist read failed: %s", exc)
        return []


def add_watchlist_symbol(user_id: str, symbol: str) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.table("watchlist_items").upsert(
            {"user_id": user_id, "symbol": symbol.upper()},
            on_conflict="user_id,symbol",
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Watchlist add failed: %s", exc)
        return False


def remove_watchlist_symbol(user_id: str, symbol: str) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        (
            client.table("watchlist_items")
            .delete()
            .eq("user_id", user_id)
            .eq("symbol", symbol.upper())
            .execute()
        )
        return True
    except Exception as exc:
        logger.warning("Watchlist remove failed: %s", exc)
        return False


def consume_rate_limit(*, bucket: str, key: str, limit: int, window_seconds: int, consume: bool = True):
    client = _get_client()
    if not client:
        return None
    try:
        result = client.rpc(
            "consume_rate_limit",
            {
                "p_bucket": bucket,
                "p_key": key,
                "p_limit": limit,
                "p_window_seconds": window_seconds,
                "p_consume": consume,
            },
        ).execute()
        data = getattr(result, "data", None)
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception as exc:
        logger.warning("Supabase rate-limit RPC failed for %s: %s", bucket, exc)
        return None
