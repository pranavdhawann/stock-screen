## Security Policy

### Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.** Instead, use GitHub's private security advisory feature:

1. Visit https://github.com/pranavdhawann/stock-screen/security/advisories/new
2. Click **"Report a vulnerability"**
3. Provide a clear description, steps to reproduce, and impact assessment
4. Submit

Your report will be visible only to the maintainer (@pranavdhawann) and will not be disclosed publicly until a fix is available.

Alternatively, if you cannot use the GitHub interface, please open a private security advisory draft and notify [@pranavdhawann](https://github.com/pranavdhawann) through a direct message on GitHub.

### Response Timeline

We aim to acknowledge reported vulnerabilities within **7 days** and release a fix or mitigation guidance within **30 days** if feasible. Response times depend on severity, complexity, and our availability — these are goals, not contractual SLAs.

### Supported Versions

**Stock Screen is a single deployed application off the `main` branch.** There are no maintained release branches or long-term support versions. Security updates are deployed directly to the live instance at https://stock-screen-25476982226.us-central1.run.app/ and automatically pushed via GitHub Actions.

If you run a fork or modified version locally, keep your dependencies up to date using `pip install --upgrade -r requirements.txt`.

### Security Scope

This project takes the following security measures seriously:

#### Web Application Security

- **Content Security Policy (CSP):** Per-request nonces on inline `<script>` tags, plus a host allowlist for `script-src`. CDN resources use Subresource Integrity (SRI) hashes. `object-src`, `frame-ancestors` are `'none'`; `base-uri` and `form-action` are `'self'`. Known gap: `style-src` still carries `'unsafe-inline'`, because several templates use inline `style="..."` attributes, which CSP nonces cannot cover. Removing it requires migrating those attributes to stylesheet classes first. `script-src` does **not** allow `unsafe-inline` or `unsafe-eval`.
- **Secure headers:** Strict-Transport-Security (HSTS), X-Content-Type-Options, X-Frame-Options, Permissions-Policy (geolocation, payment, microphone disabled).
- **Input validation:** All user input (symbols, email, passwords, search queries) validated server-side. Invalid symbols rejected with 400 responses. Market parameter restricted to `US` or `IN`.
- **Output encoding:** HTML context uses template escaping. Client-side DOM construction avoids interpolation of untrusted values.

#### Rate Limiting & Abuse Prevention

- **Server-side quotas:** Enforced via a Postgres RPC with advisory locks, survives restarts and scales across instances.
- **Public API limits:** News endpoints (60/hour), AI analysis (20/hour), forecasts (1 per 30 days), contact form (5/hour).
- **Honeypot:** Contact form includes a hidden field to catch automated spam bots.

#### Authentication & Session Security

- **Password hashing:** PBKDF2-based (Werkzeug's `generate_password_hash` / `check_password_hash`).
- **Session cookies:** HttpOnly flag set to prevent JavaScript access. SameSite=Lax to mitigate CSRF. Secure flag set in production (HTTPS only).
- **Session lifetime:** 30 days. Cleared on logout.

#### Third-Party & Upstream Security

- **API key storage:** Sensitive keys stored in GCP Secret Manager (production) or `.env` (local). Never committed to git.
- **SSRF prevention:** Allowlist on SEC EDGAR and Indian BSE/NSE URLs to prevent server-side request forgery. Only whitelisted domains are fetched.
- **XML parsing:** Uses `defusedxml` to prevent XXE attacks in RSS/XML parsing.
- **Dependency scanning:** `requirements.txt` pinned to known-good versions. Keep torch and scikit-learn updated.

#### Data Protection

- **Supabase RLS:** Row-level security is enabled on every table, and the policies grant access to the `service_role` only — `anon` and `authenticated` are revoked outright, and default privileges are revoked for future objects too. The Flask backend is the sole database client. Note that this means per-user authorization (e.g. "you may only read your own watchlist") is enforced in the application layer, scoped by the session `uid`, **not** by row-level policies. A bug in the Flask layer would not be caught by RLS.
- **Password storage:** PBKDF2 hashes via Werkzeug. Login performs a hash comparison even for unknown accounts so response timing does not reveal whether an email is registered. Sign-up still returns a distinct response for an already-registered email (a deliberate UX trade-off), rate-limited to 5/hour.
- **No PII at scale:** App does not store financial transaction history, portfolio details, or behavior tracking (analytics use privacy-friendly Umami).

### Out of Scope

The following are **not** considered in-scope vulnerabilities for this project:

- **Volumetric DoS attacks** (e.g., sending gigabytes of traffic to flood the public demo). Cloud Run auto-scales, but there is no SLA for free public access.
- **Rate-limit exhaustion on the public demo** (e.g., cycling through IPs to exceed quotas). The demo has intentionally low limits to prevent abuse; this is not a security bug.
- **Self-XSS** (e.g., storing malicious data in a watchlist that affects only the attacker). Self-inflicted harm without server-side validation issues is not in scope.
- **Missing security headers with no demonstrated impact** (e.g., a missing secondary header that does not weaken the primary policy).
- **Vulnerabilities in third-party services** (Groq API, Yahoo Finance, SEC EDGAR, Supabase, Google Cloud) that are not mitigated in Stock Screen code.
- **Local privilege escalation or client-side OS attacks** (the app does not claim to protect against malware on the user's machine).

### Educational & Informational Tool

**Stock Screen is for informational and educational purposes only. It is not financial advice.** The app provides price data, news aggregation, AI-generated sentiment analysis, and LSTM forecasts as a learning tool. Markets are risky; models are wrong; do your own research.

Users should not rely solely on this tool for investment decisions. Financial decisions should involve independent research, consultation with a licensed financial advisor, and careful risk assessment. The creators and maintainers of Stock Screen assume no liability for trading losses or financial harm resulting from use of the application.

### Acknowledgments

We appreciate responsible disclosure. If you find a genuine security vulnerability and report it privately, you will be credited in the fix commit and release notes (unless you prefer anonymity).
