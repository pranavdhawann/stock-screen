import re
from flask import Blueprint, request, jsonify
from datetime import datetime
from app.config import STOCK_DIRECTORY, INDIAN_STOCKS, MARKET_INDICES, get_company_name, get_currency, is_indian_stock, RESEND_API_KEY, CONTACT_EMAIL
from app.services import stock_data, news, sentiment, insights, sec_edgar, news_aggregator
import requests as http_requests
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/stock_list')
def stock_list():
    us_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] not in INDIAN_STOCKS]
    in_stocks = [s for s in STOCK_DIRECTORY if s['symbol'] in INDIAN_STOCKS]
    return jsonify({"US": us_stocks, "IN": in_stocks})


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
                    'chart_data': data['chart_data'][-7:],
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
    count = min(int(request.args.get('count', 10)), 25)

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


@api_bp.route('/contact', methods=['POST'])
def contact():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request'}), 400

    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    message = data.get('message', '').strip()

    if not name or not email or not message:
        return jsonify({'error': 'All fields are required'}), 400

    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Invalid email address'}), 400

    if not RESEND_API_KEY:
        logger.info("Contact form submitted (no Resend key): %s <%s>", name, email)
        return jsonify({'success': True})

    try:
        resp = http_requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'from': 'InfoEdge <onboarding@resend.dev>',
                'to': [CONTACT_EMAIL],
                'subject': f'InfoEdge Contact: {name}',
                'html': f'<h3>New contact from InfoEdge</h3>'
                        f'<p><strong>Name:</strong> {name}</p>'
                        f'<p><strong>Email:</strong> {email}</p>'
                        f'<p><strong>Message:</strong></p><p>{message}</p>',
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return jsonify({'success': True})
        else:
            logger.error("Resend API error: %s %s", resp.status_code, resp.text)
            return jsonify({'error': 'Failed to send message. Please try again.'}), 500
    except Exception as e:
        logger.error("Contact email error: %s", e)
        return jsonify({'error': 'Failed to send message. Please try again.'}), 500
