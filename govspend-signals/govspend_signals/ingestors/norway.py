"""Norway SWF (Norges Bank) ingestor — reads 13F-HR, SC 13D/13G filings via SEC EDGAR."""
from __future__ import annotations

import sys
import threading
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

_NORGES_CIK = "1463737"
_NORGES_CIK_PADDED = f"CIK{_NORGES_CIK.zfill(10)}"
_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/{_NORGES_CIK_PADDED}.json"
_EDGAR_INDEX_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=40"

_TARGET_FORMS = {"13F-HR", "SC 13G", "SC 13D"}

_rate_lock = threading.Lock()
_last_call: float = 0.0


def _rate_limited_get(
    session: requests.Session,
    url: str,
    user_agent: str,
    rate_per_second: float,
    max_retries: int = 3,
) -> requests.Response:
    """GET with rate limiting and exponential backoff on 429/503."""
    global _last_call

    with _rate_lock:
        now = time.monotonic()
        gap = 1.0 / rate_per_second
        wait = gap - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()

    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    delay = 1.0
    for attempt in range(max_retries):
        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code in (429, 503):
            print(
                f"[norway] Rate limited ({resp.status_code}), backing off {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
            continue
        return resp
    # Last attempt — raise whatever we get
    resp.raise_for_status()
    return resp


def _accession_to_url(cik: str, accession: str) -> str:
    """Build an EDGAR filing index URL from a CIK and accession number."""
    acc_clean = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/full-index/{cik}/{acc_clean}-index.htm"


def _accession_to_index_url(accession: str) -> str:
    """Build the canonical /Archives/edgar/... index URL."""
    # accession format: 0001234567-24-000001
    parts = accession.split("-")
    if len(parts) == 3:
        cik_part, year_part, seq_part = parts
        path = f"{cik_part}/{cik_part}{year_part}{seq_part}"
    else:
        path = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/full-index/{path}-index.htm"


def ingest(
    user_agent: str,
    lookback_days: int,
    rate_per_second: float = 8.0,
) -> list[Signal]:
    """Fetch Norges Bank (Norway SWF) SEC filings.

    Parameters
    ----------
    user_agent:
        Required by SEC EDGAR (e.g. ``"MyApp name@example.com"``).
    lookback_days:
        Maximum age (in days) of filings to include.
    rate_per_second:
        EDGAR API call rate limit (SEC recommends ≤ 10/s).

    Returns
    -------
    list[Signal]
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    session = requests.Session()

    try:
        resp = _rate_limited_get(session, _SUBMISSIONS_URL, user_agent, rate_per_second)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as exc:
        print(f"[norway] HTTP error fetching submissions: {exc}", file=sys.stderr)
        return []
    except requests.RequestException as exc:
        print(f"[norway] Request error fetching submissions: {exc}", file=sys.stderr)
        return []
    except ValueError as exc:
        print(f"[norway] JSON parse error: {exc}", file=sys.stderr)
        return []

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    filing_dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    primary_descriptions = filings.get("primaryDocDescription", [])

    signals: list[Signal] = []

    for i, form in enumerate(forms):
        form = (form or "").strip()
        if form not in _TARGET_FORMS:
            continue

        filing_date_raw = filing_dates[i] if i < len(filing_dates) else ""
        try:
            filing_date = date.fromisoformat(str(filing_date_raw)[:10])
        except ValueError:
            continue

        if filing_date < cutoff:
            continue

        accession = accessions[i] if i < len(accessions) else ""
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        primary_desc = primary_descriptions[i] if i < len(primary_descriptions) else ""

        # Build EDGAR filing URL
        acc_clean = accession.replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/full-index/"
            f"{_NORGES_CIK}/{acc_clean}/{primary_doc}"
            if primary_doc
            else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={_NORGES_CIK}&type={form}&dateb=&owner=include&count=40"
        )

        if form == "13F-HR":
            signal_type = "13f_filing"
            title = f"Norway SWF 13F-HR filed: {filing_date.isoformat()} (quarterly holdings update)"
            ticker = None
        elif form == "SC 13D":
            signal_type = "sc_13d"
            desc = primary_desc or primary_doc or "filing"
            title = f"Norway SWF SC 13D for {desc}: {filing_date.isoformat()}"
            ticker = None
        else:  # SC 13G
            signal_type = "sc_13g"
            desc = primary_desc or primary_doc or "filing"
            title = f"Norway SWF SC 13G for {desc}: {filing_date.isoformat()}"
            ticker = None

        signals.append(
            Signal(
                source="norway",
                signal_type=signal_type,
                title=title,
                url=filing_url,
                published=filing_date.isoformat(),
                ticker=ticker,
                company="Norges Bank Investment Management",
                amount_usd=None,
                data={
                    "accession": accession,
                    "form": form,
                    "cik": int(_NORGES_CIK),
                    "primary_doc": primary_doc,
                    "primary_doc_description": primary_desc,
                },
            )
        )

    return signals
