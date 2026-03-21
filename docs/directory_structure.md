# 📁 INFOEDGE — Directory Structure

> Complete directory layout of the **Stock Sentiment Analysis Platform** project.

```
infoedge/
│
├── .dockerignore              # Files/dirs excluded from Docker build context
├── .env                       # Environment variables (API keys, config)
├── .gcloudignore              # Files excluded from Google Cloud deployments
├── .gitignore                 # Git-ignored files and directories
├── Dockerfile                 # Docker container definition (Python 3.11-slim, gunicorn)
├── LICENSE                    # MIT License
├── README.md                  # Project overview, features, setup instructions
├── CODE_OF_CONDUCT.md         # Community code of conduct
├── CONTRIBUTING.md            # Contribution guidelines
├── PRIVACY.md                 # Privacy policy document
├── SECURITY.md                # Security policy and vulnerability reporting
├── requirements.txt           # Python dependencies (Flask, VADER, BS4, etc.)
├── app.py                     # Main Flask application — all backend logic (946 lines)
├── out.log                    # Application output log
│
├── .github/
│   └── workflows/             # GitHub Actions CI/CD workflow definitions (currently empty)
│
├── app/                       # Application package (modular structure — scaffolded)
│   ├── routes/                # Route blueprints (scaffolded, not yet populated)
│   └── services/              # Service layer modules (scaffolded, not yet populated)
│
├── config/                    # Configuration files directory (currently empty)
│
├── logs/
│   └── app.log                # Runtime application log file
│
├── model_cache/
│   ├── .locks/                # Hugging Face model lock files
│   └── models--ProsusAI--finbert/  # Cached FinBERT model for sentiment analysis
│
├── static/
│   ├── css/
│   │   └── style.css          # Main stylesheet (86 KB — full UI styling)
│   ├── js/
│   │   └── main.js            # Frontend JavaScript (16 KB — API calls, charts, interactivity)
│   └── photos/
│       ├── bg1.jpg            # Background image 1
│       ├── bg2.jpg            # Background image 2
│       ├── bg3.jpg            # Background image 3
│       └── bg4.jpg            # Background image 4
│
├── templates/
│   ├── base.html              # Jinja2 base template (shared layout, nav, footer)
│   ├── index.html             # Main dashboard page (85 KB — stock search, charts, results)
│   └── about.html             # About page
│
├── tests/                     # Test directory (scaffolded, no test files yet)
│
└── transformers_env/          # Python virtual environment for transformer models
```

---

## File & Folder Descriptions

### Root-Level Files

| File | Purpose |
|------|---------|
| `app.py` | **Core application file.** Contains the entire Flask backend: routes, VADER sentiment analysis, Yahoo Finance API integration, news scraping (BeautifulSoup), stock data processing, and API endpoints (`/api/analyze_sentiment`, `/api/search_stocks`, `/api/get_default_markets`). |
| `requirements.txt` | Lists Python dependencies: `Flask`, `gunicorn`, `requests`, `vaderSentiment`, `beautifulsoup4`, `lxml`, `Werkzeug`. |
| `Dockerfile` | Builds a production Docker image using `python:3.11-slim`, installs dependencies, creates a non-root user, and runs via `gunicorn` on port `8080`. |
| `.env` | Stores environment variables including `FINNHUB_API_KEY` and `CACHE_TTL_SECONDS`. |
| `README.md` | Comprehensive project documentation: features, tech stack, supported markets, installation, Docker deployment, and contribution guidelines. |
| `LICENSE` | MIT License. |
| `CODE_OF_CONDUCT.md` | Community conduct standards. |
| `CONTRIBUTING.md` | Step-by-step guide for contributors (fork, branch, PR workflow). |
| `PRIVACY.md` | Privacy policy detailing data handling practices. |
| `SECURITY.md` | Security policy and vulnerability disclosure procedures. |

### Directories

| Directory | Purpose |
|-----------|---------|
| `.github/workflows/` | Intended for GitHub Actions CI/CD pipelines. **Currently empty** — no workflows configured yet. |
| `app/` | Scaffolded modular application package with `routes/` and `services/` sub-packages. **Not yet populated** — all logic currently resides in `app.py`. |
| `config/` | Placeholder for external configuration files. **Currently empty.** |
| `logs/` | Stores runtime logs. Contains `app.log` with application-level log entries. |
| `model_cache/` | Hugging Face cache for downloaded models. Contains the **ProsusAI/FinBERT** model used for financial sentiment analysis. |
| `static/` | Frontend static assets — CSS, JavaScript, and background images. |
| `templates/` | Jinja2 HTML templates rendered by Flask. `base.html` provides the shared layout; `index.html` is the main dashboard; `about.html` is the informational page. |
| `tests/` | Intended for unit/integration tests. **Currently empty** — no tests written yet. |
| `transformers_env/` | Local Python virtual environment containing transformer model dependencies. |
