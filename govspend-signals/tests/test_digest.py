"""Tests for govspend_signals.digest — generate() and formatting helpers."""
from __future__ import annotations

import time

import pytest

from govspend_signals.digest import generate, DigestResult
from govspend_signals.signal import Signal
from govspend_signals.storage import Storage


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_signal(source: str = "sbir", url: str = "https://example.com/1", **kwargs) -> Signal:
    defaults = dict(
        signal_type="grant_award",
        title="Test grant",
        published="2026-05-09",
    )
    defaults.update(kwargs)
    return Signal(source=source, url=url, **defaults)


def _seed(store: Storage, *signals: Signal) -> None:
    for s in signals:
        store.mark_signal_seen(s)


# ── basic generate() tests ────────────────────────────────────────────────────

class TestGenerateBasic:
    def test_generate_returns_digest_result(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert isinstance(result, DigestResult)

    def test_generate_empty_db_has_zero_signals(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert result.total_signals == 0

    def test_generate_counts_signals(self, tmp_db):
        _seed(
            tmp_db,
            _make_signal(source="sbir", url="https://example.com/1"),
            _make_signal(source="sbir", url="https://example.com/2"),
            _make_signal(source="fedregister", url="https://example.com/3"),
        )
        result = generate(tmp_db, period_hours=24)
        assert result.total_signals == 3

    def test_generate_by_source_counts(self, tmp_db):
        _seed(
            tmp_db,
            _make_signal(source="sbir", url="https://example.com/1"),
            _make_signal(source="sbir", url="https://example.com/2"),
            _make_signal(source="fedregister", url="https://example.com/3"),
        )
        result = generate(tmp_db, period_hours=24)
        assert result.by_source.get("sbir", 0) == 2
        assert result.by_source.get("fedregister", 0) == 1

    def test_generate_period_hours_respected(self, tmp_db):
        """Signals seen 'now' should appear in 24h but vanish from 0h window."""
        _seed(tmp_db, _make_signal(url="https://example.com/1"))
        result_24h = generate(tmp_db, period_hours=24)
        assert result_24h.total_signals == 1

    def test_generate_top_signals_sorted_by_amount(self, tmp_db):
        big = _make_signal(source="usaspending", url="https://example.com/big", amount_usd=5_000_000.0)
        small = _make_signal(source="usaspending", url="https://example.com/small", amount_usd=100_000.0)
        none_ = _make_signal(source="catalyst", url="https://example.com/none", amount_usd=None)
        _seed(tmp_db, big, small, none_)

        result = generate(tmp_db, period_hours=24)
        # Top signals should be sorted by amount desc; None last
        top = result.top_signals
        amounts = [r.amount_usd for r in top]
        non_none = [a for a in amounts if a is not None]
        assert non_none == sorted(non_none, reverse=True)

    def test_generate_top_signals_max_20(self, tmp_db):
        for i in range(25):
            _seed(tmp_db, _make_signal(url=f"https://example.com/{i}", amount_usd=float(i)))
        result = generate(tmp_db, period_hours=24)
        assert len(result.top_signals) <= 20

    def test_generate_period_hours_stored(self, tmp_db):
        result = generate(tmp_db, period_hours=48)
        assert result.period_hours == 48


# ── text output tests ─────────────────────────────────────────────────────────

class TestTextOutput:
    def test_text_contains_header(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert "MORNING DIGEST" in result.text

    def test_text_contains_all_source_labels(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        for source in ("edgar", "usaspending", "fedregister", "congress", "sbir", "norway", "catalyst"):
            assert source in result.text

    def test_text_contains_signal_count(self, tmp_db):
        _seed(tmp_db, _make_signal(url="https://example.com/1"))
        result = generate(tmp_db, period_hours=24)
        assert "1" in result.text

    def test_text_includes_signal_title_in_all_section(self, tmp_db):
        sig = _make_signal(title="QuantumCo wins big", url="https://example.com/1")
        _seed(tmp_db, sig)
        result = generate(tmp_db, period_hours=24)
        assert "QuantumCo wins big" in result.text

    def test_text_includes_signal_url(self, tmp_db):
        sig = _make_signal(url="https://example.com/specific-signal")
        _seed(tmp_db, sig)
        result = generate(tmp_db, period_hours=24)
        assert "https://example.com/specific-signal" in result.text

    def test_text_no_signals_shows_none(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert "(no signals)" in result.text


# ── HTML output tests ─────────────────────────────────────────────────────────

class TestHtmlOutput:
    def test_html_is_valid_doctype(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert result.html.strip().startswith("<!DOCTYPE html>")

    def test_html_contains_title(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        assert "govspend-signals" in result.html or "Digest" in result.html

    def test_html_contains_all_source_labels(self, tmp_db):
        result = generate(tmp_db, period_hours=24)
        for source in ("edgar", "usaspending", "fedregister", "congress", "sbir", "norway", "catalyst"):
            assert source in result.html

    def test_html_contains_signal_link(self, tmp_db):
        sig = _make_signal(url="https://example.com/signal-link", title="Linked signal")
        _seed(tmp_db, sig)
        result = generate(tmp_db, period_hours=24)
        assert "https://example.com/signal-link" in result.html
        assert "Linked signal" in result.html
