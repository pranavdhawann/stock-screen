import os

# Groq API Configuration
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

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
    'User-Agent': 'Stock Screen info@stockscreen.app',
    'Accept-Encoding': 'gzip, deflate',
}
SEC_FILINGS_TTL = 1800  # 30 minutes

# Resend Email Configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
CONTACT_EMAIL = 'pranavdhawan99@gmail.com'

# News Aggregation API Keys
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '')
ALPHAVANTAGE_API_KEY = os.environ.get('ALPHAVANTAGE_API_KEY', '')

# Aggregated news cache
AGGREGATED_NEWS_CACHE_SIZE = 100
AGGREGATED_NEWS_TTL = 600  # 10 minutes

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
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd."},
    {"symbol": "INFY", "name": "Infosys Ltd."},
    {"symbol": "WIPRO", "name": "Wipro Ltd."},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd."},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd."},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd."},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd."},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd."},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd."},
    {"symbol": "SBIN", "name": "State Bank of India"},
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd."},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd."},
    {"symbol": "ITC", "name": "ITC Ltd."},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd."},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd."},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd."},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Ltd."},
    {"symbol": "CIPLA", "name": "Cipla Ltd."},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Ltd."},
    {"symbol": "BIOCON", "name": "Biocon Ltd."},
    {"symbol": "ONGC", "name": "Oil and Natural Gas Corporation Ltd."},
    {"symbol": "IOC", "name": "Indian Oil Corporation Ltd."},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Ltd."},
    {"symbol": "ADANIGREEN", "name": "Adani Green Energy Ltd."},
    {"symbol": "TATAPOWER", "name": "Tata Power Company Ltd."},
    {"symbol": "ZOMATO", "name": "Zomato Ltd."},
    {"symbol": "PAYTM", "name": "One97 Communications Ltd."},
    {"symbol": "POLICYBZR", "name": "PB Fintech Ltd."},
    {"symbol": "NAZARA", "name": "Nazara Technologies Ltd."},
]

# Precomputed lookup: symbol -> name
_COMPANY_NAMES = {s["symbol"]: s["name"] for s in STOCK_DIRECTORY}

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


def get_company_name(symbol):
    return _COMPANY_NAMES.get(symbol, f"{symbol} Corporation")


def is_indian_stock(symbol):
    return symbol in INDIAN_STOCKS


def get_yahoo_symbol(symbol):
    return f"{symbol}.NS" if is_indian_stock(symbol) else symbol


def get_currency(symbol):
    return "₹" if is_indian_stock(symbol) else "$"
