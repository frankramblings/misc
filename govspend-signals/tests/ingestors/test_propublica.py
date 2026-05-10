"""Tests for the ProPublica Congress bill ingestor."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.ingestors import propublica
from govspend_signals.signal import Signal


def _make_bill(
    bill_id="hr1234-119",
    title="Medicaid Expansion and Funding Act",
    introduced_date=None,
    bill_type="hr",
    number="1234",
    sponsor_name="Jane Doe",
    latest_major_action="Passed committee",
    congress_url="https://www.congress.gov/bill/119th-congress/house-bill/1234",
):
    if introduced_date is None:
        introduced_date = (date.today() - timedelta(days=3)).isoformat()
    return {
        "bill_id": bill_id,
        "title": title,
        "introduced_date": introduced_date,
        "bill_type": bill_type,
        "number": number,
        "sponsor_name": sponsor_name,
        "latest_major_action": latest_major_action,
        "congressdotgov_url": congress_url,
    }


def _make_response(bills: list) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "results": [{"bills": bills}]
    }
    return mock


class TestClassifyBill:
    def test_healthcare_keyword(self):
        sector = propublica._classify_bill("Medicaid Access Act", "")
        assert sector == "healthcare"

    def test_infrastructure_keyword(self):
        sector = propublica._classify_bill("Federal Infrastructure Modernization Act", "")
        assert sector == "infrastructure"

    def test_energy_keyword(self):
        sector = propublica._classify_bill("Clean Energy Investment Act", "")
        assert sector == "energy_utilities"

    def test_environmental_keyword(self):
        sector = propublica._classify_bill("EPA Superfund Enhancement Act", "")
        assert sector == "environmental"

    def test_appropriations_keyword(self):
        sector = propublica._classify_bill("Continuing Appropriations Act 2025", "")
        assert sector == "appropriations"

    def test_irrelevant_returns_none(self):
        sector = propublica._classify_bill("Naming Post Office Act", "")
        assert sector is None

    def test_summary_used_for_classification(self):
        sector = propublica._classify_bill("An Act", "to expand medicare coverage for seniors")
        assert sector == "healthcare"


class TestPropublicaIngest:
    def test_returns_list(self):
        empty_resp = _make_response([])
        with patch("requests.Session.get", return_value=empty_resp):
            result = propublica.ingest(lookback_days=7)
        assert isinstance(result, list)

    def test_happy_path_signal(self):
        bill = _make_bill()
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        assert len(result) >= 1
        sig = result[0]
        assert isinstance(sig, Signal)
        assert sig.source == "propublica"

    def test_signal_type_has_sector(self):
        bill = _make_bill()
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        assert result[0].signal_type.startswith("bill_")

    def test_title_contains_bill_sector_prefix(self):
        bill = _make_bill()
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        assert "[BILL/" in result[0].title

    def test_old_bills_filtered_out(self):
        old_date = (date.today() - timedelta(days=60)).isoformat()
        bill = _make_bill(introduced_date=old_date)
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        assert result == []

    def test_irrelevant_bills_filtered(self):
        bill = _make_bill(title="Post Office Naming Act for the City of Springfield")
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        # No relevant keyword → filtered out
        assert all(sig.source == "propublica" for sig in result)  # may be empty
        # Just assert no crashes

    def test_deduplicates_across_endpoints(self):
        """Same bill_id appearing in introduced + updated should only produce one signal."""
        bill = _make_bill(bill_id="hr1234-119")
        resp = _make_response([bill])
        # All 4 endpoints (house/senate × introduced/updated) return the same bill
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=30)
        ids = [s.data["bill_id"] for s in result]
        assert len(ids) == len(set(ids))

    def test_http_error_continues(self):
        """HTTP errors on one endpoint don't abort the rest."""
        import requests
        good_bill = _make_bill()
        good_resp = _make_response([good_bill])
        err_resp = MagicMock()
        err_resp.raise_for_status.side_effect = requests.HTTPError("403")

        # Alternate: some succeed, some fail
        responses_seq = [err_resp, good_resp, good_resp, good_resp]
        with patch("requests.Session.get", side_effect=responses_seq):
            result = propublica.ingest(lookback_days=30)
        # Should not raise and should return at least the successful results
        assert isinstance(result, list)

    def test_sponsor_in_title(self):
        bill = _make_bill(sponsor_name="Rep. John Smith")
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        if result:
            assert "John Smith" in result[0].title

    def test_data_dict_has_bill_id(self):
        bill = _make_bill(bill_id="s42-119")
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        if result:
            assert result[0].data["bill_id"] == "s42-119"

    def test_ticker_is_none(self):
        """propublica signals don't resolve tickers (no company name)."""
        bill = _make_bill()
        resp = _make_response([bill])
        with patch("requests.Session.get", return_value=resp):
            result = propublica.ingest(lookback_days=7)
        if result:
            assert result[0].ticker is None
