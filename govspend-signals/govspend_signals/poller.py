from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass

from .config import Config
from .edgar import EdgarClient, filter_filings
from .notifier import Notifier
from .storage import Storage


TICKER_MAP_REFRESH_SECONDS = 24 * 3600


@dataclass(frozen=True)
class PollResult:
    scanned_tickers: int
    unresolved_tickers: list[str]
    new_filings: int
    errors: list[str]


def _ensure_ticker_map(client: EdgarClient, store: Storage) -> None:
    age = store.ticker_map_age_seconds()
    if age is not None and age < TICKER_MAP_REFRESH_SECONDS:
        return
    print("Refreshing SEC ticker map...", file=sys.stderr, flush=True)
    mapping = client.fetch_ticker_map()
    for ticker, (cik, company) in mapping.items():
        store.upsert_ticker(ticker, cik, company)


def poll_once(
    config: Config,
    client: EdgarClient,
    store: Storage,
    notifier: Notifier,
) -> PollResult:
    _ensure_ticker_map(client, store)

    cutoff_date = (
        dt.date.today() - dt.timedelta(days=config.max_age_days)
    ).isoformat()

    unresolved: list[str] = []
    errors: list[str] = []
    new_count = 0
    scanned = 0

    for ticker in config.watchlist:
        record = store.lookup_ticker(ticker)
        if record is None:
            unresolved.append(ticker)
            continue
        scanned += 1

        try:
            filings = client.fetch_recent_filings(
                cik=record.cik,
                ticker=record.ticker,
                company=record.company,
                scan_limit=config.scan_limit,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ticker}: {exc}")
            continue

        for filing in filter_filings(
            filings, forms=config.forms_set, min_date=cutoff_date
        ):
            if store.is_seen(filing.accession):
                continue
            notifier.emit(filing)
            store.mark_seen(filing)
            new_count += 1

    return PollResult(
        scanned_tickers=scanned,
        unresolved_tickers=unresolved,
        new_filings=new_count,
        errors=errors,
    )
