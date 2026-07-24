"""Accounts and watchlists.

Server-side auth: passwords are PBKDF2-hashed with Werkzeug and stored in
Supabase through the service role; the browser only ever holds a signed
Flask session cookie. Everything degrades to a clear 503 when Supabase
isn't configured, matching the rest of the app's optional-Supabase model.
"""

from functools import wraps

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.services.http_limits import consume_limit
from app.services.supabase_client import DuplicateEmailError
from app.services.validation import is_supported_symbol, is_valid_email

import logging

logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__, url_prefix='/api')

SIGNUP_LIMIT = 5
SIGNUP_WINDOW_SECONDS = 60 * 60
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 15 * 60
WATCHLIST_MUTATION_LIMIT = 60
WATCHLIST_MUTATION_WINDOW_SECONDS = 60 * 60
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
# /api/quotes serves at most 16 symbols per request, so a larger list could
# never be priced in one call anyway.
WATCHLIST_MAX_SYMBOLS = 16

# Precomputed so login always pays the cost of a hash comparison, even when
# the email doesn't match any account - otherwise an unknown-user response
# returns near-instantly while a known-user wrong-password response pays
# for check_password_hash, letting an attacker enumerate valid emails by
# timing alone.
_DUMMY_PASSWORD_HASH = generate_password_hash("stock-screen-dummy-password-for-timing-parity")


def _sbc():
    """Supabase helper module, or None when unavailable."""
    try:
        from app.services import supabase_client
        return supabase_client if supabase_client.is_available() else None
    except ImportError:
        return None


def _accounts_unavailable():
    return jsonify({'error': 'Accounts are unavailable right now.'}), 503


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _credentials(data):
    """Validate and normalize an email/password payload.

    Returns (email, password, error_response).
    """
    email = str(data.get('email') or '').strip().lower()
    password = str(data.get('password') or '')
    if not is_valid_email(email):
        return None, None, (jsonify({'error': 'Please enter a valid email address.'}), 400)
    if not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        return None, None, (
            jsonify({'error': f'Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters.'}),
            400,
        )
    return email, password, None


def _login_session(user):
    session.clear()
    session['uid'] = str(user['id'])
    session['email'] = user['email']
    # Cached on the (signed, server-secret) session so the rate limiters can
    # check entitlement without a Supabase round-trip per request. /auth/me
    # refreshes it, which the front end calls on every page load.
    session['plan'] = user.get('plan') or 'free'
    session.permanent = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('uid'):
            return jsonify({'error': 'Sign in required.'}), 401
        return view(*args, **kwargs)
    return wrapped


@account_bp.route('/auth/signup', methods=['POST'])
def signup():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    email, password, error = _credentials(data)
    if error:
        return error

    limited = consume_limit("auth_signup", SIGNUP_LIMIT, SIGNUP_WINDOW_SECONDS)
    if limited:
        return limited

    sbc = _sbc()
    if not sbc:
        return _accounts_unavailable()

    # No check-then-insert: the app_users.email unique constraint is the
    # authority, so two concurrent signups for the same address can't both
    # pass a prior SELECT and leave the loser with an opaque 502.
    try:
        user = sbc.create_user(email, generate_password_hash(password))
    except DuplicateEmailError:
        return jsonify({'error': 'An account with that email already exists.'}), 409
    if not user:
        return jsonify({'error': 'Unable to create the account right now.'}), 502

    _login_session(user)
    return jsonify({'status': 'ok', 'email': user['email'], 'plan': session['plan']})


@account_bp.route('/auth/login', methods=['POST'])
def login():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    email, password, error = _credentials(data)
    if error:
        return error

    limited = consume_limit("auth_login", LOGIN_LIMIT, LOGIN_WINDOW_SECONDS)
    if limited:
        return limited

    sbc = _sbc()
    if not sbc:
        return _accounts_unavailable()

    user = sbc.get_user_by_email(email)
    # Always run a real hash comparison, even for an unknown email, so the
    # response time doesn't leak whether the account exists.
    password_hash = (user or {}).get('password_hash') or _DUMMY_PASSWORD_HASH
    password_ok = check_password_hash(password_hash, password)
    if not user or not password_ok:
        return jsonify({'error': 'Incorrect email or password.'}), 401

    _login_session(user)
    sbc.touch_user_login(user['id'])
    return jsonify({'status': 'ok', 'email': user['email'], 'plan': session['plan']})


@account_bp.route('/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})


@account_bp.route('/auth/me')
def me():
    if not session.get('uid'):
        return jsonify({'authenticated': False})

    # Re-read the plan here (the one place the front end hits on every page
    # load) so a grant or revocation takes effect without a re-login, while
    # the hot request paths keep reading the cached session value.
    sbc = _sbc()
    if sbc:
        session['plan'] = sbc.get_user_plan(session['uid'])

    return jsonify({
        'authenticated': True,
        'email': session.get('email'),
        'plan': session.get('plan') or 'free',
    })


@account_bp.route('/watchlist')
@login_required
def get_watchlist():
    sbc = _sbc()
    if not sbc:
        return _accounts_unavailable()
    items = sbc.get_watchlist(session['uid'])
    return jsonify({
        'symbols': [item['symbol'] for item in items],
        'max_symbols': WATCHLIST_MAX_SYMBOLS,
    })


@account_bp.route('/watchlist', methods=['POST'])
@login_required
def add_to_watchlist():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    symbol = str(data.get('symbol') or '').strip().upper()
    if not is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    # Distributed: the handler already makes Supabase round-trips to read and
    # write the watchlist, so enforcing the limit there too costs nothing
    # extra - and an in-memory limit would be per-instance, i.e. N x the cap
    # once Cloud Run scales out.
    limited = consume_limit(
        "watchlist", WATCHLIST_MUTATION_LIMIT, WATCHLIST_MUTATION_WINDOW_SECONDS
    )
    if limited:
        return limited

    sbc = _sbc()
    if not sbc:
        return _accounts_unavailable()

    current = [item['symbol'] for item in sbc.get_watchlist(session['uid'])]
    if symbol not in current and len(current) >= WATCHLIST_MAX_SYMBOLS:
        return jsonify({'error': f'Watchlist is full ({WATCHLIST_MAX_SYMBOLS} symbols max).'}), 400

    if not sbc.add_watchlist_symbol(session['uid'], symbol):
        return jsonify({'error': 'Unable to update the watchlist right now.'}), 502

    if symbol not in current:
        current.append(symbol)
    return jsonify({'status': 'ok', 'symbols': current})


@account_bp.route('/watchlist/<symbol>', methods=['DELETE'])
@login_required
def remove_from_watchlist(symbol):
    normalized = str(symbol or '').strip().upper()
    if not is_supported_symbol(normalized):
        return jsonify({'error': 'Unsupported symbol'}), 400

    # Distributed: the handler already makes Supabase round-trips to read and
    # write the watchlist, so enforcing the limit there too costs nothing
    # extra - and an in-memory limit would be per-instance, i.e. N x the cap
    # once Cloud Run scales out.
    limited = consume_limit(
        "watchlist", WATCHLIST_MUTATION_LIMIT, WATCHLIST_MUTATION_WINDOW_SECONDS
    )
    if limited:
        return limited

    sbc = _sbc()
    if not sbc:
        return _accounts_unavailable()

    if not sbc.remove_watchlist_symbol(session['uid'], normalized):
        return jsonify({'error': 'Unable to update the watchlist right now.'}), 502

    symbols = [item['symbol'] for item in sbc.get_watchlist(session['uid'])]
    return jsonify({'status': 'ok', 'symbols': symbols})
