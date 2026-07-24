"""Regression tests for the analytics CSP.

Umami Cloud serves its tracker from cloud.umami.is but POSTs collected
events to gateway.umami.is. The CSP originally allowlisted only the script
origin, so the tracker loaded, every send was blocked by connect-src, and
the dashboard reported zero visitors indefinitely - with no server-side
symptom at all. These tests pin both origins.
"""
import pytest

from app import create_app

CLOUD_SCRIPT_ORIGIN = "https://cloud.umami.is"
CLOUD_SEND_ORIGIN = "https://gateway.umami.is"


def _make_app(monkeypatch, website_id="test-website-id", src=None, send_origin=None):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    if website_id is None:
        monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    else:
        monkeypatch.setenv("UMAMI_WEBSITE_ID", website_id)
    if src is None:
        monkeypatch.delenv("UMAMI_SRC", raising=False)
    else:
        monkeypatch.setenv("UMAMI_SRC", src)
    if send_origin is None:
        monkeypatch.delenv("UMAMI_SEND_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("UMAMI_SEND_ORIGIN", send_origin)
    return create_app()


def _directive(app, name):
    with app.test_client() as client:
        csp = client.get("/").headers.get("Content-Security-Policy", "")
    return next(
        (part.strip() for part in csp.split(";") if part.strip().startswith(name)),
        "",
    )


def test_connect_src_allows_the_umami_collector(monkeypatch):
    """The bug: sends went to gateway.umami.is, which was never allowlisted."""
    app = _make_app(monkeypatch)
    assert CLOUD_SEND_ORIGIN in _directive(app, "connect-src")


def test_connect_src_still_allows_the_script_origin(monkeypatch):
    app = _make_app(monkeypatch)
    assert CLOUD_SCRIPT_ORIGIN in _directive(app, "connect-src")


def test_script_src_allows_only_the_script_origin(monkeypatch):
    """The collector is never a script source - it only receives POSTs."""
    app = _make_app(monkeypatch)
    script_src = _directive(app, "script-src")
    assert CLOUD_SCRIPT_ORIGIN in script_src
    assert CLOUD_SEND_ORIGIN not in script_src


def test_analytics_origins_absent_when_analytics_is_disabled(monkeypatch):
    app = _make_app(monkeypatch, website_id=None)
    connect_src = _directive(app, "connect-src")
    assert CLOUD_SCRIPT_ORIGIN not in connect_src
    assert CLOUD_SEND_ORIGIN not in connect_src


def test_self_hosted_instance_gets_no_cloud_collector(monkeypatch):
    """A self-hosted tracker posts to itself; cloud origins must not leak in."""
    app = _make_app(monkeypatch, src="https://analytics.example.com/script.js")
    connect_src = _directive(app, "connect-src")
    assert "https://analytics.example.com" in connect_src
    assert CLOUD_SEND_ORIGIN not in connect_src


def test_send_origin_is_overridable(monkeypatch):
    app = _make_app(monkeypatch, send_origin="https://collector.example.com")
    assert "https://collector.example.com" in _directive(app, "connect-src")


def test_connect_src_has_no_duplicate_origins(monkeypatch):
    """Script and collector origins coincide when self-hosting."""
    app = _make_app(
        monkeypatch,
        src="https://analytics.example.com/script.js",
        send_origin="https://analytics.example.com",
    )
    connect_src = _directive(app, "connect-src")
    assert connect_src.count("https://analytics.example.com") == 1
