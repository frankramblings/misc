"""Grants.gov NOFO ingestor — Notices of Funding Opportunity.

These are pre-contract leading indicators: a NOFO is published months
before awards are made, giving 3–12 months of lead time on where
government money is headed.

Free API: https://www.grants.gov/web/grants/search-grants.html
API docs: https://www.grants.gov/web/grants/s2s/grantor/schemas.html
REST endpoint: https://apply07.grants.gov/grantsws/rest/opportunities/search/
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

_SEARCH_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
_DETAIL_URL = "https://www.grants.gov/search-results-detail/{id}"

# Opportunity status codes
_ACTIVE_STATUSES = {"forecasted", "posted"}

# CFDA (Catalog of Federal Domestic Assistance) prefix codes for target sectors
# These map to our investment categories
_SECTOR_CFDA_PREFIXES: dict[str, list[str]] = {
    "healthcare": [
        "93.",  # HHS / CMS programs
        "10.551", "10.561",  # SNAP-adjacent health
    ],
    "infrastructure": [
        "20.",  # DOT
        "66.",  # EPA infrastructure
        "12.109",  # Army Corps
    ],
    "energy_utilities": [
        "81.",  # DOE
        "66.040",  # EPA clean energy
    ],
    "environmental": [
        "66.",  # EPA
        "15.608", "15.609",  # Interior / tribal
    ],
    "gov_software": [
        "93.778",  # Medicaid IT systems
        "93.725",  # HIT
    ],
}

# Keywords to filter by sector relevance
_SECTOR_KEYWORDS: list[str] = [
    "medicaid", "medicare", "cms", "health", "healthcare",
    "infrastructure", "broadband", "grid", "utility", "water",
    "energy", "renewable", "solar", "wind", "nuclear",
    "environmental", "remediation", "climate", "superfund",
    "information technology", "software", "cybersecurity",
    "transportation", "transit", "rail", "port", "bridge",
]


def _matches_sector(opportunity: dict) -> bool:
    """Return True if the opportunity is relevant to our sectors."""
    title = (opportunity.get("oppTitle") or "").lower()
    agency = (opportunity.get("agencyName") or "").lower()
    cfda = (opportunity.get("cfdaNumbers") or "")

    for keyword in _SECTOR_KEYWORDS:
        if keyword in title or keyword in agency:
            return True

    # CFDA prefix check
    for _sector, prefixes in _SECTOR_CFDA_PREFIXES.items():
        for prefix in prefixes:
            if str(cfda).startswith(prefix):
                return True

    return False


def _determine_sector(opportunity: dict) -> str:
    """Infer the investment sector from opportunity metadata."""
    title = (opportunity.get("oppTitle") or "").lower()
    agency = (opportunity.get("agencyName") or "").lower()

    if any(k in title or k in agency for k in ["medicaid", "medicare", "cms", "health"]):
        return "healthcare"
    if any(k in title or k in agency for k in ["energy", "doe", "solar", "wind", "nuclear"]):
        return "energy_utilities"
    if any(k in title or k in agency for k in ["environmental", "epa", "superfund", "remediation"]):
        return "environmental"
    if any(k in title or k in agency for k in ["transport", "highway", "transit", "rail", "port", "bridge", "dot"]):
        return "infrastructure"
    if any(k in title or k in agency for k in ["technology", "software", "cyber", "it ", "data"]):
        return "gov_software"
    if any(k in title or k in agency for k in ["infrastructure", "grid", "water", "broadband"]):
        return "infrastructure"
    return "other"


def ingest(
    lookback_days: int,
    rate_per_second: float = 3.0,
    max_results: int = 200,
    agencies: list[str] | None = None,
) -> list[Signal]:
    """Fetch active and recently posted NOFOs from Grants.gov.

    Parameters
    ----------
    lookback_days:
        How many calendar days back to look for postings.
    rate_per_second:
        API call rate limit.
    max_results:
        Maximum number of results per API call.
    agencies:
        Optional list of agency abbreviations to filter (e.g. ["HHS", "EPA"]).

    Returns
    -------
    list[Signal]
        One Signal per relevant NOFO opportunity.
    """
    sleep_s = 1.0 / rate_per_second
    today = date.today()
    start_date = today - timedelta(days=lookback_days)

    payload = {
        "startRecordNum": 0,
        "rows": max_results,
        "sortBy": "openDate|desc",
        "oppStatuses": "forecasted|posted",
        "startDate": start_date.strftime("%m-%d-%Y"),
        "endDate": today.strftime("%m-%d-%Y"),
    }

    if agencies:
        payload["agencies"] = "|".join(agencies)

    session = requests.Session()
    signals: list[Signal] = []
    seen_ids: set[str] = set()

    try:
        resp = session.post(_SEARCH_URL, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        print(f"[grants_gov] HTTP error: {exc}", file=sys.stderr)
        return []
    except requests.RequestException as exc:
        print(f"[grants_gov] Request error: {exc}", file=sys.stderr)
        return []

    try:
        data = resp.json()
    except ValueError as exc:
        print(f"[grants_gov] JSON parse error: {exc}", file=sys.stderr)
        return []

    time.sleep(sleep_s)

    opportunities = data.get("oppHits", []) or data.get("opportunities", [])
    if not opportunities and "data" in data:
        opportunities = data["data"].get("oppHits", [])

    for opp in opportunities:
        opp_id = str(opp.get("id") or opp.get("oppNumber") or "")
        if not opp_id or opp_id in seen_ids:
            continue

        if not _matches_sector(opp):
            continue

        seen_ids.add(opp_id)

        title = (opp.get("oppTitle") or "Untitled Opportunity").strip()
        agency_name = (opp.get("agencyName") or "Unknown Agency").strip()
        open_date_raw = opp.get("openDate") or opp.get("postDate") or ""
        close_date_raw = opp.get("closeDate") or ""

        try:
            pub = date.fromisoformat(str(open_date_raw)[:10]).isoformat()
        except (ValueError, TypeError):
            pub = today.isoformat()

        url = _DETAIL_URL.format(id=opp_id)

        # Award ceiling — not always present
        award_ceiling = opp.get("awardCeiling")
        amount_usd: float | None = None
        if award_ceiling:
            try:
                amount_usd = float(str(award_ceiling).replace(",", ""))
            except (ValueError, TypeError):
                pass

        sector = _determine_sector(opp)
        signal_type = f"nofo_{sector}"

        amount_str = f" (up to ${amount_usd:,.0f})" if amount_usd else ""
        close_str = f" — closes {close_date_raw[:10]}" if close_date_raw else ""
        signal_title = f"[NOFO/{sector.upper()}]{amount_str} {title} | {agency_name}{close_str}"

        signals.append(
            Signal(
                source="grants_gov",
                signal_type=signal_type,
                title=signal_title[:200],
                url=url,
                published=pub,
                ticker=None,
                company=None,
                amount_usd=amount_usd,
                data={
                    "opportunity_id": opp_id,
                    "agency": agency_name,
                    "sector": sector,
                    "close_date": close_date_raw[:10] if close_date_raw else None,
                    "cfda_numbers": opp.get("cfdaNumbers"),
                    "opportunity_number": opp.get("oppNumber"),
                    "status": opp.get("oppStatus"),
                },
            )
        )

    return signals
