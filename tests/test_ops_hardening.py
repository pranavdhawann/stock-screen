"""Operational hardening regressions.

Covers:
  - MAX_CONTENT_LENGTH falls back safely to the documented 1 MiB default
    when the env var is missing, empty, or malformed, instead of raising
    ValueError and crashing app start-up.
  - The security-headers CSP no longer declares 'unsafe-inline' for
    style-src, now that every template and static JS file has been
    migrated off inline style="" attributes onto stylesheet classes (with
    genuinely dynamic values applied via CSSOM instead).
  - No template or static JS file regresses back to using inline style=""
    attributes.
"""
import logging
import os

import pytest


def _make_app(monkeypatch, max_content_length=None):
    from app import create_app

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    if max_content_length is None:
        monkeypatch.delenv("MAX_CONTENT_LENGTH", raising=False)
    else:
        monkeypatch.setenv("MAX_CONTENT_LENGTH", max_content_length)
    return create_app()


def test_max_content_length_defaults_to_1mib_when_unset(monkeypatch):
    app = _make_app(monkeypatch, max_content_length=None)
    assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024


def test_max_content_length_malformed_falls_back_instead_of_raising(monkeypatch):
    app = _make_app(monkeypatch, max_content_length="1MB")
    assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024


def test_max_content_length_malformed_logs_a_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        _make_app(monkeypatch, max_content_length="not-a-number")

    assert any(
        "MAX_CONTENT_LENGTH" in record.getMessage() for record in caplog.records
    )


def test_max_content_length_empty_string_falls_back(monkeypatch):
    app = _make_app(monkeypatch, max_content_length="")
    assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024


def test_max_content_length_valid_override_is_respected(monkeypatch):
    app = _make_app(monkeypatch, max_content_length="2048")
    assert app.config["MAX_CONTENT_LENGTH"] == 2048


def test_csp_style_src_does_not_allow_unsafe_inline(monkeypatch):
    # Every template and static JS file has been migrated off inline
    # style="" attributes onto stylesheet classes (dynamic values are
    # applied via CSSOM instead, which style-src does not gate), so
    # 'unsafe-inline' is no longer needed for style-src.
    app = _make_app(monkeypatch)
    with app.test_client() as client:
        response = client.get("/ping") if _has_ping_route(app) else client.get("/")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "style-src" in csp
        style_src = next(
            part.strip() for part in csp.split(";") if part.strip().startswith("style-src")
        )
        assert "'unsafe-inline'" not in style_src


def _has_ping_route(app):
    return any(rule.rule == "/ping" for rule in app.url_map.iter_rules())


def test_base_html_modals_have_no_inline_style_attributes():
    with open("templates/base.html", "r", encoding="utf-8") as fh:
        content = fh.read()
    assert 'style="' not in content


def _iter_files(directory, suffix):
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(suffix):
                yield os.path.join(root, name)


def test_no_template_or_static_js_uses_inline_style_attributes():
    # Regression guard for the style-src 'unsafe-inline' removal above:
    # nothing should reintroduce an inline style="" attribute in a
    # template (including ones built as JS template-literal strings and
    # injected via innerHTML) or a static JS file.
    offenders = []
    for directory, suffix in (("templates", ".html"), ("static/js", ".js")):
        for path in _iter_files(directory, suffix):
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            if 'style="' in content:
                offenders.append(path)

    assert not offenders, f"Found inline style=\"\" attributes in: {offenders}"
