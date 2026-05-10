"""Tests for sector rotation tracker."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from govspend_signals.sector_rotation import (
    SectorSnapshot,
    compute_rotation,
    format_rotation_table,
)


def _mock_store(current: dict[str, int], prior: dict[str, int]):
    store = MagicMock()
    store.get_signal_counts_by_sector.side_effect = [current, prior]
    return store


class TestComputeRotation:
    def test_returns_list_of_snapshots(self):
        store = _mock_store({"healthcare": 10}, {"healthcare": 5})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert isinstance(result, list)
        assert all(isinstance(r, SectorSnapshot) for r in result)

    def test_velocity_computed(self):
        store = _mock_store(
            {"healthcare": 10, "infrastructure": 3},
            {"healthcare": 5, "infrastructure": 3},
        )
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        by_sector = {r.sector: r for r in result}
        assert by_sector["healthcare"].current_count == 10
        assert by_sector["healthcare"].prior_count == 5

    def test_sorted_by_current_desc(self):
        store = _mock_store(
            {"healthcare": 10, "infrastructure": 20, "energy_utilities": 5},
            {"healthcare": 5, "infrastructure": 10, "energy_utilities": 2},
        )
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        counts = [r.current_count for r in result]
        assert counts == sorted(counts, reverse=True)

    def test_zero_prior_no_crash(self):
        store = _mock_store({"healthcare": 5}, {"healthcare": 0})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert result[0].pct_change is None  # can't divide by zero

    def test_pct_change_computed(self):
        store = _mock_store({"healthcare": 10}, {"healthcare": 5})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert result[0].pct_change == pytest.approx(100.0)

    def test_pct_change_negative(self):
        store = _mock_store({"healthcare": 3}, {"healthcare": 10})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert result[0].pct_change == pytest.approx(-70.0)

    def test_empty_store_returns_empty(self):
        store = _mock_store({}, {})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert result == []

    def test_sector_only_in_prior_appears_with_zero_current(self):
        store = _mock_store({}, {"healthcare": 5})
        result = compute_rotation(store, window_hours=24, compare_hours=168)
        assert len(result) == 1
        assert result[0].current_count == 0
        assert result[0].prior_count == 5


class TestFormatRotationTable:
    def test_returns_string(self):
        snapshots = [
            SectorSnapshot("healthcare", 10, 5, 100.0),
            SectorSnapshot("infrastructure", 3, 3, 0.0),
        ]
        output = format_rotation_table(snapshots, window_hours=24, compare_hours=168)
        assert isinstance(output, str)
        assert "healthcare" in output
        assert "infrastructure" in output

    def test_shows_pct_change_positive(self):
        snapshots = [SectorSnapshot("healthcare", 10, 5, 100.0)]
        output = format_rotation_table(snapshots, window_hours=24, compare_hours=168)
        assert "+100" in output or "+100.0" in output

    def test_shows_pct_change_negative(self):
        snapshots = [SectorSnapshot("healthcare", 3, 10, -70.0)]
        output = format_rotation_table(snapshots, window_hours=24, compare_hours=168)
        assert "-70" in output

    def test_none_pct_shown_as_new(self):
        snapshots = [SectorSnapshot("healthcare", 5, 0, None)]
        output = format_rotation_table(snapshots, window_hours=24, compare_hours=168)
        assert "new" in output.lower() or "n/a" in output.lower()

    def test_empty_returns_message(self):
        output = format_rotation_table([], window_hours=24, compare_hours=168)
        assert output  # non-empty

    def test_shows_bar_chart(self):
        snapshots = [SectorSnapshot("healthcare", 10, 5, 100.0)]
        output = format_rotation_table(snapshots, window_hours=24, compare_hours=168)
        assert "█" in output

    def test_window_hours_in_header(self):
        snapshots = [SectorSnapshot("healthcare", 10, 5, 100.0)]
        output = format_rotation_table(snapshots, window_hours=48, compare_hours=336)
        assert "48" in output
        assert "336" in output
