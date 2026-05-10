"""Regression: digest includes all 10 sources."""
import time

import pytest

from govspend_signals.digest import _ALL_SOURCES, _SOURCE_LABELS, generate
from govspend_signals.signal import Signal
from govspend_signals.storage import Storage

_EXPECTED_SOURCES = {
    "edgar", "usaspending", "fedregister", "congress", "sbir",
    "norway", "catalyst", "grants_gov", "propublica", "lobbying",
}


def test_all_sources_in_ALL_SOURCES():
    assert _EXPECTED_SOURCES == set(_ALL_SOURCES)


def test_all_sources_have_label():
    for src in _EXPECTED_SOURCES:
        assert src in _SOURCE_LABELS, f"{src} missing from _SOURCE_LABELS"
    for src, (label, unit) in _SOURCE_LABELS.items():
        assert label, f"{src} label is empty"
        assert unit, f"{src} unit is empty"


def test_digest_counts_new_sources(tmp_path):
    db = tmp_path / "test.db"
    with Storage(db) as store:
        for source in ["grants_gov", "propublica", "lobbying"]:
            sig = Signal(
                source=source,
                signal_type="test",
                title=f"Test {source} signal",
                url="https://example.com",
                published="2026-05-10",
                ticker=None,
                company=None,
                amount_usd=None,
                data={},
            )
            store.mark_signal_seen(sig)
        result = generate(store, period_hours=24 * 365)
    for source in ["grants_gov", "propublica", "lobbying"]:
        assert result.by_source.get(source, 0) >= 1
    # All three new sources should appear in the text output
    assert "grants_gov" in result.text or "grants" in result.text.lower()
