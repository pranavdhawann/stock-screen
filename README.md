# Stock Screen — AI Stock Sentiment Analysis & Market Intelligence

Real-time sentiment analysis for US and Indian stocks. Aggregates news from multiple sources, analyzes it with Groq (Llama 3.3 70B), surfaces SEC filings, and delivers actionable market intelligence.

[![Live](https://img.shields.io/badge/Live-stockscreen.app-brightgreen?style=flat-square)](https://stock-sentiment-app-egc2jnomta-uc.a.run.app)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![GCP Cloud Run](https://img.shields.io/badge/GCP-Cloud%20Run-4285F4?style=flat-square&logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

## Features

- **AI Sentiment Analysis** — Groq LLM scores news sentiment with confidence metrics for any stock
- **Multi-Source News** — Aggregates from Yahoo Finance, NewsAPI, Finnhub, and Alpha Vantage in parallel
- **SEC EDGAR Filings** — Browse 10-K, 10-Q, 8-K filings with AI-generated summaries
- **US + Indian Markets** — 50+ stocks across NYSE, NASDAQ, NSE, BSE with live index tracking
- **AI Market Insights** — LLM-generated analysis of sentiment drivers, risks, and market context
- **Interactive Charts** — Price history and sentiment trends via Chart.js

## Stack

Python · Flask · Groq API (Llama 3.3 70B) · Yahoo Finance · SEC EDGAR · Bootstrap 5 · Docker · Google Cloud Run

## Run Locally

```bash
git clone https://github.com/pranavdhawann/stockscreen.git
cd stockscreen
cp .env.example .env   # add your GROQ_API_KEY
pip install -r requirements.txt
python app.py
```

## License

MIT. Not financial advice.
