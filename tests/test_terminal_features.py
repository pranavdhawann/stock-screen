"""Regression tests for the terminal upgrade: lexicon sentiment, Groq guard,
quotes endpoint, filing text extraction, and cache fallback behavior."""

import pytest


@pytest.fixture()
def client(monkeypatch):
    from app import create_app

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DISABLE_CACHE_WARMUP", "1")
    app = create_app()
    app.testing = True
    return app.test_client()


# ── Lexicon sentiment ────────────────────────────────────────────────

def test_lexicon_sentiment_labels():
    from app.services.sentiment import lexicon_sentiment

    label, confidence = lexicon_sentiment("Record profit surge as revenue beats estimates")
    assert label == "Positive"
    assert confidence > 0.55

    label, confidence = lexicon_sentiment("Shares plunge after lawsuit and layoffs warning")
    assert label == "Negative"
    assert confidence > 0.55

    label, confidence = lexicon_sentiment("Company schedules annual shareholder meeting")
    assert label == "Neutral"
    assert confidence == 0.5


def test_fallback_sentiment_returns_real_labels():
    from app.services.sentiment import _fallback_sentiment

    items = [{"title": "Stock rallies on record earnings beat", "summary": ""}]
    result = _fallback_sentiment(items)
    assert result[0]["sentiment"] == "Positive"
    assert result[0]["confidence"] > 0
    assert result[0]["analysis_source"] == "lexicon"


# ── Groq guard ───────────────────────────────────────────────────────

def test_groq_guard_trips_on_auth_error(monkeypatch):
    """A 401 disables Groq for the process, so get_client() stops handing one out.

    Asserted through get_client() rather than the breaker flag: that is the
    only way callers observe the breaker, and returning None is what routes
    every AI service onto its non-AI fallback.
    """
    from app.services import groq_guard

    monkeypatch.setattr(groq_guard, "_auth_failed", False)
    monkeypatch.setattr(groq_guard, "_client", object())
    assert groq_guard.get_client() is not None

    class FakeAuthError(Exception):
        status_code = 401

    assert groq_guard.note_groq_error(FakeAuthError("invalid_api_key"))
    assert groq_guard.get_client() is None


def test_groq_guard_ignores_transient_errors(monkeypatch):
    from app.services import groq_guard

    monkeypatch.setattr(groq_guard, "_auth_failed", False)
    monkeypatch.setattr(groq_guard, "_client", object())
    assert not groq_guard.note_groq_error(TimeoutError("read timed out"))
    assert groq_guard.get_client() is not None


# ── Quotes endpoint ──────────────────────────────────────────────────

def _fake_stock_data(symbol, period="30d"):
    return {
        "chart_data": [
            {"date": 1700000000000, "open": 10.0, "high": 11.0, "low": 9.5,
             "price": 10.5, "close": 10.5, "volume": 1000},
            {"date": 1700086400000, "open": 10.5, "high": 12.0, "low": 10.0,
             "price": 11.5, "close": 11.5, "volume": 2000},
        ],
        "current_price": 11.5,
        "price_change": 1.0,
        "price_change_percent": 9.52,
        "data_timestamp": "2026-01-01T00:00:00",
        "data_source": "test",
    }


def test_quotes_endpoint_returns_quotes(client, monkeypatch):
    from app.services import stock_data

    monkeypatch.setattr(stock_data, "fetch_stock_data", _fake_stock_data)
    response = client.get("/api/quotes?symbols=AAPL,^GSPC")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["quotes"]) == 2

    by_symbol = {q["symbol"]: q for q in payload["quotes"]}
    assert by_symbol["AAPL"]["name"] == "Apple Inc."
    assert by_symbol["^GSPC"]["name"] == "S&P 500"
    assert by_symbol["AAPL"]["day_high"] == 12.0
    assert by_symbol["AAPL"]["spark"] == [10.5, 11.5]


def test_quotes_endpoint_rejects_unsupported_symbols(client):
    assert client.get("/api/quotes?symbols=NOTREAL").status_code == 400
    assert client.get("/api/quotes").status_code == 400


def test_spy_is_supported_for_news_fallback(client):
    # SPY is the index proxy the tape and /api/news lean on, so it must pass
    # symbol validation like any other directory entry (the request itself may
    # then hit the network, so only assert it is not rejected as unsupported).
    from app.routes.api import _is_supported_symbol

    assert _is_supported_symbol("SPY")


# ── Filing text extraction ───────────────────────────────────────────

def test_readable_sentences_skip_xbrl_noise():
    from app.services.sec_edgar import _readable_sentences

    text = (
        "aapl-20260328 false 2026 Q2 0000320193 http://fasb.org/us-gaap/2025#LongTermDebtCurrent "
        "P1Y P1Y xbrli:shares iso4217:USD. "
        "The company reported strong quarterly results driven by services revenue growth and continued "
        "demand for its flagship products across all geographic segments this year."
    )
    sentences = _readable_sentences(text)
    assert len(sentences) == 1
    assert "services revenue" in sentences[0]


def test_stats_overview_without_ai():
    from app.services.sec_edgar import _stats_overview

    filings = [
        {"form": "10-K", "filing_date": "2025-11-01"},
        {"form": "8-K", "filing_date": "2026-01-15"},
    ]
    result = _stats_overview(filings, "Apple Inc.", "AAPL", "1 10-K, 1 8-K", "2025-11-01 to 2026-01-15")
    assert "Apple Inc." in result["overview"]
    assert "8-K filed on 2026-01-15" in result["overview"]


# ── Cache behavior ───────────────────────────────────────────────────

def test_memory_cache_hit_skips_supabase(monkeypatch):
    from app.services import cache as cache_module

    def _boom(*_args):
        raise AssertionError("Supabase backend should not be consulted on a memory hit")

    monkeypatch.setattr(cache_module, "_persistence_for", _boom)
    cache_module.stock_data_cache["unit_test_key"] = {"value": 42}
    try:
        assert cache_module.get_cached(cache_module.stock_data_cache, "unit_test_key") == {"value": 42}
    finally:
        cache_module.stock_data_cache.pop("unit_test_key", None)


def test_rate_limit_in_memory_mode(monkeypatch):
    from app.services import rate_limit

    def _boom(*args, **kwargs):
        raise AssertionError("distributed=False must not call Supabase")

    monkeypatch.setattr(rate_limit, "_check_supabase_limit", _boom)
    result = rate_limit.check_limit("unit_test_bucket", "client-1", 2, 60, distributed=False)
    assert result.allowed
    result = rate_limit.check_limit("unit_test_bucket", "client-1", 2, 60, distributed=False)
    assert result.allowed
    result = rate_limit.check_limit("unit_test_bucket", "client-1", 2, 60, distributed=False)
    assert not result.allowed
