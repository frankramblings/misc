"""Tests for govspend_signals.ingestors.norway."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.ingestors import norway
from govspend_signals.signal import Signal


def _make_response(body, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(response=mock)
    else:
        mock.raise_for_status.return_value = None
    return mock


def _recent(days_ago: int = 3) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _make_submissions(forms, filing_dates, accessions, primary_docs=None, primary_descs=None):
    """Build a fake EDGAR submissions JSON payload for Norges Bank."""
    n = len(forms)
    primary_docs = primary_docs or ["doc.htm"] * n
    primary_descs = primary_descs or [""] * n
    return {
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": filing_dates,
                "accessionNumber": accessions,
                "primaryDocument": primary_docs,
                "primaryDocDescription": primary_descs,
            }
        }
    }


class TestNorwayIngest:
    def test_returns_13f_signal(self):
        """13F-HR filing within lookback → Signal with correct fields."""
        payload = _make_submissions(
            forms=["13F-HR"],
            filing_dates=[_recent(2)],
            accessions=["0001463737-24-000001"],
            primary_docs=["primary-13f.xml"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert len(signals) == 1
        s = signals[0]
        assert isinstance(s, Signal)
        assert s.source == "norway"
        assert s.signal_type == "13f_filing"
        assert "Norway SWF" in s.title
        assert "Norges Bank" in (s.company or "")
        assert s.data["form"] == "13F-HR"

    def test_returns_sc_13d_signal(self):
        """SC 13D filing → Signal with signal_type sc_13d."""
        payload = _make_submissions(
            forms=["SC 13D"],
            filing_dates=[_recent(1)],
            accessions=["0001463737-24-000002"],
            primary_docs=["sc13d.htm"],
            primary_descs=["SC 13D"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert len(signals) == 1
        assert signals[0].signal_type == "sc_13d"

    def test_returns_sc_13g_signal(self):
        """SC 13G filing → Signal with signal_type sc_13g."""
        payload = _make_submissions(
            forms=["SC 13G"],
            filing_dates=[_recent(1)],
            accessions=["0001463737-24-000003"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert len(signals) == 1
        assert signals[0].signal_type == "sc_13g"

    def test_filters_old_filings(self):
        """Filings older than lookback_days are excluded."""
        payload = _make_submissions(
            forms=["13F-HR"],
            filing_dates=[(date.today() - timedelta(days=200)).isoformat()],
            accessions=["0001463737-24-000001"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert signals == []

    def test_ignores_irrelevant_form_types(self):
        """Forms not in TARGET_FORMS (e.g., 4, 8-K) are ignored."""
        payload = _make_submissions(
            forms=["4", "8-K", "10-K"],
            filing_dates=[_recent(1), _recent(2), _recent(3)],
            accessions=["acc-1", "acc-2", "acc-3"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert signals == []

    def test_handles_http_error(self):
        """HTTP error on submissions fetch → empty list, no exception."""
        with patch(
            "requests.Session.get",
            return_value=_make_response({}, status_code=503),
        ):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert signals == []

    def test_handles_empty_filings(self):
        """Submissions with no recent filings → empty list."""
        payload = {"filings": {"recent": {}}}
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert signals == []

    def test_multiple_forms_in_window(self):
        """Multiple qualifying filings all returned."""
        payload = _make_submissions(
            forms=["13F-HR", "SC 13G"],
            filing_dates=[_recent(1), _recent(2)],
            accessions=["acc-1", "acc-2"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert len(signals) == 2
        types = {s.signal_type for s in signals}
        assert "13f_filing" in types
        assert "sc_13g" in types

    def test_url_contains_cik(self):
        """The filing URL always references the Norges Bank CIK."""
        payload = _make_submissions(
            forms=["13F-HR"],
            filing_dates=[_recent(1)],
            accessions=["0001463737-24-000001"],
            primary_docs=["primary.xml"],
        )
        with patch("requests.Session.get", return_value=_make_response(payload)):
            signals = norway.ingest(user_agent="Test test@example.com", lookback_days=30)

        assert norway._NORGES_CIK in signals[0].url
