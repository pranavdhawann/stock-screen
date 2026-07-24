"""Tests for per-account plan entitlements.

Covers the three things that make "pro" real rather than cosmetic: the plan
reaches the session, the rate limiters honour it, and nothing a client
controls can grant it.
"""
import pytest

from app import create_app
from app.services import http_limits


@pytest.fixture
def app():
    application = create_app()
    application.config.update(TESTING=True, SECRET_KEY="test-secret")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _sign_in_as(client, plan):
    with client.session_transaction() as session:
        session["uid"] = "00000000-0000-0000-0000-000000000001"
        session["email"] = "pro@example.com"
        session["plan"] = plan


# --- The entitlement check itself ---------------------------------------------

def test_anonymous_requests_are_never_unlimited(app):
    with app.test_request_context("/"):
        assert http_limits.has_unlimited_access() is False


def test_free_plan_is_not_unlimited(app):
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "free"
        assert http_limits.has_unlimited_access() is False


def test_pro_plan_is_unlimited(app):
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "pro"
        assert http_limits.has_unlimited_access() is True


def test_unknown_plan_fails_closed(app):
    """A typo'd or future plan name must not accidentally grant exemption."""
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "enterprise-trial"
        assert http_limits.has_unlimited_access() is False


def test_check_outside_request_context_fails_closed():
    assert http_limits.has_unlimited_access() is False


# --- Limiter behaviour ---------------------------------------------------------

def test_pro_bypasses_a_consumed_limit(app):
    """A bucket with zero allowance still lets a pro request through."""
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "pro"
        assert http_limits.consume_limit("plan_test_bucket", 0, 60) is None


def test_free_is_still_limited_on_the_same_bucket(app):
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "free"
        limited = http_limits.consume_limit("plan_test_bucket", 0, 60)
        assert limited is not None
        assert limited[1] == 429


def test_pro_bypasses_both_tiers_of_a_tiered_limit(app):
    with app.test_request_context("/"):
        from flask import session
        session["plan"] = "pro"
        assert http_limits.consume_tiered_limit(
            "plan_tiered_bucket",
            burst_limit=0,
            burst_window_seconds=60,
            quota_limit=0,
            quota_window_seconds=60,
        ) is None


# --- Route surface -------------------------------------------------------------

def test_forecast_status_reports_unlimited_for_pro(client):
    _sign_in_as(client, "pro")
    data = client.get("/api/forecast/status").get_json()
    assert data["unlimited"] is True
    assert data["remaining"] is None


def test_forecast_status_reports_a_quota_for_free(client):
    _sign_in_as(client, "free")
    data = client.get("/api/forecast/status").get_json()
    assert data["unlimited"] is False
    assert isinstance(data["remaining"], int)


def test_there_is_no_route_that_grants_a_plan(app):
    """Plans are granted server-side only - no endpoint may set one.

    If a self-serve upgrade route is ever added it must go through payment,
    not through this gap; this test is the tripwire.
    """
    grant_routes = [
        str(rule) for rule in app.url_map.iter_rules()
        if "plan" in str(rule).lower() or "upgrade" in str(rule).lower()
    ]
    assert grant_routes == []
