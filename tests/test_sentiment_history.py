"""Tests for the persistent sentiment-history timeline backfill."""

from app.routes.api import _merge_sentiment_history


def _point(date_label, score=0.0, count=0):
    return {
        "date": 0,
        "date_label": date_label,
        "score": score,
        "headline_count": count,
    }


def test_merge_fills_only_empty_days():
    timeline = [
        _point("2026-06-01"),                      # no headlines -> backfill
        _point("2026-06-02", score=0.6, count=3),  # has headlines -> keep
        _point("2026-06-03"),                      # no history row -> keep 0
    ]
    history = [
        {"day": "2026-06-01", "score": "-0.45", "news_count": 7},
        {"day": "2026-06-02", "score": "0.9", "news_count": 9},
    ]

    merged = _merge_sentiment_history(timeline, history)

    assert merged[0]["score"] == -0.45
    assert merged[0]["headline_count"] == 7
    assert merged[0]["source"] == "history"
    # Day with live headlines is untouched by history.
    assert merged[1]["score"] == 0.6
    assert merged[1]["headline_count"] == 3
    assert "source" not in merged[1]
    # Day with no data anywhere stays at zero.
    assert merged[2]["score"] == 0.0
    assert merged[2]["headline_count"] == 0


def test_merge_handles_empty_and_malformed_input():
    assert _merge_sentiment_history([], []) == []
    assert _merge_sentiment_history(None, None) is None

    timeline = [_point("2026-06-01")]
    merged = _merge_sentiment_history(timeline, [{"day": "2026-06-01", "score": "bad"}])
    assert merged[0]["score"] == 0.0  # malformed score leaves the point alone


def test_history_functions_degrade_without_client(monkeypatch):
    from app.services import supabase_client

    monkeypatch.setattr(supabase_client, "_get_client", lambda: None)
    assert supabase_client.get_sentiment_history("AAPL") == []
    assert supabase_client.record_sentiment_snapshot(
        symbol="AAPL", day="2026-06-11", score=0.5,
        label="Positive", confidence=0.8, news_count=5,
    ) is False
