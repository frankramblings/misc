"""Tests for govspend_signals.poller — poll_once()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.config import Config, TelegramConfig, WebhookConfig, SmtpConfig
from govspend_signals.edgar import EdgarClient, Filing
from govspend_signals.notifier import FanoutNotifier
from govspend_signals.poller import poll_once, PollResult, TICKER_MAP_REFRESH_SECONDS
from govspend_signals.storage import Storage


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_config(**overrides) -> Config:
    defaults = dict(
        user_agent="Test User test@example.com",
        db_path=None,
        events_path=None,
        config_path=None,
        interval_seconds=900,
        forms=("SC 13D", "8-K", "4"),
        max_age_days=7,
        scan_limit=100,
        watchlist=("UNH", "MSFT"),
        lookback_days=7,
        usaspending_enabled=True,
        usaspending_agencies=("HHS",),
        usaspending_min_award=1_000_000.0,
        fedregister_enabled=True,
        fedregister_agencies=("CMS",),
        fedregister_doc_types=("RULE",),
        congress_enabled=True,
        sbir_enabled=True,
        sbir_agencies=("DARPA",),
        norway_enabled=True,
        catalyst_enabled=True,
        telegram=TelegramConfig(enabled=False, bot_token="", chat_id=""),
        webhook=WebhookConfig(enabled=False, url="", secret=""),
        smtp=SmtpConfig(
            enabled=False, host="smtp.gmail.com", port=587,
            username="", password="", to="", from_addr="",
        ),
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_filing(ticker: str, accession: str, form: str = "8-K", date: str = "2026-05-09") -> Filing:
    return Filing(
        cik=72971,
        ticker=ticker,
        company="Test Co",
        accession=accession,
        form=form,
        filing_date=date,
        primary_doc="d.htm",
        primary_doc_description=form,
    )


# ── poll_once tests ────────────────────────────────────────────────────────────

class TestPollOnce:
    def test_returns_poll_result(self, tmp_db):
        cfg = _make_config(watchlist=())
        client = MagicMock(spec=EdgarClient)
        client.fetch_ticker_map.return_value = {}
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert isinstance(result, PollResult)

    def test_unresolved_ticker_when_not_in_map(self, tmp_db):
        """Ticker not in DB → counted as unresolved, not an error."""
        cfg = _make_config(watchlist=("AAPL",))
        client = MagicMock(spec=EdgarClient)
        client.fetch_ticker_map.return_value = {}

        result = poll_once(cfg, client, tmp_db, MagicMock())
        assert "AAPL" in result.unresolved_tickers
        assert result.scanned_tickers == 0

    def test_new_filing_is_emitted_and_stored(self, tmp_db):
        """A filing that hasn't been seen before should be emitted once."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",), max_age_days=30)

        filing = _make_filing("UNH", "0000072971-26-000001", form="8-K", date="2026-05-09")
        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = [filing]
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)

        assert result.new_filings == 1
        notifier.emit.assert_called_once_with(filing)
        assert tmp_db.is_seen(filing.accession)

    def test_seen_filing_not_emitted_again(self, tmp_db):
        """A previously-seen accession should NOT trigger another emit."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",), max_age_days=30)

        filing = _make_filing("UNH", "0000072971-26-000001", form="8-K", date="2026-05-09")
        tmp_db.mark_seen(filing)  # pre-mark as seen

        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = [filing]
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert result.new_filings == 0
        notifier.emit.assert_not_called()

    def test_form_filter_excludes_non_matching(self, tmp_db):
        """Filing form not in config.forms should be ignored."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",), forms=("SC 13D",), max_age_days=30)

        # 8-K is not in the forms list
        filing = _make_filing("UNH", "0000072971-26-000001", form="8-K", date="2026-05-09")
        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = [filing]
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert result.new_filings == 0

    def test_old_filing_excluded_by_max_age_days(self, tmp_db):
        """Filing older than max_age_days should not be emitted."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",), forms=("8-K",), max_age_days=7)

        # Date is very old
        filing = _make_filing("UNH", "0000072971-20-000001", form="8-K", date="2020-01-01")
        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = [filing]
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert result.new_filings == 0

    def test_error_in_fetch_is_recorded_not_raised(self, tmp_db):
        """Exception from fetch_recent_filings should be captured in errors list."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",))

        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.side_effect = RuntimeError("EDGAR timeout")
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert len(result.errors) == 1
        assert "UNH" in result.errors[0]
        assert result.new_filings == 0

    def test_scanned_count_matches_resolved_tickers(self, tmp_db):
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        tmp_db.upsert_ticker("MSFT", 789019, "Microsoft")
        cfg = _make_config(watchlist=("UNH", "MSFT", "AAPL"), max_age_days=30)

        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = []
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        # AAPL is not in ticker map → unresolved
        assert result.scanned_tickers == 2
        assert "AAPL" in result.unresolved_tickers

    def test_ticker_map_refreshed_when_absent(self, tmp_db):
        """If ticker map has never been seeded, fetch_ticker_map should be called."""
        cfg = _make_config(watchlist=())
        client = MagicMock(spec=EdgarClient)
        client.fetch_ticker_map.return_value = {"UNH": (72971, "UnitedHealth")}

        poll_once(cfg, client, tmp_db, MagicMock())
        client.fetch_ticker_map.assert_called_once()

    def test_ticker_map_not_refreshed_when_fresh(self, tmp_db):
        """If ticker map was just seeded, fetch_ticker_map should NOT be called again."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",))

        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = []

        poll_once(cfg, client, tmp_db, MagicMock())
        client.fetch_ticker_map.assert_not_called()

    def test_multiple_new_filings(self, tmp_db):
        """Multiple new filings from the same ticker should all be emitted."""
        tmp_db.upsert_ticker("UNH", 72971, "UnitedHealth")
        cfg = _make_config(watchlist=("UNH",), forms=("8-K",), max_age_days=30)

        filings = [
            _make_filing("UNH", f"acc-{i}", form="8-K", date="2026-05-09")
            for i in range(5)
        ]
        client = MagicMock(spec=EdgarClient)
        client.fetch_recent_filings.return_value = filings
        notifier = MagicMock()

        result = poll_once(cfg, client, tmp_db, notifier)
        assert result.new_filings == 5
        assert notifier.emit.call_count == 5
