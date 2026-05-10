"""Tests for govspend_signals.signal — Signal dataclass."""
from __future__ import annotations

import json
import hashlib

import pytest

from govspend_signals.signal import Signal
from govspend_signals.edgar import Filing


# ── helpers ───────────────────────────────────────────────────────────────────

def make_signal(**kwargs) -> Signal:
    defaults = dict(
        source="sbir",
        signal_type="grant_award",
        title="Test grant",
        url="https://example.com/grant/1",
        published="2024-01-15",
    )
    defaults.update(kwargs)
    return Signal(**defaults)


def make_filing(**kwargs) -> Filing:
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


# ── tests ─────────────────────────────────────────────────────────────────────

class TestSignalId:
    def test_signal_id_stable(self):
        s1 = make_signal()
        s2 = make_signal()
        assert s1.id == s2.id

    def test_signal_id_is_sha256_prefix(self):
        s = make_signal(source="sbir", url="https://example.com/grant/1")
        expected = hashlib.sha256(b"sbir:https://example.com/grant/1").hexdigest()[:32]
        assert s.id == expected

    def test_signal_id_differs_by_source(self):
        s1 = make_signal(source="sbir")
        s2 = make_signal(source="edgar")
        assert s1.id != s2.id

    def test_signal_id_differs_by_url(self):
        s1 = make_signal(url="https://example.com/grant/1")
        s2 = make_signal(url="https://example.com/grant/2")
        assert s1.id != s2.id


class TestSignalToDict:
    EXPECTED_KEYS = {
        "id", "source", "signal_type", "title", "url",
        "published", "ticker", "company", "amount_usd", "data",
    }

    def test_signal_to_dict_all_keys_present(self):
        s = make_signal()
        d = s.to_dict()
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_signal_to_dict_no_extra_keys(self):
        s = make_signal()
        d = s.to_dict()
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_signal_to_dict_id_matches_property(self):
        s = make_signal()
        assert s.to_dict()["id"] == s.id

    def test_signal_to_dict_values(self):
        s = make_signal(
            source="sbir",
            signal_type="grant_award",
            title="Test grant",
            url="https://example.com/grant/1",
            published="2024-01-15",
        )
        d = s.to_dict()
        assert d["source"] == "sbir"
        assert d["signal_type"] == "grant_award"
        assert d["title"] == "Test grant"
        assert d["url"] == "https://example.com/grant/1"
        assert d["published"] == "2024-01-15"
        assert d["ticker"] is None
        assert d["company"] is None
        assert d["amount_usd"] is None
        assert d["data"] == {}


class TestSignalToJson:
    def test_signal_to_json_roundtrip(self):
        s = make_signal()
        parsed = json.loads(s.to_json())
        assert parsed == s.to_dict()

    def test_signal_to_json_is_string(self):
        s = make_signal()
        assert isinstance(s.to_json(), str)

    def test_signal_to_json_with_data(self):
        s = make_signal(data={"foo": "bar", "n": 42})
        parsed = json.loads(s.to_json())
        assert parsed["data"] == {"foo": "bar", "n": 42}

    def test_signal_to_json_with_amount(self):
        s = make_signal(amount_usd=1_500_000.0)
        parsed = json.loads(s.to_json())
        assert parsed["amount_usd"] == 1_500_000.0


class TestSignalFromFiling:
    def test_from_filing_source_is_edgar(self):
        filing = make_filing()
        s = Signal.from_filing(filing)
        assert s.source == "edgar"

    def test_from_filing_ticker_matches(self):
        filing = make_filing(ticker="UNH")
        s = Signal.from_filing(filing)
        assert s.ticker == "UNH"

    def test_from_filing_url_matches(self):
        filing = make_filing()
        s = Signal.from_filing(filing)
        assert s.url == filing.url

    def test_from_filing_published_matches_filing_date(self):
        filing = make_filing(filing_date="2024-01-15")
        s = Signal.from_filing(filing)
        assert s.published == "2024-01-15"

    def test_from_filing_signal_type_from_form(self):
        filing = make_filing(form="SC 13D")
        s = Signal.from_filing(filing)
        assert s.signal_type == "sc_13d"

    def test_from_filing_8k_signal_type(self):
        filing = make_filing(form="8-K")
        s = Signal.from_filing(filing)
        assert s.signal_type == "8-k"

    def test_from_filing_company_in_title(self):
        filing = make_filing(company="UnitedHealth", ticker="UNH", form="8-K")
        s = Signal.from_filing(filing)
        assert "UnitedHealth" in s.title
        assert "UNH" in s.title

    def test_from_filing_data_has_cik(self):
        filing = make_filing(cik=72971)
        s = Signal.from_filing(filing)
        assert s.data["cik"] == 72971

    def test_from_filing_data_has_accession(self):
        filing = make_filing(accession="0000072971-24-000001")
        s = Signal.from_filing(filing)
        assert s.data["accession"] == "0000072971-24-000001"

    def test_from_filing_works_with_mock_object(self):
        """Confirm from_filing uses getattr and works with any duck-typed object."""
        class MockFiling:
            form = "4"
            ticker = "MSFT"
            company = "Microsoft"
            filing_date = "2024-03-01"
            cik = 789019
            accession = "0000789019-24-000001"
            primary_doc = "doc.htm"
            primary_doc_description = "Form 4"
            url = "https://www.sec.gov/Archives/edgar/data/789019/000078901924000001/doc.htm"
            index_url = "https://www.sec.gov/Archives/edgar/data/789019/000078901924000001/0000789019-24-000001-index.htm"

        s = Signal.from_filing(MockFiling())
        assert s.source == "edgar"
        assert s.ticker == "MSFT"
        assert s.company == "Microsoft"
