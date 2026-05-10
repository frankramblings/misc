"""Tests for govspend_signals.notifier — StdoutNotifier, JsonlNotifier, FanoutNotifier."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.edgar import Filing
from govspend_signals.notifier import StdoutNotifier, JsonlNotifier, FanoutNotifier


# ── helpers ───────────────────────────────────────────────────────────────────

def make_filing(**kwargs) -> Filing:
    defaults = dict(
        cik=72971,
        ticker="UNH",
        company="UnitedHealth Group",
        accession="0000072971-24-000001",
        form="8-K",
        filing_date="2024-01-15",
        primary_doc="d123.htm",
        primary_doc_description="8-K",
    )
    defaults.update(kwargs)
    return Filing(**defaults)


# ── StdoutNotifier tests ──────────────────────────────────────────────────────

class TestStdoutNotifier:
    def test_stdout_notifier_emits(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing()
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert captured.out.strip() != ""

    def test_stdout_notifier_includes_ticker(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing(ticker="UNH")
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert "UNH" in captured.out

    def test_stdout_notifier_includes_form(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing(form="8-K")
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert "8-K" in captured.out

    def test_stdout_notifier_includes_date(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing(filing_date="2024-01-15")
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert "2024-01-15" in captured.out

    def test_stdout_notifier_includes_url(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing()
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert filing.url in captured.out

    def test_stdout_notifier_includes_company(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing(company="UnitedHealth Group")
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert "UnitedHealth Group" in captured.out

    def test_stdout_notifier_ends_with_newline(self, capsys):
        notifier = StdoutNotifier()
        filing = make_filing()
        notifier.emit(filing)
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")


# ── JsonlNotifier tests ───────────────────────────────────────────────────────

class TestJsonlNotifier:
    def test_jsonl_notifier_writes_record(self, tmp_path):
        path = tmp_path / "events.jsonl"
        notifier = JsonlNotifier(path)
        filing = make_filing()
        notifier.emit(filing)
        assert path.exists()
        with path.open() as fh:
            line = fh.readline().strip()
        record = json.loads(line)
        assert record is not None

    def test_jsonl_notifier_record_has_expected_fields(self, tmp_path):
        path = tmp_path / "events.jsonl"
        notifier = JsonlNotifier(path)
        filing = make_filing()
        notifier.emit(filing)
        with path.open() as fh:
            record = json.loads(fh.readline())
        assert "ticker" in record
        assert "form" in record
        assert "filing_date" in record
        assert "url" in record
        assert "index_url" in record

    def test_jsonl_notifier_record_values(self, tmp_path):
        path = tmp_path / "events.jsonl"
        notifier = JsonlNotifier(path)
        filing = make_filing(ticker="UNH", form="8-K", filing_date="2024-01-15")
        notifier.emit(filing)
        with path.open() as fh:
            record = json.loads(fh.readline())
        assert record["ticker"] == "UNH"
        assert record["form"] == "8-K"
        assert record["filing_date"] == "2024-01-15"
        assert record["url"] == filing.url
        assert record["index_url"] == filing.index_url

    def test_jsonl_notifier_appends(self, tmp_path):
        path = tmp_path / "events.jsonl"
        notifier = JsonlNotifier(path)
        f1 = make_filing(accession="0000072971-24-000001")
        f2 = make_filing(accession="0000072971-24-000002")
        notifier.emit(f1)
        notifier.emit(f2)
        with path.open() as fh:
            lines = [l.strip() for l in fh if l.strip()]
        assert len(lines) == 2

    def test_jsonl_notifier_each_line_valid_json(self, tmp_path):
        path = tmp_path / "events.jsonl"
        notifier = JsonlNotifier(path)
        for i in range(3):
            notifier.emit(make_filing(accession=f"0000072971-24-00000{i}"))
        with path.open() as fh:
            for line in fh:
                if line.strip():
                    json.loads(line)  # should not raise

    def test_jsonl_notifier_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "events.jsonl"
        notifier = JsonlNotifier(path)
        notifier.emit(make_filing())
        assert path.exists()


# ── FanoutNotifier tests ──────────────────────────────────────────────────────

class TestFanoutNotifier:
    def test_fanout_notifier_calls_both(self):
        mock_a = MagicMock()
        mock_b = MagicMock()
        fanout = FanoutNotifier(mock_a, mock_b)
        filing = make_filing()
        fanout.emit(filing)
        mock_a.emit.assert_called_once_with(filing)
        mock_b.emit.assert_called_once_with(filing)

    def test_fanout_notifier_continues_on_error(self):
        mock_a = MagicMock()
        mock_a.emit.side_effect = RuntimeError("first child exploded")
        mock_b = MagicMock()
        fanout = FanoutNotifier(mock_a, mock_b)
        filing = make_filing()
        # Should not raise even though mock_a raises
        fanout.emit(filing)
        mock_b.emit.assert_called_once_with(filing)

    def test_fanout_notifier_error_goes_to_stderr(self, capsys):
        mock_a = MagicMock()
        mock_a.emit.side_effect = ValueError("boom")
        mock_b = MagicMock()
        fanout = FanoutNotifier(mock_a, mock_b)
        fanout.emit(make_filing())
        captured = capsys.readouterr()
        assert "boom" in captured.err or "notifier error" in captured.err

    def test_fanout_notifier_no_children(self):
        fanout = FanoutNotifier()
        # Should not raise with no children
        fanout.emit(make_filing())

    def test_fanout_notifier_single_child(self):
        mock_a = MagicMock()
        fanout = FanoutNotifier(mock_a)
        filing = make_filing()
        fanout.emit(filing)
        mock_a.emit.assert_called_once_with(filing)

    def test_fanout_notifier_all_errors_still_completes(self):
        mock_a = MagicMock()
        mock_a.emit.side_effect = RuntimeError("a failed")
        mock_b = MagicMock()
        mock_b.emit.side_effect = RuntimeError("b failed")
        fanout = FanoutNotifier(mock_a, mock_b)
        # Should not raise even when both children fail
        fanout.emit(make_filing())
        mock_a.emit.assert_called_once()
        mock_b.emit.assert_called_once()
