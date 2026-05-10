"""Tests for govspend_signals.ingestors.sbir."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.ingestors import sbir
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


_SAMPLE_AWARDS = [
    {
        "contract": "DARPA-D123",
        "firm": "Quantum Dynamics Inc.",
        "award_title": "Advanced sensor prototype",
        "award_amount": 2_500_000,
        "award_date": _recent(2),
        "agency": "DARPA",
        "branch": "Defense",
        "abstract": "Novel sensor development.",
        "solicitationId": "HR001123S0001",
    },
    {
        "contract": "NIH-N456",
        "firm": "BioTech Solutions LLC",
        "award_title": "Cancer biomarker study",
        "award_amount": 750_000,
        "award_date": _recent(1),
        "agency": "NIH",
        "branch": "HHS",
        "abstract": "Phase II cancer research.",
        "solicitationId": "NIH-2024-001",
    },
]


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_returns_signals(mock_get, mock_sleep):
    """Two recent awards → two Signals with correct fields."""
    mock_get.return_value = _make_response({"docs": _SAMPLE_AWARDS})

    signals = sbir.ingest(agencies=["DARPA"], lookback_days=30)

    assert len(signals) == 2
    for s in signals:
        assert isinstance(s, Signal)
        assert s.source == "sbir"
        assert s.signal_type == "grant_award"
        assert s.url.startswith("https://www.sbir.gov/")
        assert s.published  # non-empty date string
        assert s.amount_usd is not None and s.amount_usd > 0


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_title_contains_firm_and_agency(mock_get, mock_sleep):
    mock_get.return_value = _make_response({"docs": [_SAMPLE_AWARDS[0]]})
    signals = sbir.ingest(agencies=["DARPA"], lookback_days=30)
    assert len(signals) == 1
    assert "Quantum Dynamics Inc." in signals[0].title
    assert "DARPA" in signals[0].title


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_filters_old_awards(mock_get, mock_sleep):
    """Award outside lookback_days is excluded."""
    old_award = [
        {
            "contract": "OLD-001",
            "firm": "OldCo",
            "award_title": "Ancient grant",
            "award_amount": 100_000,
            "award_date": (date.today() - timedelta(days=200)).isoformat(),
            "agency": "NSF",
        }
    ]
    mock_get.return_value = _make_response({"docs": old_award})
    signals = sbir.ingest(agencies=["NSF"], lookback_days=30)
    assert signals == []


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_handles_http_error(mock_get, mock_sleep):
    """HTTP error → empty list, no exception."""
    mock_get.return_value = _make_response({}, status_code=503)
    signals = sbir.ingest(agencies=["DARPA"], lookback_days=30)
    assert signals == []


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_multiple_agencies(mock_get, mock_sleep):
    """Each agency gets a separate API call; results are combined."""
    award_per_call = [_SAMPLE_AWARDS[0]]
    mock_get.return_value = _make_response({"docs": award_per_call})

    signals = sbir.ingest(agencies=["DARPA", "NIH"], lookback_days=30)
    # mock returns 1 result per agency call → 2 calls → 2 signals (different URLs)
    assert mock_get.call_count == 2


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_empty_docs_list(mock_get, mock_sleep):
    """Empty docs list → empty signal list."""
    mock_get.return_value = _make_response({"docs": []})
    signals = sbir.ingest(agencies=["DARPA"], lookback_days=30)
    assert signals == []


@patch("govspend_signals.ingestors.sbir.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_missing_contract_uses_fallback_url(mock_get, mock_sleep):
    """Award with no contract number falls back to base URL."""
    award = [{
        "contract": "",
        "firm": "NoCo",
        "award_title": "Widget",
        "award_amount": 50_000,
        "award_date": _recent(1),
        "agency": "DOE",
    }]
    mock_get.return_value = _make_response({"docs": award})
    signals = sbir.ingest(agencies=["DOE"], lookback_days=30)
    assert len(signals) == 1
    assert signals[0].url == "https://www.sbir.gov/"
