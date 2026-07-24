"""Tests for the paid-tier waitlist (/api/waitlist -> public.waitlist)."""
import pytest


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    from app.services import rate_limit

    rate_limit._events.clear()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    return create_app().test_client()


@pytest.fixture
def fake_supabase(monkeypatch):
    """Stand in for app.services.supabase_client with a recording waitlist."""
    from app.routes import api

    class FakeClient:
        def __init__(self):
            self.emails = []
            self.outcome = "added"

        def add_waitlist_email(self, email):
            self.emails.append(email)
            return self.outcome

    fake = FakeClient()
    monkeypatch.setattr(api, "_get_supabase_client", lambda: fake)
    return fake


def test_valid_email_is_recorded_lowercased(client, fake_supabase):
    resp = client.post("/api/waitlist", json={"email": "  Investor@Example.COM  "})

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    assert fake_supabase.emails == ["investor@example.com"]


def test_duplicate_is_indistinguishable_from_a_new_signup(client, fake_supabase):
    """Otherwise the endpoint becomes an oracle for who is on the waitlist."""
    first = client.post("/api/waitlist", json={"email": "a@example.com"})

    fake_supabase.outcome = "duplicate"
    second = client.post("/api/waitlist", json={"email": "a@example.com"})

    assert first.status_code == second.status_code == 200
    assert first.get_json() == second.get_json()


def test_invalid_emails_are_rejected_without_touching_supabase(client, fake_supabase):
    for bad in ["", "not-an-email", "no@domain", "a@b.c" + "x" * 300, "two@@at.com"]:
        resp = client.post("/api/waitlist", json={"email": bad})
        assert resp.status_code == 400, bad

    assert fake_supabase.emails == []


def test_honeypot_submissions_are_silently_dropped(client, fake_supabase):
    resp = client.post("/api/waitlist", json={"email": "bot@example.com", "website": "spam"})

    assert resp.status_code == 200          # bots must not learn they were caught
    assert fake_supabase.emails == []


def test_waitlist_reports_unavailable_rather_than_500(client, monkeypatch):
    """No Supabase configured must degrade to a clear 503, not a crash."""
    from app.routes import api

    monkeypatch.setattr(api, "_get_supabase_client", lambda: None)
    resp = client.post("/api/waitlist", json={"email": "x@example.com"})

    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_waitlist_is_rate_limited(client, fake_supabase):
    from app.routes.api import WAITLIST_LIMIT

    codes = [
        client.post("/api/waitlist", json={"email": f"user{i}@example.com"}).status_code
        for i in range(WAITLIST_LIMIT + 2)
    ]

    assert codes[:WAITLIST_LIMIT] == [200] * WAITLIST_LIMIT
    assert codes[WAITLIST_LIMIT:] == [429, 429]


def test_add_waitlist_email_maps_unique_violation_to_duplicate(monkeypatch):
    """The DB constraint, not a prior SELECT, is what detects a repeat signup."""
    from app.services import supabase_client

    class Boom:
        def table(self, _name):
            return self

        def insert(self, _row):
            return self

        def execute(self):
            raise Exception('duplicate key value violates unique constraint (23505)')

    monkeypatch.setattr(supabase_client, "_get_client", lambda: Boom())
    assert supabase_client.add_waitlist_email("dup@example.com") == "duplicate"


def test_add_waitlist_email_without_supabase_is_unavailable(monkeypatch):
    from app.services import supabase_client

    monkeypatch.setattr(supabase_client, "_get_client", lambda: None)
    assert supabase_client.add_waitlist_email("x@example.com") == "unavailable"
