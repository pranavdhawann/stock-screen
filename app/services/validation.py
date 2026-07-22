"""Shared request-input validation helpers.

Symbol and email validation used to live as private helpers inside
app/routes/api.py, and app/routes/account.py imported them directly
(including an in-function import of `_is_valid_email` to dodge a circular
import). Both blueprints now depend on this module instead of reaching into
each other's private namespace.
"""

import re

from app.config import MARKET_INDICES, STOCK_DIRECTORY

_SUPPORTED_SYMBOLS = {stock["symbol"].upper() for stock in STOCK_DIRECTORY}
_SUPPORTED_MARKET_SYMBOLS = {
    market["symbol"].upper()
    for markets in MARKET_INDICES.values()
    for market in markets
}

SYMBOL_RE = re.compile(r"^[A-Z0-9.^-]{1,16}$")
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_supported_symbol(symbol, *, include_market_indices=False):
    normalized = str(symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(normalized):
        return False
    if normalized in _SUPPORTED_SYMBOLS:
        return True
    return include_market_indices and normalized in _SUPPORTED_MARKET_SYMBOLS


def is_valid_email(email, max_length=254):
    return bool(email and len(email) <= max_length and EMAIL_RE.fullmatch(email))
