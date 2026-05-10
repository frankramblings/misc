"""Senate LDA (Lobbying Disclosure Act) ingestor — lobbying spike detector.

Companies file quarterly lobbying disclosures with the House and Senate.
A sudden spike in lobbying spend by a watchlist company on a specific bill
= they expect it to pass and benefit them. Buy before the bill makes news.

Free API: https://lda.senate.gov/api/
API docs: https://lda.senate.gov/api/redoc/v1/

Rate limit: 120 requests/minute unauthenticated; registering for a free
API key raises this to 1200/min. Set LOBBYING_API_KEY env var if you have one.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal
from govspend_signals.resolver import Resolver

_BASE_URL = "https://lda.senate.gov/api/v1"
_FILING_SEARCH = f"{_BASE_URL}/filings/"
_FILING_DETAIL_URL = "https://lda.senate.gov/filings/public/filing/{uuid}/print/"

# General issues to track (LDA uses specific issue codes)
_TARGET_ISSUE_CODES: set[str] = {
    "HCR",  # Health Issues
    "MED",  # Medicare & Medicaid
    "PHR",  # Pharmacy
    "POL",  # Political Reform
    "ENV",  # Environment/Superfund
    "ENE",  # Energy/Nuclear
    "ELE",  # Electric Utilities
    "TRN",  # Transportation
    "HOU",  # Housing
    "TAX",  # Taxation/Internal Revenue
    "SCI",  # Science/Technology
    "TEC",  # Telecommunications
    "GOV",  # Government Issues (appropriations)
    "FIN",  # Financial Institutions
    "INS",  # Insurance
    "DEF",  # Defense (included for cross-pollination signals)
    "RES",  # Natural Resources
    "WAS",  # Waste (Hazardous/Solid)
}

# Minimum quarterly lobbying spend to surface as a signal
_MIN_LOBBYING_SPEND = 50_000.0


def _quarter_range(quarters_back: int = 2) -> tuple[str, str]:
    """Return (start_date, end_date) covering the last N quarters."""
    today = date.today()
    start = today - timedelta(days=quarters_back * 92)  # ~92 days per quarter
    return start.isoformat(), today.isoformat()


def ingest(
    lookback_days: int = 90,
    api_key: str | None = None,
    rate_per_second: float = 2.0,
    min_amount: float = _MIN_LOBBYING_SPEND,
    resolver: Resolver | None = None,
) -> list[Signal]:
    """Fetch recent lobbying filings from Senate LDA.

    Parameters
    ----------
    lookback_days:
        How many days back to look for filings.
    api_key:
        Optional Senate LDA API key for higher rate limits.
    rate_per_second:
        API call rate limit.
    min_amount:
        Minimum lobbying spend (USD) to surface as a signal.
    resolver:
        Optional Resolver instance to map lobbying client names to tickers.

    Returns
    -------
    list[Signal]
    """
    sleep_s = 1.0 / rate_per_second
    cutoff = date.today() - timedelta(days=lookback_days)

    session = requests.Session()
    if api_key:
        session.headers.update({"Authorization": f"Token {api_key}"})

    signals: list[Signal] = []
    seen_ids: set[str] = set()

    # Paginate through filings
    next_url: str | None = f"{_FILING_SEARCH}?filing_type=Q&ordering=-received&page_size=100"

    pages_fetched = 0
    max_pages = 5

    while next_url and pages_fetched < max_pages:
        try:
            resp = session.get(next_url, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(f"[lobbying] HTTP error: {exc}", file=sys.stderr)
            break
        except requests.RequestException as exc:
            print(f"[lobbying] Request error: {exc}", file=sys.stderr)
            break

        try:
            data = resp.json()
        except ValueError as exc:
            print(f"[lobbying] JSON parse error: {exc}", file=sys.stderr)
            break

        pages_fetched += 1
        next_url = data.get("next")

        filings = data.get("results", [])
        for filing in filings:
            # Date filter
            received_raw = (filing.get("dt_posted") or filing.get("filing_date") or "")
            try:
                received = date.fromisoformat(str(received_raw)[:10])
            except (ValueError, TypeError):
                continue

            if received < cutoff:
                # Results are sorted by received desc — early exit
                next_url = None
                break

            filing_uuid = filing.get("filing_uuid") or filing.get("id") or ""
            if not filing_uuid or filing_uuid in seen_ids:
                continue

            # Amount filter
            income_raw = filing.get("income") or filing.get("lobbying_activities_income")
            expenses_raw = filing.get("expenses") or filing.get("lobbying_activities_expenses")
            # Use whichever is bigger (registrants report income, clients report expenses)
            amount: float = 0.0
            for raw in (income_raw, expenses_raw):
                try:
                    v = float(str(raw).replace(",", "")) if raw else 0.0
                    amount = max(amount, v)
                except (ValueError, TypeError):
                    pass

            if amount < min_amount:
                continue

            # Issue code filter
            activities = filing.get("lobbying_activities") or []
            issue_codes = {
                (act.get("general_issue_code") or "").upper()
                for act in activities
            }
            if not issue_codes.intersection(_TARGET_ISSUE_CODES):
                # If we can't read activities, check the general description
                description = (filing.get("description") or "").lower()
                if not any(k in description for k in [
                    "health", "energy", "environment", "infrastructure",
                    "medicare", "medicaid", "appropriation",
                ]):
                    continue

            seen_ids.add(filing_uuid)

            # Registrant / client names
            registrant = (
                filing.get("registrant", {}).get("name")
                or filing.get("registrant_name")
                or "Unknown Registrant"
            ).strip()
            client = (
                filing.get("client", {}).get("name")
                or filing.get("client_name")
                or registrant
            ).strip()

            # Resolve client to a watchlist ticker
            ticker = resolver.resolve(client) if resolver else None
            ticker_str = f" [{ticker}]" if ticker else ""

            url = _FILING_DETAIL_URL.format(uuid=filing_uuid)

            period_str = filing.get("period_of_report") or received_raw[:7]
            title = (
                f"[LOBBYING]{ticker_str} ${amount:,.0f} — {client} "
                f"(via {registrant}) [{period_str}]"
            )

            # Collect specific bills lobbied on
            specific_bills = []
            for act in activities[:10]:
                for bill in (act.get("bills") or [])[:3]:
                    bill_id = bill.get("congress_url") or bill.get("bill_id") or ""
                    if bill_id:
                        specific_bills.append(bill_id)

            signals.append(
                Signal(
                    source="lobbying",
                    signal_type="lobbying_report",
                    title=title[:200],
                    url=url,
                    published=received.isoformat(),
                    ticker=ticker,
                    company=client,
                    amount_usd=amount,
                    data={
                        "filing_uuid": filing_uuid,
                        "registrant": registrant,
                        "client": client,
                        "period": period_str,
                        "issue_codes": sorted(issue_codes),
                        "bills_lobbied": specific_bills[:10],
                        "ticker_resolved": ticker is not None,
                    },
                )
            )

        time.sleep(sleep_s)

    return signals
