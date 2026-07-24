import re
import requests
import logging
from datetime import datetime, timedelta
from concurrent.futures import as_completed
from defusedxml import ElementTree as ET
from email.utils import parsedate_to_datetime
from app.config import (
    NEWSAPI_KEY, FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY,
    GROQ_MODEL, is_indian_stock,
)
from app.services.cache import aggregated_news_cache, get_cached, set_cached
from app.services.executors import news_fanout_executor
from app.services.groq_guard import get_client as _get_groq_client, note_groq_error
from app.services.news import fetch_news as fetch_yahoo_news

logger = logging.getLogger(__name__)


def _safe_error_label(exc):
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code:
        return f"{type(exc).__name__} status={status_code}"
    return type(exc).__name__


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
        resp.raise_for_status()
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
        logger.error("NewsAPI fetch error: %s", _safe_error_label(e))
        return []


def _finnhub_item(article):
    return {
        'title': article.get('headline', ''),
        'summary': article.get('summary', '') or '',
        'link': article.get('url', ''),
        'publisher': article.get('source', 'Finnhub'),
        'published': article.get('datetime', int(datetime.now().timestamp())),
        'image': article.get('image', ''),
    }


def _fetch_finnhub_items(symbol, *, days=3, max_items=10):
    if not FINNHUB_API_KEY:
        return []

    try:
        today = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={
                'symbol': symbol,
                'from': start_date,
                'to': today,
                'token': FINNHUB_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []

        return [_finnhub_item(article) for article in data[:max_items]]
    except Exception as e:
        logger.error("Finnhub fetch error: %s", _safe_error_label(e))
        return []


def fetch_finnhub_company_news(symbol, *, use_cache=True):
    """Fetch stock-specific Finnhub news with the shared Supabase cache path."""
    normalized = str(symbol or "").upper().strip()
    if not FINNHUB_API_KEY:
        return {'error': 'Finnhub API key not configured', 'news': []}

    sbc = None
    if use_cache:
        try:
            from app.services import supabase_client as sbc
        except ImportError:
            sbc = None

    if sbc and sbc.is_available():
        cached = sbc.get_finnhub_cache(normalized)
        if cached:
            return {
                'news': cached['news_items'],
                'cached': True,
                'fetched_at': cached['fetched_at'],
            }

    items = _fetch_finnhub_items(normalized, days=7, max_items=15)
    if items and sbc and sbc.is_available():
        sbc.set_finnhub_cache(normalized, items)
    return {'news': items, 'cached': False}


def fetch_from_finnhub(symbol):
    """Fetch news from Finnhub for aggregate multi-source news."""
    return _fetch_finnhub_items(symbol, days=3, max_items=10)


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
        resp.raise_for_status()
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
        logger.error("Alpha Vantage fetch error: %s", _safe_error_label(e))
        return []


def fetch_from_google_rss(symbol, company_name):
    """Fetch news from Google News RSS (no API key required).

    Indian symbols get a market-hinted query (company name + NSE/India)
    and the India Google News edition, since a bare mnemonic like
    "RELIANCE" mixed with the default US edition returns few or no
    relevant results.
    """
    try:
        if is_indian_stock(symbol):
            query = f"{company_name.split()[0]}+{symbol}+NSE+India+stock"
            url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        else:
            query = f"{symbol}+{company_name.split()[0]}+stock"
            url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; StockScreen/1.0)'
        })
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        items = []
        for item_el in root.findall('.//item')[:10]:
            title = item_el.findtext('title', '')
            link = item_el.findtext('link', '')
            pub_date_str = item_el.findtext('pubDate', '')
            source = item_el.findtext('source', 'Google News')

            try:
                published = int(parsedate_to_datetime(pub_date_str).timestamp())
            except Exception:
                published = int(datetime.now().timestamp())

            items.append({
                'title': title,
                'summary': '',
                'link': link,
                'publisher': source,
                'published': published,
            })
        return items
    except Exception as e:
        logger.warning("Google RSS fetch failed: %s", _safe_error_label(e))
        return []


def fetch_from_marketwatch_rss(symbol):
    """Fetch news from MarketWatch RSS (no API key required)."""
    try:
        url = "https://feeds.marketwatch.com/marketwatch/marketpulse/"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; StockScreen/1.0)'
        })
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        items = []
        symbol_lower = symbol.lower()
        for item_el in root.findall('.//item')[:20]:
            title = item_el.findtext('title', '')
            desc = item_el.findtext('description', '') or ''
            link = item_el.findtext('link', '')
            pub_date_str = item_el.findtext('pubDate', '')

            # Filter to items mentioning the stock
            if symbol_lower not in title.lower() and symbol_lower not in desc.lower():
                continue

            try:
                published = int(parsedate_to_datetime(pub_date_str).timestamp())
            except Exception:
                published = int(datetime.now().timestamp())

            items.append({
                'title': title,
                'summary': desc[:200] if desc else '',
                'link': link,
                'publisher': 'MarketWatch',
                'published': published,
            })
        return items[:5]
    except Exception as e:
        logger.warning("MarketWatch RSS fetch failed: %s", _safe_error_label(e))
        return []


def _strip_tags(text):
    """Flatten an RSS description to plain text.

    Publisher feeds vary wildly - some send bare text, others a paragraph of
    HTML with a tracking pixel. The wire only ever renders escaped text, so
    markup is noise either way.
    """
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', text or '')).strip()


def _parse_rss_items(xml_text, default_publisher, limit):
    """Parse a generic RSS 2.0 feed into the shared news-item shape.

    Google News puts the originating outlet in <source>; ordinary publisher
    feeds have no such element and are attributed to the feed itself.
    """
    root = ET.fromstring(xml_text)
    items = []
    for item_el in root.findall('.//item')[:limit]:
        pub_date_str = item_el.findtext('pubDate', '')
        try:
            published = int(parsedate_to_datetime(pub_date_str).timestamp())
        except Exception:
            published = int(datetime.now().timestamp())

        summary = _strip_tags(item_el.findtext('description', ''))
        items.append({
            'title': item_el.findtext('title', ''),
            'summary': summary[:200],
            'link': item_el.findtext('link', ''),
            'publisher': item_el.findtext('source', '') or default_publisher,
            'published': published,
        })
    return items


def fetch_market_rss(url, default_publisher, limit=20):
    """Fetch one keyless market-wide RSS feed."""
    try:
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; StockScreen/1.0)'
        })
        resp.raise_for_status()
        return _parse_rss_items(resp.text, default_publisher, limit)
    except Exception as e:
        logger.warning("Market RSS fetch failed for %s: %s", default_publisher, _safe_error_label(e))
        return []


def fetch_finnhub_general_news():
    """Finnhub's market-wide feed (category=general), not company news."""
    if not FINNHUB_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://finnhub.io/api/v1/news',
            params={'category': 'general', 'token': FINNHUB_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        return [_finnhub_item(article) for article in data[:20]]
    except Exception as e:
        logger.warning("Finnhub general news fetch failed: %s", _safe_error_label(e))
        return []


def fetch_newsapi_general(market):
    """NewsAPI business top-headlines for the market's country."""
    if not NEWSAPI_KEY:
        return []
    try:
        resp = requests.get(
            'https://newsapi.org/v2/top-headlines',
            params={
                'category': 'business',
                'country': 'in' if market == 'IN' else 'us',
                'pageSize': 20,
                'apiKey': NEWSAPI_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'ok':
            return []

        items = []
        for article in data.get('articles', []):
            try:
                published = int(datetime.fromisoformat(
                    (article.get('publishedAt') or '').replace('Z', '+00:00')
                ).timestamp())
            except (ValueError, AttributeError):
                published = int(datetime.now().timestamp())
            items.append({
                'title': article.get('title', ''),
                'summary': (article.get('description') or '')[:200],
                'link': article.get('url', ''),
                'publisher': (article.get('source') or {}).get('name', 'NewsAPI'),
                'published': published,
            })
        return items
    except Exception as e:
        logger.warning("NewsAPI general fetch failed: %s", _safe_error_label(e))
        return []


def fetch_alphavantage_general():
    """Alpha Vantage NEWS_SENTIMENT by topic rather than by ticker."""
    if not ALPHAVANTAGE_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'NEWS_SENTIMENT',
                'topics': 'financial_markets',
                'limit': 20,
                'apikey': ALPHAVANTAGE_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = []
        for article in resp.json().get('feed', []):
            pub_str = article.get('time_published', '')
            try:
                published = int(datetime.strptime(pub_str[:15], '%Y%m%dT%H%M%S').timestamp())
            except (ValueError, AttributeError):
                published = int(datetime.now().timestamp())
            items.append({
                'title': article.get('title', ''),
                'summary': (article.get('summary') or '')[:200],
                'link': article.get('url', ''),
                'publisher': article.get('source', 'Alpha Vantage'),
                'published': published,
            })
        return items
    except Exception as e:
        logger.warning("Alpha Vantage general fetch failed: %s", _safe_error_label(e))
        return []


# Keyless market-wide feeds, per market. Google News RSS is listed first but
# carries no special weight: it 503s from datacenter IPs (Cloud Run included),
# which is precisely why the wire can no longer depend on it alone.
_MARKET_FEEDS = {
    'US': [
        ("https://news.google.com/rss/search?q=US+stock+market+Wall+Street+S%26P+500"
         "&hl=en-US&gl=US&ceid=US:en", 'Google News'),
        ("https://finance.yahoo.com/news/rssindex", 'Yahoo Finance'),
        ("https://feeds.marketwatch.com/marketwatch/topstories/", 'MarketWatch'),
        ("https://feeds.marketwatch.com/marketwatch/marketpulse/", 'MarketWatch'),
        ("https://search.cnbc.com/rs/search/combinedcms/view.xml"
         "?partnerId=wrss01&id=100003114", 'CNBC'),
    ],
    # India carries no keyed sources worth having (Finnhub/Alpha Vantage are
    # US-centric), so its redundancy has to come from breadth of publisher
    # feeds instead. Moneycontrol, Zee Business and NDTV Profit were tried and
    # rejected: the first two 403 datacenter traffic, the third's feed is
    # general news rather than markets.
    'IN': [
        ("https://news.google.com/rss/search?q=Indian+stock+market+NSE+BSE+Sensex+Nifty"
         "&hl=en-IN&gl=IN&ceid=IN:en", 'Google News India'),
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
         'Economic Times'),
        ("https://www.business-standard.com/rss/markets-106.rss", 'Business Standard'),
        ("https://www.livemint.com/rss/markets", 'Livemint'),
        ("https://www.thehindubusinessline.com/markets/feeder/default.rss",
         'Hindu BusinessLine'),
    ],
}


def fetch_general_market_news(market):
    """General market headlines for /api/market_news.

    Fans out across every configured source the way aggregate_news() does for
    a single symbol, for the same reason: this feed used to be Google News RSS
    alone, and when Google started returning 503 to Cloud Run's egress IP the
    whole Market Wire went blank. Keyless publisher feeds carry the wire on
    their own; the keyed sources (Finnhub/NewsAPI/Alpha Vantage) are additive
    when their keys are configured. Every source swallows its own failures, so
    a dead source costs coverage, never the page.
    """
    market = 'IN' if market == 'IN' else 'US'

    sources = [
        (publisher, lambda u=url, p=publisher: fetch_market_rss(u, p))
        for url, publisher in _MARKET_FEEDS[market]
    ]
    if NEWSAPI_KEY:
        sources.append(('newsapi', lambda: fetch_newsapi_general(market)))
    # Finnhub's general feed and Alpha Vantage's financial_markets topic are
    # both US-centric; for India they'd dilute the wire with off-market noise.
    if market == 'US':
        if FINNHUB_API_KEY:
            sources.append(('finnhub', fetch_finnhub_general_news))
        if ALPHAVANTAGE_API_KEY:
            sources.append(('alphavantage', fetch_alphavantage_general))

    all_items = []
    futures = {news_fanout_executor.submit(fn): name for name, fn in sources}
    for future in as_completed(futures):
        source_name = futures[future]
        try:
            result = future.result()
            logger.info("Market wire: %d items from %s (%s)", len(result), source_name, market)
            all_items.extend(result)
        except Exception as e:
            logger.warning("Market wire source %s failed: %s", source_name, _safe_error_label(e))

    unique = [item for item in _dedup_news(all_items) if item.get('title')]
    unique.sort(key=lambda x: x.get('published', 0), reverse=True)
    return unique[:30]


def _dedup_news(items):
    """Remove duplicate articles by normalized title.

    Items without a title (but with a link) still get deduplicated - and
    kept - using the link as the fallback key, instead of being silently
    dropped for lacking a title.
    """
    seen = set()
    unique = []
    for item in items:
        key = (item.get('title') or '').lower().strip() or (item.get('link') or '').strip()
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
        ('google_rss', lambda: fetch_from_google_rss(symbol, company_name)),
        ('marketwatch_rss', lambda: fetch_from_marketwatch_rss(symbol)),
    ]

    # Finnhub and Alpha Vantage can't resolve bare Indian mnemonics (e.g.
    # "RELIANCE") - they expect US-listed tickers - so skip the pointless
    # network calls for Indian symbols; Google/MarketWatch RSS still run.
    indian = is_indian_stock(symbol)

    if NEWSAPI_KEY:
        sources.append(('newsapi', lambda: fetch_from_newsapi(symbol, company_name)))
    if FINNHUB_API_KEY and not indian:
        sources.append(('finnhub', lambda: fetch_from_finnhub(symbol)))
    if ALPHAVANTAGE_API_KEY and not indian:
        sources.append(('alphavantage', lambda: fetch_from_alphavantage(symbol)))

    # Shared bounded pool rather than a fresh one per request - see
    # app/services/executors.py.
    futures = {news_fanout_executor.submit(fn): name for name, fn in sources}
    for future in as_completed(futures):
        source_name = futures[future]
        try:
            result = future.result()
            logger.info("Fetched %d items from %s for %s", len(result), source_name, symbol)
            all_items.extend(result)
        except Exception as e:
            logger.warning("Optional news source %s failed: %s", source_name, _safe_error_label(e))

    # Dedup and sort by recency
    unique = _dedup_news(all_items)
    unique.sort(key=lambda x: x.get('published', 0), reverse=True)
    result = unique[:25]

    # Only cache non-empty results so a transient all-sources failure
    # doesn't blank the news for the full TTL.
    if result:
        set_cached(aggregated_news_cache, cache_key, result)
    return result


def preprocess_with_groq(news_items, symbol):
    """Use Groq to generate concise summaries and filter by relevance.

    Returns a new list of items with filtered and updated summaries.
    Does not mutate the input list or its items; operates on copies only.
    Never exposes internal _relevance key to callers.
    """
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

        # Build a map of index -> (score, summary) from Groq response
        # This way we can work with copies and avoid mutating the original items.
        scores_and_summaries = {}

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
                        scores_and_summaries[idx] = (score, summary)
            except (ValueError, IndexError):
                continue

        # Build filtered list with copies of items, applying updates only to copies.
        # This ensures the original cached items remain unchanged.
        filtered = []
        for idx, item in enumerate(news_items):
            if idx in scores_and_summaries:
                score, summary = scores_and_summaries[idx]
            else:
                # Items without a Groq rating default to score 10 (always included)
                score, summary = 10, None

            if score >= 5:
                # Make a copy of the item dict to avoid mutating the cached original
                item_copy = dict(item)
                # Update summary if provided
                if summary:
                    item_copy['summary'] = summary
                filtered.append(item_copy)

        return filtered if filtered else news_items

    except Exception as e:
        logger.error("Groq preprocessing error: %s", e)
        note_groq_error(e)
        return news_items
