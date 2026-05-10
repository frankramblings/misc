"""USASpending.gov ingestor — contract award signals via the free public API."""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

# Map short agency codes to full toptier names expected by the API
AGENCY_NAME_MAP: dict[str, str] = {
    "HHS": "Department of Health and Human Services",
    "EPA": "Environmental Protection Agency",
    "DOE": "Department of Energy",
    "DOT": "Department of Transportation",
    "USACE": "Department of Defense",
    "USDA": "Department of Agriculture",
    "DOD": "Department of Defense",
    "NASA": "National Aeronautics and Space Administration",
    "DHS": "Department of Homeland Security",
    "VA": "Department of Veterans Affairs",
}

_BASE_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
_AWARD_BASE = "https://www.usaspending.gov/award/"


def _agency_full_name(code: str) -> str:
    """Return the full toptier agency name; fall back to the raw string."""
    return AGENCY_NAME_MAP.get(code.upper(), code)


def _make_payload(agency_name: str, start: str, end: str) -> dict:
    return {
        "filters": {
            "agencies": [
                {"type": "awarding", "tier": "toptier", "name": agency_name}
            ],
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": start, "end_date": end}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Award Type",
            "Start Date",
            "Description",
            "generated_internal_id",
        ],
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc",
    }


def ingest(
    agencies: list[str],
    lookback_days: int,
    min_award_usd: float,
    rate_per_second: float = 5.0,
    resolver=None,
) -> list[Signal]:
    """Fetch contract awards from USASpending.gov.

    Parameters
    ----------
    agencies:
        List of agency codes (e.g. ``["HHS", "EPA"]``) or full names.
    lookback_days:
        How many calendar days back to search.
    min_award_usd:
        Minimum award dollar amount; awards below this are skipped.
    rate_per_second:
        API call rate limit (calls / second).

    Returns
    -------
    list[Signal]
        Deduplicated signals, sorted descending by amount.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    sleep_s = 1.0 / rate_per_second
    session = requests.Session()
    signals: list[Signal] = []
    seen_ids: set[str] = set()

    for code in agencies:
        agency_name = _agency_full_name(code)
        payload = _make_payload(agency_name, start_str, end_str)

        try:
            resp = session.post(_BASE_URL, json=payload, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(
                f"[usaspending] HTTP error for agency {code!r}: {exc}",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
            continue
        except requests.RequestException as exc:
            print(
                f"[usaspending] Request error for agency {code!r}: {exc}",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
            continue

        try:
            results = resp.json().get("results", [])
        except ValueError as exc:
            print(f"[usaspending] JSON parse error: {exc}", file=sys.stderr)
            time.sleep(sleep_s)
            continue

        for row in results:
            amount = row.get("Award Amount") or 0.0
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = 0.0

            if amount < min_award_usd:
                continue

            generated_id = row.get("generated_internal_id") or ""
            url = f"{_AWARD_BASE}{generated_id}/" if generated_id else _AWARD_BASE

            if url in seen_ids:
                continue
            seen_ids.add(url)

            recipient = (row.get("Recipient Name") or "Unknown Recipient").strip()
            awarding = (row.get("Awarding Agency") or agency_name).strip()
            start_field = row.get("Start Date") or end_str
            # Normalise date — API returns YYYY-MM-DD but guard against other formats
            try:
                pub = date.fromisoformat(str(start_field)[:10]).isoformat()
            except ValueError:
                pub = end_str

            # Resolve recipient to a watchlist ticker
            ticker = resolver.resolve(recipient) if resolver else None

            ticker_str = f" [{ticker}]" if ticker else ""
            title = f"${amount:,.0f} contract{ticker_str} — {recipient} ({awarding})"

            signals.append(
                Signal(
                    source="usaspending",
                    signal_type="contract_award",
                    title=title,
                    url=url,
                    published=pub,
                    ticker=ticker,
                    company=recipient,
                    amount_usd=amount,
                    data={
                        "award_id": row.get("Award ID"),
                        "award_type": row.get("Award Type"),
                        "description": row.get("Description"),
                        "agency": awarding,
                        "generated_internal_id": generated_id,
                        "ticker_resolved": ticker is not None,
                    },
                )
            )

        time.sleep(sleep_s)

    return signals
