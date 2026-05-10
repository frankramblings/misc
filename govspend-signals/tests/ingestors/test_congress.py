"""Tests for govspend_signals.ingestors.congress."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from govspend_signals.ingestors import congress
from govspend_signals.ingestors.congress import _parse_amount
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


def _recent_date(days_ago: int = 5) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _old_date(days_ago: int = 500) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


_HOUSE_TRADES = [
    {
        "transaction_date": _recent_date(3),
        "ticker": "UNH",
        "asset_description": "UnitedHealth Group Inc.",
        "type": "Purchase",
        "amount": "$15,001-$50,000",
        "representative": "Rep. Jane Smith",
        "disclosure_date": _recent_date(1),
        "ptr_link": "https://disclosures.house.gov/ptr/abc123.pdf",
    },
    {
        "transaction_date": _recent_date(5),
        "ticker": "CVS",
        "asset_description": "CVS Health Corp",
        "type": "Sale (Full)",
        "amount": "$1,001-$15,000",
        "representative": "Rep. John Doe",
        "disclosure_date": _recent_date(2),
        "ptr_link": "https://disclosures.house.gov/ptr/def456.pdf",
    },
]

_SENATE_TRADES: list = []  # Empty for isolation tests


@patch("govspend_signals.ingestors.congress.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_house_trades(mock_get, mock_sleep):
    """House trades within lookback window → Signals with correct fields."""
    mock_get.side_effect = [
        _make_response(_HOUSE_TRADES),   # House call
        _make_response(_SENATE_TRADES),  # Senate call
    ]

    signals = congress.ingest(lookback_days=30)

    # At least the House trades should be returned
    house_signals = [s for s in signals if s.data.get("chamber") == "House"]
    assert len(house_signals) == 2

    unh_signals = [s for s in house_signals if s.ticker == "UNH"]
    assert len(unh_signals) == 1
    s = unh_signals[0]
    assert isinstance(s, Signal)
    assert s.source == "congress"
    assert s.signal_type == "purchase"
    assert "purchased" in s.title
    assert "UNH" in s.title
    assert s.url.endswith(".pdf")
    assert s.amount_usd == 32500.5  # midpoint of $15,001-$50,000


@patch("govspend_signals.ingestors.congress.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_filters_old_trades(mock_get, mock_sleep):
    """Trades outside lookback_days are excluded."""
    old_trade = [
        {
            "transaction_date": _old_date(200),
            "ticker": "AAPL",
            "asset_description": "Apple Inc.",
            "type": "Purchase",
            "amount": "$1,001-$15,000",
            "representative": "Rep. Old Timer",
            "disclosure_date": _old_date(198),
            "ptr_link": "https://disclosures.house.gov/ptr/old.pdf",
        }
    ]
    mock_get.side_effect = [
        _make_response(old_trade),
        _make_response([]),
    ]

    signals = congress.ingest(lookback_days=30)
    assert signals == []


def test_amount_midpoint_parsing():
    """Amount range strings map to correct midpoints."""
    assert _parse_amount("$15,001-$50,000") == 32500.5
    assert _parse_amount("$1,001-$15,000") == 8000.5
    assert _parse_amount("$50,001-$100,000") == 75000.5
    assert _parse_amount("$100,001-$250,000") == 175000.5
    assert _parse_amount("$250,001-$500,000") == 375000.5
    assert _parse_amount("$500,001-$1,000,000") == 750000.5
    assert _parse_amount("$1,000,001-$5,000,000") == 3000000.5
    assert _parse_amount("Over $5,000,000") == 5000000.0
    assert _parse_amount(None) is None


@patch("govspend_signals.ingestors.congress.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_handles_error(mock_get, mock_sleep):
    """Network error on both chambers → empty list, no exception."""
    mock_get.return_value = _make_response({}, status_code=500)

    signals = congress.ingest(lookback_days=30)
    assert signals == []
