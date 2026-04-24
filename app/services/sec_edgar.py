import requests
import logging
from urllib.parse import urlparse
from groq import Groq
from app.config import SEC_EDGAR_HEADERS, GROQ_API_KEY, GROQ_MODEL
from app.services.cache import sec_filings_cache, get_cached, set_cached

logger = logging.getLogger(__name__)

_client = None
_cik_map = None
_SEC_ALLOWED_HOSTS = {"sec.gov", "www.sec.gov"}


def _get_client():
    global _client
    if _client is None and GROQ_API_KEY:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def is_allowed_sec_url(url):
    """Return True only for SEC-hosted HTTPS filing archive URLs."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    hostname = (parsed.hostname or "").lower()
    if hostname not in _SEC_ALLOWED_HOSTS:
        return False

    # Limit to filing archive pages to reduce SSRF surface.
    return parsed.path.startswith("/Archives/")


def _load_cik_map():
    """Load full ticker-to-CIK mapping from SEC."""
    global _cik_map
    if _cik_map is not None:
        return _cik_map
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_EDGAR_HEADERS, timeout=10,
        )
        data = resp.json()
        _cik_map = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in data.values()
        }
    except Exception as e:
        logger.error("Failed to load CIK map: %s", e)
        _cik_map = {}
    return _cik_map


def get_cik_for_ticker(ticker):
    """Get CIK number for a ticker symbol."""
    cik_map = _load_cik_map()
    return cik_map.get(ticker.upper())


def fetch_filings(ticker, filing_types=None, count=10):
    """Fetch recent SEC filings for a ticker."""
    if filing_types is None:
        filing_types = ["10-K", "10-Q", "8-K"]

    cache_key = f"{ticker}_{'_'.join(filing_types)}"
    cached = get_cached(sec_filings_cache, cache_key)
    if cached is not None:
        return cached

    cik = get_cik_for_ticker(ticker)
    if not cik:
        return {"error": f"No CIK found for {ticker}. SEC filings are only available for US-listed companies.", "filings": []}

    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=SEC_EDGAR_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        filings = []
        row_count = min(len(forms), len(dates), len(accessions))
        for i in range(row_count):
            if forms[i] in filing_types:
                accession_clean = accessions[i].replace("-", "")
                cik_num = cik.lstrip("0")
                doc = primary_docs[i] if i < len(primary_docs) else ""
                filings.append({
                    "form": forms[i],
                    "filing_date": dates[i],
                    "accession": accessions[i],
                    "description": descriptions[i] if i < len(descriptions) else forms[i],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{doc}" if doc else "",
                })
                if len(filings) >= count:
                    break

        result = {
            "ticker": ticker,
            "cik": cik,
            "company_name": data.get("name", ticker),
            "filings": filings,
        }
        set_cached(sec_filings_cache, cache_key, result)
        return result

    except Exception as e:
        logger.error("Error fetching SEC filings for %s: %s", ticker, e)
        return {"error": str(e), "filings": []}


def summarize_filing(filing_url, filing_type, company_name):
    """Use Groq to generate a readable summary of a filing."""
    client = _get_client()
    if not client:
        return {"summary": "AI summary unavailable (no API key configured)"}

    if not is_allowed_sec_url(filing_url):
        return {"summary": "Invalid filing URL. Only SEC EDGAR filing archive URLs are allowed."}

    try:
        resp = requests.get(filing_url, headers=SEC_EDGAR_HEADERS, timeout=15)
        resp.raise_for_status()
        content = resp.text[:8000]
    except Exception:
        return {"summary": "Unable to fetch filing content from SEC."}

    prompt = f"""Summarize this SEC {filing_type} filing for {company_name}.
Provide:
1. Key Highlights (3-5 bullet points)
2. Financial Metrics Mentioned (revenue, net income, EPS if available)
3. Notable Risks or Opportunities
4. One-sentence Executive Summary

Filing excerpt:
{content}

Respond in plain text with clear section headers."""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a financial analyst who summarizes SEC filings clearly and concisely for investors."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return {"summary": response.choices[0].message.content.strip()}
    except Exception as e:
        logger.error("Error summarizing filing: %s", e)
        return {"summary": f"Error generating summary: {str(e)}"}


def generate_filings_overview(filings, company_name, ticker):
    """Generate an AI overview paragraph based on the filing list."""
    client = _get_client()
    if not client or not filings:
        return {"overview": "AI overview unavailable."}

    type_counts = {}
    for f in filings:
        type_counts[f["form"]] = type_counts.get(f["form"], 0) + 1

    filing_summary = ", ".join(f"{count} {ftype}" for ftype, count in type_counts.items())
    dates = [f["filing_date"] for f in filings]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"

    prompt = f"""Write a concise 2-3 sentence overview of {company_name} ({ticker})'s SEC filing activity.
They have {len(filings)} recent filings ({filing_summary}) spanning {date_range}.
Focus on what this filing pattern suggests about the company's regulatory activity and disclosure frequency.
Respond with just the overview paragraph, no headers or bullet points."""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a financial analyst providing brief company overviews based on SEC filing patterns."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=256,
        )
        return {"overview": response.choices[0].message.content.strip()}
    except Exception as e:
        logger.error("Error generating filings overview: %s", e)
        return {"overview": f"Unable to generate overview: {str(e)}"}
