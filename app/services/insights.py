import json
import re
import logging
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and GROQ_API_KEY:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _count_sentiments(news_items):
    counts = {"Positive": 0, "Negative": 0, "Neutral": 0, "Unknown": 0}
    for item in news_items:
        s = item.get('sentiment', 'Neutral')
        counts[s] = counts.get(s, 0) + 1
    return counts


def _compute_change_30d(stock_data):
    chart = stock_data.get('chart_data', []) if stock_data else []
    if len(chart) >= 2:
        first = chart[0].get('price', 0)
        last = chart[-1].get('price', 0)
        if first:
            return round(((last - first) / first) * 100, 2)
    return 0


def _sentiment_label(pos, neg, total):
    if total == 0:
        return "Neutral"
    ratio = (pos - neg) / total
    if ratio >= 0.3:
        return "Bullish"
    elif ratio <= -0.3:
        return "Bearish"
    return "Neutral"


def _compute_source_breakdown(sentiment_counts, company_name, symbol):
    pos = sentiment_counts.get("Positive", 0)
    neg = sentiment_counts.get("Negative", 0)
    neu = sentiment_counts.get("Neutral", 0) + sentiment_counts.get("Unknown", 0)
    total = max(pos + neg + neu, 1)
    # Largest-remainder method to ensure percentages sum to exactly 100
    raw = [pos / total * 100, neu / total * 100, neg / total * 100]
    floored = [int(x) for x in raw]
    remainders = sorted(range(3), key=lambda i: raw[i] - floored[i], reverse=True)
    for i in range(100 - sum(floored)):
        floored[remainders[i]] += 1
    return {
        "bullish_pct": floored[0],
        "neutral_pct": floored[1],
        "bearish_pct": floored[2],
        "analyst_takeaway": f"Based on {total} articles: {pos} bullish, {neg} bearish, {neu} neutral.",
    }


def _build_report_summary(parsed, company_name, symbol):
    one_liner = parsed.get("verdict", {}).get("one_liner", f"Mixed outlook for {symbol}")
    note = parsed.get("analyst_note", "")
    summary = f"{one_liner}. {note}" if note else one_liner
    return {
        "title": f"{company_name} ({symbol}) — Sentiment Analysis",
        "executive_summary": summary,
        "disclaimer": "This analysis is AI-generated using public news data. Not financial advice.",
    }


def _build_backward_compat(parsed, sentiment_counts):
    verdict = parsed.get("verdict", {})
    one_liner = verdict.get("one_liner", "")
    note = parsed.get("analyst_note", "")
    outlook = f"{one_liner}. {note}" if note else one_liner

    risks = parsed.get("risks", [])[:3]
    catalysts = parsed.get("catalysts", [])[:3]

    return {
        "market_outlook": outlook,
        "risk_factors": [r.get("text", "") for r in risks],
        "opportunities": [c.get("text", "") for c in catalysts if c.get("direction") == "up"][:3],
        "key_points": [
            one_liner,
            parsed.get("trending", {}).get("what_to_watch", ""),
        ],
        "sentiment_summary": {
            "positive_news": sentiment_counts.get("Positive", 0),
            "negative_news": sentiment_counts.get("Negative", 0),
            "neutral_news": sentiment_counts.get("Neutral", 0) + sentiment_counts.get("Unknown", 0),
        },
    }


def _parse_llm_json(raw):
    """Parse JSON from LLM response, handling markdown fences."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            return json.loads(match.group())
        raise


def _safe_get_parsed(parsed):
    """Extract all fields from parsed JSON with safe defaults."""
    verdict = parsed.get("verdict", {})
    return {
        "verdict": {
            "signal": verdict.get("signal", "Neutral"),
            "one_liner": verdict.get("one_liner", ""),
            "confidence_label": verdict.get("confidence_label", "Low"),
            "confidence_explanation": verdict.get("confidence_explanation", ""),
        },
        "analyst_note": parsed.get("analyst_note", ""),
        "catalysts": parsed.get("catalysts", [])[:3],
        "risks": parsed.get("risks", [])[:3],
        "sentiment_velocity": {
            "trend": parsed.get("sentiment_velocity", {}).get("trend", "stable"),
            "label": parsed.get("sentiment_velocity", {}).get("label", "Insufficient data"),
        },
        "keywords_enriched": [
            {
                "text": kw.get("word", ""),
                "weight": min(20, max(1, int(kw.get("weight", 1)) * 2)),
                "sentiment": kw.get("sentiment", "neutral"),
            }
            for kw in parsed.get("keywords", [])[:15]
        ],
        "trending": {
            "is_high_volume": bool(parsed.get("trending", {}).get("is_high_volume", False)),
            "reason": parsed.get("trending", {}).get("reason", ""),
            "category": parsed.get("trending", {}).get("category", "other"),
            "what_to_watch": parsed.get("trending", {}).get("what_to_watch", ""),
        },
    }


def generate_insights(news_items, symbol, company_name, stock_data):
    """Generate AI-powered market insights using Groq."""
    sentiment_counts = _count_sentiments(news_items)

    client = _get_client()
    if not client or not news_items:
        return _fallback_insights(news_items, symbol, company_name, sentiment_counts)

    # Prepare data for prompt
    pos = sentiment_counts.get("Positive", 0)
    neg = sentiment_counts.get("Negative", 0)
    neu = sentiment_counts.get("Neutral", 0) + sentiment_counts.get("Unknown", 0)
    total = len(news_items)

    change_30d = _compute_change_30d(stock_data)
    price = stock_data.get('current_price', 'N/A') if stock_data else 'N/A'
    pct = stock_data.get('price_change_percent', 0) if stock_data else 0
    currency = "₹" if symbol in ('TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM',
                                   'HDFCBANK', 'ICICIBANK', 'KOTAKBANK', 'AXISBANK',
                                   'SBIN', 'RELIANCE', 'HINDUNILVR', 'ITC',
                                   'BHARTIARTL', 'MARUTI', 'SUNPHARMA', 'DRREDDY',
                                   'CIPLA', 'DIVISLAB', 'BIOCON', 'ONGC', 'IOC',
                                   'BPCL', 'ADANIGREEN', 'TATAPOWER', 'ZOMATO',
                                   'PAYTM', 'POLICYBZR', 'NAZARA') else "$"

    sent_label = _sentiment_label(pos, neg, total)
    sent_score = round((pos - neg) / max(total, 1), 2)
    confidence = round(sum(item.get('confidence', 0.5) for item in news_items) / max(total, 1), 2)

    news_lines = "\n".join(
        f"- {item['title']} (Sentiment: {item.get('sentiment', 'N/A')})"
        for item in news_items[:8]
    )

    prompt = f"""Stock: {company_name} ({symbol})
Price: {currency}{price} | Day: {pct:+.2f}% | 30d: {change_30d:+.2f}%
Sentiment: {sent_label} ({sent_score}) | Confidence: {confidence:.0%}
Articles: {total} ({pos} positive, {neg} negative, {neu} neutral)

Recent News:
{news_lines}

Return this JSON:
{{
  "verdict": {{"signal":"Bullish|Bearish|Neutral","one_liner":"max 12 words","confidence_label":"High|Medium|Low","confidence_explanation":"one sentence"}},
  "analyst_note": "2-3 sentences synthesizing what the data means together",
  "catalysts": [{{"tag":"short label","direction":"up|down|neutral","text":"one sentence"}}],
  "risks": [{{"text":"one sentence","severity":"High|Medium|Low"}}],
  "sentiment_velocity": {{"trend":"improving|declining|stable","label":"short description"}},
  "keywords": [{{"word":"keyword","weight":1-10,"sentiment":"positive|negative|neutral"}}],
  "trending": {{"is_high_volume":true,"reason":"max 15 words","category":"earnings|macro|product|legal|other","what_to_watch":"one sentence"}}
}}

Rules: catalysts max 3, risks max 3, keywords max 15. All text concise."""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a financial analyst. Given stock data and news, produce a JSON analysis. Respond ONLY with valid JSON, no markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
        )

        raw = response.choices[0].message.content.strip()
        parsed = _parse_llm_json(raw)
        safe = _safe_get_parsed(parsed)

        # Server-side computed fields
        source_breakdown = _compute_source_breakdown(sentiment_counts, company_name, symbol)
        report_summary = _build_report_summary(parsed, company_name, symbol)
        compat = _build_backward_compat(parsed, sentiment_counts)

        return {
            **safe,
            "source_breakdown": source_breakdown,
            "report_summary": report_summary,
            **compat,
        }

    except Exception as e:
        logger.error("Groq insights generation failed: %s", e)
        return _fallback_insights(news_items, symbol, company_name, sentiment_counts)


def _fallback_insights(news_items, symbol, company_name, sentiment_counts):
    """Fallback when Groq is unavailable. Returns same shape as rich insights."""
    total = len(news_items) if news_items else 1
    pos = sentiment_counts.get("Positive", 0)
    neg = sentiment_counts.get("Negative", 0)
    pos_ratio = pos / total
    neg_ratio = neg / total

    if pos_ratio > 0.6:
        signal = "Bullish"
        outlook = f"Bullish outlook for {symbol} with strong positive sentiment."
    elif neg_ratio > 0.6:
        signal = "Bearish"
        outlook = f"Bearish outlook for {symbol} with significant negative sentiment."
    elif pos_ratio > neg_ratio:
        signal = "Bullish"
        outlook = f"Cautiously optimistic outlook for {symbol} with mixed but slightly positive sentiment."
    elif neg_ratio > pos_ratio:
        signal = "Bearish"
        outlook = f"Cautious outlook for {symbol} with slightly negative sentiment."
    else:
        signal = "Neutral"
        outlook = f"Neutral outlook for {symbol} with balanced sentiment."

    source_breakdown = _compute_source_breakdown(sentiment_counts, company_name, symbol)

    return {
        # Rich fields (with safe defaults)
        "verdict": {
            "signal": signal,
            "one_liner": outlook,
            "confidence_label": "Low",
            "confidence_explanation": "AI analysis temporarily unavailable.",
        },
        "analyst_note": "AI insights temporarily unavailable. Showing basic analysis.",
        "catalysts": [],
        "risks": [],
        "sentiment_velocity": {"trend": "stable", "label": "Insufficient data"},
        "keywords_enriched": [],
        "trending": {
            "is_high_volume": False,
            "reason": "",
            "category": "other",
            "what_to_watch": "",
        },
        "source_breakdown": source_breakdown,
        "report_summary": {
            "title": f"{company_name} ({symbol}) — Sentiment Analysis",
            "executive_summary": outlook,
            "disclaimer": "This analysis is AI-generated using public news data. Not financial advice.",
        },
        # Backward-compat fields
        "market_outlook": outlook,
        "risk_factors": [],
        "opportunities": [],
        "key_points": ["AI insights temporarily unavailable. Showing basic analysis."],
        "sentiment_summary": {
            "positive_news": sentiment_counts.get("Positive", 0),
            "negative_news": sentiment_counts.get("Negative", 0),
            "neutral_news": sentiment_counts.get("Neutral", 0) + sentiment_counts.get("Unknown", 0),
        },
    }


def extract_keywords_from_news(news_items):
    """Extract keywords from news content for word cloud."""
    if not news_items:
        return []

    all_text = " ".join(
        item.get('title', '') + " " + item.get('summary', '')
        for item in news_items
    )

    words = re.findall(r'\b[a-zA-Z]{3,}\b', all_text.lower())

    stopwords = {
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
        'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
        'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who',
        'boy', 'did', 'man', 'oil', 'sit', 'try', 'use', 'she', 'put', 'end',
        'why', 'let', 'say', 'ask', 'run', 'own', 'set', 'too', 'any', 'many',
        'some', 'time', 'very', 'when', 'come', 'here', 'just', 'like', 'long',
        'make', 'much', 'over', 'such', 'take', 'than', 'them', 'well', 'were',
    }

    word_freq = {}
    for word in words:
        if word not in stopwords:
            word_freq[word] = word_freq.get(word, 0) + 1

    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

    sentiment_keywords = {
        'positive': {'growth', 'profit', 'revenue', 'success', 'strong', 'increase', 'gain', 'rise', 'boost', 'improve', 'excellent', 'outstanding', 'record', 'breakthrough', 'innovation', 'expansion', 'partnership', 'deal', 'acquisition', 'investment', 'upgrade', 'beat', 'exceed', 'surge', 'rally', 'bullish', 'optimistic', 'confidence', 'momentum', 'leadership', 'dominance'},
        'negative': {'loss', 'decline', 'fall', 'drop', 'crash', 'plunge', 'slump', 'weak', 'poor', 'disappoint', 'miss', 'cut', 'reduce', 'layoff', 'crisis', 'concern', 'risk', 'threat', 'challenge', 'problem', 'issue', 'trouble', 'struggle', 'pressure', 'volatility', 'uncertainty', 'bearish', 'pessimistic', 'downgrade', 'warning', 'caution'},
    }

    keywords = []
    for word, freq in sorted_words[:15]:
        sentiment = 'neutral'
        if word in sentiment_keywords['positive']:
            sentiment = 'positive'
        elif word in sentiment_keywords['negative']:
            sentiment = 'negative'

        keywords.append({
            'text': word,
            'weight': min(20, freq * 2),
            'sentiment': sentiment,
        })

    return keywords
