"""Tests for govspend_signals.edgar — EdgarClient, Filing, filter_filings, _RateLimiter."""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from govspend_signals.edgar import (
    EdgarClient,
    Filing,
    _RateLimiter,
    filter_filings,
    SEC_TICKERS_URL,
    SEC_SUBMISSIONS_URL,
)


# ── Filing property tests ─────────────────────────────────────────────────────

class TestFilingProperties:
    def _make_filing(self, **kwargs) -> Filing:
        defaults = dict(
            cik=72971,
            ticker="UNH",
            company="UnitedHealth",
            accession="0000072971-24-000001",
            form="8-K",
            filing_date="2024-01-15",
            primary_doc="d123.htm",
            primary_doc_description="8-K",
        )
        defaults.update(kwargs)
        return Filing(**defaults)

    def test_filing_url(self):
        filing = self._make_filing()
        assert filing.url == (
            "https://www.sec.gov/Archives/edgar/data/"
            "72971/000007297124000001/d123.htm"
        )

    def test_filing_url_strips_dashes_from_accession(self):
        filing = self._make_filing(accession="0000072971-24-000001")
        assert "000007297124000001" in filing.url

    def test_filing_index_url(self):
        filing = self._make_filing()
        assert filing.index_url == (
            "https://www.sec.gov/Archives/edgar/data/"
            "72971/000007297124000001/0000072971-24-000001-index.htm"
        )

    def test_filing_url_uses_accession_when_no_primary_doc(self):
        filing = self._make_filing(primary_doc="")
        # When primary_doc is empty/falsy, falls back to accession-based URL
        assert "0000072971-24-000001-index.htm" in filing.url

    def test_filing_is_frozen(self):
        filing = self._make_filing()
        with pytest.raises((AttributeError, TypeError)):
            filing.ticker = "AAPL"  # type: ignore[misc]


# ── EdgarClient construction tests ───────────────────────────────────────────

class TestEdgarClientConstruction:
    def test_edgar_client_requires_email_in_user_agent(self):
        with pytest.raises(ValueError, match="email"):
            EdgarClient("No Email")

    def test_edgar_client_requires_nonempty_user_agent(self):
        with pytest.raises(ValueError):
            EdgarClient("")

    def test_edgar_client_accepts_valid_user_agent(self):
        client = EdgarClient("Test User test@example.com")
        assert client is not None

    def test_edgar_client_accepts_name_and_email(self):
        client = EdgarClient("John Doe john.doe@corp.com", rate_per_second=1.0)
        assert client is not None


# ── fetch_ticker_map tests ────────────────────────────────────────────────────

TICKER_MAP_JSON = {
    "0": {"cik_str": "72971", "ticker": "UNH", "title": "UNITEDHEALTH GROUP INC"},
    "1": {"cik_str": "789019", "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "2": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."},
}


class TestFetchTickerMap:
    def _make_client(self) -> EdgarClient:
        return EdgarClient("Test User test@example.com", rate_per_second=100.0)

    def test_fetch_ticker_map(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = TICKER_MAP_JSON

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_ticker_map()

        assert "UNH" in result
        assert result["UNH"] == (72971, "UNITEDHEALTH GROUP INC")
        assert "MSFT" in result
        assert result["MSFT"] == (789019, "MICROSOFT CORP")

    def test_fetch_ticker_map_uppercases_tickers(self):
        client = self._make_client()
        json_data = {"0": {"cik_str": "123", "ticker": "msft", "title": "Microsoft"}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = json_data

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_ticker_map()

        assert "MSFT" in result

    def test_fetch_ticker_map_calls_correct_url(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = TICKER_MAP_JSON

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.fetch_ticker_map()

        mock_get.assert_called_once_with(SEC_TICKERS_URL, timeout=client._timeout)


# ── fetch_recent_filings tests ────────────────────────────────────────────────

SUBMISSIONS_JSON = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000072971-24-000001", "0000072971-24-000002"],
            "form": ["8-K", "SC 13D"],
            "filingDate": ["2024-01-15", "2024-01-10"],
            "primaryDocument": ["d123.htm", "d456.htm"],
            "primaryDocDescription": ["8-K", "SC 13D"],
        }
    }
}


class TestFetchRecentFilings:
    def _make_client(self) -> EdgarClient:
        return EdgarClient("Test User test@example.com", rate_per_second=100.0)

    def test_fetch_recent_filings(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SUBMISSIONS_JSON

        with patch.object(client._session, "get", return_value=mock_resp):
            filings = client.fetch_recent_filings(
                cik=72971, ticker="UNH", company="UnitedHealth"
            )

        assert len(filings) == 2
        assert filings[0].accession == "0000072971-24-000001"
        assert filings[0].form == "8-K"
        assert filings[0].filing_date == "2024-01-15"
        assert filings[1].accession == "0000072971-24-000002"
        assert filings[1].form == "SC 13D"

    def test_fetch_recent_filings_sets_ticker_and_company(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SUBMISSIONS_JSON

        with patch.object(client._session, "get", return_value=mock_resp):
            filings = client.fetch_recent_filings(
                cik=72971, ticker="UNH", company="UnitedHealth"
            )

        for f in filings:
            assert f.ticker == "UNH"
            assert f.company == "UnitedHealth"
            assert f.cik == 72971

    def test_fetch_recent_filings_respects_scan_limit(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SUBMISSIONS_JSON

        with patch.object(client._session, "get", return_value=mock_resp):
            filings = client.fetch_recent_filings(
                cik=72971, ticker="UNH", company="UnitedHealth", scan_limit=1
            )

        assert len(filings) == 1

    def test_fetch_recent_filings_empty_response(self):
        client = self._make_client()
        empty_resp = {"filings": {"recent": {}}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = empty_resp

        with patch.object(client._session, "get", return_value=mock_resp):
            filings = client.fetch_recent_filings(
                cik=72971, ticker="UNH", company="UnitedHealth"
            )

        assert filings == []

    def test_fetch_recent_filings_calls_correct_url(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SUBMISSIONS_JSON

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.fetch_recent_filings(cik=72971, ticker="UNH", company="UnitedHealth")

        expected_url = SEC_SUBMISSIONS_URL.format(cik=72971)
        mock_get.assert_called_once_with(expected_url, timeout=client._timeout)


# ── filter_filings tests ──────────────────────────────────────────────────────

def _make_filing(form="8-K", filing_date="2024-01-15", **kwargs) -> Filing:
    defaults = dict(
        cik=72971,
        ticker="UNH",
        company="UnitedHealth",
        accession="0000072971-24-000001",
        primary_doc="d123.htm",
        primary_doc_description="",
    )
    defaults.update(kwargs)
    return Filing(form=form, filing_date=filing_date, **defaults)


class TestFilterFilings:
    def test_filter_filings_by_form(self):
        filings = [
            _make_filing(form="8-K", accession="acc-1"),
            _make_filing(form="SC 13D", accession="acc-2"),
            _make_filing(form="4", accession="acc-3"),
            _make_filing(form="8-K", accession="acc-4"),
        ]
        result = filter_filings(filings, forms={"8-K"})
        assert len(result) == 2
        assert all(f.form == "8-K" for f in result)

    def test_filter_filings_by_min_date(self):
        filings = [
            _make_filing(filing_date="2024-01-20", accession="acc-1"),
            _make_filing(filing_date="2024-01-10", accession="acc-2"),
            _make_filing(filing_date="2024-01-15", accession="acc-3"),
        ]
        result = filter_filings(filings, forms={"8-K"}, min_date="2024-01-15")
        dates = [f.filing_date for f in result]
        assert "2024-01-10" not in dates
        assert "2024-01-15" in dates
        assert "2024-01-20" in dates

    def test_filter_filings_no_min_date(self):
        filings = [
            _make_filing(filing_date="2020-01-01", accession="acc-1"),
            _make_filing(filing_date="2019-06-15", accession="acc-2"),
        ]
        result = filter_filings(filings, forms={"8-K"})
        assert len(result) == 2

    def test_filter_filings_empty_input(self):
        result = filter_filings([], forms={"8-K"})
        assert result == []

    def test_filter_filings_no_match(self):
        filings = [_make_filing(form="SC 13D", accession="acc-1")]
        result = filter_filings(filings, forms={"8-K"})
        assert result == []

    def test_filter_filings_multiple_forms(self):
        filings = [
            _make_filing(form="8-K", accession="acc-1"),
            _make_filing(form="SC 13D", accession="acc-2"),
            _make_filing(form="4", accession="acc-3"),
        ]
        result = filter_filings(filings, forms={"8-K", "SC 13D"})
        assert len(result) == 2


# ── _RateLimiter tests ────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_rate_limiter_enforces_delay(self):
        limiter = _RateLimiter(rate_per_second=2.0)  # 0.5s interval
        start = time.monotonic()
        limiter.wait()
        limiter.wait()
        elapsed = time.monotonic() - start
        # Two calls at 2/sec → at least ~0.5s total
        assert elapsed >= 0.45  # small buffer for timing slop

    def test_rate_limiter_single_call_is_fast(self):
        limiter = _RateLimiter(rate_per_second=10.0)
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        # First call should be near-instant (no prior call to sleep against)
        assert elapsed < 0.5

    def test_rate_limiter_high_rate(self):
        """High rate limit means very short or no sleep."""
        limiter = _RateLimiter(rate_per_second=1000.0)
        start = time.monotonic()
        limiter.wait()
        limiter.wait()
        elapsed = time.monotonic() - start
        # Should complete quickly at 1000 calls/sec
        assert elapsed < 0.1
