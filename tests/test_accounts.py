"""Accounts and watchlist endpoint behavior with a faked Supabase layer."""

import pytest
from werkzeug.security import generate_password_hash


class FakeStore:
    """Stands in for app.services.supabase_client."""

    def __init__(self):
        self.users = {}
        self.watchlists = {}
        self.next_id = 1

    def is_available(self):
        return True

    def get_user_by_email(self, email):
        return self.users.get(email.strip().lower())

    def create_user(self, email, password_hash):
        email = email.strip().lower()
        if email in self.users:
            return None
        user = {"id": f"user-{self.next_id}", "email": email, "password_hash": password_hash}
        self.next_id += 1
        self.users[email] = user
        return user

    def touch_user_login(self, user_id):
        pass

    def get_watchlist(self, user_id):
        return [{"symbol": s} for s in self.watchlists.get(user_id, [])]

    def add_watchlist_symbol(self, user_id, symbol):
        items = self.watchlists.setdefault(user_id, [])
        if symbol not in items:
            items.append(symbol)
        return True

    def remove_watchlist_symbol(self, user_id, symbol):
        items = self.watchlists.get(user_id, [])
        if symbol in items:
            items.remove(symbol)
        return True


@pytest.fixture()
def client_and_store(monkeypatch):
    from app import create_app
    from app.routes import account
    from app.services import rate_limit

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DISABLE_CACHE_WARMUP", "1")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    rate_limit._events.clear()

    store = FakeStore()
    monkeypatch.setattr(account, "_sbc", lambda: store)

    app = create_app()
    app.testing = True
    return app.test_client(), store


def _signup(client, email="user@example.com", password="hunter2secure"):
    return client.post("/api/auth/signup", json={"email": email, "password": password})


def test_signup_creates_account_and_session(client_and_store):
    client, store = client_and_store

    response = _signup(client)
    assert response.status_code == 200
    assert response.get_json()["email"] == "user@example.com"

    me = client.get("/api/auth/me").get_json()
    assert me["authenticated"] is True
    assert me["email"] == "user@example.com"

    # Password is stored hashed, never plain.
    stored = store.users["user@example.com"]["password_hash"]
    assert "hunter2secure" not in stored


def test_signup_rejects_duplicates_and_weak_input(client_and_store):
    client, _ = client_and_store

    assert _signup(client).status_code == 200
    assert _signup(client).status_code == 409
    assert _signup(client, email="not-an-email").status_code == 400
    assert _signup(client, email="ok@example.com", password="short").status_code == 400


def test_login_verifies_password_and_logout_clears_session(client_and_store):
    client, store = client_and_store
    store.create_user("user@example.com", generate_password_hash("hunter2secure"))

    bad = client.post("/api/auth/login", json={"email": "user@example.com", "password": "wrongpassword"})
    assert bad.status_code == 401

    good = client.post("/api/auth/login", json={"email": "User@Example.com", "password": "hunter2secure"})
    assert good.status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").get_json()["authenticated"] is False


def test_watchlist_requires_sign_in(client_and_store):
    client, _ = client_and_store

    assert client.get("/api/watchlist").status_code == 401
    assert client.post("/api/watchlist", json={"symbol": "AAPL"}).status_code == 401
    assert client.delete("/api/watchlist/AAPL").status_code == 401


def test_watchlist_add_list_remove_roundtrip(client_and_store):
    client, _ = client_and_store
    _signup(client)

    assert client.post("/api/watchlist", json={"symbol": "aapl"}).status_code == 200
    assert client.post("/api/watchlist", json={"symbol": "TCS"}).status_code == 200
    # Unsupported symbols never reach the store.
    assert client.post("/api/watchlist", json={"symbol": "../etc"}).status_code == 400

    listed = client.get("/api/watchlist").get_json()
    assert listed["symbols"] == ["AAPL", "TCS"]

    assert client.delete("/api/watchlist/AAPL").status_code == 200
    assert client.get("/api/watchlist").get_json()["symbols"] == ["TCS"]


def test_watchlist_enforces_symbol_cap(client_and_store):
    client, store = client_and_store
    _signup(client)

    from app.routes.account import WATCHLIST_MAX_SYMBOLS
    from app.config import STOCK_DIRECTORY

    symbols = [s["symbol"] for s in STOCK_DIRECTORY][: WATCHLIST_MAX_SYMBOLS + 1]
    for symbol in symbols[:WATCHLIST_MAX_SYMBOLS]:
        assert client.post("/api/watchlist", json={"symbol": symbol}).status_code == 200

    overflow = client.post("/api/watchlist", json={"symbol": symbols[-1]})
    assert overflow.status_code == 400
    # Re-adding an existing symbol is still fine at the cap.
    assert client.post("/api/watchlist", json={"symbol": symbols[0]}).status_code == 200


def test_accounts_return_503_when_supabase_missing(monkeypatch):
    from app import create_app
    from app.routes import account
    from app.services import rate_limit

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DISABLE_CACHE_WARMUP", "1")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    rate_limit._events.clear()
    monkeypatch.setattr(account, "_sbc", lambda: None)

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = _signup(client)
    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"].lower()
