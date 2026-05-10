"""Tests for the Senate LDA lobbying spike detector."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.ingestors import lobbying
from govspend_signals.signal import Signal


def _make_filing(
    uuid="FILING-001",
    received=None,
    income=500_000,
    expenses=None,
    client_name="Centene Corporation",
    registrant_name="Smith Lobbying LLC",
    period="2025Q1",
    activities=None,
):
    if received is None:
        received = (date.today() - timedelta(days=5)).isoformat()
    if activities is None:
        activities = [{"general_issue_code": "HCR", "bills": []}]
    return {
        "filing_uuid": uuid,
        "dt_posted": received,
        "income": income,
        "expenses": expenses,
        "client": {"name": client_name},
        "registrant": {"name": registrant_name},
        "period_of_report": period,
        "lobbying_activities": activities,
    }


def _make_paginated_resp(filings: list, next_url: str | None = None) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"results": filings, "next": next_url}
    return mock


class TestLobbyingIngest:
    def test_returns_list(self):
        with patch("requests.Session.get", return_value=_make_paginated_resp([])):
            result = lobbying.ingest(lookback_days=90)
        assert isinstance(result, list)

    def test_happy_path_signal(self):
        filing = _make_filing()
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90)
        assert len(result) == 1
        sig = result[0]
        assert isinstance(sig, Signal)
        assert sig.source == "lobbying"
        assert sig.signal_type == "lobbying_report"

    def test_amount_from_income(self):
        filing = _make_filing(income=750_000)
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, min_amount=50_000)
        assert result[0].amount_usd == 750_000.0

    def test_amount_from_expenses_when_income_null(self):
        filing = _make_filing(income=None, expenses=300_000)
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, min_amount=50_000)
        assert result[0].amount_usd == 300_000.0

    def test_below_min_amount_filtered(self):
        filing = _make_filing(income=10_000)
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, min_amount=50_000)
        assert result == []

    def test_old_filing_triggers_stop(self):
        """Filings older than cutoff should stop pagination (early exit)."""
        old_date = (date.today() - timedelta(days=200)).isoformat()
        filing = _make_filing(received=old_date)
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90)
        assert result == []

    def test_irrelevant_issue_code_filtered(self):
        """Filing with no matching issue code AND no keyword in description."""
        filing = _make_filing(
            activities=[{"general_issue_code": "AGR", "bills": []}],  # Agriculture
        )
        filing["description"] = "assistance for farmers"
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, min_amount=50_000)
        assert result == []

    def test_description_fallback_keyword_match(self):
        """If activities is empty, check description keywords."""
        filing = _make_filing(activities=[])
        filing["description"] = "Issues related to health and medicare reimbursements"
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, min_amount=50_000)
        assert len(result) == 1

    def test_deduplicates_by_uuid(self):
        filing = _make_filing(uuid="DUP-001")
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing, filing])):
            result = lobbying.ingest(lookback_days=90)
        assert len(result) == 1

    def test_title_contains_lobbying_prefix(self):
        filing = _make_filing()
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90)
        assert result[0].title.startswith("[LOBBYING]")

    def test_resolver_called_for_client(self):
        from unittest.mock import MagicMock
        from govspend_signals.resolver import Resolver
        filing = _make_filing(client_name="Centene Corporation")
        mock_resolver = MagicMock(spec=Resolver)
        mock_resolver.resolve.return_value = "CNC"
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, resolver=mock_resolver)
        assert result[0].ticker == "CNC"
        mock_resolver.resolve.assert_called_once_with("Centene Corporation")

    def test_ticker_in_title_when_resolved(self):
        from govspend_signals.resolver import Resolver
        filing = _make_filing(client_name="Centene Corporation")
        mock_resolver = MagicMock(spec=Resolver)
        mock_resolver.resolve.return_value = "CNC"
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90, resolver=mock_resolver)
        assert "[CNC]" in result[0].title

    def test_http_error_breaks_loop(self):
        import requests
        with patch("requests.Session.get", side_effect=requests.HTTPError("500")):
            result = lobbying.ingest(lookback_days=90)
        assert result == []

    def test_request_error_breaks_loop(self):
        import requests
        with patch("requests.Session.get", side_effect=requests.RequestException("timeout")):
            result = lobbying.ingest(lookback_days=90)
        assert result == []

    def test_max_pages_respected(self):
        """Should not fetch more than max_pages (5) pages."""
        filing = _make_filing()
        # Return a next_url forever — internal max_pages should stop us
        resp = _make_paginated_resp([filing], next_url="https://lda.senate.gov/api/v1/filings/?page=2")
        with patch("requests.Session.get", return_value=resp) as mock_get:
            lobbying.ingest(lookback_days=90)
            # Internal max_pages=5 hard-coded in ingestor
            assert mock_get.call_count <= 5

    def test_data_has_filing_uuid(self):
        filing = _make_filing(uuid="UUID-XYZ")
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90)
        assert result[0].data["filing_uuid"] == "UUID-XYZ"

    def test_data_has_issue_codes(self):
        filing = _make_filing(activities=[{"general_issue_code": "HCR", "bills": []}])
        with patch("requests.Session.get", return_value=_make_paginated_resp([filing])):
            result = lobbying.ingest(lookback_days=90)
        assert "HCR" in result[0].data["issue_codes"]
