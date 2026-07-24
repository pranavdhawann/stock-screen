"""Tests for the architecture pass: compression, cache busting, shared
worker pools, the named persistent-cache registry, and tiered rate limits.
"""
import gzip

import pytest


def read(path):
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    return create_app().test_client()


# --- Response compression ------------------------------------------------------

def test_html_is_compressed_when_the_client_accepts_it(client):
    """~100KB of unminified JS/CSS/HTML used to go out uncompressed."""
    plain = client.get("/about", headers={"Accept-Encoding": "identity"})
    zipped = client.get("/about", headers={"Accept-Encoding": "gzip"})

    assert zipped.headers.get("Content-Encoding") == "gzip"
    # Not compared byte-for-byte: each response carries its own CSP nonce.
    decompressed = gzip.decompress(zipped.data)
    assert decompressed.lstrip().startswith(b"<!DOCTYPE")
    assert decompressed.rstrip().endswith(b"</html>")
    assert len(zipped.data) < len(plain.data) / 2, "compression should more than halve the page"


def test_json_api_responses_are_compressed(client):
    resp = client.get("/api/stock_list", headers={"Accept-Encoding": "gzip"})

    assert resp.headers.get("Content-Encoding") == "gzip"
    assert b"AAPL" in gzip.decompress(resp.data)


def test_uncompressed_clients_still_get_valid_responses(client):
    resp = client.get("/about", headers={"Accept-Encoding": "identity"})

    assert resp.status_code == 200
    assert "Content-Encoding" not in resp.headers
    assert b"<html" in resp.data.lower()


# --- Static asset cache busting ------------------------------------------------

def test_static_urls_carry_a_content_version(client):
    """A deploy must not leave browsers on last release's JS."""
    body = client.get("/").get_data(as_text=True)

    assert "css/style.css?v=" in body
    assert "js/main.js?v=" in body


def test_asset_version_changes_when_the_file_changes(tmp_path):
    from app import _compute_asset_version

    asset = tmp_path / "app.js"
    asset.write_text("console.log(1)", encoding="utf-8")
    first = _compute_asset_version(str(tmp_path), "app.js")

    asset.write_text("console.log(1) // now with more bytes", encoding="utf-8")
    second = _compute_asset_version(str(tmp_path), "app.js")

    assert first and second and first != second


def test_missing_asset_degrades_to_an_unversioned_url(tmp_path):
    """A bad filename must not 500 the page that references it."""
    from app import _compute_asset_version

    assert _compute_asset_version(str(tmp_path), "does-not-exist.js") is None


# --- Shared worker pools -------------------------------------------------------

def test_fanout_paths_do_not_build_per_request_thread_pools():
    """Each request used to spawn its own pool; under load that multiplied."""
    api = read("app/routes/api.py")
    aggregator = read("app/services/news_aggregator.py")

    assert "with ThreadPoolExecutor(" not in api
    assert "with ThreadPoolExecutor(" not in aggregator
    assert "market_data_executor" in api
    assert "news_fanout_executor" in aggregator


def test_pools_are_bounded_and_env_tunable(monkeypatch):
    from app.services import executors

    assert executors.news_fanout_executor._max_workers >= 1
    assert executors.market_data_executor._max_workers >= 1

    monkeypatch.setenv("NEWS_FANOUT_WORKERS", "3")
    assert executors._pool_size("NEWS_FANOUT_WORKERS", 12) == 3

    # A misconfigured value must fall back, not produce a broken pool.
    monkeypatch.setenv("NEWS_FANOUT_WORKERS", "not-a-number")
    assert executors._pool_size("NEWS_FANOUT_WORKERS", 12) == 12
    monkeypatch.setenv("NEWS_FANOUT_WORKERS", "0")
    assert executors._pool_size("NEWS_FANOUT_WORKERS", 12) == 12


# --- Named persistent-cache registry -------------------------------------------

def test_caches_declare_persistence_by_name_not_object_identity():
    from app.services import cache as cache_module

    assert cache_module.stock_data_cache.name == "stock_data"
    assert cache_module.market_news_cache.name == "market_news"

    # Rebinding a cache to a fresh object must not silently lose persistence,
    # which is exactly what an id()-keyed lookup did.
    rebuilt = cache_module.NamedTTLCache("stock_data", 10, 60)
    assert rebuilt.name in cache_module._PERSISTENT_BACKENDS


def test_market_news_cache_is_declared_memory_only():
    from app.services import cache as cache_module

    assert "market_news" not in cache_module._PERSISTENT_BACKENDS
    assert cache_module._persistence_for(cache_module.market_news_cache) is None


def test_persistence_lookup_is_not_permanently_disabled_by_one_outage(monkeypatch):
    """The old memoized map could latch 'no Supabase' for the process life."""
    from app.services import cache as cache_module

    monkeypatch.setattr(cache_module, "_sb", lambda: None)
    assert cache_module._persistence_for(cache_module.stock_data_cache) is None

    class FakeSbc:
        def get_stock_data_cache(self, _key):
            return None

        def set_stock_data_cache(self, _key, _value):
            return True

    monkeypatch.setattr(cache_module, "_sb", lambda: FakeSbc())
    assert cache_module._persistence_for(cache_module.stock_data_cache) is not None


# --- Tiered rate limits --------------------------------------------------------

def test_burst_guard_trips_before_the_hourly_quota(client, monkeypatch):
    """In-memory limits are per instance; the burst tier is the cheap one."""
    from app.routes.api import PUBLIC_NEWS_BURST_LIMIT, PUBLIC_NEWS_LIMIT

    assert PUBLIC_NEWS_BURST_LIMIT < PUBLIC_NEWS_LIMIT

    codes = [
        client.get("/api/market_news?market=US").status_code
        for _ in range(PUBLIC_NEWS_BURST_LIMIT + 2)
    ]

    assert codes[0] == 200
    assert 429 in codes, "a burst must be rejected without waiting for the hourly quota"


def test_quota_tier_is_distributed_and_burst_tier_is_not():
    """The whole point: the durable quota must survive scale-out."""
    from app.services import http_limits

    source = read("app/services/http_limits.py")
    assert "distributed=False" in source     # burst tier, local
    assert "distributed=True" in source      # quota tier, shared
    assert hasattr(http_limits, "consume_tiered_limit")


def test_watchlist_mutations_use_the_shared_limiter():
    account = read("app/routes/account.py")

    assert "distributed=False" not in account, (
        "watchlist limits must be cross-instance; the handler already does Supabase I/O"
    )


# --- Deployment / CPU contention -----------------------------------------------

def test_torch_thread_count_is_capped():
    """One forecast used to fan out across every vCPU and stall other requests."""
    import torch

    from app.services import forecasting  # noqa: F401 - import applies the cap

    assert torch.get_num_threads() == 1


def test_dockerfile_process_model_is_tunable_without_a_rebuild():
    dockerfile = read("Dockerfile")

    assert "--workers $GUNICORN_WORKERS" in dockerfile
    assert "--threads $GUNICORN_THREADS" in dockerfile
    assert "OMP_NUM_THREADS=1" in dockerfile


# --- Ephemeral fallback store --------------------------------------------------

def test_sentiment_store_directory_is_configurable(monkeypatch, tmp_path):
    """On Cloud Run the default path is scratch space wiped on every deploy."""
    from app.services import sentiment_store

    monkeypatch.setenv("SENTIMENT_STORE_DIR", str(tmp_path / "mounted"))
    assert sentiment_store._instance_dir() == str(tmp_path / "mounted")

    monkeypatch.delenv("SENTIMENT_STORE_DIR")
    assert sentiment_store._instance_dir().endswith("instance")


def test_ephemeral_storage_warns_once_in_production(monkeypatch, caplog):
    from app.services import sentiment_store

    monkeypatch.setattr(sentiment_store, "_ephemeral_warned", False)
    monkeypatch.setenv("K_SERVICE", "stock-screen")
    monkeypatch.delenv("SENTIMENT_STORE_DIR", raising=False)

    with caplog.at_level("WARNING"):
        sentiment_store._warn_if_ephemeral()
        sentiment_store._warn_if_ephemeral()

    assert sum("ephemeral container filesystem" in r.message for r in caplog.records) == 1
