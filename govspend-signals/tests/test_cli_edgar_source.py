"""Test that govspend ingest --source edgar actually runs the EDGAR poller."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from govspend_signals.cli import main


def _write_minimal_config(path):
    path.write_text(
        "[poller]\ninterval_seconds=900\n"
        "[watchlist]\nhealthcare=[\"UNH\"]\n"
        "[ingestors]\nlookback_days=7\n"
        "[notifiers.telegram]\nenabled=false\nbot_token=\"\"\nchat_id=\"\"\n"
        "[notifiers.webhook]\nenabled=false\nurl=\"\"\nsecret=\"\"\n"
        "[notifiers.smtp]\nenabled=false\nhost=\"smtp.gmail.com\"\n"
        "port=587\nusername=\"\"\nto=\"\"\n"
    )


def test_ingest_source_edgar_calls_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("GOVSPEND_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("GOVSPEND_EVENTS", str(tmp_path / "events.jsonl"))
    cfg_file = tmp_path / "config.toml"
    _write_minimal_config(cfg_file)

    poll_result = MagicMock()
    poll_result.new_filings = 0
    poll_result.unresolved_tickers = []
    poll_result.errors = []
    poll_result.scanned_tickers = 1

    with patch("govspend_signals.poller.poll_once", return_value=poll_result) as mock_poll, \
         patch("govspend_signals.edgar.EdgarClient.fetch_ticker_map", return_value={}):
        rc = main(["ingest", "--config", str(cfg_file), "--source", "edgar", "--quiet"])

    mock_poll.assert_called_once()
    assert rc == 0


def test_ingest_no_source_does_not_call_poll_directly(tmp_path, monkeypatch):
    """When no --source is given, the general ingest path runs (not poll_once directly)."""
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("GOVSPEND_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("GOVSPEND_EVENTS", str(tmp_path / "events.jsonl"))
    cfg_file = tmp_path / "config.toml"
    _write_minimal_config(cfg_file)

    # All ingestors will fail gracefully — we just verify poll_once is NOT called
    with patch("govspend_signals.poller.poll_once") as mock_poll, \
         patch("govspend_signals.ingestors.usaspending.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.fedregister.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.congress.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.sbir.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.norway.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.catalyst.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.grants_gov.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.propublica.ingest", return_value=[]), \
         patch("govspend_signals.ingestors.lobbying.ingest", return_value=[]):
        rc = main(["ingest", "--config", str(cfg_file), "--quiet"])

    mock_poll.assert_not_called()
    assert rc == 0
