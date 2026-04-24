import requests
from datetime import datetime
from app.config import YAHOO_HEADERS, YAHOO_TIMEOUT
from app.services.cache import news_cache, get_cached, set_cached
import logging

logger = logging.getLogger(__name__)


def fetch_news(symbol, company_name):
    """Fetch real news from Yahoo Finance. Returns list of raw news items (without sentiment)."""
    cached = get_cached(news_cache, symbol)
    if cached is not None:
        return cached

    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}&quotesCount=1&newsCount=25"
        response = requests.get(url, headers=YAHOO_HEADERS, timeout=YAHOO_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        news_items = []
        if "news" in data and data["news"]:
            for news in data["news"]:
                title = news.get("title", "")
                summary = news.get("summary", "")

                # Check relevance
                title_lower = title.lower()
                summary_lower = summary.lower()
                is_relevant = (
                    symbol.lower() in title_lower
                    or symbol.lower() in summary_lower
                    or company_name.lower().split()[0] in title_lower
                    or any(word in title_lower for word in company_name.lower().split()[:2])
                )

                if is_relevant:
                    news_items.append({
                        'title': title,
                        'summary': summary,
                        'link': news.get("link", f"https://finance.yahoo.com/quote/{symbol}"),
                        'publisher': news.get("publisher", "Yahoo Finance"),
                        'published': news.get("providerPublishTime", int(datetime.now().timestamp())),
                    })

                if len(news_items) >= 20:
                    break

        set_cached(news_cache, symbol, news_items)
        return news_items

    except Exception as e:
        logger.error("Error fetching news for %s: %s", symbol, e)
        return []
