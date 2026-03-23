# Stock Screen — AI-Powered Stock Sentiment & Market Intelligence

**Real-time stock analysis, news sentiment scoring, SEC filing intelligence, and AI forecasting — all in one terminal-style dashboard.**

[![Live Demo](https://img.shields.io/badge/Live%20Demo-stock--screen-FFD700?style=for-the-badge&logo=google-cloud&logoColor=white)](https://stock-screen-25476982226.us-central1.run.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-Production-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com)

---

## Features

### Market Sentiment Analysis
Analyze any US or Indian stock with AI-powered sentiment scoring. Aggregates news from multiple sources, scores each article, and produces an overall bullish/bearish/neutral verdict with confidence levels.

### Multi-Source News Aggregation
Pulls financial news from Google RSS, MarketWatch, Finnhub, and Currents API. Deduplicates, ranks by relevance, and presents a unified news feed per ticker.

### SEC Filing Intelligence
Search and summarize SEC EDGAR filings (10-K, 10-Q, 8-K) using large language models. Get AI-generated overviews of a company's latest regulatory disclosures.

### Interactive Charts
Price charts with 30-day, 1-year, and 5-year views. Sentiment trend overlays. Powered by Chart.js.

### AI Forecasting Engine *(Coming Soon)*
Graph Neural Networks combining price patterns, news sentiment, stock correlations, SEC filings, and time-series data for directional predictions.

---

## Project Structure

```
static/          → CSS, JavaScript (client-side)
templates/       → Jinja2 HTML templates
Dockerfile       → Production container config
requirements.txt → Python dependencies
.env.example     → Environment variable template
```

> Backend source (routes, services, config) is not included in this repository.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

**Disclaimer:** Stock Screen is for informational and educational purposes only. It is not financial advice. Always do your own research before making investment decisions.

---

<p align="center">
  <a href="https://stock-screen-25476982226.us-central1.run.app/">
    <strong>Try the Live Demo</strong>
  </a>
</p>
