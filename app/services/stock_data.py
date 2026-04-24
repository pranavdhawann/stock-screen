import requests
from datetime import datetime
from app.config import get_yahoo_symbol, YAHOO_HEADERS, YAHOO_TIMEOUT
from app.services.cache import stock_data_cache, get_cached, set_cached
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_ohlcv_history(symbol, range_period='6mo', interval='1d'):
    """Fetch raw OHLCV history from Yahoo Finance as a DataFrame."""
    try:
        yahoo_symbol = get_yahoo_symbol(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval={interval}&range={range_period}"

        response = requests.get(url, headers=YAHOO_HEADERS, timeout=YAHOO_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if "chart" not in data or "result" not in data["chart"] or not data["chart"]["result"]:
            logger.warning("No OHLCV chart data returned for %s", symbol)
            return None

        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        quotes = (result.get("indicators") or {}).get("quote") or []
        if not timestamps or not quotes:
            logger.warning("Missing OHLCV timestamp/quote data for %s", symbol)
            return None

        quote = quotes[0]
        rows = []
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        for idx, timestamp in enumerate(timestamps):
            values = {
                "Open": opens[idx] if idx < len(opens) else None,
                "High": highs[idx] if idx < len(highs) else None,
                "Low": lows[idx] if idx < len(lows) else None,
                "Close": closes[idx] if idx < len(closes) else None,
                "Volume": volumes[idx] if idx < len(volumes) else None,
            }
            if any(v is None for v in values.values()):
                continue
            rows.append({
                "Date": pd.to_datetime(timestamp, unit="s", utc=True),
                **values,
            })

        if not rows:
            logger.warning("No complete OHLCV rows available for %s", symbol)
            return None

        frame = pd.DataFrame(rows).set_index("Date").sort_index()
        return frame.astype({
            "Open": float,
            "High": float,
            "Low": float,
            "Close": float,
            "Volume": float,
        })
    except Exception as e:
        logger.error("Error fetching OHLCV history for %s: %s", symbol, e)
        return None


def fetch_stock_data(symbol, period='30d'):
    """Fetch real stock data from Yahoo Finance. Returns dict or None on failure.

    Args:
        symbol: Stock ticker symbol
        period: Time range - '30d', '1y', or '5y'
    """
    VALID_PERIODS = {'30d': ('1d', '30d'), '1y': ('1d', '1y'), '5y': ('1wk', '5y')}
    interval, yf_range = VALID_PERIODS.get(period, ('1d', '30d'))

    cache_key = f"{symbol}_{period}"
    cached = get_cached(stock_data_cache, cache_key)
    if cached is not None:
        return cached

    try:
        yahoo_symbol = get_yahoo_symbol(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval={interval}&range={yf_range}"

        response = requests.get(url, headers=YAHOO_HEADERS, timeout=YAHOO_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if "chart" not in data or "result" not in data["chart"] or not data["chart"]["result"]:
            logger.warning("No chart data returned for %s", symbol)
            return None

        result = data["chart"]["result"][0]

        if "timestamp" not in result or "indicators" not in result:
            logger.warning("Missing timestamp/indicators for %s", symbol)
            return None

        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        chart_data = []
        close_prices = quotes.get("close", [])
        volumes = quotes.get("volume", [])
        for i, timestamp in enumerate(timestamps):
            if (i < len(close_prices)
                    and close_prices[i] is not None
                    and close_prices[i] > 0):
                price = float(close_prices[i])
                volume = 0
                if i < len(volumes) and volumes[i] is not None:
                    volume = int(volumes[i])
                chart_data.append({
                    "date": timestamp * 1000,
                    "price": round(price, 2),
                    "volume": volume,
                })

        if len(chart_data) >= 2:
            current_price = chart_data[-1]["price"]
            previous_price = chart_data[-2]["price"]
        elif len(chart_data) == 1:
            current_price = chart_data[0]["price"]
            previous_price = current_price
        else:
            return None

        if previous_price == 0:
            previous_price = current_price
        price_change = current_price - previous_price
        price_change_percent = (price_change / previous_price) * 100 if previous_price != 0 else 0

        result_data = {
            "chart_data": chart_data,
            "current_price": round(current_price, 2),
            "price_change": round(price_change, 2),
            "price_change_percent": round(price_change_percent, 2),
            "data_timestamp": datetime.now().isoformat(),
            "data_source": "Yahoo Finance (Real-time)",
        }

        set_cached(stock_data_cache, cache_key, result_data)
        return result_data

    except Exception as e:
        logger.error("Error fetching stock data for %s: %s", symbol, e)
        return None
