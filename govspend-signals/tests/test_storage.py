"""Tests for govspend_signals.storage — Storage class."""
from __future__ import annotations

import time

import pytest

from govspend_signals.edgar import Filing
from govspend_signals.signal import Signal


# ── helpers ───────────────────────────────────────────────────────────────────

def make_filing(**kwargs) -> Filing:
    defaults = dict(
        cik=72971,
        ticker="UNH",
        company="UnitedHealth",
        accession="0000072971-24-000001",
        form="8-K",
        filing_date="2024-01-15",
        primary_doc="d123.htm",
        primary_doc_description="8-K",
    )
    defaults.update(kwargs)
    return Filing(**defaults)


def make_signal(**kwargs) -> Signal:
    defaults = dict(
        source="sbir",
        signal_type="grant_award",
        title="Test grant",
        url="https://example.com/grant/1",
        published="2024-01-15",
    )
    defaults.update(kwargs)
    return Signal(**defaults)


# ── schema tests ──────────────────────────────────────────────────────────────

class TestSchema:
    def test_init_creates_schema(self, tmp_db):
        conn = tmp_db._conn
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            ).fetchall()
        }
        assert "filings_seen" in tables
        assert "ticker_map" in tables
        assert "meta" in tables
        assert "signals" in tables
        assert "idx_filings_ticker_date" in tables
        assert "idx_signals_source_published" in tables
        assert "idx_signals_ticker" in tables


# ── filings_seen tests ────────────────────────────────────────────────────────

class TestFilingsSeen:
    def test_is_seen_false_initially(self, tmp_db):
        assert tmp_db.is_seen("fake-accession") is False

    def test_mark_seen_and_is_seen(self, tmp_db):
        filing = make_filing()
        tmp_db.mark_seen(filing)
        assert tmp_db.is_seen(filing.accession) is True

    def test_mark_seen_idempotent(self, tmp_db):
        filing = make_filing()
        tmp_db.mark_seen(filing)
        # Should not raise on second call (INSERT OR IGNORE)
        tmp_db.mark_seen(filing)
        assert tmp_db.is_seen(filing.accession) is True

    def test_mark_seen_stores_fields(self, tmp_db):
        filing = make_filing()
        tmp_db.mark_seen(filing)
        row = tmp_db._conn.execute(
            "SELECT ticker, cik, company, form FROM filings_seen WHERE accession = ?",
            (filing.accession,),
        ).fetchone()
        assert row["ticker"] == "UNH"
        assert row["cik"] == 72971
        assert row["company"] == "UnitedHealth"
        assert row["form"] == "8-K"

    def test_different_accessions_tracked_separately(self, tmp_db):
        f1 = make_filing(accession="0000072971-24-000001")
        f2 = make_filing(accession="0000072971-24-000002")
        tmp_db.mark_seen(f1)
        assert tmp_db.is_seen("0000072971-24-000001") is True
        assert tmp_db.is_seen("0000072971-24-000002") is False
        tmp_db.mark_seen(f2)
        assert tmp_db.is_seen("0000072971-24-000002") is True


# ── ticker_map tests ──────────────────────────────────────────────────────────

class TestTickerMap:
    def test_upsert_ticker_and_lookup(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        record = tmp_db.lookup_ticker("UNH")
        assert record is not None
        assert record.ticker == "UNH"
        assert record.cik == 72971
        assert record.company == "UnitedHealth"

    def test_lookup_ticker_case_insensitive(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        record = tmp_db.lookup_ticker("unh")
        assert record is not None
        assert record.ticker == "UNH"

    def test_lookup_ticker_missing(self, tmp_db):
        result = tmp_db.lookup_ticker("AAPL")
        assert result is None

    def test_upsert_ticker_updates_existing(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "OldName")
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth Group")
        record = tmp_db.lookup_ticker("UNH")
        assert record.company == "UnitedHealth Group"

    def test_ticker_map_age_none_when_empty(self, tmp_db):
        assert tmp_db.ticker_map_age_seconds() is None

    def test_ticker_map_age_returns_seconds(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        age = tmp_db.ticker_map_age_seconds()
        assert age is not None
        assert age >= 0

    def test_ticker_map_age_is_small_after_fresh_upsert(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        age = tmp_db.ticker_map_age_seconds()
        # Should be very small (well under 5 seconds in CI)
        assert age < 5

    def test_ticker_stored_uppercase(self, tmp_db):
        tmp_db.upsert_ticker("msft", 789019, "Microsoft")
        record = tmp_db.lookup_ticker("MSFT")
        assert record is not None
        assert record.ticker == "MSFT"


# ── signals tests ─────────────────────────────────────────────────────────────

class TestSignals:
    def test_signal_is_signal_seen_false_initially(self, tmp_db):
        assert tmp_db.is_signal_seen("fake-id-that-does-not-exist") is False

    def test_mark_signal_seen_and_is_seen(self, tmp_db):
        signal = make_signal()
        tmp_db.mark_signal_seen(signal)
        assert tmp_db.is_signal_seen(signal.id) is True

    def test_mark_signal_seen_idempotent(self, tmp_db):
        signal = make_signal()
        tmp_db.mark_signal_seen(signal)
        tmp_db.mark_signal_seen(signal)  # should not raise
        assert tmp_db.is_signal_seen(signal.id) is True

    def test_get_signals_since_returns_recent(self, tmp_db):
        ts_before = int(time.time()) - 1
        s1 = make_signal(url="https://example.com/grant/1")
        s2 = make_signal(url="https://example.com/grant/2")
        tmp_db.mark_signal_seen(s1)
        tmp_db.mark_signal_seen(s2)
        rows = tmp_db.get_signals_since(ts_before)
        assert len(rows) == 2

    def test_get_signals_since_excludes_old(self, tmp_db):
        s1 = make_signal(url="https://example.com/grant/1")
        tmp_db.mark_signal_seen(s1)
        # Query for signals seen in the future — should return nothing
        future_ts = int(time.time()) + 3600
        rows = tmp_db.get_signals_since(future_ts)
        assert len(rows) == 0

    def test_get_signals_since_filter_by_source(self, tmp_db):
        ts_before = int(time.time()) - 1
        s1 = make_signal(source="sbir", url="https://example.com/sbir/1")
        s2 = make_signal(source="fedregister", url="https://example.com/fed/1")
        tmp_db.mark_signal_seen(s1)
        tmp_db.mark_signal_seen(s2)
        rows = tmp_db.get_signals_since(ts_before, source="sbir")
        assert len(rows) == 1
        assert rows[0].source == "sbir"

    def test_get_signals_since_returns_signal_row_fields(self, tmp_db):
        ts_before = int(time.time()) - 1
        s = make_signal(
            source="sbir",
            signal_type="grant_award",
            title="Test grant",
            url="https://example.com/grant/99",
            published="2024-01-15",
            ticker="UNH",
            company="UnitedHealth",
            amount_usd=500_000.0,
            data={"agency": "NIH"},
        )
        tmp_db.mark_signal_seen(s)
        rows = tmp_db.get_signals_since(ts_before)
        assert len(rows) == 1
        row = rows[0]
        assert row.id == s.id
        assert row.source == "sbir"
        assert row.signal_type == "grant_award"
        assert row.title == "Test grant"
        assert row.ticker == "UNH"
        assert row.company == "UnitedHealth"
        assert row.amount_usd == 500_000.0
        assert row.data == {"agency": "NIH"}

    def test_signal_count_since(self, tmp_db):
        ts_before = int(time.time()) - 1
        s1 = make_signal(source="sbir", url="https://example.com/sbir/1")
        s2 = make_signal(source="sbir", url="https://example.com/sbir/2")
        s3 = make_signal(source="fedregister", url="https://example.com/fed/1")
        tmp_db.mark_signal_seen(s1)
        tmp_db.mark_signal_seen(s2)
        tmp_db.mark_signal_seen(s3)
        counts = tmp_db.signal_count_since(ts_before)
        assert counts["sbir"] == 2
        assert counts["fedregister"] == 1

    def test_signal_count_since_empty(self, tmp_db):
        ts = int(time.time()) - 1
        counts = tmp_db.signal_count_since(ts)
        assert counts == {}

    def test_signal_count_excludes_old_signals(self, tmp_db):
        s = make_signal(url="https://example.com/grant/1")
        tmp_db.mark_signal_seen(s)
        future_ts = int(time.time()) + 3600
        counts = tmp_db.signal_count_since(future_ts)
        assert counts == {}

    def test_context_manager(self, tmp_path):
        from govspend_signals.storage import Storage
        with Storage(tmp_path / "ctx.db") as store:
            store.upsert_ticker("UNH", 72971, "UnitedHealth")
        # After __exit__, connection is closed — no error raised


def test_get_signal_counts_by_sector(tmp_path):
    from govspend_signals.storage import Storage
    from govspend_signals.signal import Signal
    import time

    db = tmp_path / "state.db"
    sectors_data = {
        "healthcare": [("grants_gov", "nofo_healthcare"), ("propublica", "bill_healthcare")],
        "energy_utilities": [("grants_gov", "nofo_energy_utilities")],
        "infrastructure": [("propublica", "bill_infrastructure")],
    }
    with Storage(db) as store:
        for sector, items in sectors_data.items():
            for source, signal_type in items:
                sig = Signal(
                    source=source, signal_type=signal_type,
                    title=f"Test {signal_type}", url=f"https://example.com/{signal_type}",
                    published="2026-05-10", ticker=None, company=None,
                    amount_usd=None, data={},
                )
                store.mark_signal_seen(sig)
        since_ts = int(time.time()) - 3600
        counts = store.get_signal_counts_by_sector(since_ts)

    assert counts.get("healthcare", 0) == 2
    assert counts.get("energy_utilities", 0) == 1
    assert counts.get("infrastructure", 0) == 1


def test_get_signal_counts_by_sector_source_fallback(tmp_path):
    """Source-level bucket used for ingestors without sector in signal_type."""
    from govspend_signals.storage import Storage
    from govspend_signals.signal import Signal
    import time

    db = tmp_path / "state2.db"
    with Storage(db) as store:
        sig = Signal(
            source="usaspending", signal_type="contract_award",
            title="Big contract", url="https://example.com/usa",
            published="2026-05-10", ticker="UNH", company=None,
            amount_usd=5_000_000.0, data={},
        )
        store.mark_signal_seen(sig)
        since_ts = int(time.time()) - 3600
        counts = store.get_signal_counts_by_sector(since_ts)

    assert counts.get("contracts", 0) == 1
