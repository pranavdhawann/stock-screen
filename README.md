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

### AI Forecasting Engine
Short-horizon LSTM forecasts from recent OHLCV history, with server-side usage controls for the public demo.

---

## Project Structure

```
app/             - Flask routes, services, and config
lstm/            - Forecasting model and inference helpers
static/          - CSS, JavaScript (client-side)
templates/       - Jinja2 HTML templates
tests/           - Regression and security tests
wsgi.py          - Production WSGI entrypoint
Dockerfile       - Production container config
requirements.txt - Production Python dependencies
requirements-dev.txt - Local test dependencies
.env.example     - Environment variable template
```

---

## Local Development

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m flask --app app:create_app run
```

Required runtime values are documented in `.env.example`. `GROQ_API_KEY` enables AI summaries and sentiment analysis. `SECRET_KEY` should be set for any deployed environment. `SEC_EDGAR_USER_AGENT` must identify the app/contact for SEC EDGAR requests. Set `TRUST_PROXY_HEADERS=true` only when the app is deployed behind a trusted proxy that controls `X-Forwarded-For`. `MAX_CONTENT_LENGTH` defaults to 1 MiB to reject oversized API bodies.

## Supabase

Supabase is used only from the Flask backend through `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. Do not expose the service key to browser code. If Supabase is not configured, cache lookups fall back to in-memory `cachetools` caches.

The connected `infoedge` project stores persistent cache tables in `public`. RLS is enabled with server-role-only policies, anon/authenticated table grants are revoked, and the app accesses those tables only from backend routes. Expired cache rows can be pruned with `public.cleanup_expired_cache()`.

## API Providers and Rate Limits

Provider usage is backend-owned unless noted otherwise:

| Provider | Used for | App bucket |
| --- | --- | --- |
| Yahoo Finance chart API | OHLCV, stock charts, LSTM forecast inputs | No explicit app bucket on market/chart endpoints |
| Google News RSS + MarketWatch RSS | Free public news aggregation | `public_news`: 60/hour per client |
| Finnhub | Optional ticker-specific company news | `public_news`: 60/hour per client |
| Currents API | Optional market headlines | `public_news`: 60/hour per client |
| NewsAPI + Alpha Vantage | Optional multi-source news enrichment | Called through sentiment/news aggregation flows |
| Groq | Sentiment analysis, AI insights, filing summaries | `analyze_sentiment`, `filing_summary`, `filings_overview`: 20/hour per client |
| EmailJS | Contact form delivery | `contact`: 5/hour per client |
| Supabase | Persistent cache and rate-limit RPC | Server-side only via service key |

Forecasting uses the bundled local LSTM checkpoint and is limited to `forecast`: 1 run per 30 days per client. Source code can prove which providers are wired and how the app rate-limits them, but it cannot prove whether the connected vendor accounts are on free, paid, trial, or overage-enabled plans; verify that in each provider dashboard.

## Tests

```powershell
python -m pytest -q
python -m compileall app lstm
```

The regression suite covers startup/import safety, server-side forecast quota enforcement, frontend DOM/fetch hardening, cache cleanup contracts, and LSTM checkpoint loading safeguards.

## Production

The container starts Gunicorn from `wsgi:app` and copies both `app/` and `lstm/` so the forecast endpoint can load the bundled model artifact. Production startup fails if `SECRET_KEY` is missing.

```powershell
docker build -t infoedge .
docker run --env-file .env -p 8080:8080 infoedge
```

### GCP Cloud Run Release Contract

The live deployment is GCP Cloud Run. Do not deploy secret values as plain environment variables. Store `SECRET_KEY`, `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FINNHUB_API_KEY`, `CURRENTS_API_KEY`, and other provider keys in Secret Manager, then wire them with `--set-secrets` or `--update-secrets`.

Use a dedicated runtime service account instead of the default Compute Engine service account, and grant it only `roles/secretmanager.secretAccessor` for the secrets this service reads.

Before the next production deploy, enable Secret Manager, create new secret versions, rotate any provider keys that were previously configured as plain Cloud Run environment variables, and then deploy only Secret Manager references.

```powershell
gcloud services enable secretmanager.googleapis.com
gcloud iam service-accounts create infoedge-runner --display-name "Infoedge Cloud Run runtime"
gcloud secrets add-iam-policy-binding infoedge-secret-key `
  --member serviceAccount:infoedge-runner@PROJECT_ID.iam.gserviceaccount.com `
  --role roles/secretmanager.secretAccessor
```

Repeat the per-secret IAM binding for each secret wired to the service.

Example shape, with secret names adjusted to the GCP project:

```powershell
gcloud run deploy stock-screen `
  --region us-central1 `
  --source . `
  --service-account infoedge-runner@PROJECT_ID.iam.gserviceaccount.com `
  --set-env-vars FLASK_ENV=production,LOG_LEVEL=INFO,TRUST_PROXY_HEADERS=false,MAX_CONTENT_LENGTH=1048576 `
  --set-secrets SECRET_KEY=infoedge-secret-key:latest,GROQ_API_KEY=infoedge-groq-api-key:latest,SUPABASE_URL=infoedge-supabase-url:latest,SUPABASE_SERVICE_KEY=infoedge-supabase-service-key:latest `
  --allow-unauthenticated
```

Post-deploy checks:

```powershell
python -m pytest -q
python -m compileall app lstm
node --check static\js\index-page.js
node --check static\js\main.js
node --check static\js\contact.js
curl.exe -sS -D - -o NUL https://stock-screen-25476982226.us-central1.run.app/ |
  Select-String -Pattern "content-security-policy:|strict-transport-security:|permissions-policy:|x-frame-options:|x-content-type-options:|referrer-policy:" -CaseSensitive:$false
```

For stronger public protection, place Cloud Run behind an external HTTPS load balancer with Cloud Armor and set service ingress to `internal-and-cloud-load-balancing`, so traffic reaches the app through the protected load balancer path rather than directly through the `run.app` URL.

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
