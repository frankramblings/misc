"""SBIR/STTR grant award ingestor — fetches from the public SBIR API."""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

_BASE_URL = "https://api.sbir.gov/awards"
_DETAIL_URL = "https://www.sbir.gov/sbc/detail/{contract}"
_FALLBACK_URL = "https://www.sbir.gov/"


def _award_url(row: dict) -> str:
    contract = (row.get("contract") or "").strip()
    if contract:
        return _DETAIL_URL.format(contract=contract)
    return _FALLBACK_URL


def ingest(
    agencies: list[str],
    lookback_days: int,
    rate_per_second: float = 3.0,
) -> list[Signal]:
    """Fetch SBIR/STTR grant awards.

    Parameters
    ----------
    agencies:
        Agency codes to query, e.g. ``["DARPA", "NIH", "NSF"]``.
    lookback_days:
        Maximum age (in days) of awards to include.
    rate_per_second:
        API call rate limit.

    Returns
    -------
    list[Signal]
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    sleep_s = 1.0 / rate_per_second
    session = requests.Session()
    signals: list[Signal] = []
    seen_urls: set[str] = set()

    for agency in agencies:
        params = {
            "agency": agency,
            "rows": 200,
            "start": 0,
            "s": "award_date",
            "o": "desc",
        }

        try:
            resp = session.get(_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(f"[sbir] HTTP error for agency {agency!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_s)
            continue
        except requests.RequestException as exc:
            print(f"[sbir] Request error for agency {agency!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_s)
            continue

        try:
            payload = resp.json()
        except ValueError as exc:
            print(f"[sbir] JSON parse error for agency {agency!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_s)
            continue

        docs = payload.get("docs") or []

        for row in docs:
            award_date_raw = (row.get("award_date") or "").strip()
            if not award_date_raw:
                # Try proposal_award_date as fallback
                award_date_raw = (row.get("proposal_award_date") or "").strip()

            try:
                award_date = date.fromisoformat(award_date_raw[:10])
            except (ValueError, TypeError):
                continue

            if award_date < cutoff:
                continue

            url = _award_url(row)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            firm = (row.get("firm") or "Unknown Firm").strip()
            award_title = (row.get("award_title") or "").strip()
            amount_raw = row.get("award_amount")
            try:
                amount = float(amount_raw) if amount_raw is not None else 0.0
            except (TypeError, ValueError):
                amount = 0.0

            agency_code = (row.get("agency") or agency).strip()
            title = f"[SBIR/{agency_code}] ${amount:,.0f} — {firm}: {award_title[:60]}"

            signals.append(
                Signal(
                    source="sbir",
                    signal_type="grant_award",
                    title=title,
                    url=url,
                    published=award_date.isoformat(),
                    ticker=None,
                    company=firm,
                    amount_usd=amount,
                    data={
                        "agency": agency_code,
                        "branch": row.get("branch"),
                        "abstract": row.get("abstract"),
                        "solicitation_id": row.get("solicitationId"),
                    },
                )
            )

        time.sleep(sleep_s)

    return signals
