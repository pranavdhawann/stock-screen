import requests
from datetime import datetime
from app.config import get_yahoo_symbol, YAHOO_HEADERS, YAHOO_TIMEOUT
from app.services.cache import stock_data_cache, get_cached, set_cached
import logging

logger = logging.getLogger(__name__)


def fetch_stock_data(symbol):
    """Fetch real stock data from Yahoo Finance. Returns dict or None on failure."""
    cached = get_cached(stock_data_cache, symbol)
    if cached is not None:
        return cached

    try:
        yahoo_symbol = get_yahoo_symbol(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=30d"

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
        for i, timestamp in enumerate(timestamps):
            if (i < len(quotes["close"])
                    and quotes["close"][i] is not None
                    and quotes["close"][i] > 0):
                price = float(quotes["close"][i])
                volume = int(quotes["volume"][i]) if quotes["volume"][i] is not None else 0
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

        set_cached(stock_data_cache, symbol, result_data)
        return result_data

    except Exception as e:
        logger.error("Error fetching stock data for %s: %s", symbol, e)
        return None
