from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .edgar import Filing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS filings_seen (
    accession TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik INTEGER NOT NULL,
    company TEXT,
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    first_seen_ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_filings_ticker_date
    ON filings_seen (ticker, filing_date DESC);

CREATE TABLE IF NOT EXISTS ticker_map (
    ticker TEXT PRIMARY KEY,
    cik INTEGER NOT NULL,
    company TEXT,
    updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass(frozen=True)
class TickerRecord:
    ticker: str
    cik: int
    company: str


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def is_seen(self, accession: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM filings_seen WHERE accession = ?",
            (accession,),
        ).fetchone()
        return row is not None

    def mark_seen(self, filing: Filing) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO filings_seen "
            "(accession, ticker, cik, company, form, filing_date, first_seen_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                filing.accession,
                filing.ticker,
                filing.cik,
                filing.company,
                filing.form,
                filing.filing_date,
                int(time.time()),
            ),
        )
        self._conn.commit()

    def upsert_ticker(self, ticker: str, cik: int, company: str) -> None:
        self._conn.execute(
            "INSERT INTO ticker_map (ticker, cik, company, updated_ts) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "cik = excluded.cik, "
            "company = excluded.company, "
            "updated_ts = excluded.updated_ts",
            (ticker.upper(), cik, company, int(time.time())),
        )
        self._conn.commit()

    def lookup_ticker(self, ticker: str) -> TickerRecord | None:
        row = self._conn.execute(
            "SELECT ticker, cik, company FROM ticker_map WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
        if row is None:
            return None
        return TickerRecord(ticker=row["ticker"], cik=row["cik"], company=row["company"])

    def ticker_map_age_seconds(self) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(updated_ts) AS ts FROM ticker_map"
        ).fetchone()
        if row is None or row["ts"] is None:
            return None
        return int(time.time()) - int(row["ts"])
