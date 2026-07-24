"""Regression tests for the debug pass over the codebase and Supabase.

Covers five issues found while auditing app/routes/api.py, app/services/cache.py
and the Track News front-end against the live Supabase schema:

1. Stored sentiment snapshots outside the price chart's window never rendered.
2. _sentiment_divergence walked timeline[idx]/chart_data[idx] in lockstep with
   no guard, so any change to the timeline's length was an IndexError waiting.
3. /api/market_news persisted its dict payload into the Supabase-backed
   aggregated_news_cache table under a fake `symbol`.
4. news_aggregator.has_extra_sources() was dead once analyze_sentiment stopped
   branching on it.
5. Track News rendered whichever /api/market_news response landed last, not the
   one for the market currently selected.
"""
from datetime import datetime, timezone

import pytest


def _ms(day):
    """UTC midnight of an ISO day as epoch milliseconds (chart_data's unit)."""
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    return create_app().test_client()


# --- Issue 1: sentiment history retention on the graph -------------------------

def test_history_days_outside_the_chart_window_are_kept():
    """Snapshots on non-trading days had no chart point to land on.

    _build_sentiment_timeline emits exactly one point per chart_data row, so a
    snapshot recorded on a weekend - or on any day older than the 30d chart -
    stayed invisible forever even though Supabase retains it indefinitely.
    """
    from app.routes.api import _extend_timeline_with_history

    timeline = [
        {"date": _ms("2026-07-20"), "date_label": "2026-07-20", "score": -0.3, "headline_count": 4},
        {"date": _ms("2026-07-21"), "date_label": "2026-07-21", "score": 0.1, "headline_count": 2},
    ]
    history = [
        {"day": "2026-06-14", "score": 0.2205, "news_count": 21},   # a Sunday
        {"day": "2026-07-20", "score": 0.99, "news_count": 9},      # already on the chart
    ]

    extended = _extend_timeline_with_history(timeline, history)
    by_day = {point["date_label"]: point for point in extended}

    assert "2026-06-14" in by_day, "off-chart history day must still reach the graph"
    assert by_day["2026-06-14"]["score"] == 0.22
    assert by_day["2026-06-14"]["headline_count"] == 21
    assert by_day["2026-06-14"]["source"] == "history"
    # The chart's own point wins for a day it already covers.
    assert by_day["2026-07-20"]["score"] == -0.3
    # Chronological, and using the same epoch-ms unit the front-end feeds to
    # `new Date(...)` - seconds would render every history point in 1970.
    assert [p["date"] for p in extended] == sorted(p["date"] for p in extended)
    assert by_day["2026-06-14"]["date"] == _ms("2026-06-14")


def test_analyze_sentiment_requests_and_renders_a_full_30_day_history(client, monkeypatch):
    """End-to-end: the route must ask for >=30 days and surface off-chart days."""
    from app.routes import api

    requested = {}

    def fake_history(symbol, days=30):
        requested["days"] = days
        return [
            {"day": "2026-06-14", "score": 0.22, "label": "Positive", "confidence": 0.5, "news_count": 21},
            {"day": "2026-07-21", "score": 0.31, "label": "Positive", "confidence": 0.6, "news_count": 12},
        ]

    monkeypatch.setattr(api, "_get_supabase_client", lambda: None)
    monkeypatch.setattr(api.sentiment_store, "get_sentiment_history", fake_history)
    monkeypatch.setattr(api.sentiment_store, "record_sentiment_snapshot", lambda **_kw: True)
    monkeypatch.setattr(api.news_aggregator, "aggregate_news",
                        lambda *_a: [{"title": "n", "summary": "", "published": 1_784_000_000}])
    monkeypatch.setattr(api.news_aggregator, "preprocess_with_groq", lambda items, *_a: items)
    monkeypatch.setattr(api.stock_data, "fetch_stock_data", lambda _s: {
        "current_price": 1, "price_change": 0, "price_change_percent": 0,
        "chart_data": [{"date": _ms("2026-07-21"), "price": 10.0, "volume": 1}],
        "data_timestamp": "2026-07-22T00:00:00", "data_source": "test",
    })
    monkeypatch.setattr(api.sentiment, "analyze_news_sentiment", lambda items, *_a: items)
    monkeypatch.setattr(api.sentiment, "compute_overall_sentiment",
                        lambda _i: {"overall_sentiment": "Neutral", "confidence": 0.5})
    monkeypatch.setattr(api.insights, "generate_insights", lambda *_a: {})
    monkeypatch.setattr(api.insights, "extract_keywords_from_news", lambda _i: [])

    payload = client.post("/api/analyze_sentiment", json={"symbol": "AAPL"}).get_json()

    assert requested["days"] >= 30, "history window must cover at least 30 days"
    days = {point["date_label"] for point in payload["sentiment_timeline"]}
    assert "2026-06-14" in days, "stored history must survive onto the returned timeline"


# --- Issue 2: divergence's index-alignment contract ----------------------------

def test_divergence_survives_a_timeline_shorter_than_the_chart():
    """The loop reads timeline[idx] for every chart_data idx - guard, don't crash."""
    from app.routes.api import _sentiment_divergence

    chart_data = [{"price": 10.0}, {"price": 11.0}, {"price": 12.0}, {"price": 13.0}]
    short_timeline = [{"score": 0.1}, {"score": 0.2}, {"score": 0.3}]

    assert _sentiment_divergence(short_timeline, chart_data) == 0.0


# --- Issue 3: market news must not pollute the Supabase news cache -------------

def test_market_news_does_not_write_to_the_supabase_news_cache(client, monkeypatch):
    """/api/market_news shared aggregated_news_cache, which cache.py persists.

    That mapped a dict payload into the aggregated_news_cache table's news_items
    column (which otherwise holds a list of articles) under symbol='market_news_US'.
    """
    from app.routes import api
    from app.services import cache as cache_module

    persisted = []
    monkeypatch.setattr(cache_module, "_sb", lambda: None)
    monkeypatch.setattr(api.news_aggregator, "fetch_general_market_news",
                        lambda market: [{"title": f"{market} headline", "summary": "",
                                         "link": "https://example.com/a", "publisher": "T",
                                         "published": 1_784_000_000}])
    monkeypatch.setattr(cache_module, "_persist_to_supabase",
                        lambda sb_set, key, value: persisted.append(key))

    cache_module.market_news_cache.clear()
    cache_module.aggregated_news_cache.clear()

    assert client.get("/api/market_news?market=US").status_code == 200

    assert persisted == [], "market news must never reach the symbol-keyed Supabase table"
    assert "market_news_US" not in cache_module.aggregated_news_cache
    assert cache_module.market_news_cache.get("market_news_US") is not None
    # The per-symbol cache must stay mapped to Supabase - only market news moved.
    assert id(cache_module.aggregated_news_cache) != id(cache_module.market_news_cache)


# --- Issue 4: dead paid-key probe ---------------------------------------------

def test_has_extra_sources_is_gone():
    """analyze_sentiment stopped branching on it; nothing else ever called it."""
    from app.services import news_aggregator

    assert not hasattr(news_aggregator, "has_extra_sources")


# --- Issue 5: Track News response ordering ------------------------------------

def test_track_news_ignores_out_of_order_responses():
    """Toggling US->IN quickly could render the slower US response last."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "static" / "js" / "track-news.js"
    text = source.read_text(encoding="utf-8")

    assert "requestToken" in text, "each fetch needs a token to detect staleness"
    assert "requestToken !== token" in text, "a superseded response must be discarded"
