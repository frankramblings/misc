"""Tests for the grants.gov NOFO ingestor."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from govspend_signals.ingestors import grants_gov
from govspend_signals.signal import Signal


def _make_opp(
    opp_id="GRANT001",
    title="Medicaid IT Modernization Initiative",
    agency="Department of Health and Human Services",
    open_date="2025-04-01",
    close_date="2025-06-01",
    award_ceiling=5_000_000,
    cfda="93.778",
    status="posted",
):
    return {
        "id": opp_id,
        "oppTitle": title,
        "agencyName": agency,
        "openDate": open_date,
        "closeDate": close_date,
        "awardCeiling": award_ceiling,
        "cfdaNumbers": cfda,
        "oppStatus": status,
    }


def _mock_resp(opps: list) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"oppHits": opps}
    return mock


class TestGrantsGovIngest:
    def test_returns_list(self):
        with patch("requests.Session.post", return_value=_mock_resp([])):
            result = grants_gov.ingest(lookback_days=7)
        assert isinstance(result, list)

    def test_happy_path_signal(self):
        opp = _make_opp()
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert len(result) == 1
        sig = result[0]
        assert isinstance(sig, Signal)
        assert sig.source == "grants_gov"
        assert "healthcare" in sig.signal_type

    def test_title_contains_nofo(self):
        opp = _make_opp()
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert "[NOFO/" in result[0].title

    def test_amount_usd_parsed(self):
        opp = _make_opp(award_ceiling=5_000_000)
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert result[0].amount_usd == 5_000_000.0

    def test_irrelevant_opportunity_filtered(self):
        opp = _make_opp(
            title="Arts Endowment Community Grant",
            agency="National Endowment for the Arts",
            cfda="45.024",
        )
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert result == []

    def test_deduplicates_by_id(self):
        opp = _make_opp()
        with patch("requests.Session.post", return_value=_mock_resp([opp, opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert len(result) == 1

    def test_http_error_returns_empty(self):
        import requests
        with patch("requests.Session.post", side_effect=requests.HTTPError("500")):
            result = grants_gov.ingest(lookback_days=7)
        assert result == []

    def test_request_error_returns_empty(self):
        import requests
        with patch("requests.Session.post", side_effect=requests.RequestException("timeout")):
            result = grants_gov.ingest(lookback_days=7)
        assert result == []

    def test_json_parse_error_returns_empty(self):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.side_effect = ValueError("not json")
        with patch("requests.Session.post", return_value=mock):
            result = grants_gov.ingest(lookback_days=7)
        assert result == []

    def test_energy_sector_detected(self):
        opp = _make_opp(
            title="DOE Renewable Energy Grid Modernization",
            agency="Department of Energy",
            cfda="81.041",
        )
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert len(result) == 1
        assert "energy" in result[0].signal_type or "energy" in result[0].title.lower()

    def test_data_dict_has_opportunity_id(self):
        opp = _make_opp(opp_id="TESTID123")
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert result[0].data["opportunity_id"] == "TESTID123"

    def test_close_date_in_title(self):
        opp = _make_opp(close_date="2025-07-15")
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert "2025-07-15" in result[0].title

    def test_no_amount_ceiling_allowed(self):
        opp = _make_opp(award_ceiling=None)
        opp["awardCeiling"] = None
        with patch("requests.Session.post", return_value=_mock_resp([opp])):
            result = grants_gov.ingest(lookback_days=30)
        assert len(result) == 1
        assert result[0].amount_usd is None

    def test_alternative_data_key_oppHits(self):
        """Handles alternate response key structure."""
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"data": {"oppHits": [_make_opp()]}}
        with patch("requests.Session.post", return_value=mock):
            result = grants_gov.ingest(lookback_days=30)
        assert len(result) == 1
