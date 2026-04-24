"""
Hybrid cache layer: Supabase (persistent) → in-memory TTLCache (fallback).

Every get/set checks Supabase first. If Supabase is not configured or
the call fails, falls back to the original in-memory cachetools caches.
This means the app works identically with or without Supabase credentials.
"""

from cachetools import TTLCache
from threading import RLock
from app.config import (
    STOCK_DATA_CACHE_SIZE, STOCK_DATA_TTL,
    NEWS_CACHE_SIZE, NEWS_TTL,
    SENTIMENT_CACHE_SIZE, SENTIMENT_TTL,
    SEC_FILINGS_CACHE_SIZE, SEC_FILINGS_TTL,
    AGGREGATED_NEWS_CACHE_SIZE, AGGREGATED_NEWS_TTL,
)

# ── In-memory caches (fallback when Supabase is not available) ──
stock_data_cache = TTLCache(maxsize=STOCK_DATA_CACHE_SIZE, ttl=STOCK_DATA_TTL)
news_cache = TTLCache(maxsize=NEWS_CACHE_SIZE, ttl=NEWS_TTL)
sentiment_cache = TTLCache(maxsize=SENTIMENT_CACHE_SIZE, ttl=SENTIMENT_TTL)
sec_filings_cache = TTLCache(maxsize=SEC_FILINGS_CACHE_SIZE, ttl=SEC_FILINGS_TTL)
aggregated_news_cache = TTLCache(maxsize=AGGREGATED_NEWS_CACHE_SIZE, ttl=AGGREGATED_NEWS_TTL)
_cache_lock = RLock()


def _sb():
    """Lazy import to avoid circular dependency at module load time."""
    try:
        from app.services import supabase_client as sbc
        return sbc if sbc.is_available() else None
    except Exception:
        return None


# ── Map each in-memory cache object to its Supabase getter/setter ───
# We identify caches by their id() so callers keep using the same API.
_SB_MAP = None


def _sb_map():
    """Build map lazily after supabase_client is importable."""
    global _SB_MAP
    if _SB_MAP is not None:
        return _SB_MAP

    sbc = _sb()
    if not sbc:
        _SB_MAP = {}
        return _SB_MAP

    _SB_MAP = {
        id(stock_data_cache): (sbc.get_stock_data_cache, sbc.set_stock_data_cache),
        id(aggregated_news_cache): (sbc.get_aggregated_news_cache, sbc.set_aggregated_news_cache),
        id(sentiment_cache): (sbc.get_sentiment_cache, sbc.set_sentiment_cache),
        id(sec_filings_cache): (sbc.get_sec_filings_cache, sbc.set_sec_filings_cache),
    }
    return _SB_MAP


def get_cached(cache, key):
    """Try Supabase first, then in-memory."""
    mapping = _sb_map()
    sb_pair = mapping.get(id(cache))
    if sb_pair:
        sb_get, _ = sb_pair
        try:
            result = sb_get(key)
            if result is not None:
                return result
        except Exception:
            pass  # fall through to in-memory

    with _cache_lock:
        return cache.get(key)


def set_cached(cache, key, value):
    """Write to both Supabase and in-memory."""
    # Always write in-memory (fast local cache)
    with _cache_lock:
        cache[key] = value

    # Also persist to Supabase
    mapping = _sb_map()
    sb_pair = mapping.get(id(cache))
    if sb_pair:
        _, sb_set = sb_pair
        try:
            sb_set(key, value)
        except Exception:
            pass  # in-memory still has it
