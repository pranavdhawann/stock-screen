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
)

logger = logging.getLogger(__name__)

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
    except ImportError:
        return None
    except Exception as exc:
        logger.warning("Persistent cache client unavailable: %s", exc)
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
        # Don't memoize the empty map: a transient failure at first call
        # would otherwise disable the persistent cache for the process life.
        return {}

    _SB_MAP = {
        id(stock_data_cache): (sbc.get_stock_data_cache, sbc.set_stock_data_cache),
        id(aggregated_news_cache): (sbc.get_aggregated_news_cache, sbc.set_aggregated_news_cache),
        id(sentiment_cache): (sbc.get_sentiment_cache, sbc.set_sentiment_cache),
        id(sec_filings_cache): (sbc.get_sec_filings_cache, sbc.set_sec_filings_cache),
    }
    return _SB_MAP


# Background worker for Supabase persistence so requests never block on it.
_persist_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache-persist")


def get_cached(cache, key):
    """In-memory first (no network), then Supabase with memory backfill."""
    with _cache_lock:
        value = cache.get(key)
    if value is not None:
        return value

    mapping = _sb_map()
    sb_pair = mapping.get(id(cache))
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

    mapping = _sb_map()
    sb_pair = mapping.get(id(cache))
    if sb_pair:
        _, sb_set = sb_pair
        _persist_executor.submit(_persist_to_supabase, sb_set, key, value)
