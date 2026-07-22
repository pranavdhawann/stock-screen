"""Regression tests for the audit fixes:

1. Rate-limit client identity (X-Forwarded-For parsed from the right, not
   spoofable by a client-supplied header) -
   app/services/http_limits.py::client_key and
   app/config.py::TRUSTED_PROXY_HOPS.
2. The in-memory rate-limit map is bounded via a round-robin sweep instead
   of growing forever - app/services/rate_limit.py.
3. Sentiment-history persistence runs on a bounded ThreadPoolExecutor
   instead of spawning a raw thread per request - app/routes/api.py.
4. Login always performs a password-hash comparison, even for an unknown
   email, so response timing doesn't leak account existence -
   app/routes/account.py.
5. Symbol/email validation lives in app/services/validation.py and the
   request-scoped rate-limit glue in app/services/http_limits.py, both
   shared by the two blueprints instead of one importing the other's
   private helpers.
"""

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ── (1) X-Forwarded-For parsed from the right ──────────────────────────


def test_client_key_ignores_forwarded_header_when_proxy_trust_disabled(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", False)

    app = create_app()
    with app.test_request_context(
        headers={"X-Forwarded-For": "1.2.3.4"},
        environ_base={"REMOTE_ADDR": "10.0.0.9"},
    ):
        assert http_limits.client_key() == "10.0.0.9"


def test_client_key_selects_last_hop_when_trusted(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 1)

    app = create_app()
    with app.test_request_context(headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}):
        # 10.0.0.1 is the entry Cloud Run itself appends; 203.0.113.5 is
        # whatever the client claimed and must NOT be trusted.
        assert http_limits.client_key() == "10.0.0.1"


def test_client_key_is_not_spoofable_via_forwarded_header(monkeypatch):
    """A client that changes only the leftmost (client-controlled) entry of
    X-Forwarded-For must not be able to change its derived rate-limit
    identity - that would let a single attacker bypass the limiter by
    sending a fresh random value on every request.
    """
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 1)

    app = create_app()
    with app.test_request_context(headers={"X-Forwarded-For": "attacker-spoof-1, 10.0.0.1"}):
        key_a = http_limits.client_key()
    with app.test_request_context(headers={"X-Forwarded-For": "attacker-spoof-2, 10.0.0.1"}):
        key_b = http_limits.client_key()

    assert key_a == key_b == "10.0.0.1"


def test_client_key_hops_two_selects_second_from_right(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 2)

    app = create_app()
    with app.test_request_context(headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"}):
        assert http_limits.client_key() == "2.2.2.2"


def test_client_key_falls_back_to_remote_addr_when_header_missing(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 1)

    app = create_app()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "192.168.1.1"}):
        assert http_limits.client_key() == "192.168.1.1"


def test_client_key_falls_back_to_remote_addr_when_hops_out_of_range(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 5)

    app = create_app()
    with app.test_request_context(
        headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"},
        environ_base={"REMOTE_ADDR": "203.0.113.9"},
    ):
        assert http_limits.client_key() == "203.0.113.9"


def test_client_key_falls_back_to_remote_addr_on_malformed_header(monkeypatch):
    from app import create_app
    from app.services import http_limits

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(http_limits, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(http_limits, "TRUSTED_PROXY_HOPS", 1)

    app = create_app()
    with app.test_request_context(
        headers={"X-Forwarded-For": " , , "},
        environ_base={"REMOTE_ADDR": "198.51.100.2"},
    ):
        assert http_limits.client_key() == "198.51.100.2"


def test_config_parses_trusted_proxy_hops_with_fallback(monkeypatch):
    from app import config

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "4")
    assert config._parse_trusted_proxy_hops() == 4

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "not-a-number")
    assert config._parse_trusted_proxy_hops() == 1

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "-3")
    assert config._parse_trusted_proxy_hops() == 1

    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert config._parse_trusted_proxy_hops() == 1


def test_deploy_workflow_enables_trust_proxy_headers():
    deploy = _read(".github/workflows/deploy.yml")
    assert "TRUST_PROXY_HEADERS=true" in deploy


# ── (2) Bounded rate-limit map sweep ───────────────────────────────────


def test_expired_rate_limit_keys_are_evicted_via_bounded_sweep():
    from app.services import rate_limit

    rate_limit._events.clear()
    rate_limit._sweep_order.clear()

    key_count = 50
    tiny_window = 0.05
    for i in range(key_count):
        result = rate_limit.check_limit(
            f"sweep-bucket-{i}", "same-client", limit=100, window_seconds=tiny_window, distributed=False
        )
        assert result.allowed is True

    assert len(rate_limit._events) == key_count

    # Let every entry's single event age out of its window.
    time.sleep(tiny_window + 0.1)

    # One status() call only sweeps a small, bounded batch - the map must
    # not be fully drained in a single call (proves the cost is O(small),
    # not O(map size)).
    rate_limit.status("sweep-trigger", "same-client", limit=1, window_seconds=tiny_window)
    assert 0 < len(rate_limit._events) < key_count

    # Enough additional calls must fully drain the now-expired entries via
    # the round-robin sweep, without anyone ever querying them directly.
    for _ in range(20):
        rate_limit.status("sweep-trigger", "same-client", limit=1, window_seconds=tiny_window)

    assert len(rate_limit._events) == 0

    rate_limit._events.clear()
    rate_limit._sweep_order.clear()


def test_rate_limit_sweep_batch_size_is_small():
    from app.services import rate_limit

    # The whole point of the fix is that a single request never has to walk
    # the whole map - guard the batch size stays a small constant.
    assert rate_limit._SWEEP_BATCH_SIZE <= 32
    assert rate_limit._SWEEP_SIZE_THRESHOLD >= rate_limit._SWEEP_BATCH_SIZE


# ── (3) Bounded executor for sentiment-history persistence ────────────


def test_sentiment_persistence_does_not_spawn_raw_threads():
    api_src = _read("app/routes/api.py")
    assert "from threading import Thread" not in api_src
    assert "threading.Thread" not in api_src
    assert "Thread(" not in api_src


def test_persist_sentiment_snapshot_uses_bounded_executor():
    from concurrent.futures import ThreadPoolExecutor

    from app.routes import api

    assert isinstance(api._SENTIMENT_PERSIST_EXECUTOR, ThreadPoolExecutor)
    assert api._SENTIMENT_PERSIST_EXECUTOR._max_workers <= 4

    calls = []

    class FakeSbc:
        @staticmethod
        def record_sentiment_snapshot(**kwargs):
            calls.append(kwargs)

    api._persist_sentiment_snapshot(
        FakeSbc(),
        "AAPL",
        [{"sentiment": "Positive", "confidence": 0.5, "published": 0}],
        {"overall_sentiment": "Positive", "confidence": 0.5},
    )

    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.02)

    assert len(calls) == 1
    assert calls[0]["symbol"] == "AAPL"


# ── (4) Login timing parity for unknown emails ─────────────────────────


def test_login_hashes_password_even_for_unknown_email(monkeypatch):
    from app import create_app
    from app.routes import account as account_module
    from app.services import rate_limit

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DISABLE_CACHE_WARMUP", "1")
    monkeypatch.setattr(rate_limit, "_get_supabase_client", lambda: None)
    rate_limit._events.clear()

    calls = []
    original_check = account_module.check_password_hash

    def spy_check(pwhash, password):
        calls.append(pwhash)
        return original_check(pwhash, password)

    monkeypatch.setattr(account_module, "check_password_hash", spy_check)

    class EmptyStore:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def get_user_by_email(_email):
            return None

    monkeypatch.setattr(account_module, "_sbc", lambda: EmptyStore())

    app = create_app()
    app.testing = True
    response = app.test_client().post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "somepassword123"},
    )

    assert response.status_code == 401
    assert len(calls) == 1
    assert calls[0] == account_module._DUMMY_PASSWORD_HASH


# ── (5) Shared validation module ───────────────────────────────────────


def test_validation_helpers_live_in_shared_service_module():
    from app.services import validation

    assert validation.is_supported_symbol("AAPL") is True
    assert validation.is_supported_symbol("../etc/passwd") is False
    assert validation.is_valid_email("user@example.com") is True
    assert validation.is_valid_email("not-an-email") is False


def test_api_keeps_thin_is_supported_symbol_wrapper_for_existing_regression_test():
    # tests/test_audit_regressions.py greps for these literal strings and
    # must not be edited, so api.py must retain a real `def
    # _is_supported_symbol` even though the logic now lives in
    # app.services.validation.
    api_src = _read("app/routes/api.py")
    assert "def _is_supported_symbol" in api_src
    assert "if not _is_supported_symbol(symbol):" in api_src


def test_account_module_no_longer_imports_private_helpers_from_api():
    account_src = _read("app/routes/account.py")
    assert "_is_supported_symbol" not in account_src
    assert "_is_valid_email" not in account_src
    assert "from app.services.validation import" in account_src


def test_account_module_imports_nothing_from_the_api_blueprint():
    # The request-scoped rate-limit glue moved to app/services/http_limits.py
    # alongside the validators, so account.py no longer reaches into the api
    # blueprint at all - the two blueprints are now siblings over shared
    # services rather than one depending on the other's private namespace.
    account_src = _read("app/routes/account.py")
    assert "from app.routes.api import" not in account_src
    assert "app.routes.api" not in account_src
    assert "from app.services.http_limits import consume_limit" in account_src


def test_api_blueprint_uses_shared_http_limits_module():
    api_src = _read("app/routes/api.py")
    assert "from app.services.http_limits import" in api_src
    # The request-identity logic must live in exactly one place.
    assert "def _client_key" not in api_src
    assert "X-Forwarded-For" not in api_src
