"""
Hybrid cache layer: in-memory TTLCache (fast) → Supabase (persistent).

Reads hit the in-memory cache first (no network), then fall back to
Supabase and backfill memory on a hit. Writes update memory synchronously
and persist to Supabase on a background worker so the request path never
waits on the network. The app works identically with or without Supabase
credentials.
"""

from cachetools import TTLCache
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import logging
from app.config import (
    STOCK_DATA_CACHE_SIZE, STOCK_DATA_TTL,
    NEWS_CACHE_SIZE, NEWS_TTL,
    SENTIMENT_CACHE_SIZE, SENTIMENT_TTL,
    SEC_FILINGS_CACHE_SIZE, SEC_FILINGS_TTL,
    AGGREGATED_NEWS_CACHE_SIZE, AGGREGATED_NEWS_TTL,
    MARKET_NEWS_CACHE_SIZE,
)

logger = logging.getLogger(__name__)

class NamedTTLCache(TTLCache):
    """A TTLCache that carries its own name.

    Persistence used to be looked up by id(cache_object), which was opaque -
    nothing at a cache's definition site told you whether it was backed by
    Supabase - and would silently stop persisting if a cache were ever
    rebound to a new object. The name travels with the object instead, and
    _PERSISTENT_BACKENDS below is the single readable answer to "which caches
    persist, and to what".
    """

    def __init__(self, name, maxsize, ttl):
        super().__init__(maxsize=maxsize, ttl=ttl)
        self.name = name


# ── In-memory caches (fallback when Supabase is not available) ──
stock_data_cache = NamedTTLCache("stock_data", STOCK_DATA_CACHE_SIZE, STOCK_DATA_TTL)
news_cache = NamedTTLCache("news", NEWS_CACHE_SIZE, NEWS_TTL)
sentiment_cache = NamedTTLCache("sentiment", SENTIMENT_CACHE_SIZE, SENTIMENT_TTL)
sec_filings_cache = NamedTTLCache("sec_filings", SEC_FILINGS_CACHE_SIZE, SEC_FILINGS_TTL)
aggregated_news_cache = NamedTTLCache("aggregated_news", AGGREGATED_NEWS_CACHE_SIZE, AGGREGATED_NEWS_TTL)
# Deliberately absent from _PERSISTENT_BACKENDS: market-wide headlines have no
# symbol to key a Supabase row on, and their payload is a dict rather than the
# list of articles that aggregated_news_cache's news_items column stores.
market_news_cache = NamedTTLCache("market_news", MARKET_NEWS_CACHE_SIZE, AGGREGATED_NEWS_TTL)
_cache_lock = RLock()


# Cache name -> the supabase_client getter/setter pair that persists it.
# A cache absent from this table is memory-only, by design.
_PERSISTENT_BACKENDS = {
    "stock_data": ("get_stock_data_cache", "set_stock_data_cache"),
    "aggregated_news": ("get_aggregated_news_cache", "set_aggregated_news_cache"),
    "sentiment": ("get_sentiment_cache", "set_sentiment_cache"),
    "sec_filings": ("get_sec_filings_cache", "set_sec_filings_cache"),
}


def _sb():
    """Lazy import to avoid circular dependency at module load time."""
    try:
        from app.services import supabase_client as sbc
        return sbc if sbc.is_available() else None
    except ImportError:
        return None
    except Exception as exc:
        logger.warning("Persistent cache client unavailable: %s", exc)
        return None


def _persistence_for(cache):
    """(getter, setter) for this cache's Supabase twin, or None.

    Resolved per call rather than memoized into a map: supabase_client caches
    the constructed client itself, so this stays cheap, and a Supabase outage
    at first use no longer disables persistence for the process lifetime.
    """
    entry = _PERSISTENT_BACKENDS.get(getattr(cache, "name", None))
    if not entry:
        return None
    sbc = _sb()
    if not sbc:
        return None
    getter_name, setter_name = entry
    return getattr(sbc, getter_name), getattr(sbc, setter_name)


# Background worker for Supabase persistence so requests never block on it.
_persist_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache-persist")


def get_cached(cache, key):
    """In-memory first (no network), then Supabase with memory backfill."""
    with _cache_lock:
        value = cache.get(key)
    if value is not None:
        return value

    sb_pair = _persistence_for(cache)
    if sb_pair:
        sb_get, _ = sb_pair
        try:
            result = sb_get(key)
            if result is not None:
                # Backfill memory so subsequent reads skip the network.
                with _cache_lock:
                    cache[key] = result
                return result
        except Exception as exc:
            logger.warning("Persistent cache read failed for %r: %s", key, exc)

    return None


def _persist_to_supabase(sb_set, key, value):
    try:
        sb_set(key, value)
    except Exception as exc:
        logger.warning("Persistent cache write failed for %r: %s", key, exc)


def set_cached(cache, key, value):
    """Write in-memory synchronously; persist to Supabase in the background."""
    with _cache_lock:
        cache[key] = value

    sb_pair = _persistence_for(cache)
    if sb_pair:
        _, sb_set = sb_pair
        _persist_executor.submit(_persist_to_supabase, sb_set, key, value)
