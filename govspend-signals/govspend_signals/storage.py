from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .edgar import Filing

if TYPE_CHECKING:
    from .signal import Signal


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

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    ticker TEXT,
    company TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published TEXT NOT NULL,
    amount_usd REAL,
    data_json TEXT,
    first_seen_ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_source_published
    ON signals (source, published DESC);

CREATE INDEX IF NOT EXISTS idx_signals_ticker
    ON signals (ticker, published DESC);
"""


@dataclass(frozen=True)
class TickerRecord:
    ticker: str
    cik: int
    company: str


@dataclass(frozen=True)
class SignalRow:
    id: str
    source: str
    signal_type: str
    ticker: str | None
    company: str | None
    title: str
    url: str
    published: str
    amount_usd: float | None
    data: dict
    first_seen_ts: int


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

    # ── EDGAR backward-compat methods ──────────────────────────────────────

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

    # ── Signal methods ─────────────────────────────────────────────────────

    def is_signal_seen(self, signal_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()
        return row is not None

    def mark_signal_seen(self, signal: "Signal") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO signals "
            "(id, source, signal_type, ticker, company, title, url, published, "
            " amount_usd, data_json, first_seen_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal.id,
                signal.source,
                signal.signal_type,
                signal.ticker,
                signal.company,
                signal.title,
                signal.url,
                signal.published,
                signal.amount_usd,
                json.dumps(signal.data),
                int(time.time()),
            ),
        )
        self._conn.commit()

    def get_signals_since(
        self,
        since_ts: int,
        source: str | None = None,
    ) -> list[SignalRow]:
        if source:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE first_seen_ts >= ? AND source = ? "
                "ORDER BY published DESC",
                (since_ts, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE first_seen_ts >= ? ORDER BY published DESC",
                (since_ts,),
            ).fetchall()
        return [
            SignalRow(
                id=r["id"],
                source=r["source"],
                signal_type=r["signal_type"],
                ticker=r["ticker"],
                company=r["company"],
                title=r["title"],
                url=r["url"],
                published=r["published"],
                amount_usd=r["amount_usd"],
                data=json.loads(r["data_json"] or "{}"),
                first_seen_ts=r["first_seen_ts"],
            )
            for r in rows
        ]

    def signal_count_since(self, since_ts: int) -> dict[str, int]:
        """Return {source: count} for signals seen since `since_ts`."""
        rows = self._conn.execute(
            "SELECT source, COUNT(*) AS n FROM signals "
            "WHERE first_seen_ts >= ? GROUP BY source",
            (since_ts,),
        ).fetchall()
        return {r["source"]: r["n"] for r in rows}

    def get_signal_counts_by_sector(self, since_ts: int) -> dict[str, int]:
        """Return {sector: count} inferred from signal_type naming convention.

        Ingestors encode sector in signal_type as '{prefix}_{sector}', e.g.:
          'nofo_healthcare', 'bill_energy_utilities'
        Ingestors without sector encoding are bucketed by source name.
        """
        rows = self._conn.execute(
            "SELECT signal_type, source, COUNT(*) as n "
            "FROM signals WHERE first_seen_ts >= ? "
            "GROUP BY signal_type, source",
            (since_ts,),
        ).fetchall()

        _SECTOR_PREFIXES = ["nofo_", "bill_"]
        _SOURCE_SECTORS = {
            "usaspending": "contracts",
            "fedregister": "regulation",
            "congress": "congressional_trades",
            "sbir": "sbir_grants",
            "norway": "sovereign_wealth",
            "catalyst": "catalyst",
            "edgar": "edgar_filings",
            "lobbying": "lobbying",
        }

        counts: dict[str, int] = {}
        for row in rows:
            signal_type = row["signal_type"]
            source = row["source"]
            n = row["n"]
            sector = None
            for prefix in _SECTOR_PREFIXES:
                if signal_type.startswith(prefix):
                    sector = signal_type[len(prefix):]
                    break
            if sector is None:
                sector = _SOURCE_SECTORS.get(source, source)
            counts[sector] = counts.get(sector, 0) + n

        return counts

    # ── Ticker map methods ─────────────────────────────────────────────────

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
