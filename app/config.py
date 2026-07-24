import os

# Groq API Configuration
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

# Supabase server-side cache/storage. Keep the service key server-only.
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
TRUST_PROXY_HEADERS = os.environ.get('TRUST_PROXY_HEADERS', '').lower() in {'1', 'true', 'yes'}


def _parse_trusted_proxy_hops():
    """Number of trusted reverse-proxy hops in front of this app.

    Only meaningful when TRUST_PROXY_HEADERS is on. Cloud Run appends the
    real client IP as the last entry of X-Forwarded-For, so hops=1 (the
    default) selects that last entry. Any unparsable or non-positive value
    falls back to 1 rather than disabling the right-to-left parse.
    """
    raw = os.environ.get('TRUSTED_PROXY_HOPS', '1')
    try:
        hops = int(raw)
    except (TypeError, ValueError):
        return 1
    return hops if hops >= 1 else 1


TRUSTED_PROXY_HOPS = _parse_trusted_proxy_hops()

# Cache TTL (seconds)
STOCK_DATA_TTL = 300      # 5 minutes
NEWS_TTL = 900             # 15 minutes
SENTIMENT_TTL = 900        # 15 minutes

# Cache sizes
STOCK_DATA_CACHE_SIZE = 50
NEWS_CACHE_SIZE = 50
SENTIMENT_CACHE_SIZE = 100
SEC_FILINGS_CACHE_SIZE = 50

# SEC EDGAR Configuration
SEC_EDGAR_HEADERS = {
    'User-Agent': os.environ.get('SEC_EDGAR_USER_AGENT', 'Stock Screen app@stockscreen.app'),
    'Accept-Encoding': 'gzip, deflate',
}
SEC_FILINGS_TTL = 1800  # 30 minutes

# Pro plan catalogue.
#
# Checkout is not processed in-app. A request records the intent (plan +
# email) in public.pro_payment_requests and hands back a hosted checkout URL
# when one is configured - a Stripe Payment Link, a Razorpay page, whatever
# the operator sets. With no URL configured the request is still recorded and
# the user is told the link will be emailed, so the flow degrades cleanly
# before a payment provider is wired up.
#
# Prices are strings on purpose: they are display copy only, never used in a
# calculation, and the app never sees a real amount.
def _plan_link(env_name):
    """A checkout URL from the environment, or '' if it isn't a usable one.

    Anything that isn't plain https is dropped rather than handed to a
    browser: this value ends up in an href, so a javascript: or data: URL
    misconfigured here would be a stored-XSS vector on every visitor who
    asks for a link.
    """
    value = os.environ.get(env_name, '').strip()
    return value if value.lower().startswith('https://') else ''


PRO_PLANS = [
    {
        'code': 'pro_monthly',
        'name': 'Pro Monthly',
        'price': os.environ.get('PRO_MONTHLY_PRICE', '$19 / month'),
        'summary': 'Billed monthly. Cancel any time.',
        'payment_link': _plan_link('PRO_MONTHLY_PAYMENT_LINK'),
    },
    {
        'code': 'pro_annual',
        'name': 'Pro Annual',
        'price': os.environ.get('PRO_ANNUAL_PRICE', '$190 / year'),
        'summary': 'Billed yearly — two months free.',
        'payment_link': _plan_link('PRO_ANNUAL_PAYMENT_LINK'),
    },
]

PRO_PLANS_BY_CODE = {plan['code']: plan for plan in PRO_PLANS}

# EmailJS Configuration (server-side contact form)
EMAILJS_SERVICE_ID = os.environ.get('EMAILJS_SERVICE_ID', '')
EMAILJS_TEMPLATE_ID = os.environ.get('EMAILJS_TEMPLATE_ID', '')
EMAILJS_PUBLIC_KEY = os.environ.get('EMAILJS_PUBLIC_KEY', '')

# News Aggregation API Keys
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '')
ALPHAVANTAGE_API_KEY = os.environ.get('ALPHAVANTAGE_API_KEY', '')

# Aggregated news cache
AGGREGATED_NEWS_CACHE_SIZE = 100
AGGREGATED_NEWS_TTL = 600  # 10 minutes

# General market headlines (/api/market_news). Only one entry per market, and
# deliberately memory-only: the Supabase aggregated_news_cache table is keyed
# by `symbol` and its news_items column holds a list of articles, neither of
# which fits a market-wide payload.
MARKET_NEWS_CACHE_SIZE = 8

# Yahoo Finance request headers
YAHOO_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
YAHOO_TIMEOUT = 10

# Indian stocks that need .NS suffix for Yahoo Finance
INDIAN_STOCKS = [
    'TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM', 'HDFCBANK', 'ICICIBANK', 'KOTAKBANK',
    'AXISBANK', 'SBIN', 'RELIANCE', 'HINDUNILVR', 'ITC', 'BHARTIARTL', 'MARUTI',
    'SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'BIOCON', 'ONGC', 'IOC', 'BPCL',
    'ADANIGREEN', 'TATAPOWER', 'ZOMATO', 'PAYTM', 'POLICYBZR', 'NAZARA'
]

# Complete stock directory (single source of truth)
STOCK_DIRECTORY = [
    # US Stocks
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust"},
    {"symbol": "AAPL", "name": "Apple Inc."},
    {"symbol": "MSFT", "name": "Microsoft Corporation"},
    {"symbol": "GOOGL", "name": "Alphabet Inc."},
    {"symbol": "AMZN", "name": "Amazon.com Inc."},
    {"symbol": "TSLA", "name": "Tesla Inc."},
    {"symbol": "META", "name": "Meta Platforms Inc."},
    {"symbol": "NVDA", "name": "NVIDIA Corporation"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co."},
    {"symbol": "V", "name": "Visa Inc."},
    {"symbol": "JNJ", "name": "Johnson & Johnson"},
    {"symbol": "NFLX", "name": "Netflix Inc."},
    {"symbol": "UBER", "name": "Uber Technologies Inc."},
    {"symbol": "SHOP", "name": "Shopify Inc."},
    {"symbol": "ZM", "name": "Zoom Video Communications Inc."},
    {"symbol": "PLTR", "name": "Palantir Technologies Inc."},
    {"symbol": "MA", "name": "Mastercard Inc."},
    {"symbol": "PYPL", "name": "PayPal Holdings Inc."},
    {"symbol": "WMT", "name": "Walmart Inc."},
    {"symbol": "DIS", "name": "Walt Disney Company"},
    {"symbol": "NKE", "name": "Nike Inc."},
    {"symbol": "XOM", "name": "Exxon Mobil Corporation"},
    {"symbol": "BA", "name": "Boeing Company"},
    {"symbol": "CAT", "name": "Caterpillar Inc."},
    # Indian Stocks
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd.", "bse_code": "532540"},
    {"symbol": "INFY", "name": "Infosys Ltd.", "bse_code": "500209"},
    {"symbol": "WIPRO", "name": "Wipro Ltd.", "bse_code": "507685"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd.", "bse_code": "532281"},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd.", "bse_code": "532755"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd.", "bse_code": "500180"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd.", "bse_code": "532174"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd.", "bse_code": "500247"},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd.", "bse_code": "532215"},
    {"symbol": "SBIN", "name": "State Bank of India", "bse_code": "500112"},
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd.", "bse_code": "500325"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd.", "bse_code": "500696"},
    {"symbol": "ITC", "name": "ITC Ltd.", "bse_code": "500875"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd.", "bse_code": "532454"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd.", "bse_code": "532500"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd.", "bse_code": "524715"},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Ltd.", "bse_code": "500124"},
    {"symbol": "CIPLA", "name": "Cipla Ltd.", "bse_code": "500087"},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Ltd.", "bse_code": "532488"},
    {"symbol": "BIOCON", "name": "Biocon Ltd.", "bse_code": "532523"},
    {"symbol": "ONGC", "name": "Oil and Natural Gas Corporation Ltd.", "bse_code": "500312"},
    {"symbol": "IOC", "name": "Indian Oil Corporation Ltd.", "bse_code": "530965"},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Ltd.", "bse_code": "500547"},
    {"symbol": "ADANIGREEN", "name": "Adani Green Energy Ltd.", "bse_code": "541450"},
    {"symbol": "TATAPOWER", "name": "Tata Power Company Ltd.", "bse_code": "500400"},
    {"symbol": "ZOMATO", "name": "Zomato Ltd.", "bse_code": "543320"},
    {"symbol": "PAYTM", "name": "One97 Communications Ltd.", "bse_code": "543396"},
    {"symbol": "POLICYBZR", "name": "PB Fintech Ltd.", "bse_code": "543390"},
    {"symbol": "NAZARA", "name": "Nazara Technologies Ltd.", "bse_code": "543280"},
]

# Precomputed lookup: symbol -> name
_COMPANY_NAMES = {s["symbol"]: s["name"] for s in STOCK_DIRECTORY}
_STOCKS_BY_SYMBOL = {s["symbol"]: s for s in STOCK_DIRECTORY}

# Market index definitions
MARKET_INDICES = {
    'US': [
        {'symbol': '^DJI', 'name': 'Dow Jones Industrial Average', 'display_name': 'Dow Jones'},
        {'symbol': '^GSPC', 'name': 'S&P 500', 'display_name': 'S&P 500'},
    ],
    'IN': [
        {'symbol': '^NSEI', 'name': 'Nifty 50', 'display_name': 'Nifty 50'},
        {'symbol': '^BSESN', 'name': 'S&P BSE Sensex', 'display_name': 'Sensex'},
    ],
}

# Indian market indices, quoted in rupees. Kept separate from INDIAN_STOCKS
# (equities) because get_yahoo_symbol() must NOT append ".NS" to these -
# Yahoo's index tickers (^NSEI, ^BSESN) are already correct as-is and a
# ".NS" suffix would break the lookup. Only get_currency() should consult
# this set.
INDIAN_MARKET_INDEX_SYMBOLS = {market['symbol'].upper() for market in MARKET_INDICES['IN']}


def _normalize_symbol(symbol):
    return str(symbol or "").upper()


def get_company_name(symbol):
    normalized = _normalize_symbol(symbol)
    return _COMPANY_NAMES.get(normalized, f"{normalized} Corporation")


def get_stock_metadata(symbol):
    return _STOCKS_BY_SYMBOL.get(_normalize_symbol(symbol), {})


def is_indian_stock(symbol):
    return _normalize_symbol(symbol) in INDIAN_STOCKS


def get_yahoo_symbol(symbol):
    normalized = _normalize_symbol(symbol)
    return f"{normalized}.NS" if is_indian_stock(normalized) else normalized


def get_currency(symbol):
    normalized = _normalize_symbol(symbol)
    if is_indian_stock(normalized) or normalized in INDIAN_MARKET_INDEX_SYMBOLS:
        return "₹"
    return "$"
