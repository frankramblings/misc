"""ProPublica Congress API ingestor — bills, votes, and appropriations.

Tracks legislation that allocates money BEFORE contracts are signed.
A bill passing committee is a 3–18 month leading indicator for contract awards.

Free API — no key required for basic endpoints.
Docs: https://projects.propublica.org/api-docs/congress-api/

Sectors covered:
- Healthcare: HHS, CMS, Medicaid, Medicare appropriations
- Infrastructure: transportation, water, energy infrastructure bills
- Utilities/Energy: DOE, EPA, clean energy
- Environmental: EPA, Superfund, climate
- Government IT: appropriations for federal IT modernization
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

_BASE_URL = "https://api.propublica.org/congress/v1"
_BILL_URL = "https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_number}"
_RECENT_BILLS_URL = "{base}/{congress}/both/bills/{bill_type}.json"

# Current Congress (119th as of 2025-2026)
_CURRENT_CONGRESS = 119

# Keywords to flag as sector-relevant
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "healthcare": [
        "medicaid", "medicare", "cms", "health care", "healthcare",
        "affordable care act", "chip", "aca", "hospital", "prescription drug",
        "insulin", "public health",
    ],
    "infrastructure": [
        "infrastructure", "broadband", "highway", "transit", "rail",
        "port", "bridge", "roads", "water infrastructure", "usace",
        "army corps",
    ],
    "energy_utilities": [
        "energy", "electricity", "grid", "solar", "wind", "nuclear",
        "doe", "department of energy", "clean energy", "renewable",
        "lng", "natural gas", "pipeline",
    ],
    "environmental": [
        "epa", "environmental protection", "superfund", "climate",
        "remediation", "clean water", "clean air", "carbon",
    ],
    "gov_software": [
        "technology modernization", "federal it", "cybersecurity",
        "cisa", "information technology", "digital services",
    ],
    "appropriations": [
        "appropriations", "continuing resolution", "omnibus",
        "budget", "debt ceiling", "government funding",
    ],
}


def _classify_bill(title: str, summary: str) -> str | None:
    """Return the investment sector if the bill is relevant, else None."""
    combined = (title + " " + (summary or "")).lower()
    for sector, keywords in _SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return sector
    return None


def _congress_bill_url(congress: int, bill_type: str, bill_number: str) -> str:
    type_map = {
        "hr": "house-bill",
        "s": "senate-bill",
        "hjres": "house-joint-resolution",
        "sjres": "senate-joint-resolution",
        "hres": "house-resolution",
        "sres": "senate-resolution",
    }
    bill_type_long = type_map.get(bill_type.lower(), bill_type)
    return f"https://www.congress.gov/bill/{congress}th-congress/{bill_type_long}/{bill_number}"


def ingest(
    lookback_days: int = 30,
    congress: int = _CURRENT_CONGRESS,
    rate_per_second: float = 2.0,
    api_key: str | None = None,
) -> list[Signal]:
    """Fetch recent Congressional bills relevant to our investment sectors.

    Parameters
    ----------
    lookback_days:
        How many calendar days back to look for introduced/updated bills.
    congress:
        Congressional session number (default: 119th).
    rate_per_second:
        API call rate limit.
    api_key:
        ProPublica API key (optional — some endpoints work without it,
        but a key increases rate limits).

    Returns
    -------
    list[Signal]
        One Signal per relevant bill introduced or updated recently.
    """
    sleep_s = 1.0 / rate_per_second
    cutoff = date.today() - timedelta(days=lookback_days)

    session = requests.Session()
    headers = {"X-API-Key": api_key} if api_key else {}
    session.headers.update(headers)

    signals: list[Signal] = []
    seen_ids: set[str] = set()

    # Fetch recently introduced bills from both chambers
    for bill_type in ("introduced", "updated"):
        for chamber in ("house", "senate"):
            url = f"{_BASE_URL}/{congress}/{chamber}/bills/{bill_type}.json"
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.HTTPError as exc:
                print(
                    f"[propublica] HTTP error ({chamber}/{bill_type}): {exc}",
                    file=sys.stderr,
                )
                time.sleep(sleep_s)
                continue
            except requests.RequestException as exc:
                print(
                    f"[propublica] Request error ({chamber}/{bill_type}): {exc}",
                    file=sys.stderr,
                )
                time.sleep(sleep_s)
                continue

            try:
                data = resp.json()
            except ValueError as exc:
                print(f"[propublica] JSON parse error: {exc}", file=sys.stderr)
                time.sleep(sleep_s)
                continue

            bills = []
            results = data.get("results", [])
            if results and isinstance(results, list):
                bills = results[0].get("bills", []) if isinstance(results[0], dict) else results

            for bill in bills:
                bill_id = bill.get("bill_id") or bill.get("bill_slug") or ""
                if not bill_id or bill_id in seen_ids:
                    continue

                # Date filter
                intro_date_raw = (
                    bill.get("introduced_date")
                    or bill.get("latest_major_action_date")
                    or ""
                )
                try:
                    intro_date = date.fromisoformat(str(intro_date_raw)[:10])
                except (ValueError, TypeError):
                    continue

                if intro_date < cutoff:
                    continue

                title = (bill.get("title") or bill.get("short_title") or "").strip()
                summary = (bill.get("summary") or bill.get("latest_major_action") or "")

                sector = _classify_bill(title, summary)
                if sector is None:
                    continue

                seen_ids.add(bill_id)

                # Build URL
                bill_type_code = (bill.get("bill_type") or "hr").lower()
                bill_number = str(bill.get("number") or "")
                bill_url = (
                    bill.get("congressdotgov_url")
                    or _congress_bill_url(congress, bill_type_code, bill_number)
                )

                sponsor = (bill.get("sponsor_name") or "").strip()
                sponsor_str = f" (sponsor: {sponsor})" if sponsor else ""
                status = (
                    bill.get("latest_major_action")
                    or bill.get("status")
                    or ""
                )[:100]

                signal_title = (
                    f"[BILL/{sector.upper()}] {title}{sponsor_str}"
                )

                signals.append(
                    Signal(
                        source="propublica",
                        signal_type=f"bill_{sector}",
                        title=signal_title[:200],
                        url=bill_url,
                        published=intro_date.isoformat(),
                        ticker=None,
                        company=None,
                        amount_usd=None,
                        data={
                            "bill_id": bill_id,
                            "bill_type": bill_type_code,
                            "bill_number": bill_number,
                            "sector": sector,
                            "sponsor": sponsor,
                            "latest_action": status,
                            "chamber": chamber,
                            "congress": congress,
                            "committees": bill.get("committees") or [],
                        },
                    )
                )

            time.sleep(sleep_s)

    # Deduplicate by ID (same bill may appear in introduced + updated)
    seen_final: set[str] = set()
    deduped: list[Signal] = []
    for s in signals:
        bid = s.data.get("bill_id", "")
        if bid and bid not in seen_final:
            seen_final.add(bid)
            deduped.append(s)
        elif not bid:
            deduped.append(s)

    return deduped
