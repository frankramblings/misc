"""Tests for govspend_signals.ingestors.usaspending."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.ingestors import usaspending
from govspend_signals.signal import Signal


def _make_response(body: dict, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(
            response=mock
        )
    else:
        mock.raise_for_status.return_value = None
    return mock


_SAMPLE_RESULTS = [
    {
        "Award ID": "CONT_AWD_ABC123",
        "Recipient Name": "Acme Health Corp",
        "Award Amount": 5_000_000.0,
        "Awarding Agency": "Department of Health and Human Services",
        "Award Type": "Definitive Contract",
        "Start Date": "2024-01-10",
        "Description": "IT services",
        "generated_internal_id": "CONT_AWD_ABC123",
    },
    {
        "Award ID": "CONT_AWD_DEF456",
        "Recipient Name": "Green Solutions LLC",
        "Award Amount": 1_200_000.0,
        "Awarding Agency": "Environmental Protection Agency",
        "Award Type": "Definitive Contract",
        "Start Date": "2024-01-12",
        "Description": "Environmental monitoring",
        "generated_internal_id": "CONT_AWD_DEF456",
    },
]


@patch("govspend_signals.ingestors.usaspending.time.sleep", return_value=None)
@patch("requests.Session.post")
def test_ingest_returns_signals(mock_post, mock_sleep):
    """Two awards above the threshold → two Signals with correct fields."""
    mock_post.return_value = _make_response({"results": _SAMPLE_RESULTS})

    signals = usaspending.ingest(
        agencies=["HHS"],
        lookback_days=30,
        min_award_usd=100_000.0,
    )

    assert len(signals) == 2
    titles = [s.title for s in signals]
    assert any("Acme Health Corp" in t for t in titles)
    assert any("5,000,000" in t for t in titles)

    for s in signals:
        assert isinstance(s, Signal)
        assert s.source == "usaspending"
        assert s.signal_type == "contract_award"
        assert s.url.startswith("https://www.usaspending.gov/award/")
        assert s.published  # non-empty date string
        assert s.amount_usd is not None and s.amount_usd >= 100_000.0


@patch("govspend_signals.ingestors.usaspending.time.sleep", return_value=None)
@patch("requests.Session.post")
def test_ingest_filters_below_threshold(mock_post, mock_sleep):
    """Award below min_award_usd is excluded."""
    low_award = [
        {
            "Award ID": "CONT_AWD_LOW",
            "Recipient Name": "Tiny Vendor",
            "Award Amount": 500.0,
            "Awarding Agency": "Environmental Protection Agency",
            "Award Type": "Definitive Contract",
            "Start Date": "2024-01-10",
            "Description": "Small purchase",
            "generated_internal_id": "CONT_AWD_LOW",
        }
    ]
    mock_post.return_value = _make_response({"results": low_award})

    signals = usaspending.ingest(
        agencies=["EPA"],
        lookback_days=30,
        min_award_usd=1_000.0,
    )

    assert signals == []


@patch("govspend_signals.ingestors.usaspending.time.sleep", return_value=None)
@patch("requests.Session.post")
def test_ingest_handles_http_error(mock_post, mock_sleep):
    """HTTP error returns empty list without raising."""
    mock_post.return_value = _make_response({}, status_code=500)

    signals = usaspending.ingest(
        agencies=["HHS"],
        lookback_days=30,
        min_award_usd=0.0,
    )

    assert signals == []
