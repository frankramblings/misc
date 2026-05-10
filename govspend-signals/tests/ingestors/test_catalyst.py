"""Tests for govspend_signals.ingestors.catalyst."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from govspend_signals.ingestors import catalyst
from govspend_signals.signal import Signal


class TestCatalystIngest:
    def test_returns_list_of_signals(self):
        signals = catalyst.ingest(lookback_days=7)
        assert isinstance(signals, list)
        # Some signals should exist (FOMC 2026, CMS events, Beige Book)
        # — at minimum the ones within ±30 days

    def test_all_signals_are_signal_instances(self):
        signals = catalyst.ingest(lookback_days=365)
        for s in signals:
            assert isinstance(s, Signal)

    def test_all_signals_have_source_catalyst(self):
        signals = catalyst.ingest(lookback_days=365)
        for s in signals:
            assert s.source == "catalyst"

    def test_signal_type_is_upcoming_or_recent(self):
        signals = catalyst.ingest(lookback_days=365)
        valid_types = {"upcoming_event", "recent_event"}
        for s in signals:
            assert s.signal_type in valid_types

    def test_upcoming_events_are_in_the_next_30_days(self):
        today = date.today()
        future_cutoff = today + timedelta(days=30)
        signals = catalyst.ingest(lookback_days=0)
        for s in signals:
            if s.signal_type == "upcoming_event":
                event_date = date.fromisoformat(s.published)
                assert today <= event_date <= future_cutoff

    def test_recent_events_are_within_lookback(self):
        lookback = 365
        today = date.today()
        cutoff = today - timedelta(days=lookback)
        signals = catalyst.ingest(lookback_days=lookback)
        for s in signals:
            if s.signal_type == "recent_event":
                event_date = date.fromisoformat(s.published)
                assert cutoff <= event_date < today

    def test_signals_sorted_by_published_date(self):
        signals = catalyst.ingest(lookback_days=365)
        dates = [s.published for s in signals]
        assert dates == sorted(dates)

    def test_title_starts_with_catalyst_prefix(self):
        signals = catalyst.ingest(lookback_days=365)
        for s in signals:
            assert s.title.startswith("[CATALYST]")

    def test_fomc_signals_have_category_fomc(self):
        signals = catalyst.ingest(lookback_days=365)
        fomc_signals = [s for s in signals if "FOMC Meeting" in s.title]
        for s in fomc_signals:
            assert s.data["category"] == "fomc"

    def test_beige_book_signals_present(self):
        signals = catalyst.ingest(lookback_days=365)
        beige = [s for s in signals if "Beige Book" in s.title]
        # Beige Book is generated for each FOMC meeting → at least one
        assert len(beige) >= 1

    def test_cms_signals_have_category_cms(self):
        signals = catalyst.ingest(lookback_days=365)
        cms_signals = [s for s in signals if s.data.get("category") == "cms"]
        # CMS events exist in the calendar
        assert len(cms_signals) >= 1

    def test_no_signals_with_far_future_lookback_zero(self):
        """lookback_days=0 means only upcoming (next 30 days) events."""
        signals = catalyst.ingest(lookback_days=0)
        today = date.today()
        for s in signals:
            # All should be upcoming, none past
            if s.signal_type == "recent_event":
                pytest.fail(f"Got a recent_event with lookback_days=0: {s.title}")

    def test_signals_have_nonempty_url(self):
        signals = catalyst.ingest(lookback_days=365)
        for s in signals:
            assert s.url and s.url.startswith("http")

    def test_signals_have_nonempty_description_in_data(self):
        signals = catalyst.ingest(lookback_days=365)
        for s in signals:
            assert "description" in s.data
            assert s.data["description"]
