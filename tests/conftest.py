"""Shared pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def isolate_local_sentiment_store(tmp_path, monkeypatch):
    """Point the local sentiment-history fallback at a per-test directory.

    app/services/sentiment_store.py writes to <project_root>/instance, and
    /api/analyze_sentiment persists a snapshot on every call - including when
    the route is exercised under test with no Supabase configured. Without this
    fixture the suite accumulated real snapshots in the developer's working
    tree and later runs read them back, so a test's result depended on how many
    times the suite had been run before.

    Redirects via SENTIMENT_STORE_DIR rather than patching _instance_dir, so
    the real resolution path still runs. Tests that need something else can
    override the env var or patch _instance_dir directly; either applies after
    this one.
    """
    monkeypatch.setenv("SENTIMENT_STORE_DIR", str(tmp_path / "instance"))
