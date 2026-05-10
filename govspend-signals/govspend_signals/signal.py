"""Unified Signal dataclass emitted by all ingestors.

Every ingestor (EDGAR, USASpending, Federal Register, congressional trades,
SBIR, Norway fund, catalyst calendar) maps its raw data to this type before
emitting to notifiers or writing to storage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Signal:
    """A single market-relevant signal from any ingestor."""

    # Required fields
    source: str          # "edgar" | "usaspending" | "fedregister" | "congress" | "sbir" | "norway" | "catalyst"
    signal_type: str     # e.g. "sc_13d", "contract_award", "rule_change", "stock_trade", "grant_award", "upcoming_event"
    title: str           # human-readable one-liner (fits in a push notification)
    url: str             # canonical source URL
    published: str       # ISO date "YYYY-MM-DD"

    # Optional enrichment
    ticker: str | None = None         # related equity ticker if known
    company: str | None = None        # company / org name
    amount_usd: float | None = None   # dollar amount if relevant (award, trade value, etc.)
    data: dict = field(default_factory=dict)   # source-specific payload (always serializable)

    @property
    def id(self) -> str:
        """Stable content-addressable ID: first 32 hex chars of SHA-256(source:url)."""
        raw = f"{self.source}:{self.url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "signal_type": self.signal_type,
            "title": self.title,
            "url": self.url,
            "published": self.published,
            "ticker": self.ticker,
            "company": self.company,
            "amount_usd": self.amount_usd,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_filing(cls, filing: object) -> "Signal":
        """Convert a govspend_signals.edgar.Filing to a Signal."""
        # Import here to avoid circular imports
        form: str = getattr(filing, "form", "")
        signal_type = form.lower().replace(" ", "_").replace("/", "_")
        ticker: str | None = getattr(filing, "ticker", None)
        company: str | None = getattr(filing, "company", None)
        return cls(
            source="edgar",
            signal_type=signal_type,
            title=f"{form} — {company} ({ticker})",
            url=getattr(filing, "url", ""),
            published=getattr(filing, "filing_date", ""),
            ticker=ticker,
            company=company,
            data={
                "cik": getattr(filing, "cik", None),
                "accession": getattr(filing, "accession", None),
                "form": form,
                "primary_doc": getattr(filing, "primary_doc", None),
                "primary_doc_description": getattr(filing, "primary_doc_description", None),
                "index_url": getattr(filing, "index_url", None),
            },
        )
