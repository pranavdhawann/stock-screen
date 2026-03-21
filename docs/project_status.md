# 📊 INFOEDGE — Project Status

> Current state, known limitations, and data integrity notes for the **Stock Sentiment Analysis Platform**.

**Last Updated:** March 15, 2026

---

## Current Progress

### ✅ What's Working

- **Core Sentiment Analysis** — VADER-based NLP sentiment analysis is fully functional with financial-domain keyword enhancement (positive/negative word lists boost accuracy for market-related text).
- **Real-Time Stock Data** — Yahoo Finance API integration provides 30-day price history for 50+ US and Indian stocks, with automatic `.NS` suffix handling for NSE-listed stocks.
- **News Aggregation** — Real news is fetched from Yahoo Finance's search API, filtered for relevance, and analyzed per-article with sentiment/confidence scores.
- **Frontend Dashboard** — Fully styled, responsive UI with stock search, sentiment breakdown, price charts (Chart.js), keyword cloud, and market insights.
- **Market Indices** — Default market view for US (Dow Jones, S&P 500) and India (Nifty 50, Sensex).
- **Docker Deployment** — Production-ready `Dockerfile` using `python:3.11-slim` and `gunicorn`, deployable to Google Cloud Run.
- **Health Check Endpoint** — `/health` and `/ping` endpoints for Cloud Run readiness/liveness probes.

### 🔧 In Progress / Incomplete

| Area | Status | Notes |
|------|--------|-------|
| `app/routes/` | 🟡 Scaffolded only | Directory exists but contains no route modules — all routes are in `app.py` |
| `app/services/` | 🟡 Scaffolded only | Directory exists but contains no service modules — all logic is in `app.py` |
| `config/` | 🟡 Empty | No configuration files; all config is hardcoded or in `.env` |
| `tests/` | 🔴 No tests | Test directory exists but contains zero test files |
| `.github/workflows/` | 🔴 No CI/CD | Workflow directory exists but is empty — no automated testing or deployment pipelines |

---

## Known Flaws & Limitations

### Architecture

1. **Monolithic `app.py`** — The entire backend (946 lines) lives in a single file. Routes, business logic, data fetching, NLP processing, and utility functions are all co-located. The `app/routes/` and `app/services/` directories were scaffolded for modularization but remain unused.

2. **No Test Coverage** — The `tests/` directory is empty. There are no unit tests, integration tests, or end-to-end tests for any functionality.

3. **No CI/CD Pipeline** — `.github/workflows/` is empty. There is no automated build, test, or deployment process configured.

4. **Hardcoded Stock Lists** — The supported stock symbols and company names are duplicated as hardcoded dictionaries in multiple places within `app.py` (the Indian stocks list appears at least 3 times: lines 20–24, 636–691, 896–901).

### Data & API

5. **Yahoo Finance API Fragility** — The app scrapes Yahoo Finance's undocumented/unofficial API endpoints (`query1.finance.yahoo.com`). These endpoints are not guaranteed stable and may break without notice or impose rate limits.

6. **No API Caching** — Despite having a `CACHE_TTL_SECONDS` environment variable, there is no caching implementation in the application. Every request triggers fresh API calls to Yahoo Finance.

7. **No Authentication / Rate Limiting** — The application exposes its API endpoints without any form of authentication or rate limiting for incoming requests.

### Sentiment Analysis

8. **VADER Only (No FinBERT Integration)** — Although the **ProsusAI/FinBERT** model is downloaded and cached in `model_cache/`, the application **does not use it**. Sentiment analysis relies solely on VADER with custom financial keyword boosting. The FinBERT model appears to be prepared for future use but is not imported or called.

9. **Sentiment Data for Charts is Simulated** — The `generate_stock_sentiment_data()` function creates **randomly generated** sentiment-over-time data for the chart visualizations. This data does not reflect actual historical sentiment from news; it's a random walk correlated loosely with price movement.

---

## Fake / Placeholder / Mock Data

| What | Where | Why |
|------|-------|-----|
| **Simulated stock prices** | `get_simulated_stock_data()` (lines 101–133) | Used as a **fallback** when Yahoo Finance API calls fail. Generates 30 days of random-walk price data. Users see `"Simulated Data (Fallback)"` as the data source label. |
| **Simulated sentiment timeline** | `generate_stock_sentiment_data()` (lines 506–546) | **Always used** for the sentiment-over-time chart. Generates random sentiment scores loosely correlated with price movement using hardcoded volatility profiles per stock. This data does not come from actual news analysis. |
| **Generic fallback news** | `get_alternative_news()` (lines 263–295) | When real news scraping fails or returns fewer than 3 articles, **placeholder news items** are generated with titles like _"[Company] Stock Analysis - Indian Market Update"_ and fixed `Neutral` sentiment at 0.6 confidence. |
| **Hardcoded sentiment profiles** | `generate_stock_sentiment_data()` (lines 510–521) | Pre-defined base sentiment and volatility values for 10 US stocks (AAPL, MSFT, GOOGL, etc.). Other stocks default to `{ base_sentiment: 0.0, volatility: 0.4 }`. |
| **README live demo link** | `README.md` line 42 | Points to a Google Cloud Run URL — the deployed instance may or may not be active. The README notes it uses _"sample data and simulated market conditions for educational purposes."_ |

---

## Summary

The project is a **functional MVP** — the core sentiment analysis pipeline and frontend dashboard work end-to-end. However, it has significant technical debt:

- **No modularization** despite scaffolded directories
- **No tests or CI/CD**
- **Phantom FinBERT dependency** (downloaded but unused)
- **Mixed real and simulated data** without always making this transparent to the user
- The sentiment timeline chart in particular shows entirely fabricated data while appearing to be real analysis

The next logical steps would be: refactoring `app.py` into the `app/` package structure, integrating the cached FinBERT model, implementing actual historical sentiment tracking, adding tests, and setting up CI/CD.
