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


# Read-only endpoints whose paths mention plans but cannot change one.
# Anything else matching the tripwire below is a bug, not an entry to add.
_PLAN_SAFE_ROUTES = {"/api/pro/plans"}


def test_there_is_no_route_that_grants_a_plan(app):
    """Plans are granted server-side only - no endpoint may set one.

    If a self-serve upgrade route is ever added it must go through payment,
    not through this gap; this test is the tripwire.
    """
    grant_routes = [
        str(rule) for rule in app.url_map.iter_rules()
        if ("plan" in str(rule).lower() or "upgrade" in str(rule).lower())
        and str(rule) not in _PLAN_SAFE_ROUTES
    ]
    assert grant_routes == []


def test_the_plan_catalogue_is_read_only(app):
    """/api/pro/plans lists prices; it must never accept a write."""
    rule = next(r for r in app.url_map.iter_rules() if str(r) == "/api/pro/plans")

    assert rule.methods & {"POST", "PUT", "PATCH", "DELETE"} == set()


def test_requesting_a_payment_link_does_not_change_a_plan(client, monkeypatch):
    """The purchase flow records intent only - entitlement still comes later."""
    from app.routes import api as api_routes
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)

    recorded = []

    class _StubSupabase:
        @staticmethod
        def add_pro_payment_request(email, plan):
            recorded.append((email, plan))
            return "added"

        @staticmethod
        def set_user_plan(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the payment-link route must not grant a plan")

    monkeypatch.setattr(api_routes, "_get_supabase_client", lambda: _StubSupabase)

    _sign_in_as(client, "free")
    response = client.post(
        "/api/pro/payment-link",
        json={"email": "buyer@example.com", "plan": "pro_monthly"},
    )

    assert response.status_code == 200
    assert recorded == [("buyer@example.com", "pro_monthly")]
    with client.session_transaction() as session:
        assert session["plan"] == "free"


def test_payment_link_rejects_an_unknown_plan(client, monkeypatch):
    from app.routes import api as api_routes
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    monkeypatch.setattr(api_routes, "_get_supabase_client", lambda: None)

    response = client.post(
        "/api/pro/payment-link",
        json={"email": "buyer@example.com", "plan": "pro_free_forever"},
    )

    assert response.status_code == 400
