"""Local JSON-file-backed sentiment history store.

Fallback for when Supabase (SUPABASE_URL / SUPABASE_SERVICE_KEY) is not
configured, so the sentiment-history timeline still persists across
requests and process restarts instead of silently doing nothing. Mirrors
the get_sentiment_history()/record_sentiment_snapshot() interface in
app.services.supabase_client (same argument names, same row shape, same
upsert-on-(symbol, day) semantics) so app/routes/api.py can call whichever
backend is available without branching on shape.

Thread-safe: a module-level threading.Lock serializes all reads/writes,
since this is invoked from a ThreadPoolExecutor (background sentiment
persistence) as well as the request thread. Every public function catches
its own exceptions and logs instead of raising, so a disk/permissions
problem here never surfaces as a 500 in the request path.

Storage is capped to bound file growth: at most _MAX_DAYS_PER_SYMBOL rows
per symbol (oldest dropped first) and at most _MAX_SYMBOLS distinct
symbols tracked (least-recently-updated symbol evicted first).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_MAX_DAYS_PER_SYMBOL = 90
_MAX_SYMBOLS = 500
_STORE_FILENAME = "sentiment_history.json"


def _instance_dir():
    """Directory for local persisted data, mirroring Flask's instance folder.

    Computed independently of any Flask app/request context, because this
    store is also called from a background ThreadPoolExecutor where no
    context is pushed. Defaults to <project_root>/instance - the same
    location Flask(__name__) in app/__init__.py would use.

    SENTIMENT_STORE_DIR overrides it. That matters on Cloud Run, where the
    container filesystem is ephemeral and per-instance: pointing this at a
    mounted volume is the only way the fallback survives a restart. See
    _warn_if_ephemeral() - the default there loses history on every deploy.
    """
    override = os.environ.get("SENTIMENT_STORE_DIR", "").strip()
    if override:
        return override
    app_package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../app
    project_root = os.path.dirname(app_package_dir)  # .../stock-screen
    return os.path.join(project_root, "instance")


_ephemeral_warned = False


def _warn_if_ephemeral():
    """Warn once when this store is the only thing holding sentiment history.

    Reaching this module at all means Supabase was unavailable. In a managed
    container that is a silent data-loss path: writes land on a scratch
    filesystem that is discarded on the next deploy or scale-down, and every
    instance keeps its own divergent copy. Worth one loud line rather than
    discovering it when the graph is empty.
    """
    global _ephemeral_warned
    if _ephemeral_warned:
        return
    _ephemeral_warned = True

    in_managed_container = bool(os.environ.get("K_SERVICE")) or \
        os.environ.get("FLASK_ENV", "").lower() == "production"
    if in_managed_container and not os.environ.get("SENTIMENT_STORE_DIR", "").strip():
        logger.warning(
            "Persisting sentiment history to the ephemeral container filesystem at %s. "
            "This is lost on redeploy/scale-down and is not shared between instances. "
            "Configure Supabase, or set SENTIMENT_STORE_DIR to a mounted volume.",
            _instance_dir(),
        )


def _store_path():
    return os.path.join(_instance_dir(), _STORE_FILENAME)


def _load_locked():
    """Load the whole store from disk. Caller must hold _lock."""
    path = _store_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.error("Failed to read local sentiment store at %s", path, exc_info=True)
        return {}


def _save_locked(data):
    """Write the whole store to disk atomically. Caller must hold _lock."""
    directory = _instance_dir()
    path = _store_path()
    try:
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp_path, path)
    except Exception:
        logger.error("Failed to write local sentiment store at %s", path, exc_info=True)


def _evict_oldest_symbol_locked(data, *, keep):
    """Drop the least-recently-updated symbol (other than `keep`).

    Caller must hold _lock. Keeps total tracked symbols bounded.
    """
    def _last_updated(sym):
        rows = data.get(sym) or []
        return max((row.get("updated_at") or "" for row in rows), default="")

    candidates = [sym for sym in data.keys() if sym != keep]
    if not candidates:
        return
    oldest = min(candidates, key=_last_updated)
    data.pop(oldest, None)


def get_sentiment_history(symbol, days=30):
    """Daily sentiment snapshots for a symbol, oldest first.

    Same shape as app.services.supabase_client.get_sentiment_history:
    a list of {day, score, label, confidence, news_count} dicts.
    """
    normalized = str(symbol or "").upper().strip()
    if not normalized:
        return []
    try:
        with _lock:
            data = _load_locked()
        rows = data.get(normalized) or []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        return sorted(
            (row for row in rows if str(row.get("day", "")) >= cutoff),
            key=lambda row: row.get("day", ""),
        )
    except Exception:
        logger.error("Local sentiment history read failed for %s", symbol, exc_info=True)
        return []


def record_sentiment_snapshot(
    *,
    symbol,
    day,
    score,
    label,
    confidence,
    news_count,
    updated_at=None,
):
    """Upsert today's aggregated sentiment, keyed on (symbol, day).

    Mirrors app.services.supabase_client.record_sentiment_snapshot's
    signature and behavior. score/confidence are always stored as floats
    (never int()), matching the numeric(6,4)/numeric(4,3) columns in the
    Supabase schema (supabase/migrations/20260611013000_add_sentiment_history.sql)
    that this local store stands in for. Returns True on success, False on
    any failure - never raises.
    """
    normalized = str(symbol or "").upper().strip()
    day_str = str(day or "").strip()
    if not normalized or not day_str:
        return False

    _warn_if_ephemeral()

    try:
        score_f = float(score)
        confidence_f = float(confidence or 0)
    except (TypeError, ValueError):
        logger.error(
            "Invalid local sentiment snapshot values for %s: score=%r confidence=%r",
            symbol, score, confidence,
        )
        return False

    row = {
        "day": day_str,
        "score": round(score_f, 4),
        "label": str(label or "Neutral"),
        "confidence": round(confidence_f, 3),
        "news_count": int(news_count or 0),
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }

    try:
        with _lock:
            data = _load_locked()
            rows = [r for r in (data.get(normalized) or []) if r.get("day") != day_str]
            rows.append(row)
            rows.sort(key=lambda r: r.get("day", ""))
            if len(rows) > _MAX_DAYS_PER_SYMBOL:
                rows = rows[-_MAX_DAYS_PER_SYMBOL:]
            data[normalized] = rows

            if len(data) > _MAX_SYMBOLS:
                _evict_oldest_symbol_locked(data, keep=normalized)

            _save_locked(data)
        return True
    except Exception:
        logger.error("Local sentiment history write failed for %s", symbol, exc_info=True)
        return False
