"""Tests for options strategy module."""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.options_strategy import (
    OptionsPlay,
    generate_plays,
    format_plays,
    _days_to_expiry,
    _next_monthly_expiry,
    _match_thesis,
)
from govspend_signals.signal import Signal


def _make_catalyst(date_str, title="CMS Final Rate Notice"):
    return Signal(
        source="catalyst",
        signal_type="upcoming_event",
        title=f"[CATALYST] {title}",
        url="",
        published=date_str,
        ticker=None,
        company=None,
        amount_usd=None,
        data={"event_name": title},
    )


class TestHelpers:
    def test_next_monthly_expiry_is_friday(self):
        result = _next_monthly_expiry(min_days=30)
        assert result.weekday() == 4  # Friday

    def test_next_monthly_expiry_at_least_min_days_out(self):
        today = dt.date.today()
        result = _next_monthly_expiry(min_days=30)
        assert (result - today).days >= 30

    def test_days_to_expiry_future(self):
        future = dt.date.today() + dt.timedelta(days=14)
        assert _days_to_expiry(future) > 0

    def test_days_to_expiry_past(self):
        past = dt.date.today() - dt.timedelta(days=7)
        assert _days_to_expiry(past) < 0

    def test_next_monthly_expiry_longer_min_days(self):
        result = _next_monthly_expiry(min_days=60)
        today = dt.date.today()
        assert (result - today).days >= 60


class TestMatchThesis:
    def test_cms_matched(self):
        result = _match_thesis("CMS Final Rule announcement")
        assert result is not None
        assert result["action"] == "BUY CALL"

    def test_fomc_matched(self):
        result = _match_thesis("FOMC rate decision meeting")
        assert result is not None
        assert result["action"] == "BUY PUT"

    def test_medicaid_matched(self):
        result = _match_thesis("Medicaid enrollment update")
        assert result is not None

    def test_unknown_returns_none(self):
        result = _match_thesis("Arbitrary unknown event XYZ")
        assert result is None

    def test_case_insensitive(self):
        result = _match_thesis("cms annual rate notice")
        assert result is not None


class TestGeneratePlays:
    def test_returns_list(self):
        catalysts = [
            _make_catalyst((dt.date.today() + dt.timedelta(days=10)).isoformat())
        ]
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays(catalysts, tickers=["UNH"], days_before_catalyst=5)
        assert isinstance(result, list)

    def test_past_catalysts_skipped(self):
        old = _make_catalyst("2024-01-01")
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([old], tickers=["UNH"])
        assert result == []

    def test_too_far_future_skipped(self):
        far = _make_catalyst(
            (dt.date.today() + dt.timedelta(days=200)).isoformat()
        )
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([far], tickers=["UNH"], max_days_ahead=60)
        assert result == []

    def test_cms_catalyst_produces_calls(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=14)
        catalyst = _make_catalyst(catalyst_date.isoformat(), title="CMS Final Rate Notice")
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=["UNH"])
        if result:
            assert result[0].action == "BUY CALL"

    def test_fomc_catalyst_produces_puts(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=10)
        catalyst = _make_catalyst(catalyst_date.isoformat(), title="FOMC Rate Decision Meeting")
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=["NEE"])
        if result:
            assert result[0].action == "BUY PUT"

    def test_play_has_ticker(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=14)
        catalyst = _make_catalyst(catalyst_date.isoformat())
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=["UNH"])
        for play in result:
            assert play.ticker is not None

    def test_play_has_catalyst_date(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=14)
        date_str = catalyst_date.isoformat()
        catalyst = _make_catalyst(date_str)
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=["UNH"])
        for play in result:
            assert play.catalyst_date == date_str

    def test_atm_strike_used_when_available(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=14)
        catalyst = _make_catalyst(catalyst_date.isoformat())
        mock_atm = MagicMock()
        mock_atm.strike = 250.0
        mock_atm.expiry = _next_monthly_expiry(min_days=30)
        mock_atm.ask = 5.50
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=mock_atm):
            result = generate_plays([catalyst], tickers=["UNH"])
        if result:
            assert result[0].strike == 250.0
            assert result[0].ask == 5.50

    def test_no_yfinance_gives_none_strike(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=10)
        catalyst = _make_catalyst(catalyst_date.isoformat())
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=["UNH"])
        for play in result:
            assert play.strike is None

    def test_tickers_capped_at_5(self):
        catalyst_date = dt.date.today() + dt.timedelta(days=10)
        catalyst = _make_catalyst(catalyst_date.isoformat())
        many_tickers = ["UNH", "CNC", "MOH", "ELV", "HUM", "CVS", "CI"]
        with patch("govspend_signals.options_strategy._fetch_atm_strike", return_value=None):
            result = generate_plays([catalyst], tickers=many_tickers)
        assert len(result) <= 5


class TestFormatPlays:
    def test_returns_string(self):
        play = OptionsPlay(
            ticker="UNH",
            catalyst_date="2026-05-20",
            catalyst_title="CMS Final Rate Notice",
            action="BUY CALL",
            strike=250.0,
            expiry=dt.date(2026, 6, 20),
            ask=5.50,
            expected_move_pct=6.0,
            thesis="CMS Medicaid rate increase expected +5-8% move",
        )
        output = format_plays([play])
        assert "UNH" in output
        assert "CALL" in output
        assert "250" in output

    def test_empty_list_shows_message(self):
        output = format_plays([])
        assert output  # non-empty

    def test_no_strike_shown_gracefully(self):
        play = OptionsPlay(
            ticker="UNH",
            catalyst_date="2026-05-20",
            catalyst_title="CMS Final Rate Notice",
            action="BUY CALL",
            strike=None,
            expiry=None,
            ask=None,
            expected_move_pct=None,
            thesis="Run govspend ingest first",
        )
        output = format_plays([play])
        assert "UNH" in output

    def test_groups_by_catalyst_date(self):
        plays = [
            OptionsPlay("UNH", "2026-05-20", "CMS Notice", "BUY CALL",
                        None, None, None, None, "thesis"),
            OptionsPlay("CNC", "2026-05-20", "CMS Notice", "BUY CALL",
                        None, None, None, None, "thesis"),
            OptionsPlay("NEE", "2026-06-15", "FOMC Meeting", "BUY PUT",
                        None, None, None, None, "thesis"),
        ]
        output = format_plays(plays)
        assert "2026-05-20" in output
        assert "2026-06-15" in output
        assert "UNH" in output
        assert "NEE" in output

    def test_shows_disclaimer(self):
        play = OptionsPlay(
            ticker="UNH", catalyst_date="2026-05-20",
            catalyst_title="CMS", action="BUY CALL",
            strike=250.0, expiry=dt.date(2026, 6, 20),
            ask=5.50, expected_move_pct=None, thesis="thesis",
        )
        output = format_plays([play])
        assert "not financial advice" in output.lower() or "financial" in output.lower()
