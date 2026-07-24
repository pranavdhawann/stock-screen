"""Regression tests for the market-scoping, news-volume and sentiment-history fixes.

Covers the eight issues fixed in the market-specific/news/sentiment pass:
US vs India scoping of movers, suggestions and general news; the Market Wire
empty-state bug; per-stock news volume; and sentiment history persistence via
the local fallback store used when Supabase is not configured.
"""
import json
from datetime import date, datetime, timezone

import pytest


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    return create_app().test_client()


# --- Issue 1/5: market scoping -------------------------------------------------

def test_stock_list_honours_market_param(client):
    """/api/stock_list used to ignore ?market= and always return both universes."""
    both = client.get("/api/stock_list").get_json()
    assert both["US"] and both["IN"]

    only_in = client.get("/api/stock_list?market=IN").get_json()
    assert only_in["IN"] and only_in["US"] == []

    only_us = client.get("/api/stock_list?market=US").get_json()
    assert only_us["US"] and only_us["IN"] == []

    assert client.get("/api/stock_list?market=BOGUS").status_code == 400


def test_search_suggestions_are_market_scoped(client):
    from app.config import INDIAN_STOCKS

    indian = {s["symbol"] for s in client.get("/api/search_stocks?q=T&market=IN").get_json()}
    american = {s["symbol"] for s in client.get("/api/search_stocks?q=T&market=US").get_json()}

    assert indian and american
    assert indian <= set(INDIAN_STOCKS)
    assert not (american & set(INDIAN_STOCKS))


# --- Issue 1: Indian index currency -------------------------------------------

def test_indian_indices_use_rupee_but_keep_bare_yahoo_symbol():
    """^NSEI/^BSESN rendered as $ because is_indian_stock() only matched equities."""
    from app.config import get_currency, get_yahoo_symbol

    assert get_currency("^NSEI") == "₹"
    assert get_currency("^BSESN") == "₹"
    assert get_currency("^DJI") == "$"
    assert get_currency("TCS") == "₹"
    assert get_currency("AAPL") == "$"

    # Indices must NOT get a .NS suffix - that would break the Yahoo lookup.
    assert get_yahoo_symbol("^NSEI") == "^NSEI"
    assert get_yahoo_symbol("^BSESN") == "^BSESN"
    assert get_yahoo_symbol("TCS") == "TCS.NS"


# --- Issue 3/2: market news endpoint ------------------------------------------

def test_market_news_is_per_market_and_validated(client, monkeypatch):
    from app.routes import api

    calls = []

    def fake_fetch(market):
        calls.append(market)
        return [{
            "title": f"{market} headline",
            "summary": "",
            "link": "https://example.com/a",
            "publisher": "Test",
            "published": 1_784_000_000,
        }]

    from app.services.cache import market_news_cache

    market_news_cache.clear()
    monkeypatch.setattr(api.news_aggregator, "fetch_general_market_news", fake_fetch)

    us = client.get("/api/market_news?market=US").get_json()
    india = client.get("/api/market_news?market=IN").get_json()

    assert us["market"] == "US" and us["news"][0]["title"] == "US headline"
    assert india["market"] == "IN" and india["news"][0]["title"] == "IN headline"
    assert calls == ["US", "IN"], "each market must fetch its own feed (no cache collision)"
    assert client.get("/api/market_news?market=BOGUS").status_code == 400


def test_market_news_degrades_without_api_keys(client, monkeypatch):
    """Must return an empty list + error, never a 500, when upstream fails."""
    from app.routes import api
    from app.services.cache import market_news_cache

    market_news_cache.clear()  # don't serve a prior test's cached feed

    def boom(_market):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(api.news_aggregator, "fetch_general_market_news", boom)
    resp = client.get("/api/market_news?market=US")
    assert resp.status_code == 200
    assert resp.get_json()["news"] == []


# --- Issue 7: news volume ------------------------------------------------------

def test_analyze_sentiment_always_uses_the_free_rss_aggregator(monkeypatch, client):
    """Free Google/MarketWatch RSS used to be gated behind a paid-key check."""
    from app.routes import api

    used = {}

    def fake_aggregate(symbol, company_name):
        used["called"] = True
        return [{"title": f"{symbol} news", "summary": "", "published": 1_784_000_000}]

    monkeypatch.setattr(api.news_aggregator, "aggregate_news", fake_aggregate)
    monkeypatch.setattr(api.news_aggregator, "preprocess_with_groq", lambda items, *_a: items)
    monkeypatch.setattr(api.stock_data, "fetch_stock_data", lambda _s: {
        "current_price": 1, "price_change": 0, "price_change_percent": 0,
        "chart_data": [], "data_timestamp": "2026-06-03T00:00:00", "data_source": "test",
    })
    monkeypatch.setattr(api.sentiment, "analyze_news_sentiment", lambda items, *_a: items)
    monkeypatch.setattr(api.sentiment, "compute_overall_sentiment",
                        lambda _i: {"overall_sentiment": "Neutral", "confidence": 0.5})
    monkeypatch.setattr(api.insights, "generate_insights", lambda *_a: {})
    monkeypatch.setattr(api.insights, "extract_keywords_from_news", lambda _i: [])

    resp = client.post("/api/analyze_sentiment", json={"symbol": "AAPL"})
    assert resp.status_code == 200
    assert used.get("called"), "aggregate_news must run even with no paid API keys"


def test_dedup_keeps_untitled_items_with_distinct_links():
    """_dedup_news silently dropped any item with a blank title."""
    from app.services.news_aggregator import _dedup_news

    items = [
        {"title": "Alpha", "link": "https://example.com/1"},
        {"title": "Alpha", "link": "https://example.com/1"},   # true duplicate
        {"title": "", "link": "https://example.com/2"},
        {"title": "", "link": "https://example.com/3"},
    ]
    kept = _dedup_news(items)
    links = {i["link"] for i in kept}
    assert "https://example.com/2" in links
    assert "https://example.com/3" in links
    assert len(kept) == 3


def test_indian_symbols_skip_providers_that_cannot_resolve_them(monkeypatch):
    """Finnhub/AlphaVantage can't resolve bare NSE mnemonics - don't call them."""
    from app.services import news_aggregator as na

    called = []
    monkeypatch.setattr(na, "FINNHUB_API_KEY", "x")
    monkeypatch.setattr(na, "ALPHAVANTAGE_API_KEY", "x")
    monkeypatch.setattr(na, "NEWSAPI_KEY", "")
    monkeypatch.setattr(na, "fetch_from_finnhub", lambda *a, **k: called.append("finnhub") or [])
    monkeypatch.setattr(na, "fetch_from_alphavantage", lambda *a, **k: called.append("av") or [])
    monkeypatch.setattr(na, "fetch_from_google_rss", lambda *a, **k: [])
    monkeypatch.setattr(na, "fetch_from_marketwatch_rss", lambda *a, **k: [])
    monkeypatch.setattr(na, "fetch_yahoo_news", lambda *a, **k: [])
    monkeypatch.setattr(na, "get_cached", lambda *a, **k: None)
    monkeypatch.setattr(na, "set_cached", lambda *a, **k: None)

    na.aggregate_news("RELIANCE", "Reliance Industries Ltd.")
    assert called == [], "Indian symbols must skip Finnhub/AlphaVantage"

    called.clear()
    na.aggregate_news("AAPL", "Apple Inc.")
    assert "finnhub" in called and "av" in called, "US symbols must still use them"


# --- Issue 6: sentiment history persistence -----------------------------------

def test_sentiment_store_round_trips_and_upserts(tmp_path, monkeypatch):
    from app.services import sentiment_store as store

    monkeypatch.setattr(store, "_instance_dir", lambda: str(tmp_path))

    today = date(2026, 7, 22).isoformat()
    now = datetime.now(timezone.utc).isoformat()

    assert store.record_sentiment_snapshot(
        symbol="AAPL", day=today, score=0.4213, label="Positive",
        confidence=0.71, news_count=9, updated_at=now,
    )
    rows = store.get_sentiment_history("AAPL", days=30)
    assert len(rows) == 1
    # Score must stay a float - an int() cast would flatten every score to 0.
    assert isinstance(rows[0]["score"], float) and rows[0]["score"] == 0.4213

    # Same (symbol, day) upserts rather than appending a second row.
    store.record_sentiment_snapshot(
        symbol="AAPL", day=today, score=-0.2, label="Negative",
        confidence=0.6, news_count=4, updated_at=now,
    )
    rows = store.get_sentiment_history("AAPL", days=30)
    assert len(rows) == 1 and rows[0]["score"] == -0.2

    # Survives a fresh read from disk (this is the "persists across refresh" case).
    on_disk = json.loads((tmp_path / "sentiment_history.json").read_text())
    assert on_disk["AAPL"][0]["score"] == -0.2

    assert store.get_sentiment_history("NOSUCH", days=30) == []


def test_history_backfills_only_days_without_live_headlines():
    """Live headlines must win over stored history for the same day."""
    from app.routes.api import _merge_sentiment_history

    timeline = [
        {"date": 1, "date_label": "2026-07-17", "score": 0.0, "headline_count": 0},
        {"date": 2, "date_label": "2026-07-20", "score": -0.3, "headline_count": 4},
    ]
    history = [
        {"day": "2026-07-17", "score": 0.42, "news_count": 9},
        {"day": "2026-07-20", "score": 0.99, "news_count": 9},
    ]
    merged = _merge_sentiment_history(timeline, history)

    assert merged[0]["score"] == 0.42 and merged[0]["source"] == "history"
    assert merged[1]["score"] == -0.3 and "source" not in merged[1]
