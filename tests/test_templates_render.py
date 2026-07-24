"""Every page must actually render.

The suite previously exercised only JSON API routes, so a template-level
mistake was invisible to it: a Jinja tag written inside an HTML comment in
base.html opened an unclosed block and 500'd every single page while the
whole suite stayed green. These tests walk the real routes.
"""
import pytest


PAGES = ["/", "/sec-filings", "/forecasting", "/track-news", "/about"]

# Pages that draw charts and therefore must pull in Chart.js; everything else
# must NOT, since that is the point of base.html's chart_libs block.
CHART_PAGES = {"/", "/sec-filings", "/forecasting"}


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    return create_app().test_client()


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200, f"{path} did not render"
    assert b"<html" in response.data.lower()


@pytest.mark.parametrize("path", PAGES)
def test_chart_js_is_only_loaded_where_charts_exist(client, path):
    body = client.get(path).get_data(as_text=True)
    loads_chartjs = "chart.umd.min.js" in body

    if path in CHART_PAGES:
        assert loads_chartjs, f"{path} draws charts but does not load Chart.js"
        assert "chartjs-adapter-date-fns" in body, f"{path} is missing the date adapter"
    else:
        assert not loads_chartjs, f"{path} loads Chart.js but has no charts"


@pytest.mark.parametrize("path", PAGES)
def test_no_font_awesome_or_cdnjs_references_remain(client, path):
    """Font Awesome was loaded site-wide while zero fa-* icons were ever used."""
    body = client.get(path).get_data(as_text=True)

    assert "cdnjs.cloudflare.com" not in body
    assert "font-awesome" not in body.lower()
    # The CSP must not keep the origin allowlisted either.
    csp = client.get(path).headers["Content-Security-Policy"]
    assert "cdnjs.cloudflare.com" not in csp


@pytest.mark.parametrize("path", PAGES)
def test_waitlist_cta_and_modal_are_available_site_wide(client, path):
    body = client.get(path).get_data(as_text=True)

    assert 'data-action="open-waitlist-modal"' in body
    assert 'id="waitlistModal"' in body
    assert "js/waitlist-modal.js" in body


def test_forecasting_page_says_ai_not_lstm(client):
    body = client.get("/forecasting").get_data(as_text=True)

    assert "LSTM" not in body
    assert "AI forecast" in body
