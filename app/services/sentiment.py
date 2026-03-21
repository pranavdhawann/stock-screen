import json
import logging
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL
from app.services.cache import sentiment_cache, get_cached, set_cached

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and GROQ_API_KEY:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def analyze_news_sentiment(news_items, symbol=""):
    """Analyze sentiment for a batch of news items using Groq. Returns news items with sentiment added."""
    if not news_items:
        return []

    # Build cache key from symbol + titles
    cache_key = f"{symbol}|" + "|".join(item['title'][:50] for item in news_items)
    cached = get_cached(sentiment_cache, cache_key)
    if cached is not None:
        return cached

    client = _get_client()
    if not client:
        logger.warning("Groq client not available (missing API key). Returning unknown sentiment.")
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
        return _fallback_sentiment(news_items)


def _fallback_sentiment(news_items):
    """Return news items with unknown sentiment when Groq is unavailable."""
    return [{**item, 'sentiment': 'Unknown', 'confidence': 0} for item in news_items]


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
    elif avg_score <= -0.3:
        return {"overall_sentiment": "Negative", "confidence": round(min(0.95, avg_confidence), 2)}
    else:
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
