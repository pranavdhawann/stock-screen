from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from app.config import GROQ_MODEL, get_stock_metadata
from app.services.groq_guard import get_client as _get_client, note_groq_error

logger = logging.getLogger(__name__)

_ALLOWED_ARCHIVE_PATHS = {
    "www.bseindia.com": (
        "/xml-data/corpfiling/attachlive/",
        "/xml-data/corpfiling/attachhis/",
    ),
    "nsearchives.nseindia.com": (
        "/corporate/",
    ),
}
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockScreen/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.bseindia.com/",
}


def is_allowed_indian_filing_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    hostname = (parsed.hostname or "").lower()
    allowed_prefixes = _ALLOWED_ARCHIVE_PATHS.get(hostname)
    if not allowed_prefixes:
        return False
    path = parsed.path.lower()
    return any(path.startswith(prefix) for prefix in allowed_prefixes)


def _fetch_bse_announcements(symbol: str, count: int) -> list[dict]:
    meta = get_stock_metadata(symbol)
    bse_code = meta.get("bse_code")
    if not bse_code:
        return []

    response = requests.get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w",
        params={
            "strCat": "-1",
            "strPrevDate": "",
            "strScrip": bse_code,
            "strSearch": "P",
            "strToDate": "",
            "strType": "C",
            "subcategory": "-1",
        },
        headers=_BSE_HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("Table") or payload.get("table") or []

    filings = []
    for row in rows[:count]:
        headline = row.get("HEADLINE") or row.get("NEWSSUB") or row.get("SLONGNAME") or "Corporate Announcement"
        date = row.get("NEWS_DT") or row.get("DT_TM") or row.get("DissemDT")
        attachment = row.get("ATTACHMENTNAME") or row.get("NSURL") or ""
        if attachment and not attachment.startswith("http"):
            attachment = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}"
        filing_type = _classify_indian_filing(headline)
        filings.append(
            {
                "form": filing_type,
                "filing_date": _normalize_date(date),
                "description": headline,
                "url": attachment if is_allowed_indian_filing_url(attachment) else "",
                "source": "BSE",
            }
        )
    return filings


def _classify_indian_filing(text: str) -> str:
    lowered = (text or "").lower()
    if "annual report" in lowered:
        return "Annual Report"
    if "financial result" in lowered or "results" in lowered:
        return "Financial Results"
    if "shareholding" in lowered:
        return "Shareholding Pattern"
    return "Corporate Announcement"


def _normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y"):
        parsed = _parse_date_prefix(text, fmt)
        if parsed:
            return parsed
    return text[:10]


def _parse_date_prefix(text: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(text[: len(fmt)], fmt).date().isoformat()
    except ValueError:
        return None


def fetch_indian_filings(ticker: str, filing_types: list[str], count: int = 10) -> dict:
    ticker = ticker.upper()
    company_name = get_stock_metadata(ticker).get("name", ticker)
    try:
        filings = _fetch_bse_announcements(ticker, count)
    except Exception as exc:
        logger.warning("BSE filing fetch failed for %s: %s", ticker, exc)
        filings = []

    selected = set(filing_types or [])
    if selected:
        filings = [filing for filing in filings if filing.get("form") in selected]

    return {
        "ticker": ticker,
        "company_name": company_name,
        "market": "IN",
        "filings": filings[:count],
        "error": None if filings else "No Indian filings found from BSE for this symbol.",
    }


def _fetch_text(url: str, byte_limit: int = 600_000) -> str:
    with requests.get(url, headers=_BSE_HEADERS, timeout=15, stream=True) as response:
        response.raise_for_status()
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
            if not chunk:
                continue
            total += len(chunk)
            if total > byte_limit:
                remaining = byte_limit - (total - len(chunk))
                chunks.append(chunk[: max(0, remaining)])
                break
            chunks.append(chunk)
        return "".join(chunks)


def summarize_indian_filing(url: str, filing_type: str, company_name: str) -> dict:
    if not is_allowed_indian_filing_url(url):
        return {"summary": "Invalid filing URL. Only official BSE and NSE filing archive URLs are allowed."}

    client = _get_client()
    if not client:
        return {"summary": "AI summary unavailable (no API key configured)."}

    try:
        content = _fetch_text(url)[:8000]
    except Exception as exc:
        logger.warning("Indian filing fetch failed: %s", exc)
        return {"summary": "Unable to fetch filing content from the exchange archive."}

    prompt = f"""Summarize this Indian market {filing_type} filing for {company_name}.
Provide key highlights, important dates or numbers, notable risks, and a one-sentence investor takeaway.

Filing excerpt:
{content}

Respond in plain text with concise section headers."""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You summarize official Indian exchange filings for investors."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return {"summary": response.choices[0].message.content.strip()}
    except Exception as exc:
        logger.warning("Indian filing summary failed: %s", exc)
        note_groq_error(exc)
        return {"summary": "Unable to generate summary right now."}


def generate_indian_filings_overview(filings: list[dict], company_name: str, ticker: str) -> dict:
    if not filings:
        return {"overview": "No filings to analyze."}
    counts: dict[str, int] = {}
    for filing in filings:
        form = filing.get("form", "Filing")
        counts[form] = counts.get(form, 0) + 1
    summary = ", ".join(f"{count} {form}" for form, count in counts.items())
    return {
        "overview": (
            f"{company_name or ticker} has {len(filings)} recent Indian exchange filings "
            f"covering {summary}. Review the latest disclosures directly before relying on this summary."
        )
    }
