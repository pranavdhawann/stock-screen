from flask import Blueprint, request, jsonify
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
from app.config import (
    STOCK_DIRECTORY, INDIAN_STOCKS, MARKET_INDICES,
    get_company_name, get_currency, is_indian_stock,
    EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY,
    PRO_PLANS, PRO_PLANS_BY_CODE,
)
from app.services import (
    bse_filings, stock_data, sentiment, insights, sec_edgar,
    news_aggregator, forecasting, indicators, validation, sentiment_store,
)
from app.services.cache import market_news_cache, get_cached, set_cached
from app.services.executors import market_data_executor
from app.services.http_limits import (
    client_key as _client_key,
    consume_limit as _consume_limit,
    consume_tiered_limit as _consume_tiered_limit,
    has_unlimited_access as _has_unlimited_access,
)
from app.services.rate_limit import status as rate_limit_status
import requests as http_requests
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')

FORECAST_LIMIT = 1
FORECAST_WINDOW_SECONDS = 30 * 24 * 60 * 60
AI_LIMIT = 20
AI_WINDOW_SECONDS = 60 * 60
CONTACT_LIMIT = 5
CONTACT_WINDOW_SECONDS = 60 * 60
CONTACT_NAME_MAX_LENGTH = 120
CONTACT_EMAIL_MAX_LENGTH = 254
CONTACT_MESSAGE_MAX_LENGTH = 3000
PUBLIC_NEWS_LIMIT = 60
PUBLIC_NEWS_WINDOW_SECONDS = 60 * 60
# Local anti-hammer window checked before the durable hourly quota above.
# See http_limits.consume_tiered_limit for why the public news endpoints need
# both a per-instance burst guard and a cross-instance quota.
PUBLIC_NEWS_BURST_LIMIT = 15
PUBLIC_NEWS_BURST_WINDOW_SECONDS = 60
WAITLIST_LIMIT = 5
WAITLIST_WINDOW_SECONDS = 60 * 60
WAITLIST_EMAIL_MAX_LENGTH = 254

# Deliberately identical for a new address and one already on the list - see
# supabase_client.add_waitlist_email() on why the two must not be told apart.
WAITLIST_CONFIRMATION = "You're on the list. We'll email you when paid-tier access opens."

PRO_REQUEST_LIMIT = 5
PRO_REQUEST_WINDOW_SECONDS = 60 * 60
# Shown when the plan has no hosted checkout URL configured yet. The request
# is still recorded either way, so the user is never left with nothing.
PRO_REQUEST_PENDING_MESSAGE = (
    "Request received. We'll email your payment link shortly."
)

# How far back the sentiment graph asks for stored daily snapshots. Nothing
# prunes public.sentiment_history, so this is purely a read window.
#
# fetch_stock_data's default '30d' period is 30 *trading* days, which spans
# roughly 44 calendar days - so a 30-calendar-day window would leave the
# oldest couple of weeks of the chart unable to show stored scores. 60 covers
# the whole chart with margin and is well above the 30-day floor we promise.
SENTIMENT_HISTORY_DAYS = 60

_VALID_MARKETS = {"US", "IN"}
_SEC_FILING_TYPES = ("10-K", "10-Q", "8-K")
_INDIAN_FILING_TYPES = ("Annual Report", "Financial Results", "Corporate Announcement", "Shareholding Pattern")
_MAX_OVERVIEW_FILINGS = 25

# Bounded background worker for sentiment-history writes so a burst of
# requests can't spawn an unbounded number of raw threads (mirrors the
# cache-persist pool in app/services/cache.py).
_SENTIMENT_PERSIST_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sentiment-persist")

# Logged once (not per-request) the first time Supabase is unavailable and
# analyze_sentiment falls back to the local sentiment_store, so the log
# stays useful instead of repeating on every request.
_supabase_unavailable_warned = False
_supabase_unavailable_lock = threading.Lock()


def _warn_supabase_unavailable_once():
    global _supabase_unavailable_warned
    with _supabase_unavailable_lock:
        if _supabase_unavailable_warned:
            return
        _supabase_unavailable_warned = True
    logger.warning(
        "Supabase is unavailable (SUPABASE_URL/SUPABASE_SERVICE_KEY not configured or "
        "unreachable); falling back to the local sentiment_store for sentiment history."
    )


def _is_supported_symbol(symbol, *, include_market_indices=False):
    """Thin wrapper kept for in-module call sites and backward compatibility.

    The real implementation lives in app.services.validation, shared with
    app.routes.account so neither blueprint reaches into the other's
    private helpers.
    """
    return validation.is_supported_symbol(symbol, include_market_indices=include_market_indices)


def _generic_error(message="Request failed. Please try again."):
    return jsonify({"error": message})


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _short_text(value, limit=160):
    return str(value or "").strip()[:limit]


def _symbol_text(value):
    return str(value or "").strip().upper()


def _is_valid_email(email, max_length=254):
    """Thin wrapper delegating to app.services.validation (see above)."""
    return validation.is_valid_email(email, max_length)


def _json_number(value, digits=2):
    try:
        number = round(float(value), digits)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _volume_liquidity_metrics(chart_data):
    volumes = []
    relative_volume = []
    dollar_volume = []
    volume_spike = []

    for idx, item in enumerate(chart_data or []):
        volume = int(item.get("volume") or 0)
        price = float(item.get("price") or item.get("close") or 0)
        window = chart_data[max(0, idx - 19):idx + 1]
        window_volumes = [int(row.get("volume") or 0) for row in window]
        avg_volume = sum(window_volumes) / len(window_volumes) if window_volumes else 0
        rel = volume / avg_volume if avg_volume else 0

        volumes.append(volume)
        relative_volume.append(_json_number(rel, 2))
        dollar_volume.append(_json_number(price * volume, 2))
        volume_spike.append(rel >= 2.0 if avg_volume else False)

    return {
        "volume": volumes,
        "relative_volume": relative_volume,
        "dollar_volume": dollar_volume,
        "volume_spike": volume_spike,
    }


def _timestamp_to_day(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1e12:
        number /= 1000
    return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()


def _news_sentiment_score(item):
    sentiment_label = str(item.get("sentiment") or "Neutral").lower()
    confidence = float(item.get("confidence") or 0)
    if sentiment_label in {"positive", "very positive", "bullish"}:
        return confidence
    if sentiment_label in {"negative", "very negative", "bearish"}:
        return -confidence
    if sentiment_label == "unknown":
        return None
    return 0.0


def _build_sentiment_timeline(analyzed_news, chart_data):
    by_day = defaultdict(list)
    for item in analyzed_news or []:
        day = _timestamp_to_day(item.get("published"))
        score = _news_sentiment_score(item)
        if day and score is not None:
            by_day[day].append(score)

    timeline = []
    for point in chart_data or []:
        day = _timestamp_to_day(point.get("date"))
        scores = by_day.get(day, [])
        score = sum(scores) / len(scores) if scores else 0.0
        timeline.append({
            "date": point.get("date"),
            "date_label": day,
            "score": round(score, 2),
            "headline_count": len(scores),
        })
    return timeline


def _day_to_epoch_ms(day_label):
    """UTC midnight of an ISO day as epoch milliseconds.

    chart_data points carry `date` in epoch ms (see stock_data.fetch_stock_data),
    and the front-end passes it straight to `new Date(...)`, so history-only
    points must use the same unit - seconds would render them in 1970.
    """
    try:
        parsed = datetime.strptime(str(day_label), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return int(parsed.timestamp() * 1000)


def _merge_sentiment_history(timeline, history_rows):
    """Fill timeline days that have no current headlines with stored history.

    Without this, any day older than the news lookback window renders as a
    flat 0 even though we analyzed it before.

    Only fills points that already exist, so the timeline stays 1:1 with
    chart_data - see _sentiment_divergence. Days the chart never covers are
    handled by _extend_timeline_with_history instead.
    """
    history_map = {str(row.get("day")): row for row in history_rows or []}
    for point in timeline or []:
        if point.get("headline_count"):
            continue
        hist = history_map.get(point.get("date_label"))
        if not hist:
            continue
        try:
            point["score"] = round(float(hist.get("score") or 0), 2)
        except (TypeError, ValueError):
            continue
        point["headline_count"] = int(hist.get("news_count") or 0)
        point["source"] = "history"
    return timeline


def _extend_timeline_with_history(timeline, history_rows):
    """Append stored days that the price chart never covers.

    _build_sentiment_timeline emits exactly one point per chart_data row, and
    fetch_stock_data's default '30d' period returns only ~21 *trading* days.
    A snapshot recorded on a weekend or holiday therefore had no point to land
    on and stayed invisible forever, even though Supabase retains
    sentiment_history indefinitely. Appending those days is what actually gets
    a full SENTIMENT_HISTORY_DAYS window onto the graph.

    Must run AFTER _sentiment_divergence, which walks timeline[idx] and
    chart_data[idx] in lockstep and needs that 1:1 alignment intact.
    """
    points = list(timeline or [])
    known = {point.get("date_label") for point in points}
    for row in history_rows or []:
        day = str(row.get("day") or "")
        if not day or day in known:
            continue
        stamp = _day_to_epoch_ms(day)
        if stamp is None:
            continue
        try:
            score = round(float(row.get("score") or 0), 2)
        except (TypeError, ValueError):
            continue
        known.add(day)
        points.append({
            "date": stamp,
            "date_label": day,
            "score": score,
            "headline_count": int(row.get("news_count") or 0),
            "source": "history",
        })
    points.sort(key=lambda point: point.get("date") or 0)
    return points


def _log_persist_result(symbol, future):
    """done_callback for the sentiment-persist executor.

    submit() swallowed any exception raised inside the worker thread until
    someone inspected the returned Future, so a persistence failure never
    surfaced anywhere. This makes it observable in the logs instead.
    """
    try:
        exc = future.exception()
    except Exception as callback_exc:  # pragma: no cover - defensive only
        logger.error("Sentiment persist callback failed for %s: %s", symbol, callback_exc, exc_info=True)
        return
    if exc is not None:
        logger.error("Sentiment snapshot persist failed for %s: %s", symbol, exc, exc_info=exc)
    elif future.result() is False:
        logger.warning("Sentiment snapshot persist returned failure for %s", symbol)


def _persist_sentiment_snapshot(history_backend, symbol, analyzed_news, overall):
    """Store today's aggregate score so it survives the cache TTL.

    `history_backend` is either app.services.supabase_client or
    app.services.sentiment_store - both expose the same
    record_sentiment_snapshot(**kwargs) -> bool signature.
    """
    scores = [
        score for score in (_news_sentiment_score(item) for item in analyzed_news)
        if score is not None
    ]
    if not scores:
        return
    snapshot = {
        "symbol": symbol,
        "day": datetime.now(timezone.utc).date().isoformat(),
        "score": sum(scores) / len(scores),
        "label": overall.get("overall_sentiment", "Neutral"),
        "confidence": float(overall.get("confidence") or 0),
        "news_count": len(scores),
    }
    future = _SENTIMENT_PERSIST_EXECUTOR.submit(history_backend.record_sentiment_snapshot, **snapshot)
    future.add_done_callback(lambda f: _log_persist_result(symbol, f))


def _sentiment_divergence(timeline, chart_data, window=14):
    """Correlation gap between recent price moves and sentiment.

    `timeline` must be the chart-aligned timeline from
    _build_sentiment_timeline: one point per chart_data row, in the same
    order, since the loop below reads timeline[idx] and chart_data[idx]
    together. A shorter timeline is unusable rather than an IndexError.
    """
    if len(timeline or []) < 3 or len(chart_data or []) < 3:
        return 0.0
    if len(timeline) < len(chart_data):
        logger.warning(
            "Sentiment timeline (%d points) is shorter than chart data (%d); "
            "skipping divergence.", len(timeline), len(chart_data),
        )
        return 0.0

    price_returns = []
    scores = []
    start = max(1, len(chart_data) - window)
    for idx in range(start, len(chart_data)):
        previous = float(chart_data[idx - 1].get("price") or 0)
        current = float(chart_data[idx].get("price") or 0)
        if previous:
            price_returns.append((current - previous) / previous)
            scores.append(float(timeline[idx].get("score") or 0))

    if len(price_returns) < 2:
        return 0.0
    avg_price = sum(price_returns) / len(price_returns)
    avg_score = sum(scores) / len(scores)
    price_delta = [value - avg_price for value in price_returns]
    score_delta = [value - avg_score for value in scores]
    denom = (sum(value * value for value in price_delta) * sum(value * value for value in score_delta)) ** 0.5
    if not denom:
        return 0.0
    correlation = sum(p * s for p, s in zip(price_delta, score_delta, strict=True)) / denom
    return round(-correlation, 3)


def _validate_overview_filings(filings, allowed_types):
    if not isinstance(filings, list):
        return None, "filings must be a list of filing objects"

    normalized = []
    for filing in filings[:_MAX_OVERVIEW_FILINGS]:
        if not isinstance(filing, dict):
            return None, "filings must be a list of filing objects"

        form = _short_text(filing.get("form"), 80)
        filing_date = _short_text(filing.get("filing_date"), 30)
        if not form or not filing_date:
            return None, "each filing must include form and filing_date"
        if form not in allowed_types:
            return None, "Unsupported filing type"

        normalized.append({
            "form": form,
            "filing_date": filing_date,
            "description": _short_text(filing.get("description"), 240),
            "url": _short_text(filing.get("url"), 500),
            "source": _short_text(filing.get("source"), 80),
        })

    return normalized, None


def _parse_filing_types(raw_types, allowed_types):
    if raw_types is None:
        return list(allowed_types), None
    selected = [item.strip() for item in str(raw_types or "").split(",") if item.strip()]
    if not selected:
        return None, "At least one filing type is required"
    if any(item not in allowed_types for item in selected):
        return None, "Unsupported filing type"
    return selected, None


def _get_supabase_client():
    """Return optional Supabase helper module, or None if not installed locally."""
    try:
        from app.services import supabase_client as sbc  # type: ignore
        return sbc
    except ImportError:
        logger.info("supabase_client not available; using non-cached local behavior.")
        return None


@api_bp.route('/stock_list')
def stock_list():
    market = request.args.get('market', '').upper()
    if market and market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400

    us_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] not in INDIAN_STOCKS]
    in_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] in INDIAN_STOCKS]

    # When a specific market is requested, only populate that market's list
    # but keep both keys present for backward compatibility with clients
    # that always read both.
    if market == 'US':
        in_stocks = []
    elif market == 'IN':
        us_stocks = []

    return jsonify({"US": us_stocks, "IN": in_stocks})


@api_bp.route('/news')
def get_news():
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400
    limited = _consume_tiered_limit(
        "public_news",
        burst_limit=PUBLIC_NEWS_BURST_LIMIT,
        burst_window_seconds=PUBLIC_NEWS_BURST_WINDOW_SECONDS,
        quota_limit=PUBLIC_NEWS_LIMIT,
        quota_window_seconds=PUBLIC_NEWS_WINDOW_SECONDS,
    )
    if limited:
        return limited
    try:
        company_name = get_company_name(symbol)
        # Always use aggregator - Google RSS and MarketWatch don't need API keys
        news_items = news_aggregator.aggregate_news(symbol, company_name)
        return jsonify({'symbol': symbol, 'news_items': news_items or []})
    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}")
        return _generic_error("Unable to fetch news right now."), 500


@api_bp.route('/chart_data')
def get_chart_data():
    symbol = request.args.get('symbol', '').upper()
    period = request.args.get('period', '30d')
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol, include_market_indices=True):
        return jsonify({'error': 'Unsupported symbol'}), 400
    if period not in ('30d', '1y', '5y'):
        return jsonify({'error': 'Invalid period. Use 30d, 1y, or 5y'}), 400
    try:
        sd = stock_data.fetch_stock_data(symbol, period=period)
        if not sd:
            return jsonify({'error': f'Unable to fetch chart data for {symbol}'}), 503
        liquidity = _volume_liquidity_metrics(sd['chart_data'])
        return jsonify({
            'symbol': symbol,
            'period': period,
            'chart_data': sd['chart_data'],
            **liquidity,
            'current_price': sd['current_price'],
            'price_change': sd['price_change'],
            'price_change_percent': sd['price_change_percent'],
            'currency': get_currency(symbol),
        })
    except Exception as e:
        logger.error(f"Error fetching chart data for {symbol}: {e}")
        return _generic_error("Unable to fetch chart data right now."), 500


@api_bp.route("/indicators/<ticker>")
def get_indicators(ticker):
    symbol = _symbol_text(ticker)
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    limited = _consume_limit("indicators", AI_LIMIT, AI_WINDOW_SECONDS)
    if limited:
        return limited

    try:
        history = stock_data.fetch_ohlcv_history(symbol, range_period="6mo", interval="1d")
        if history is None or history.empty:
            return jsonify({'error': f'Unable to fetch indicator data for {symbol}'}), 503
        payload = indicators.compute_indicators(history)
        return jsonify({
            "symbol": symbol,
            "currency": get_currency(symbol),
            **payload,
        })
    except Exception as e:
        logger.error("Indicator request failed for %s: %s", symbol, e)
        return _generic_error("Unable to compute indicators right now."), 500


@api_bp.route('/search_stocks')
def search_stocks():
    query = request.args.get('q', '').lower()
    market = request.args.get('market', '').upper()
    if market and market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400
    if not query:
        return jsonify([])

    results = []
    for stock in STOCK_DIRECTORY:
        if market == 'US' and stock['symbol'] in INDIAN_STOCKS:
            continue
        if market == 'IN' and stock['symbol'] not in INDIAN_STOCKS:
            continue
        if query in stock['symbol'].lower() or query in stock['name'].lower():
            results.append({
                'symbol': stock['symbol'],
                'name': stock['name'],
                'display': f"{stock['symbol']} - {stock['name']}",
            })
    return jsonify(results[:20])


@api_bp.route('/forecast', methods=['POST'])
def forecast_stock():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    symbol = _symbol_text(data.get('symbol'))
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    limited = _consume_limit("forecast", FORECAST_LIMIT, FORECAST_WINDOW_SECONDS)
    if limited:
        return limited

    try:
        result = forecasting.generate_forecast(symbol)
        result["usage"] = _forecast_usage()
        return jsonify(result)
    except ValueError as e:
        logger.error("Forecast request validation failed for %s: %s", symbol, e)
        return jsonify({'error': 'Unable to generate a forecast for that symbol.'}), 400
    except Exception as e:
        logger.error("Forecast request failed for %s: %s", symbol, e)
        return jsonify({'error': 'Forecast generation failed. Please try again.'}), 500


def _forecast_usage():
    """Remaining forecast quota, or an unlimited marker for pro accounts.

    Without this a pro user would be told "0 remaining" by the very endpoint
    that just served them an unmetered forecast.
    """
    if _has_unlimited_access():
        return {"unlimited": True, "limit": None, "remaining": None, "reset_at": None}
    quota = rate_limit_status("forecast", _client_key(), FORECAST_LIMIT, FORECAST_WINDOW_SECONDS)
    return {
        "unlimited": False,
        "limit": FORECAST_LIMIT,
        "remaining": quota.remaining,
        "reset_at": quota.reset_at.isoformat(),
    }


@api_bp.route('/forecast/status')
def forecast_status():
    return jsonify(_forecast_usage())


@api_bp.route('/get_default_markets')
def get_default_markets():
    try:
        location = request.args.get('location', 'US').upper()
        if location not in _VALID_MARKETS:
            return jsonify({'error': 'location must be US or IN'}), 400
        markets = MARKET_INDICES[location]

        # Fetch all indices in parallel on the shared market-data pool - each
        # fetch may hit the network. See app/services/executors.py for why
        # this is not a per-request ThreadPoolExecutor.
        fetched = list(market_data_executor.map(
            lambda market: stock_data.fetch_stock_data(market['symbol']),
            markets,
        ))

        market_data = []
        for market, data in zip(markets, fetched):
            if data:
                market_info = {
                    'symbol': market['symbol'],
                    'name': market['name'],
                    'display_name': market['display_name'],
                    'current_price': data['current_price'],
                    'price_change': data['price_change'],
                    'price_change_percent': data['price_change_percent'],
                    'chart_data': data['chart_data'],
                    'currency': '₹' if location == 'IN' else '$',
                    'is_indian_market': location == 'IN',
                }
            else:
                market_info = {
                    'symbol': market['symbol'],
                    'name': market['name'],
                    'display_name': market['display_name'],
                    'current_price': 0,
                    'price_change': 0,
                    'price_change_percent': 0,
                    'chart_data': [],
                    'currency': '₹' if location == 'IN' else '$',
                    'is_indian_market': location == 'IN',
                    'error': 'Market data temporarily unavailable',
                }
            market_data.append(market_info)

        return jsonify({
            'markets': market_data,
            'location': location,
            'timestamp': datetime.now().isoformat(),
        })

    except Exception as e:
        logger.error("Error in get_default_markets: %s", e)
        return _generic_error("Unable to load market data right now."), 500


_INDEX_DISPLAY_NAMES = {
    market["symbol"].upper(): market["display_name"]
    for markets in MARKET_INDICES.values()
    for market in markets
}
_MAX_QUOTE_SYMBOLS = 16


def _build_quote(symbol):
    """Build a compact terminal-style quote row from cached stock data."""
    data = stock_data.fetch_stock_data(symbol)
    if not data:
        return None

    chart_data = data.get('chart_data') or []
    last = chart_data[-1] if chart_data else {}
    highs = [point['high'] for point in chart_data if point.get('high') is not None]
    lows = [point['low'] for point in chart_data if point.get('low') is not None]

    name = _INDEX_DISPLAY_NAMES.get(symbol) or get_company_name(symbol)
    return {
        'symbol': symbol,
        'name': name,
        'price': data['current_price'],
        'change': data['price_change'],
        'change_percent': data['price_change_percent'],
        'day_high': last.get('high'),
        'day_low': last.get('low'),
        'range_high': max(highs) if highs else None,
        'range_low': min(lows) if lows else None,
        'volume': last.get('volume') or 0,
        'currency': get_currency(symbol),
        # 30-day close series for sparklines; data is already in hand.
        'spark': [point['price'] for point in chart_data[-30:]],
    }


@api_bp.route('/quotes')
def get_quotes():
    """Batch quote endpoint for the ticker tape and movers grid.

    Served from the shared stock-data cache; fetches uncached symbols in
    parallel so a cold load is one round-trip wide, not N deep.
    """
    raw = request.args.get('symbols', '')
    requested = [item.strip().upper() for item in raw.split(',') if item.strip()]
    symbols = [
        symbol for symbol in list(dict.fromkeys(requested))[:_MAX_QUOTE_SYMBOLS]
        if _is_supported_symbol(symbol, include_market_indices=True)
    ]
    if not symbols:
        return jsonify({'error': 'At least one supported symbol is required'}), 400

    try:
        results = list(market_data_executor.map(_build_quote, symbols))
        quotes = [quote for quote in results if quote]
        return jsonify({
            'quotes': quotes,
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Error in get_quotes: %s", e)
        return _generic_error("Unable to load quotes right now."), 500


@api_bp.route('/analyze_sentiment', methods=['POST'])
def analyze_sentiment():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    symbol = _symbol_text(data.get('symbol'))

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    limited = _consume_limit("analyze_sentiment", AI_LIMIT, AI_WINDOW_SECONDS)
    if limited:
        return limited

    try:
        company_name = get_company_name(symbol)

        # 1. Fetch stock data
        sd = stock_data.fetch_stock_data(symbol)
        if not sd:
            return jsonify({
                'error': f'Unable to fetch stock data for {symbol}. Yahoo Finance may be temporarily unavailable.'
            }), 503

        # 2. Fetch news. aggregate_news() always includes the free Google/
        # MarketWatch RSS sources (no API key needed) and conditionally adds
        # paid sources internally when their keys are configured, so it is
        # always the right call here - not just when paid keys are present.
        # preprocess_with_groq() is a no-op passthrough when GROQ_API_KEY is
        # unset, so this degrades safely with zero API keys.
        news_items = news_aggregator.aggregate_news(symbol, company_name)
        news_items = news_aggregator.preprocess_with_groq(news_items, symbol)

        # 3. Analyze sentiment via Groq
        analyzed_news = sentiment.analyze_news_sentiment(news_items, symbol)

        # 4. Compute overall sentiment
        overall = sentiment.compute_overall_sentiment(analyzed_news)

        # 5. Derive sentiment timelines from real news, then backfill days
        # outside the news lookback window with stored daily snapshots so the
        # chart shows real past scores instead of flat zeros.
        sentiment_data = sentiment.derive_sentiment_timeline(analyzed_news)
        sentiment_timeline = _build_sentiment_timeline(analyzed_news, sd['chart_data'])

        # History backend: Supabase when configured/reachable, otherwise the
        # local sentiment_store fallback - never skipped outright, so
        # history persists either way instead of silently doing nothing.
        sbc = _get_supabase_client()
        if sbc and sbc.is_available():
            history_backend = sbc
        else:
            _warn_supabase_unavailable_once()
            history_backend = sentiment_store

        history_rows = history_backend.get_sentiment_history(symbol, SENTIMENT_HISTORY_DAYS)
        sentiment_timeline = _merge_sentiment_history(sentiment_timeline, history_rows)
        _persist_sentiment_snapshot(history_backend, symbol, analyzed_news, overall)

        # Divergence walks the timeline and chart_data by index, so it has to
        # run while they are still 1:1 - i.e. before history-only days (weekends,
        # anything older than the chart window) are appended.
        sentiment_divergence = _sentiment_divergence(sentiment_timeline, sd['chart_data'])
        sentiment_timeline = _extend_timeline_with_history(sentiment_timeline, history_rows)
        liquidity = _volume_liquidity_metrics(sd['chart_data'])

        # 6. Generate AI insights
        ai_insights = insights.generate_insights(analyzed_news, symbol, company_name, sd)

        # 7. Extract keywords
        keywords = insights.extract_keywords_from_news(analyzed_news)

        return jsonify({
            'symbol': symbol,
            'company_name': company_name,
            'news_count': len(analyzed_news),
            'overall_sentiment': overall['overall_sentiment'],
            'confidence': overall['confidence'],
            'news_items': analyzed_news,
            'chart_data': sd['chart_data'],
            **liquidity,
            'sentiment_data': sentiment_data,
            'sentiment_timeline': sentiment_timeline,
            'sentiment_divergence': sentiment_divergence,
            'keywords': ai_insights.get('keywords_enriched') or keywords,
            'current_price': sd['current_price'],
            'price_change': sd['price_change'],
            'price_change_percent': sd['price_change_percent'],
            'currency': get_currency(symbol),
            'is_indian_stock': is_indian_stock(symbol),
            'insights': ai_insights,
            'data_timestamp': sd['data_timestamp'],
            'data_source': sd['data_source'],
        })

    except Exception as e:
        logger.error("Error in analyze_sentiment for %s: %s", symbol, e)
        return _generic_error("Unable to analyze sentiment right now."), 500


@api_bp.route('/sec_filings')
def get_sec_filings():
    ticker = request.args.get('ticker', '').upper()
    market = request.args.get('market', 'US').upper()
    if not ticker:
        return jsonify({'error': 'Ticker is required'}), 400
    if market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400

    allowed_types = _INDIAN_FILING_TYPES if market == 'IN' else _SEC_FILING_TYPES
    filing_types, filing_error = _parse_filing_types(request.args.get('types'), allowed_types)
    if filing_error:
        return jsonify({'error': filing_error}), 400
    count_raw = request.args.get('count', 10)
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'count must be a valid integer'}), 400
    count = max(1, min(count, 25))

    if market == 'IN':
        if not is_indian_stock(ticker):
            return jsonify({
                'error': f'{ticker} is not in the supported India stock list for filings.',
                'filings': [],
            }), 400
        result = bse_filings.fetch_indian_filings(ticker, filing_types, count)
        return jsonify(result)

    if not _is_supported_symbol(ticker):
        return jsonify({'error': 'Unsupported ticker'}), 400

    result = sec_edgar.fetch_filings(ticker, filing_types, count)
    return jsonify(result)


@api_bp.route('/sec_filing_summary', methods=['POST'])
def get_filing_summary():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    url = data.get('url')
    market = _short_text(data.get('market', 'US'), 8).upper()
    company_name = _short_text(data.get('company_name'), 160)

    if not url:
        return jsonify({'error': 'Filing URL is required'}), 400
    if market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400

    allowed_types = _INDIAN_FILING_TYPES if market == 'IN' else _SEC_FILING_TYPES
    filing_type = _short_text(data.get('filing_type') or allowed_types[0], 80)
    if filing_type not in allowed_types:
        return jsonify({'error': 'Unsupported filing type'}), 400

    if market == 'IN':
        if not bse_filings.is_allowed_indian_filing_url(url):
            return jsonify({
                'error': 'Invalid filing URL. Only official BSE and NSE filing archive URLs are allowed.'
            }), 400
        limited = _consume_limit("filing_summary", AI_LIMIT, AI_WINDOW_SECONDS)
        if limited:
            return limited
        result = bse_filings.summarize_indian_filing(url, filing_type, company_name)
        return jsonify(result)

    if not sec_edgar.is_allowed_sec_url(url):
        return jsonify({'error': 'Invalid filing URL. Only SEC EDGAR filing archive URLs are allowed.'}), 400

    limited = _consume_limit("filing_summary", AI_LIMIT, AI_WINDOW_SECONDS)
    if limited:
        return limited

    result = sec_edgar.summarize_filing(url, filing_type, company_name)
    return jsonify(result)


@api_bp.route('/sec_filings_overview', methods=['POST'])
def get_filings_overview():
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400
    market = _short_text(data.get('market', 'US'), 8).upper()
    filings = data.get('filings', [])
    company_name = _short_text(data.get('company_name'), 160)
    ticker = _short_text(data.get('ticker'), 24)

    if market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400

    allowed_types = _INDIAN_FILING_TYPES if market == 'IN' else _SEC_FILING_TYPES
    filings, validation_error = _validate_overview_filings(filings, allowed_types)
    if validation_error:
        return jsonify({'error': validation_error}), 400

    if not filings:
        return jsonify({'overview': 'No filings to analyze.'})

    limited = _consume_limit("filings_overview", AI_LIMIT, AI_WINDOW_SECONDS)
    if limited:
        return limited

    if market == 'IN':
        result = bse_filings.generate_indian_filings_overview(filings, company_name, ticker)
        return jsonify(result)

    result = sec_edgar.generate_filings_overview(filings, company_name, ticker)
    return jsonify(result)


@api_bp.route('/waitlist', methods=['POST'])
def join_waitlist():
    """Record a request for paid-tier access.

    Stores only the address - public.waitlist is (id, email, created_at) and
    there is exactly one paid tier to request, so there is nothing else worth
    collecting. Mirrors /contact's honeypot + rate-limit shape.
    """
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400

    if data.get("website") or data.get("company"):
        logger.info("Waitlist honeypot submission ignored from %s", _client_key())
        return jsonify({'status': 'ok', 'message': WAITLIST_CONFIRMATION})

    email = str(data.get('email') or '').strip().lower()
    if not _is_valid_email(email, WAITLIST_EMAIL_MAX_LENGTH):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    limited = _consume_limit("waitlist", WAITLIST_LIMIT, WAITLIST_WINDOW_SECONDS)
    if limited:
        return limited

    sbc = _get_supabase_client()
    outcome = sbc.add_waitlist_email(email) if sbc else 'unavailable'
    if outcome == 'unavailable':
        return jsonify({'error': 'The waitlist is unavailable right now. Please try again later.'}), 503

    # 'added' and 'duplicate' intentionally return the same body and status.
    return jsonify({'status': 'ok', 'message': WAITLIST_CONFIRMATION})


@api_bp.route('/pro/plans')
def list_pro_plans():
    """Purchasable Pro plans, for the upgrade modal.

    Served from config rather than hardcoded in the template so prices and
    checkout links stay a deployment concern. The payment link itself is not
    exposed here - it is only returned by /pro/payment-link, alongside the
    recorded request, so a link never leaks without a request behind it.
    """
    return jsonify({
        'plans': [
            {
                'code': plan['code'],
                'name': plan['name'],
                'price': plan['price'],
                'summary': plan['summary'],
            }
            for plan in PRO_PLANS
        ],
    })


@api_bp.route('/pro/payment-link', methods=['POST'])
def request_pro_payment_link():
    """Record a request to buy Pro and hand back the checkout link.

    No payment is processed here: the response is either an operator-configured
    hosted checkout URL (Stripe Payment Link, Razorpay page, ...) or a promise
    to email one. Either way the request lands in public.pro_payment_requests
    so nothing is lost when no provider is wired up yet.
    """
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400

    if data.get("website") or data.get("company"):
        logger.info("Pro request honeypot submission ignored from %s", _client_key())
        return jsonify({'status': 'ok', 'message': PRO_REQUEST_PENDING_MESSAGE})

    email = str(data.get('email') or '').strip().lower()
    if not _is_valid_email(email, WAITLIST_EMAIL_MAX_LENGTH):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    plan_code = str(data.get('plan') or '').strip()
    plan = PRO_PLANS_BY_CODE.get(plan_code)
    if not plan:
        return jsonify({'error': 'Please choose a plan'}), 400

    limited = _consume_limit("pro_request", PRO_REQUEST_LIMIT, PRO_REQUEST_WINDOW_SECONDS)
    if limited:
        return limited

    sbc = _get_supabase_client()
    outcome = sbc.add_pro_payment_request(email, plan['code']) if sbc else 'unavailable'
    if outcome == 'unavailable':
        return jsonify({
            'error': 'Unable to record your request right now. Please try again later.',
        }), 503

    payment_link = plan['payment_link']
    return jsonify({
        'status': 'ok',
        'plan': plan['code'],
        'plan_name': plan['name'],
        'payment_link': payment_link,
        'message': (
            f"Payment link ready for {plan['name']}."
            if payment_link else PRO_REQUEST_PENDING_MESSAGE
        ),
    })


@api_bp.route('/contact', methods=['POST'])
def send_contact_message():
    """Validate and forward contact form messages through the server-side mail provider."""
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Invalid request'}), 400

    if data.get("website") or data.get("company"):
        logger.info("Contact honeypot submission ignored from %s", _client_key())
        return jsonify({'status': 'ok', 'message': 'Message sent.'})

    name = str(data.get('name') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    message = str(data.get('message') or '').strip()

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if len(name) > CONTACT_NAME_MAX_LENGTH:
        return jsonify({'error': f'Name must be {CONTACT_NAME_MAX_LENGTH} characters or fewer'}), 400
    if not _is_valid_email(email, CONTACT_EMAIL_MAX_LENGTH):
        return jsonify({'error': 'Please enter a valid email address'}), 400
    if not message:
        return jsonify({'error': 'Message is required'}), 400
    if len(message) > CONTACT_MESSAGE_MAX_LENGTH:
        return jsonify({'error': f'Message must be {CONTACT_MESSAGE_MAX_LENGTH} characters or fewer'}), 400

    if not (EMAILJS_SERVICE_ID and EMAILJS_TEMPLATE_ID and EMAILJS_PUBLIC_KEY):
        return jsonify({'error': 'Contact service is not configured.'}), 503

    limited = _consume_limit("contact", CONTACT_LIMIT, CONTACT_WINDOW_SECONDS)
    if limited:
        return limited

    try:
        http_requests.post(
            'https://api.emailjs.com/api/v1.0/email/send',
            json={
                'service_id': EMAILJS_SERVICE_ID,
                'template_id': EMAILJS_TEMPLATE_ID,
                'user_id': EMAILJS_PUBLIC_KEY,
                'template_params': {
                    'from_name': name,
                    'from_email': email,
                    'message': message,
                },
            },
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        logger.error("Contact email error: %s", e)
        return jsonify({'error': 'Unable to send message right now.'}), 502

    return jsonify({'status': 'ok', 'message': 'Message sent.'})


@api_bp.route('/market_news')
def get_market_news():
    """General market headlines for the Track News page.

    Works with zero API keys via the free Google News RSS path in
    news_aggregator. Cached per-market so US and IN never collide, in the
    memory-only market_news_cache - see app/services/cache.py for why this
    payload must not reach the symbol-keyed Supabase news table.
    """
    market = request.args.get('market', 'US').upper()
    if market not in _VALID_MARKETS:
        return jsonify({'error': 'market must be US or IN'}), 400

    limited = _consume_tiered_limit(
        "public_news",
        burst_limit=PUBLIC_NEWS_BURST_LIMIT,
        burst_window_seconds=PUBLIC_NEWS_BURST_WINDOW_SECONDS,
        quota_limit=PUBLIC_NEWS_LIMIT,
        quota_window_seconds=PUBLIC_NEWS_WINDOW_SECONDS,
    )
    if limited:
        return limited

    cache_key = f"market_news_{market}"
    try:
        cached = get_cached(market_news_cache, cache_key)
        if cached is not None:
            return jsonify(cached)

        news_items = news_aggregator.fetch_general_market_news(market)
        payload = {
            'news': news_items,
            'market': market,
            'fetched_at': int(datetime.now(timezone.utc).timestamp()),
        }
        # Only cache non-empty results so a transient RSS failure doesn't
        # blank the page for the full cache TTL (matches aggregate_news).
        if news_items:
            set_cached(market_news_cache, cache_key, payload)
        return jsonify(payload)
    except Exception as e:
        logger.error("Error in get_market_news for %s: %s", market, e)
        return jsonify({
            'error': 'Unable to fetch market news right now.',
            'news': [],
            'market': market,
            'fetched_at': int(datetime.now(timezone.utc).timestamp()),
        }), 200


@api_bp.route('/finnhub_news')
def get_finnhub_news():
    """Proxy for Finnhub stock-specific company news through the shared aggregator."""
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    limited = _consume_tiered_limit(
        "public_news",
        burst_limit=PUBLIC_NEWS_BURST_LIMIT,
        burst_window_seconds=PUBLIC_NEWS_BURST_WINDOW_SECONDS,
        quota_limit=PUBLIC_NEWS_LIMIT,
        quota_window_seconds=PUBLIC_NEWS_WINDOW_SECONDS,
    )
    if limited:
        return limited

    try:
        payload = news_aggregator.fetch_finnhub_company_news(symbol)
        return jsonify({'symbol': symbol, **payload})

    except Exception as e:
        logger.error("Finnhub proxy fetch error for %s: %s", symbol, type(e).__name__)
        return jsonify({'error': 'Unable to fetch Finnhub news right now.', 'news': []}), 200
