from cachetools import TTLCache
from app.config import (
    STOCK_DATA_CACHE_SIZE, STOCK_DATA_TTL,
    NEWS_CACHE_SIZE, NEWS_TTL,
    SENTIMENT_CACHE_SIZE, SENTIMENT_TTL,
    SEC_FILINGS_CACHE_SIZE, SEC_FILINGS_TTL,
    AGGREGATED_NEWS_CACHE_SIZE, AGGREGATED_NEWS_TTL,
)

stock_data_cache = TTLCache(maxsize=STOCK_DATA_CACHE_SIZE, ttl=STOCK_DATA_TTL)
news_cache = TTLCache(maxsize=NEWS_CACHE_SIZE, ttl=NEWS_TTL)
sentiment_cache = TTLCache(maxsize=SENTIMENT_CACHE_SIZE, ttl=SENTIMENT_TTL)
sec_filings_cache = TTLCache(maxsize=SEC_FILINGS_CACHE_SIZE, ttl=SEC_FILINGS_TTL)
aggregated_news_cache = TTLCache(maxsize=AGGREGATED_NEWS_CACHE_SIZE, ttl=AGGREGATED_NEWS_TTL)


def get_cached(cache, key):
    return cache.get(key)


def set_cached(cache, key, value):
    cache[key] = value
