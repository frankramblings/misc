"""Congressional STOCK Act trade disclosure ingestor.

Fetches House and Senate member stock trades from the public watcher APIs:
  - https://housestockwatcher.com/api
  - https://senatestockwatcher.com/api
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta

import requests

from govspend_signals.signal import Signal

_HOUSE_URL = "https://housestockwatcher.com/api"
_SENATE_URL = "https://senatestockwatcher.com/api"

# Maps the amount range strings returned by the APIs to midpoint dollar values
_AMOUNT_MIDPOINTS: dict[str, float] = {
    "$1,001 - $15,000": 8000.5,
    "$1,001-$15,000": 8000.5,
    "$15,001 - $50,000": 32500.5,
    "$15,001-$50,000": 32500.5,
    "$50,001 - $100,000": 75000.5,
    "$50,001-$100,000": 75000.5,
    "$100,001 - $250,000": 175000.5,
    "$100,001-$250,000": 175000.5,
    "$250,001 - $500,000": 375000.5,
    "$250,001-$500,000": 375000.5,
    "$500,001 - $1,000,000": 750000.5,
    "$500,001-$1,000,000": 750000.5,
    "$1,000,001 - $5,000,000": 3000000.5,
    "$1,000,001-$5,000,000": 3000000.5,
    "Over $5,000,000": 5000000.0,
    "over $5,000,000": 5000000.0,
}


def _parse_amount(raw: str | None) -> float | None:
    """Return the midpoint dollar value for an amount range string."""
    if not raw:
        return None
    key = raw.strip()
    # Try exact match first
    if key in _AMOUNT_MIDPOINTS:
        return _AMOUNT_MIDPOINTS[key]
    # Try normalised (collapse spaces around hyphen)
    normalised = key.replace(" - ", "-")
    return _AMOUNT_MIDPOINTS.get(normalised)


def _parse_date(raw: str | None) -> date | None:
    """Parse various date string formats into a date object."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _format_action(trade_type: str) -> str:
    """Return human-friendly verb for a trade type."""
    lower = trade_type.lower()
    if "purchase" in lower:
        return "purchased"
    if "sale" in lower:
        return "sold"
    return lower


def _fetch_trades(
    session: requests.Session,
    url: str,
    chamber: str,
    name_field: str,
    cutoff: date,
    sleep_s: float,
) -> list[Signal]:
    """Fetch and filter trades from one chamber's API endpoint."""
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        trades = resp.json()
    except requests.HTTPError as exc:
        print(f"[congress] HTTP error ({chamber}): {exc}", file=sys.stderr)
        return []
    except requests.RequestException as exc:
        print(f"[congress] Request error ({chamber}): {exc}", file=sys.stderr)
        return []
    except ValueError as exc:
        print(f"[congress] JSON parse error ({chamber}): {exc}", file=sys.stderr)
        return []

    time.sleep(sleep_s)

    signals: list[Signal] = []
    seen_urls: set[str] = set()

    for trade in trades:
        # Date filter
        tx_date = _parse_date(trade.get("transaction_date"))
        if tx_date is None or tx_date < cutoff:
            continue

        # Type filter — only purchases and sales
        trade_type: str = (trade.get("type") or "").strip()
        lower_type = trade_type.lower()
        if "purchase" not in lower_type and "sale" not in lower_type:
            continue

        # Ticker filter
        ticker = (trade.get("ticker") or "").strip()
        if not ticker or ticker == "--":
            continue

        ticker = ticker.upper()

        ptr_link = (trade.get("ptr_link") or "").strip()
        url_key = ptr_link or f"{chamber}:{trade.get('transaction_date')}:{ticker}"
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        name = (trade.get(name_field) or "Unknown").strip()
        amount_raw = trade.get("amount")
        amount_usd = _parse_amount(str(amount_raw) if amount_raw else None)
        action = _format_action(trade_type)
        signal_type = "purchase" if "purchase" in lower_type else "sale"

        amount_display = str(amount_raw).strip() if amount_raw else "unknown amount"
        title = f"[{chamber}] {name} {action} {ticker} ({amount_display})"

        disclosure_date = (trade.get("disclosure_date") or "").strip()
        asset_description = (trade.get("asset_description") or "").strip()

        signals.append(
            Signal(
                source="congress",
                signal_type=signal_type,
                title=title,
                url=ptr_link or f"https://{chamber.lower()}stockwatcher.com/",
                published=tx_date.isoformat(),
                ticker=ticker,
                company=None,
                amount_usd=amount_usd,
                data={
                    "chamber": chamber,
                    "name": name,
                    "asset_description": asset_description,
                    "disclosure_date": disclosure_date,
                },
            )
        )

    return signals


def ingest(lookback_days: int, rate_per_second: float = 3.0) -> list[Signal]:
    """Fetch congressional STOCK Act trade disclosures.

    Parameters
    ----------
    lookback_days:
        Maximum age (in days) of trades to include.
    rate_per_second:
        API call rate limit.

    Returns
    -------
    list[Signal]
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    sleep_s = 1.0 / rate_per_second
    session = requests.Session()

    house_signals = _fetch_trades(
        session, _HOUSE_URL, "House", "representative", cutoff, sleep_s
    )
    senate_signals = _fetch_trades(
        session, _SENATE_URL, "Senate", "senator", cutoff, sleep_s
    )

    return house_signals + senate_signals
