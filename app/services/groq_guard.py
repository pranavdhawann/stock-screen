"""Process-wide circuit breaker for Groq authentication failures.

GROQ_API_KEY is read once at import time, so a 401 (invalid/revoked key)
will fail identically for the lifetime of the process. Without this guard
every request still pays for the failing call (the SDK retries internally),
which adds seconds of latency on top of the broken feature. Services check
`groq_disabled()` before building a client and report failures through
`note_groq_error()`.
"""

import logging

logger = logging.getLogger(__name__)

_auth_failed = False


def groq_disabled() -> bool:
    return _auth_failed


def note_groq_error(exc) -> bool:
    """Record a Groq error; trips the breaker on auth failures.

    Returns True if the breaker is now tripped.
    """
    global _auth_failed
    status = getattr(exc, "status_code", None)
    if status == 401 or "invalid_api_key" in str(exc).lower():
        if not _auth_failed:
            logger.error(
                "GROQ_API_KEY rejected (401). Disabling Groq for this process; "
                "AI features fall back to built-in analyzers. Rotate the key and restart."
            )
        _auth_failed = True
    return _auth_failed
