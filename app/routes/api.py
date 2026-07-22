from flask import Blueprint, request, jsonify
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from app.config import (
    STOCK_DIRECTORY, INDIAN_STOCKS, MARKET_INDICES,
    get_company_name, get_currency, is_indian_stock,
    CURRENTS_API_KEY,
    EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY,
)
from app.services import (
    bse_filings, stock_data, news, sentiment, insights, sec_edgar,
    news_aggregator, forecasting, indicators, validation,
)
from app.services.http_limits import (
    client_key as _client_key,
    consume_limit as _consume_limit,
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

_VALID_MARKETS = {"US", "IN"}
_SEC_FILING_TYPES = ("10-K", "10-Q", "8-K")
_INDIAN_FILING_TYPES = ("Annual Report", "Financial Results", "Corporate Announcement", "Shareholding Pattern")
_MAX_OVERVIEW_FILINGS = 25

# Bounded background worker for sentiment-history writes so a burst of
# requests can't spawn an unbounded number of raw threads (mirrors the
# cache-persist pool in app/services/cache.py).
_SENTIMENT_PERSIST_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sentiment-persist")


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


def _merge_sentiment_history(timeline, history_rows):
    """Fill timeline days that have no current headlines with stored history.

    Without this, any day older than the news lookback window renders as a
    flat 0 even though we analyzed it before.
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


def _persist_sentiment_snapshot(sbc, symbol, analyzed_news, overall):
    """Store today's aggregate score so it survives the cache TTL."""
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
    _SENTIMENT_PERSIST_EXECUTOR.submit(sbc.record_sentiment_snapshot, **snapshot)


def _sentiment_divergence(timeline, chart_data, window=14):
    if len(timeline or []) < 3 or len(chart_data or []) < 3:
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
    us_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] not in INDIAN_STOCKS]
    in_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] in INDIAN_STOCKS]
    return jsonify({"US": us_stocks, "IN": in_stocks})


@api_bp.route('/news')
def get_news():
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400
    limited = _consume_limit("public_news", PUBLIC_NEWS_LIMIT, PUBLIC_NEWS_WINDOW_SECONDS, distributed=False)
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
        quota = rate_limit_status("forecast", _client_key(), FORECAST_LIMIT, FORECAST_WINDOW_SECONDS)
        result["usage"] = {
            "remaining": quota.remaining,
            "reset_at": quota.reset_at.isoformat(),
        }
        return jsonify(result)
    except ValueError as e:
        logger.error("Forecast request validation failed for %s: %s", symbol, e)
        return jsonify({'error': 'Unable to generate a forecast for that symbol.'}), 400
    except Exception as e:
        logger.error("Forecast request failed for %s: %s", symbol, e)
        return jsonify({'error': 'Forecast generation failed. Please try again.'}), 500


@api_bp.route('/forecast/status')
def forecast_status():
    quota = rate_limit_status("forecast", _client_key(), FORECAST_LIMIT, FORECAST_WINDOW_SECONDS)
    return jsonify({
        "limit": FORECAST_LIMIT,
        "remaining": quota.remaining,
        "reset_at": quota.reset_at.isoformat(),
    })


@api_bp.route('/get_default_markets')
def get_default_markets():
    try:
        location = request.args.get('location', 'US').upper()
        if location not in _VALID_MARKETS:
            return jsonify({'error': 'location must be US or IN'}), 400
        markets = MARKET_INDICES[location]

        # Fetch all indices in parallel - each fetch may hit the network.
        with ThreadPoolExecutor(max_workers=max(len(markets), 1)) as executor:
            fetched = list(executor.map(
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
        with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as executor:
            results = list(executor.map(_build_quote, symbols))
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

        # 2. Fetch news (multi-source if API keys available, otherwise Yahoo only)
        if news_aggregator.has_extra_sources():
            news_items = news_aggregator.aggregate_news(symbol, company_name)
            news_items = news_aggregator.preprocess_with_groq(news_items, symbol)
        else:
            news_items = news.fetch_news(symbol, company_name)

        # 3. Analyze sentiment via Groq
        analyzed_news = sentiment.analyze_news_sentiment(news_items, symbol)

        # 4. Compute overall sentiment
        overall = sentiment.compute_overall_sentiment(analyzed_news)

        # 5. Derive sentiment timelines from real news, then backfill days
        # outside the news lookback window with stored daily snapshots so the
        # chart shows real past scores instead of flat zeros.
        sentiment_data = sentiment.derive_sentiment_timeline(analyzed_news)
        sentiment_timeline = _build_sentiment_timeline(analyzed_news, sd['chart_data'])
        sbc = _get_supabase_client()
        if sbc and sbc.is_available():
            sentiment_timeline = _merge_sentiment_history(
                sentiment_timeline, sbc.get_sentiment_history(symbol)
            )
            _persist_sentiment_snapshot(sbc, symbol, analyzed_news, overall)
        sentiment_divergence = _sentiment_divergence(sentiment_timeline, sd['chart_data'])
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


@api_bp.route('/currents_news')
def get_currents_news():
    """Proxy for Currents API general market/finance news."""
    limited = _consume_limit("public_news", PUBLIC_NEWS_LIMIT, PUBLIC_NEWS_WINDOW_SECONDS, distributed=False)
    if limited:
        return limited

    sbc = _get_supabase_client()

    # 1. Check Supabase cache
    if sbc and sbc.is_available():
        cached = sbc.get_currents_cache()
        if cached:
            return jsonify({
                'news': cached['news_items'],
                'cached': True,
                'fetched_at': cached['fetched_at'],
            })

    # 2. No cache hit - call Currents API
    if not CURRENTS_API_KEY:
        return jsonify({'error': 'Currents API key not configured', 'news': []}), 200

    try:
        resp = http_requests.get(
            'https://api.currentsapi.services/v1/latest-news',
            params={
                'apiKey': CURRENTS_API_KEY,
                'language': 'en',
                'category': 'finance,business',
            },
            # Keep the tail short: when Currents is slow the client falls
            # back to SPY news, so waiting 10s only delays the fallback.
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'ok':
            logger.error("Currents API error: %s", data)
            return jsonify({'error': 'Currents API error', 'news': []}), 200

        items = []
        for article in data.get('news', [])[:20]:
            pub_date = article.get('published', '')
            try:
                published = int(datetime.fromisoformat(
                    pub_date.replace('Z', '+00:00').replace(' +0000', '+00:00')
                ).timestamp())
            except (ValueError, AttributeError):
                published = int(datetime.now().timestamp())

            items.append({
                'title': article.get('title', ''),
                'summary': (article.get('description', '') or '')[:200],
                'link': article.get('url', ''),
                'publisher': article.get('author', '') or 'Currents',
                'published': published,
                'image': article.get('image', ''),
            })

        # 3. Store in Supabase cache
        if items and sbc and sbc.is_available():
            sbc.set_currents_cache(items)

        return jsonify({'news': items, 'cached': False})

    except Exception as e:
        logger.error("Currents API fetch error: %s", type(e).__name__)
        return jsonify({'error': 'Unable to fetch market headlines right now.', 'news': []}), 200


@api_bp.route('/finnhub_news')
def get_finnhub_news():
    """Proxy for Finnhub stock-specific company news through the shared aggregator."""
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if not _is_supported_symbol(symbol):
        return jsonify({'error': 'Unsupported symbol'}), 400

    limited = _consume_limit("public_news", PUBLIC_NEWS_LIMIT, PUBLIC_NEWS_WINDOW_SECONDS, distributed=False)
    if limited:
        return limited

    try:
        payload = news_aggregator.fetch_finnhub_company_news(symbol)
        return jsonify({'symbol': symbol, **payload})

    except Exception as e:
        logger.error("Finnhub proxy fetch error for %s: %s", symbol, type(e).__name__)
        return jsonify({'error': 'Unable to fetch Finnhub news right now.', 'news': []}), 200
