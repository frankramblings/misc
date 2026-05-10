"""Tests for price_context catalyst reaction analysis."""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.price_context import (
    CatalystReaction,
    _nearest_price,
    analyse_catalyst_reactions,
    print_reactions,
)
from govspend_signals.signal import Signal


def _make_catalyst(date_str="2025-03-15", title="[CATALYST] FOMC Meeting — rate decision"):
    return Signal(
        source="catalyst",
        signal_type="upcoming_event",
        title=title,
        url="",
        published=date_str,
        ticker=None,
        company=None,
        amount_usd=None,
        data={},
    )


def _make_prices(base_date: dt.date, n: int = 30, base_price: float = 100.0) -> dict[str, float]:
    """Generate fake price series starting `n` days before base_date."""
    prices = {}
    price = base_price
    for i in range(-n, n + 1):
        d = base_date + dt.timedelta(days=i)
        # Skip weekends (rough approximation)
        if d.weekday() < 5:
            prices[d.isoformat()] = price
            price *= 1.002  # +0.2% per day for testing
    return prices


class TestNearestPrice:
    def test_exact_date_found(self):
        prices = {"2025-03-15": 100.0, "2025-03-14": 99.0}
        result = _nearest_price(prices, dt.date(2025, 3, 15), direction=1)
        assert result is not None
        assert result[1] == 100.0

    def test_skips_to_next_trading_day(self):
        prices = {"2025-03-17": 101.0}  # Monday if Saturday = 2025-03-15
        result = _nearest_price(prices, dt.date(2025, 3, 15), direction=1)
        assert result is not None
        assert result[1] == 101.0

    def test_backward_search(self):
        prices = {"2025-03-13": 98.0}
        result = _nearest_price(prices, dt.date(2025, 3, 15), direction=-1)
        # Should look backward for nearest date
        assert result is not None

    def test_no_price_nearby_returns_none(self):
        result = _nearest_price({}, dt.date(2025, 3, 15), direction=1)
        assert result is None


class TestCatalystReaction:
    def test_dataclass_fields(self):
        r = CatalystReaction(
            ticker="UNH",
            catalyst_date="2025-03-15",
            catalyst_title="FOMC",
            return_before=2.5,
            return_after=-1.2,
            days_before=5,
            days_after=10,
        )
        assert r.ticker == "UNH"
        assert r.return_before == 2.5
        assert r.return_after == -1.2


class TestAnalyseCatalystReactions:
    def test_returns_list(self):
        event = _make_catalyst()
        with patch("govspend_signals.price_context._fetch_prices", return_value={}):
            result = analyse_catalyst_reactions([event], tickers=["UNH"])
        assert isinstance(result, list)

    def test_no_events_returns_empty(self):
        result = analyse_catalyst_reactions([], tickers=["UNH"])
        assert result == []

    def test_no_tickers_returns_empty(self):
        event = _make_catalyst()
        result = analyse_catalyst_reactions([event], tickers=[])
        assert result == []

    def test_missing_price_data_returns_empty(self):
        event = _make_catalyst("2025-03-15")
        with patch("govspend_signals.price_context._fetch_prices", return_value={}):
            result = analyse_catalyst_reactions([event], tickers=["UNH"])
        assert result == []

    def test_computes_return_before(self):
        base = dt.date(2025, 3, 15)
        prices = _make_prices(base, n=20)
        event = _make_catalyst(base.isoformat())

        with patch("govspend_signals.price_context._fetch_prices", return_value=prices):
            result = analyse_catalyst_reactions(
                [event], tickers=["UNH"], days_before=5, days_after=10
            )

        assert len(result) == 1
        assert result[0].return_before is not None

    def test_computes_return_after(self):
        base = dt.date(2025, 3, 15)
        prices = _make_prices(base, n=20)
        event = _make_catalyst(base.isoformat())

        with patch("govspend_signals.price_context._fetch_prices", return_value=prices):
            result = analyse_catalyst_reactions(
                [event], tickers=["UNH"], days_before=5, days_after=10
            )

        assert result[0].return_after is not None

    def test_return_is_percentage(self):
        base = dt.date(2025, 3, 15)
        prices = _make_prices(base, n=20, base_price=100.0)
        event = _make_catalyst(base.isoformat())

        with patch("govspend_signals.price_context._fetch_prices", return_value=prices):
            result = analyse_catalyst_reactions(
                [event], tickers=["UNH"], days_before=5, days_after=10
            )

        if result and result[0].return_after is not None:
            # Should be in % terms (not fraction), so roughly -20 to +20 for sane data
            assert -100 < result[0].return_after < 100

    def test_multiple_tickers(self):
        base = dt.date(2025, 3, 15)
        prices = _make_prices(base, n=20)
        event = _make_catalyst(base.isoformat())

        with patch("govspend_signals.price_context._fetch_prices", return_value=prices):
            result = analyse_catalyst_reactions(
                [event], tickers=["UNH", "CNC", "ELV"]
            )

        # One result per ticker (if prices are found)
        tickers_in_result = {r.ticker for r in result}
        assert tickers_in_result.issubset({"UNH", "CNC", "ELV"})

    def test_multiple_events(self):
        base1 = dt.date(2025, 3, 15)
        base2 = dt.date(2025, 6, 15)
        prices = {}
        prices.update(_make_prices(base1, n=20))
        prices.update(_make_prices(base2, n=20))

        events = [_make_catalyst(base1.isoformat()), _make_catalyst(base2.isoformat())]

        with patch("govspend_signals.price_context._fetch_prices", return_value=prices):
            result = analyse_catalyst_reactions(events, tickers=["UNH"])

        assert len(result) == 2

    def test_invalid_date_event_skipped(self):
        event = MagicMock()
        event.published = "not-a-date"
        event.title = "Bad date event"

        with patch("govspend_signals.price_context._fetch_prices", return_value={}):
            result = analyse_catalyst_reactions([event], tickers=["UNH"])
        assert result == []


class TestPrintReactions:
    def test_prints_output(self, capsys):
        r = CatalystReaction(
            ticker="UNH",
            catalyst_date="2025-03-15",
            catalyst_title="FOMC Meeting",
            return_before=1.5,
            return_after=-0.8,
            days_before=5,
            days_after=10,
        )
        print_reactions([r])
        out = capsys.readouterr().out
        assert "UNH" in out
        assert "FOMC" in out

    def test_empty_list_message(self, capsys):
        print_reactions([])
        out = capsys.readouterr().out
        assert out  # Should print something

    def test_none_returns_shown_as_na(self, capsys):
        r = CatalystReaction(
            ticker="UNH",
            catalyst_date="2025-03-15",
            catalyst_title="CMS Rate Notice",
            return_before=None,
            return_after=None,
            days_before=5,
            days_after=10,
        )
        print_reactions([r])
        out = capsys.readouterr().out
        assert "n/a" in out

    def test_avg_stats_shown(self, capsys):
        reactions = [
            CatalystReaction("UNH", "2025-01-15", "FOMC", 1.0, 2.0, 5, 10),
            CatalystReaction("UNH", "2025-04-15", "FOMC", 3.0, -1.0, 5, 10),
        ]
        print_reactions(reactions)
        out = capsys.readouterr().out
        assert "avg" in out.lower()
