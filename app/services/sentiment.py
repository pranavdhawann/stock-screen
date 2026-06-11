import hashlib
import json
import logging
import re
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL
from app.services.cache import sentiment_cache, get_cached, set_cached
from app.services.groq_guard import groq_disabled, note_groq_error

logger = logging.getLogger(__name__)

_client = None

# Finance-tuned lexicon used when Groq is unavailable. Shared shape with
# the keyword extractor in insights.py but tuned for headline scoring.
POSITIVE_WORDS = frozenset({
    'growth', 'profit', 'profits', 'revenue', 'success', 'strong', 'increase',
    'increases', 'gain', 'gains', 'rise', 'rises', 'boost', 'boosts',
    'improve', 'improves', 'improved', 'excellent', 'outstanding', 'record',
    'breakthrough', 'innovation', 'expansion', 'partnership', 'deal',
    'acquisition', 'investment', 'upgrade', 'upgrades', 'upgraded', 'beat',
    'beats', 'exceed', 'exceeds', 'surge', 'surges', 'soar', 'soars', 'rally',
    'rallies', 'bullish', 'optimistic', 'confidence', 'momentum', 'outperform',
    'outperforms', 'win', 'wins', 'jump', 'jumps', 'climb', 'climbs', 'high',
    'higher', 'top', 'tops', 'buy', 'dividend', 'buyback', 'blockbuster',
})
NEGATIVE_WORDS = frozenset({
    'loss', 'losses', 'decline', 'declines', 'fall', 'falls', 'fell', 'drop',
    'drops', 'dropped', 'crash', 'crashes', 'plunge', 'plunges', 'slump',
    'slumps', 'weak', 'weaker', 'poor', 'disappoint', 'disappoints',
    'disappointing', 'miss', 'misses', 'missed', 'cut', 'cuts', 'reduce',
    'layoff', 'layoffs', 'crisis', 'concern', 'concerns', 'risk', 'risks',
    'threat', 'threats', 'problem', 'problems', 'trouble', 'struggle',
    'struggles', 'pressure', 'volatility', 'uncertainty', 'bearish',
    'pessimistic', 'downgrade', 'downgrades', 'downgraded', 'warning',
    'lawsuit', 'probe', 'investigation', 'recall', 'fraud', 'sink', 'sinks',
    'tumble', 'tumbles', 'selloff', 'sell-off', 'low', 'lower', 'short',
})


def _get_client():
    global _client
    if groq_disabled():
        return None
    if _client is None and GROQ_API_KEY:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def lexicon_sentiment(text):
    """Score text against the finance lexicon. Returns (label, confidence)."""
    words = re.findall(r"[a-z][a-z'-]*", str(text or '').lower())
    pos = sum(1 for word in words if word in POSITIVE_WORDS)
    neg = sum(1 for word in words if word in NEGATIVE_WORDS)
    if pos == neg:
        return 'Neutral', 0.5
    # More hits = more confidence, capped well below LLM-grade certainty.
    confidence = round(min(0.8, 0.55 + 0.06 * abs(pos - neg)), 2)
    return ('Positive', confidence) if pos > neg else ('Negative', confidence)


def analyze_news_sentiment(news_items, symbol=""):
    """Analyze sentiment for a batch of news items using Groq. Returns news items with sentiment added."""
    if not news_items:
        return []

    # Key on a digest of the titles - the raw concatenation was hundreds of
    # characters and bloated the Supabase key column.
    titles_digest = hashlib.sha256(
        "|".join(item['title'] for item in news_items).encode('utf-8', 'ignore')
    ).hexdigest()[:32]
    cache_key = f"{symbol}|{titles_digest}"
    cached = get_cached(sentiment_cache, cache_key)
    if cached is not None:
        return cached

    client = _get_client()
    if not client:
        logger.warning("Groq client not available; using lexicon sentiment analyzer.")
        return _fallback_sentiment(news_items)

    # Build batch prompt — send all news in one request
    articles = []
    for i, item in enumerate(news_items):
        articles.append(f"Article {i+1}:\nTitle: {item['title']}\nSummary: {item.get('summary', '')}")

    prompt = f"""Analyze the financial sentiment of each article below. For each article, respond with the sentiment (Positive, Negative, or Neutral) and a confidence score between 0.5 and 0.95.

{chr(10).join(articles)}

Respond ONLY with a JSON array. Each element must have: "index" (1-based), "sentiment" (Positive/Negative/Neutral), "confidence" (float 0.5-0.95).
Example: [{{"index": 1, "sentiment": "Positive", "confidence": 0.82}}]"""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a financial sentiment analyst. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        raw = response.choices[0].message.content.strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        sentiments = json.loads(raw)
        sentiment_map = {s["index"]: s for s in sentiments}

        result = []
        for i, item in enumerate(news_items):
            s = sentiment_map.get(i + 1, {})
            result.append({
                **item,
                'sentiment': s.get('sentiment', 'Neutral'),
                'confidence': round(min(0.95, max(0.5, s.get('confidence', 0.5))), 2),
            })

        set_cached(sentiment_cache, cache_key, result)
        return result

    except Exception as e:
        logger.error("Groq sentiment analysis failed: %s", e)
        note_groq_error(e)
        return _fallback_sentiment(news_items)


def _fallback_sentiment(news_items):
    """Score items with the built-in lexicon when Groq is unavailable.

    Results are intentionally not cached so Groq is retried once it works.
    """
    result = []
    for item in news_items:
        label, confidence = lexicon_sentiment(
            f"{item.get('title', '')} {item.get('summary', '')}"
        )
        result.append({
            **item,
            'sentiment': label,
            'confidence': confidence,
            'analysis_source': 'lexicon',
        })
    return result


def compute_overall_sentiment(analyzed_news):
    """Compute weighted overall sentiment from analyzed news items."""
    if not analyzed_news:
        return {"overall_sentiment": "Neutral", "confidence": 0.5}

    total_weighted_score = 0
    total_weight = 0

    for item in analyzed_news:
        sentiment = item.get('sentiment', 'Neutral')
        confidence = item.get('confidence', 0.5)

        if sentiment == 'Positive':
            score = 1
        elif sentiment == 'Negative':
            score = -1
        elif sentiment == 'Unknown':
            continue
        else:
            score = 0

        total_weighted_score += score * confidence
        total_weight += confidence

    if total_weight == 0:
        return {"overall_sentiment": "Unknown", "confidence": 0}

    avg_score = total_weighted_score / total_weight
    avg_confidence = total_weight / len(analyzed_news)

    if avg_score >= 0.3:
        return {"overall_sentiment": "Positive", "confidence": round(min(0.95, avg_confidence), 2)}
    if avg_score <= -0.3:
        return {"overall_sentiment": "Negative", "confidence": round(min(0.95, avg_confidence), 2)}
    return {"overall_sentiment": "Neutral", "confidence": round(avg_confidence, 2)}


def derive_sentiment_timeline(analyzed_news):
    """Derive sentiment timeline from actual news dates and their computed scores."""
    timeline = []
    for item in analyzed_news:
        published = item.get('published')
        if not published:
            continue

        sentiment = item.get('sentiment', 'Neutral')
        confidence = item.get('confidence', 0.5)

        if sentiment == 'Positive':
            score = confidence
        elif sentiment == 'Negative':
            score = -confidence
        elif sentiment == 'Unknown':
            continue
        else:
            score = 0

        timeline.append({
            'date': published * 1000 if published < 1e12 else published,
            'sentiment': round(score, 2),
        })

    timeline.sort(key=lambda x: x['date'])
    return timeline
