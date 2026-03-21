import requests
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from groq import Groq
from app.config import (
    NEWSAPI_KEY, FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY,
    GROQ_API_KEY, GROQ_MODEL, YAHOO_HEADERS, YAHOO_TIMEOUT,
)
from app.services.cache import aggregated_news_cache, get_cached, set_cached
from app.services.news import fetch_news as fetch_yahoo_news

logger = logging.getLogger(__name__)

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def fetch_from_newsapi(symbol, company_name):
    """Fetch news from NewsAPI.org."""
    if not NEWSAPI_KEY:
        return []

    try:
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q': f'{symbol} OR {company_name.split()[0]}',
                'from': three_days_ago,
                'sortBy': 'publishedAt',
                'pageSize': 10,
                'language': 'en',
                'apiKey': NEWSAPI_KEY,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get('status') != 'ok':
            return []

        items = []
        for article in data.get('articles', []):
            pub_date = article.get('publishedAt', '')
            try:
                published = int(datetime.fromisoformat(pub_date.replace('Z', '+00:00')).timestamp())
            except (ValueError, AttributeError):
                published = int(datetime.now().timestamp())

            items.append({
                'title': article.get('title', ''),
                'summary': article.get('description', '') or '',
                'link': article.get('url', ''),
                'publisher': article.get('source', {}).get('name', 'NewsAPI'),
                'published': published,
            })
        return items
    except Exception as e:
        logger.error("NewsAPI fetch error: %s", e)
        return []


def fetch_from_finnhub(symbol):
    """Fetch news from Finnhub."""
    if not FINNHUB_API_KEY:
        return []

    try:
        today = datetime.now().strftime('%Y-%m-%d')
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={
                'symbol': symbol,
                'from': three_days_ago,
                'to': today,
                'token': FINNHUB_API_KEY,
            },
            timeout=10,
        )
        data = resp.json()
        if not isinstance(data, list):
            return []

        items = []
        for article in data[:10]:
            items.append({
                'title': article.get('headline', ''),
                'summary': article.get('summary', '') or '',
                'link': article.get('url', ''),
                'publisher': article.get('source', 'Finnhub'),
                'published': article.get('datetime', int(datetime.now().timestamp())),
            })
        return items
    except Exception as e:
        logger.error("Finnhub fetch error: %s", e)
        return []


def fetch_from_alphavantage(symbol):
    """Fetch news from Alpha Vantage."""
    if not ALPHAVANTAGE_API_KEY:
        return []

    try:
        resp = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'NEWS_SENTIMENT',
                'tickers': symbol,
                'limit': 10,
                'apikey': ALPHAVANTAGE_API_KEY,
            },
            timeout=10,
        )
        data = resp.json()
        feed = data.get('feed', [])

        items = []
        for article in feed:
            pub_str = article.get('time_published', '')
            try:
                published = int(datetime.strptime(pub_str[:15], '%Y%m%dT%H%M%S').timestamp())
            except (ValueError, AttributeError):
                published = int(datetime.now().timestamp())

            items.append({
                'title': article.get('title', ''),
                'summary': article.get('summary', '') or '',
                'link': article.get('url', ''),
                'publisher': article.get('source', 'Alpha Vantage'),
                'published': published,
            })
        return items
    except Exception as e:
        logger.error("Alpha Vantage fetch error: %s", e)
        return []


def _dedup_news(items):
    """Remove duplicate articles by normalized title."""
    seen = set()
    unique = []
    for item in items:
        key = item['title'].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def aggregate_news(symbol, company_name):
    """Fetch from all available sources, dedup, sort, and return."""
    cache_key = f"agg_{symbol}"
    cached = get_cached(aggregated_news_cache, cache_key)
    if cached is not None:
        return cached

    all_items = []
    sources = [
        ('yahoo', lambda: fetch_yahoo_news(symbol, company_name)),
    ]

    if NEWSAPI_KEY:
        sources.append(('newsapi', lambda: fetch_from_newsapi(symbol, company_name)))
    if FINNHUB_API_KEY:
        sources.append(('finnhub', lambda: fetch_from_finnhub(symbol)))
    if ALPHAVANTAGE_API_KEY:
        sources.append(('alphavantage', lambda: fetch_from_alphavantage(symbol)))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): name for name, fn in sources}
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                result = future.result()
                logger.info("Fetched %d items from %s for %s", len(result), source_name, symbol)
                all_items.extend(result)
            except Exception as e:
                logger.error("Error fetching from %s: %s", source_name, e)

    # Dedup and sort by recency
    unique = _dedup_news(all_items)
    unique.sort(key=lambda x: x.get('published', 0), reverse=True)
    result = unique[:25]

    set_cached(aggregated_news_cache, cache_key, result)
    return result


def preprocess_with_groq(news_items, symbol):
    """Use Groq to generate concise summaries and filter by relevance."""
    client = _get_groq_client()
    if not client or not news_items:
        return news_items

    titles = "\n".join(f"{i+1}. {item['title']}" for i, item in enumerate(news_items[:15]))

    prompt = f"""For each headline about {symbol}, rate relevance (1-10) and write a 1-sentence summary.
Return as numbered list: "N. [score] summary"

Headlines:
{titles}"""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a financial news editor. Rate relevance and summarize concisely."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        text = response.choices[0].message.content.strip()

        # Parse responses
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Expected: "1. [8] Summary text here"
            try:
                parts = line.split('.', 1)
                idx = int(parts[0].strip()) - 1
                rest = parts[1].strip()
                # Extract score in brackets
                if rest.startswith('['):
                    bracket_end = rest.index(']')
                    score = int(rest[1:bracket_end])
                    summary = rest[bracket_end + 1:].strip()
                    if 0 <= idx < len(news_items):
                        news_items[idx]['_relevance'] = score
                        if summary:
                            news_items[idx]['summary'] = summary
            except (ValueError, IndexError):
                continue

        # Filter by relevance >= 5
        filtered = [item for item in news_items if item.get('_relevance', 10) >= 5]
        # Clean up internal field
        for item in filtered:
            item.pop('_relevance', None)

        return filtered if filtered else news_items

    except Exception as e:
        logger.error("Groq preprocessing error: %s", e)
        return news_items


def has_extra_sources():
    """Check if any additional news API keys are configured."""
    return bool(NEWSAPI_KEY or FINNHUB_API_KEY or ALPHAVANTAGE_API_KEY)
