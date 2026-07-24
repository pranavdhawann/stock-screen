"""Every page must actually render.

The suite previously exercised only JSON API routes, so a template-level
mistake was invisible to it: a Jinja tag written inside an HTML comment in
base.html opened an unclosed block and 500'd every single page while the
whole suite stayed green. These tests walk the real routes.
"""
import pytest


PAGES = ["/", "/sec-filings", "/forecasting", "/track", "/about"]

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
def test_pro_cta_and_modal_are_available_site_wide(client, path):
    body = client.get(path).get_data(as_text=True)

    assert 'data-action="open-waitlist-modal"' in body
    assert 'id="waitlistModal"' in body
    assert "js/pro-modal.js" in body
    # The modal must offer a plan picker, not just an email capture.
    assert 'id="wlPlanOptions"' in body


def test_track_news_url_still_resolves(client):
    """The page moved from /track-news to /track; old links must not 404."""
    response = client.get("/track-news")

    assert response.status_code == 301
    assert response.headers["Location"].endswith("/track")


def test_track_page_shows_market_wire_above_track_a_stock(client):
    body = client.get("/track").get_data(as_text=True)

    assert "MARKET WIRE" in body
    assert "TRACK A STOCK" in body
    assert body.index("MARKET WIRE") < body.index("TRACK A STOCK")


def test_track_page_has_no_stock_news_section(client):
    """The per-ticker Stock News feed was removed from the page."""
    body = client.get("/track").get_data(as_text=True)

    assert "STOCK NEWS" not in body
    assert 'id="stockNewsContainer"' not in body


def test_market_wire_offers_a_load_more_control(client):
    body = client.get("/track").get_data(as_text=True)

    assert 'id="marketWireMoreBtn"' in body


def test_market_wire_starts_with_five_headlines():
    """The wire opens short; the rest is behind LOAD MORE."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "static" / "js" / "market-wire.js"
    text = source.read_text(encoding="utf-8")

    assert "const PAGE_SIZE = 5;" in text


def test_the_search_box_lives_on_track_not_markets(client):
    """"Track a Stock" moved off the Markets page; only one page owns it."""
    markets = client.get("/").get_data(as_text=True)
    track = client.get("/track").get_data(as_text=True)

    assert 'id="stockSearch"' not in markets
    assert 'id="stockSearch"' in track


def test_nav_lists_track_second(client):
    body = client.get("/").get_data(as_text=True)
    links = body[body.index('id="navLinks"'):body.index('class="nav-actions"')]
    labels = [line.strip() for line in links.splitlines() if line.strip().startswith("<span>")]

    assert labels[:2] == ["<span>Markets</span>", "<span>Track</span>"]


def test_forecasting_page_says_ai_not_lstm(client):
    body = client.get("/forecasting").get_data(as_text=True)

    assert "LSTM" not in body
    assert "AI forecast" in body
