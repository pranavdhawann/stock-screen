"""Shared, bounded worker pools for outbound fan-out.

Every fan-out site used to build its own pool per request
(``with ThreadPoolExecutor(...) as executor:``). Under load that multiplied:
gunicorn serves 8 request threads, and a single /analyze_sentiment added 6
more for news sources while a concurrent /quotes added up to 8 of its own -
dozens of short-lived threads per second, each with its own stack, all
competing for the same couple of Cloud Run vCPUs. Thread *creation* also is
not free, and it happened on the request path.

These pools are built once per process and shared. Work still runs in
parallel, but total outbound concurrency is capped, so overload degrades as
queueing instead of as unbounded thread growth. Sizes are env-tunable because
the right number depends on the instance's CPU allocation.

Nesting rule: nothing running *on* one of these pools may block waiting on
the same pool, or it can deadlock once the pool is saturated. Today only
gunicorn request threads submit work; pool workers just do network I/O.
The pools are intentionally separate rather than one shared pool, so a burst
of news fan-out cannot starve market-data fan-out (and vice versa).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor


def _pool_size(env_var: str, default: int) -> int:
    """Read a pool size from the environment, falling back to `default`.

    Anything unparsable or below 1 falls back rather than producing a broken
    pool - a misconfigured env var should not take the process down.
    """
    try:
        size = int(os.environ.get(env_var, default))
    except (TypeError, ValueError):
        return default
    return size if size >= 1 else default


# News aggregation fans out to up to 6 sources per symbol.
NEWS_FANOUT_POOL_SIZE = _pool_size("NEWS_FANOUT_WORKERS", 12)

# Market indices and the /quotes ticker tape - short, cacheable Yahoo calls.
MARKET_DATA_POOL_SIZE = _pool_size("MARKET_DATA_WORKERS", 12)

news_fanout_executor = ThreadPoolExecutor(
    max_workers=NEWS_FANOUT_POOL_SIZE, thread_name_prefix="news-fanout"
)

market_data_executor = ThreadPoolExecutor(
    max_workers=MARKET_DATA_POOL_SIZE, thread_name_prefix="market-data"
)
