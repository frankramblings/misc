"""Tests for ethical screen basket builder."""
from __future__ import annotations

import pytest

from govspend_signals.basket import (
    EXCLUDED_TICKERS,
    BasketPosition,
    build_basket,
    format_basket,
)


class TestExcludedTickers:
    def test_defense_contractors_excluded(self):
        for ticker in ["LMT", "RTX", "NOC", "GD", "BA"]:
            assert ticker in EXCLUDED_TICKERS, f"{ticker} should be excluded"

    def test_fossil_fuel_excluded(self):
        for ticker in ["XOM", "CVX", "COP", "SLB", "HAL"]:
            assert ticker in EXCLUDED_TICKERS, f"{ticker} should be excluded"

    def test_managed_care_not_excluded(self):
        assert "UNH" not in EXCLUDED_TICKERS
        assert "CNC" not in EXCLUDED_TICKERS
        assert "MOH" not in EXCLUDED_TICKERS

    def test_clean_utilities_not_excluded(self):
        assert "NEE" not in EXCLUDED_TICKERS
        assert "XEL" not in EXCLUDED_TICKERS

    def test_infrastructure_not_excluded(self):
        assert "PWR" not in EXCLUDED_TICKERS
        assert "ACM" not in EXCLUDED_TICKERS


class TestBuildBasket:
    def test_returns_list(self):
        result = build_basket(["UNH", "CNC", "LMT"], {})
        assert isinstance(result, list)

    def test_excludes_defense_tickers(self):
        result = build_basket(["UNH", "CNC", "LMT"], {})
        tickers = [p.ticker for p in result]
        assert "LMT" not in tickers
        assert "UNH" in tickers
        assert "CNC" in tickers

    def test_weights_sum_to_100(self):
        result = build_basket(["UNH", "CNC", "MOH", "NEE"], {})
        total = sum(p.weight_pct for p in result)
        assert abs(total - 100.0) < 0.1

    def test_higher_contract_value_gets_higher_weight(self):
        contract_amounts = {"UNH": 10_000_000.0, "CNC": 1_000_000.0}
        result = build_basket(["UNH", "CNC"], contract_amounts)
        by_ticker = {p.ticker: p for p in result}
        assert by_ticker["UNH"].weight_pct > by_ticker["CNC"].weight_pct

    def test_no_signals_gives_equal_weights(self):
        result = build_basket(["UNH", "CNC", "NEE"], {})
        weights = [p.weight_pct for p in result]
        assert max(weights) - min(weights) < 0.1

    def test_all_tickers_excluded_returns_empty(self):
        result = build_basket(["LMT", "RTX", "XOM"], {})
        assert result == []

    def test_sector_labelled(self):
        result = build_basket(["UNH"], {})
        assert result
        assert result[0].sector  # non-empty

    def test_unh_sector_is_healthcare(self):
        result = build_basket(["UNH"], {})
        assert result[0].sector == "healthcare"

    def test_sorted_by_weight_desc(self):
        contract_amounts = {"UNH": 10_000_000.0, "CNC": 5_000_000.0, "NEE": 1_000_000.0}
        result = build_basket(["UNH", "CNC", "NEE"], contract_amounts)
        weights = [p.weight_pct for p in result]
        assert weights == sorted(weights, reverse=True)

    def test_min_weight_drops_small_positions(self):
        # With many tickers and high min_weight, some should be dropped
        many = ["UNH", "CNC", "MOH", "NEE", "DUK", "SO", "PWR", "MTZ",
                "J", "ACM", "CLH", "RSG"]
        result = build_basket(many, {}, min_weight_pct=10.0)
        for pos in result:
            assert pos.weight_pct >= 10.0 - 0.01  # allow float tolerance

    def test_empty_watchlist(self):
        result = build_basket([], {})
        assert result == []

    def test_fossil_excluded_from_mixed_list(self):
        result = build_basket(["UNH", "XOM", "CVX", "NEE"], {})
        tickers = [p.ticker for p in result]
        assert "XOM" not in tickers
        assert "CVX" not in tickers
        assert "UNH" in tickers
        assert "NEE" in tickers


class TestFormatBasket:
    def test_returns_string(self):
        pos = BasketPosition(
            ticker="UNH", sector="healthcare",
            weight_pct=50.0, contract_usd=5_000_000.0,
        )
        output = format_basket([pos])
        assert isinstance(output, str)
        assert "UNH" in output

    def test_shows_weight(self):
        pos = BasketPosition(
            ticker="UNH", sector="healthcare",
            weight_pct=42.5, contract_usd=0.0,
        )
        output = format_basket([pos])
        assert "42.5" in output or "42" in output

    def test_shows_contract_amount(self):
        pos = BasketPosition(
            ticker="UNH", sector="healthcare",
            weight_pct=100.0, contract_usd=5_000_000.0,
        )
        output = format_basket([pos])
        assert "$" in output

    def test_empty_shows_message(self):
        output = format_basket([])
        assert output  # non-empty
        assert "eligible" in output.lower() or "exclude" in output.lower()

    def test_shows_excluded_count(self):
        pos = BasketPosition(
            ticker="UNH", sector="healthcare",
            weight_pct=100.0, contract_usd=0.0,
        )
        output = format_basket([pos])
        assert "Excluded" in output or "excluded" in output.lower()

    def test_shows_total_row(self):
        positions = [
            BasketPosition("UNH", "healthcare", 60.0, 5_000_000.0),
            BasketPosition("NEE", "utilities", 40.0, 2_000_000.0),
        ]
        output = format_basket(positions)
        assert "TOTAL" in output or "100" in output
