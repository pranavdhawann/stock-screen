import re
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from app.config import (
    STOCK_DIRECTORY, INDIAN_STOCKS, MARKET_INDICES,
    get_company_name, get_currency, is_indian_stock,
    RESEND_API_KEY, CURRENTS_API_KEY, FINNHUB_API_KEY,
    EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY,
)
from app.services import stock_data, news, sentiment, insights, sec_edgar, news_aggregator
import requests as http_requests
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')


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
    try:
        company_name = get_company_name(symbol)
        # Always use aggregator — Google RSS and MarketWatch don't need API keys
        news_items = news_aggregator.aggregate_news(symbol, company_name)
        return jsonify({'symbol': symbol, 'news_items': news_items or []})
    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/chart_data')
def get_chart_data():
    symbol = request.args.get('symbol', '').upper()
    period = request.args.get('period', '30d')
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    if period not in ('30d', '1y', '5y'):
        return jsonify({'error': 'Invalid period. Use 30d, 1y, or 5y'}), 400
    try:
        sd = stock_data.fetch_stock_data(symbol, period=period)
        if not sd:
            return jsonify({'error': f'Unable to fetch chart data for {symbol}'}), 503
        return jsonify({
            'symbol': symbol,
            'period': period,
            'chart_data': sd['chart_data'],
            'current_price': sd['current_price'],
            'price_change': sd['price_change'],
            'price_change_percent': sd['price_change_percent'],
            'currency': get_currency(symbol),
        })
    except Exception as e:
        logger.error(f"Error fetching chart data for {symbol}: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/search_stocks')
def search_stocks():
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])

    results = []
    for stock in STOCK_DIRECTORY:
        if query in stock['symbol'].lower() or query in stock['name'].lower():
            results.append({
                'symbol': stock['symbol'],
                'name': stock['name'],
                'display': f"{stock['symbol']} - {stock['name']}",
            })
    return jsonify(results[:20])


@api_bp.route('/get_default_markets')
def get_default_markets():
    try:
        location = request.args.get('location', 'US')
        markets = MARKET_INDICES.get(location, MARKET_INDICES['US'])

        market_data = []
        for market in markets:
            data = stock_data.fetch_stock_data(market['symbol'])

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
        return jsonify({'error': str(e)}), 500


@api_bp.route('/analyze_sentiment', methods=['POST'])
def analyze_sentiment():
    data = request.get_json()
    symbol = data.get('symbol') if data else None

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

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

        # 5. Derive sentiment timeline from real news
        sentiment_timeline = sentiment.derive_sentiment_timeline(analyzed_news)

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
            'sentiment_data': sentiment_timeline,
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
        return jsonify({'error': str(e)}), 500


@api_bp.route('/sec_filings')
def get_sec_filings():
    ticker = request.args.get('ticker', '').upper()
    if not ticker:
        return jsonify({'error': 'Ticker is required'}), 400

    filing_types = request.args.get('types', '10-K,10-Q,8-K').split(',')
    count_raw = request.args.get('count', 10)
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'count must be a valid integer'}), 400
    count = max(1, min(count, 25))

    result = sec_edgar.fetch_filings(ticker, filing_types, count)
    return jsonify(result)


@api_bp.route('/sec_filing_summary', methods=['POST'])
def get_filing_summary():
    data = request.get_json()
    url = data.get('url') if data else None
    filing_type = data.get('filing_type', '10-K') if data else '10-K'
    company_name = data.get('company_name', '') if data else ''

    if not url:
        return jsonify({'error': 'Filing URL is required'}), 400

    if not sec_edgar.is_allowed_sec_url(url):
        return jsonify({'error': 'Invalid filing URL. Only SEC EDGAR filing archive URLs are allowed.'}), 400

    result = sec_edgar.summarize_filing(url, filing_type, company_name)
    return jsonify(result)


@api_bp.route('/sec_filings_overview', methods=['POST'])
def get_filings_overview():
    data = request.get_json()
    filings = data.get('filings', []) if data else []
    company_name = data.get('company_name', '') if data else ''
    ticker = data.get('ticker', '') if data else ''

    if not filings:
        return jsonify({'overview': 'No filings to analyze.'})

    result = sec_edgar.generate_filings_overview(filings, company_name, ticker)
    return jsonify(result)


@api_bp.route('/emailjs_config')
def emailjs_config():
    """Return public EmailJS credentials for the frontend contact modal."""
    return jsonify({
        'service_id': EMAILJS_SERVICE_ID,
        'template_id': EMAILJS_TEMPLATE_ID,
        'public_key': EMAILJS_PUBLIC_KEY,
    })


@api_bp.route('/currents_news')
def get_currents_news():
    """Proxy for Currents API — general market/finance news.
    Checks Supabase cache first (2.4h TTL), then calls Currents API."""
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

    # 2. No cache hit — call Currents API
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
            timeout=10,
        )
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
        logger.error("Currents API fetch error: %s", e)
        return jsonify({'error': str(e), 'news': []}), 200


@api_bp.route('/finnhub_news')
def get_finnhub_news():
    """Proxy for Finnhub — stock-specific company news.
    Checks Supabase cache first (1h TTL per ticker), then calls Finnhub API."""
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

    sbc = _get_supabase_client()

    # 1. Check Supabase cache
    if sbc and sbc.is_available():
        cached = sbc.get_finnhub_cache(symbol)
        if cached:
            return jsonify({
                'symbol': symbol,
                'news': cached['news_items'],
                'cached': True,
                'fetched_at': cached['fetched_at'],
            })

    # 2. No cache hit — call Finnhub API
    if not FINNHUB_API_KEY:
        return jsonify({'error': 'Finnhub API key not configured', 'news': []}), 200

    try:
        today = datetime.now().strftime('%Y-%m-%d')
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        resp = http_requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={
                'symbol': symbol,
                'from': seven_days_ago,
                'to': today,
                'token': FINNHUB_API_KEY,
            },
            timeout=10,
        )
        data = resp.json()
        if not isinstance(data, list):
            return jsonify({'error': 'Unexpected Finnhub response', 'news': []}), 200

        items = []
        for article in data[:15]:
            items.append({
                'title': article.get('headline', ''),
                'summary': (article.get('summary', '') or '')[:200],
                'link': article.get('url', ''),
                'publisher': article.get('source', 'Finnhub'),
                'published': article.get('datetime', int(datetime.now().timestamp())),
                'image': article.get('image', ''),
            })

        # 3. Store in Supabase cache
        if items and sbc and sbc.is_available():
            sbc.set_finnhub_cache(symbol, items)

        return jsonify({'symbol': symbol, 'news': items, 'cached': False})

    except Exception as e:
        logger.error("Finnhub proxy fetch error for %s: %s", symbol, e)
        return jsonify({'error': str(e), 'news': []}), 200


@api_bp.route('/waitlist', methods=['POST'])
def join_waitlist():
    """Add email to forecasting Pro waitlist and send confirmation."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request'}), 400

    email = (data.get('email') or '').strip().lower()
    if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    sbc = _get_supabase_client()
    if not sbc:
        return jsonify({'error': 'Waitlist storage is not configured on this local setup.'}), 503

    status, msg = sbc.add_to_waitlist(email)

    if status == 'duplicate':
        return jsonify({'status': 'duplicate', 'message': "You're already on the list!"})

    if status == 'error':
        return jsonify({'error': msg}), 500

    # Send confirmation email via Resend
    if RESEND_API_KEY:
        try:
            http_requests.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': f'Bearer {RESEND_API_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': 'Stock Screen <onboarding@resend.dev>',
                    'to': [email],
                    'subject': "You're on the list!",
                    'html': (
                        '<div style="font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 32px;">'
                        '<h2 style="color: #FFA500; margin-bottom: 16px;">Stock Screen</h2>'
                        '<p>Thanks for your interest in <strong>Forecasting Pro</strong>.</p>'
                        "<p>We'll notify you the moment it launches.</p>"
                        '<hr style="border-color: #333; margin: 24px 0;">'
                        '<p style="color: #666; font-size: 12px;">Stock Screen &mdash; Market intelligence, rebuilt.</p>'
                        '</div>'
                    ),
                },
                timeout=10,
            )
        except Exception as e:
            logger.error("Waitlist confirmation email error: %s", e)

    return jsonify({'status': 'ok', 'message': "You're on the list! Check your inbox."})
