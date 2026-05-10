"""Smoke tests for the Rich terminal dashboard.

These tests verify that the dashboard functions don't crash and produce
output, without requiring a real TTY or Rich library.
"""
from __future__ import annotations

import time
from io import StringIO
from unittest.mock import MagicMock, patch, PropertyMock
import sys

import pytest

from govspend_signals.signal import Signal


def _make_signal(
    source="usaspending",
    signal_type="contract_award",
    title="Test contract award",
    ticker="UNH",
    amount_usd=5_000_000.0,
    published="2025-04-01",
):
    return Signal(
        source=source,
        signal_type=signal_type,
        title=title,
        url="https://example.com/test",
        published=published,
        ticker=ticker,
        company="Test Company",
        amount_usd=amount_usd,
        data={},
    )


class TestDashboardImport:
    def test_module_importable(self):
        import govspend_signals.dashboard as dash
        assert hasattr(dash, "render_static")
        assert hasattr(dash, "render_live")

    def test_source_styles_defined(self):
        from govspend_signals.dashboard import SOURCE_STYLES
        for source in ["edgar", "usaspending", "fedregister", "congress", "sbir",
                       "norway", "catalyst", "grants_gov", "propublica", "lobbying"]:
            assert source in SOURCE_STYLES

    def test_source_icons_defined(self):
        from govspend_signals.dashboard import SOURCE_ICONS
        for source in ["edgar", "usaspending", "fedregister", "congress", "sbir",
                       "norway", "catalyst", "grants_gov", "propublica", "lobbying"]:
            assert source in SOURCE_ICONS


class TestDashboardWithoutRich:
    """Verify graceful fallback when Rich is not installed."""

    def test_render_static_no_rich(self):
        import govspend_signals.dashboard as dash
        original = dash._RICH_AVAILABLE
        try:
            dash._RICH_AVAILABLE = False
            store = MagicMock()
            # Should print an error and not raise
            with patch("builtins.print") as mock_print:
                dash.render_static(store)
            mock_print.assert_called_once()
            args = mock_print.call_args[0][0]
            assert "rich" in args.lower() or "pip" in args.lower()
        finally:
            dash._RICH_AVAILABLE = original

    def test_render_live_no_rich(self):
        import govspend_signals.dashboard as dash
        original = dash._RICH_AVAILABLE
        try:
            dash._RICH_AVAILABLE = False
            store = MagicMock()
            with patch("builtins.print") as mock_print:
                dash.render_live(store)
            mock_print.assert_called_once()
        finally:
            dash._RICH_AVAILABLE = original


class TestMakeSignalTable:
    def test_returns_table_with_rich(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_signal_table
        table = _make_signal_table([])
        from rich.table import Table
        assert isinstance(table, Table)

    def test_empty_rows_adds_placeholder(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_signal_table
        table = _make_signal_table([])
        # Row count should include the placeholder row
        assert table.row_count >= 1

    def test_rows_populate_table(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_signal_table
        sigs = [_make_signal() for _ in range(5)]
        table = _make_signal_table(sigs)
        assert table.row_count == 5

    def test_max_rows_respected(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_signal_table
        sigs = [_make_signal() for _ in range(50)]
        table = _make_signal_table(sigs, max_rows=10)
        assert table.row_count == 10

    def test_no_ticker_shows_dash(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_signal_table
        sig = _make_signal(ticker=None)
        table = _make_signal_table([sig])
        # Should not crash when ticker is None
        assert table.row_count == 1


class TestMakeSourcePanel:
    def test_returns_panel_with_rich(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_source_panel
        from rich.panel import Panel
        panel = _make_source_panel({"edgar": 5, "usaspending": 3})
        assert isinstance(panel, Panel)

    def test_empty_source_dict(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_source_panel
        panel = _make_source_panel({})
        assert panel is not None


class TestMakeTickerPanel:
    def test_no_tickers_shows_placeholder(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_ticker_panel
        panel = _make_ticker_panel([])
        assert panel is not None

    def test_aggregates_by_ticker(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_ticker_panel
        sigs = [_make_signal(ticker="UNH", amount_usd=1_000_000) for _ in range(3)]
        panel = _make_ticker_panel(sigs)
        assert panel is not None

    def test_skips_none_ticker(self):
        pytest.importorskip("rich")
        from govspend_signals.dashboard import _make_ticker_panel
        sigs = [_make_signal(ticker=None)]
        panel = _make_ticker_panel(sigs)
        assert panel is not None


class TestRenderStatic:
    def test_render_static_runs_with_rich(self, tmp_path):
        pytest.importorskip("rich")
        import sqlite3
        from govspend_signals.storage import Storage

        db = tmp_path / "test.db"
        with Storage(db) as store:
            from govspend_signals import dashboard as dash
            # Should not raise
            dash.render_static(store, period_hours=24)
