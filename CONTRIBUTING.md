## Contributing to Stock Screen

Issues and pull requests are welcome. This guide covers local setup, project structure, testing expectations, and ground rules.

### Local Development

**Clone and set up the environment:**

```bash
git clone https://github.com/pranavdhawann/stock-screen.git
cd stock-screen

python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
cp .env.example .env               # Windows: Copy-Item .env.example .env
```

**Run the development server:**

```bash
flask --app app:create_app run
```

Open http://127.0.0.1:5000. Market data and news work out of the box with zero API keys (Yahoo Finance + free RSS). Add keys to `.env` as you explore new features.

### Project Map

```
app/
  __init__.py           Flask app factory, security headers, session config
  config.py             Stock directory, API keys, cache settings, TTLs
  routes/
    main.py             Page routes (/, /about, /sec-filings, /forecasting) + health checks
    api.py              JSON endpoints (search, analyze, forecast, filings, quotes, contact)
    account.py          Sign-up/login/watchlist mutations, PBKDF2 password hashing
  services/
    stock_data.py       Yahoo Finance OHLCV + quotes
    news.py             Yahoo Finance search API, single-source news fetch
    news_aggregator.py  Multi-source news (Google/MarketWatch RSS, NewsAPI,
                        Finnhub, Alpha Vantage) with dedup + relevance ranking
    sentiment.py        Groq LLM headline sentiment + finance-lexicon fallback
    insights.py         Market verdict, catalysts, risks, keyword extraction
    sec_edgar.py        SEC EDGAR 10-K/10-Q/8-K fetching, parsing, AI summaries
    bse_filings.py      Indian BSE/NSE disclosures + AI summaries
    forecasting.py      LSTM model inference (bundled PyTorch checkpoint)
    indicators.py       Technical analysis (SMA, EMA, Bollinger, RSI, MACD)
    cache.py            Hybrid in-memory TTL + Supabase caching layer
    rate_limit.py       Server-side quota enforcement (durable RPC-backed)
    groq_guard.py       Circuit breaker + shared client for the Groq API
    validation.py       Shared symbol/email validation used by both blueprints
    supabase_client.py  Supabase service-role client (cache, quotas, accounts)

lstm/
  __init__.py           Makes `lstm` a real package; import via `lstm.src.*`
  model.pt              Bundled trained checkpoint loaded at inference time
  src/models/lstm.py    LSTMForecaster network definition
  src/preprocessing/    Feature engineering (features.py) and splits.py
  src/data/loader.py    OHLCV loading helpers
  src/utils/            Config and seeding helpers
  cli_legacy/           Legacy training/forecast CLI — unsupported, not used
                        by the web app

static/
  js/                   Vanilla JavaScript (Chart.js, utils, no build step)
  css/                  Terminal UI styling

templates/
  base.html             Layout, CSP nonce injection, SRI-pinned CDN scripts,
                        contact + auth modals (sign-in is a modal, not a page)
  index.html            Dashboard, tabs, responsive grid
  (others)              about.html, sec_filings.html, forecasting.html

supabase/
  migrations/           PostgreSQL schema, RLS policies, rate-limit RPC, pg_cron cleanup

tests/
  test_audit_regressions.py    Startup, security headers, XSS/SSRF hardening.
                               Several tests grep raw source text — if you move
                               code between files, check this file still matches.
  test_terminal_features.py    API behavior, rate limits, symbol validation
  test_accounts.py             Sign-up, login, watchlist mutations
  test_sentiment_history.py    Sentiment caching and fallback
  test_client_identity.py      X-Forwarded-For parsing, rate-limit key derivation
  test_news_cache_isolation.py Cached news items are never mutated in place
  test_ops_hardening.py        Request-body limit fallback, CSP invariants
  test_lstm_packaging.py       lstm imports cleanly without sys.path hacks

.github/
  workflows/deploy.yml  CI: pytest on PRs, auto-deploy main to Cloud Run
  PULL_REQUEST_TEMPLATE.md
```

### Running Tests

```bash
python -m pytest -q
```

The whole suite must pass before submitting. It covers:

- Startup safety (app factory, WSGI, imports)
- Server-side quota enforcement (rate limits hold across instances)
- XSS hardening (CSP nonces, SRI pinning, whitelisted CSS classes)
- SSRF protection (filing-URL allowlists)
- Cache cleanup contracts
- Supabase migration invariants
- Password hashing and session security
- Symbol validation and market routing

Run tests locally before pushing. CI runs them again on every pull request and blocks merge if they fail.

### CI/CD Pipeline

- **On every pull request:** pytest runs in Ubuntu with Python 3.11 and CPU torch. Must pass to merge.
- **On push to main:** Same test suite runs, then auto-deploys to GCP Cloud Run via keyless WIF auth.
- **Smoke test:** After deployment, a curl to `/ping` confirms the service is live.

Never commit secrets to `.env` or lock files. Use GCP Secret Manager for production keys.

### Code Style

Match the existing code:

- **Functions:** Plain module-level functions (not classes) where possible. Use `functools.wraps` for decorators.
- **Logging:** Add `logger = logging.getLogger(__name__)` at the top of each module. Log errors, warnings, and key decisions—not debug noise unless `LOG_LEVEL=DEBUG`.
- **Type hints:** Older modules have minimal or no type hints. Newer code uses `from __future__ import annotations`. If you add hints, be consistent within the file.
- **Error handling:** Catch broad exceptions, log them, and return user-friendly JSON or HTML. Never leak stack traces to clients.
- **Security:** Validate all user input server-side. Use parameterized queries or ORM methods. Escape/sanitize for the context (HTML, SQL, URL).
- **Terminal UI:** Keep it dense and dark. Use the existing Chart.js + vanilla JS pattern. No heavy frameworks or build steps.

**Checklist before submitting:**

- [ ] `python -m pytest -q` passes
- [ ] No secrets, API keys, or `.env` files in the diff
- [ ] Server-side validation added for any new user input
- [ ] UI changes keep the dense dark-terminal style
- [ ] Manually tested the affected page/endpoint in a browser

### Good First Contributions

The README highlights areas perfect for getting started:

- **📈 Add symbols** — Extend the stock directory in `app/config.py` with ticker/company-name pairs. Yahoo Finance works for most US stocks; Indian stocks need `.NS` suffixes.
- **🌐 New news sources** — Implement a fetcher function in `app/services/news_aggregator.py` following the existing pattern (handle errors gracefully, return a list of dicts with title/summary/link/publisher/published timestamp).
- **🧪 More regression tests** — Write pytest tests in `tests/`. Focus on edge cases, error handling, and security boundaries.
- **🎨 Terminal UI polish** — Improve spacing, readability, mobile responsiveness, or dark-theme consistency in `templates/` and `static/js/`. Keep it minimal and dense.

Open an issue first if you're unsure whether an idea fits the roadmap.

### Questions?

See the main [README.md](README.md), check existing [issues](https://github.com/pranavdhawann/stock-screen/issues), or ask in a new issue. Thanks for contributing!
