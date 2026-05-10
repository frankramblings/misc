"""Tests for govspend_signals.ingestors.fedregister."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.ingestors import fedregister
from govspend_signals.ingestors.fedregister import _agency_to_slug
from govspend_signals.signal import Signal


def _make_response(body: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(response=mock)
    else:
        mock.raise_for_status.return_value = None
    return mock


_SAMPLE_DOCS = [
    {
        "title": "Medicare Advantage Rates 2025",
        "document_number": "2024-12345",
        "publication_date": "2024-04-07",
        "agencies": [{"name": "Centers for Medicare & Medicaid Services"}],
        "html_url": "https://www.federalregister.gov/d/2024-12345",
        "abstract": "Final rate announcement for MA plans.",
        "type": "RULE",
    },
    {
        "title": "Clean Air Standards Update",
        "document_number": "2024-67890",
        "publication_date": "2024-04-10",
        "agencies": [{"name": "Environmental Protection Agency"}],
        "html_url": "https://www.federalregister.gov/d/2024-67890",
        "abstract": "Proposed revisions to air quality standards.",
        "type": "PROPOSED_RULE",
    },
]


@patch("govspend_signals.ingestors.fedregister.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_returns_signals(mock_get, mock_sleep):
    """Two documents in response → two Signals with correct fields."""
    mock_get.return_value = _make_response(
        {"results": _SAMPLE_DOCS, "next_page_url": None}
    )

    signals = fedregister.ingest(
        agencies=["Centers for Medicare & Medicaid Services"],
        doc_types=["RULE", "PROPOSED_RULE"],
        lookback_days=90,
    )

    assert len(signals) == 2
    for s in signals:
        assert isinstance(s, Signal)
        assert s.source == "fedregister"
        assert s.url.startswith("https://www.federalregister.gov/")
        assert s.published  # non-empty


def test_ingest_agency_slug_conversion():
    """Agency names are correctly converted to FR API slug format."""
    assert _agency_to_slug("Centers for Medicare & Medicaid Services") == (
        "centers-for-medicare-medicaid-services"
    )
    assert _agency_to_slug("Environmental Protection Agency") == (
        "environmental-protection-agency"
    )
    assert _agency_to_slug("Department of Health and Human Services") == (
        "department-of-health-and-human-services"
    )


@patch("govspend_signals.ingestors.fedregister.time.sleep", return_value=None)
@patch("requests.Session.get")
def test_ingest_handles_http_error(mock_get, mock_sleep):
    """HTTP error → empty list, no exception."""
    mock_get.return_value = _make_response({}, status_code=503)

    signals = fedregister.ingest(
        agencies=["EPA"],
        doc_types=["RULE"],
        lookback_days=30,
    )

    assert signals == []
