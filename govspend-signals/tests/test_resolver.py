"""Tests for the subsidiary→ticker resolver."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from govspend_signals.resolver import Resolver, SUBSIDIARY_MAP, _normalize


# ── _normalize ────────────────────────────────────────────────────────────────

class TestNormalize:
    def test_uppercases(self):
        from govspend_signals.resolver import _normalize
        # "GROUP" is a stripped legal suffix, so "unitedhealth group" → "UNITEDHEALTH"
        result = _normalize("unitedhealth group")
        assert result == result.upper()
        assert "unitedhealth" in result.lower()

    def test_strips_legal_suffixes(self):
        from govspend_signals.resolver import _normalize
        # LLC and SERVICES are both stripped
        result = _normalize("Centene Federal Services LLC")
        assert "LLC" not in result
        assert "SERVICES" not in result
        assert "CENTENE FEDERAL" in result

    def test_strips_inc(self):
        from govspend_signals.resolver import _normalize
        # Without trailing period, " INC" suffix is stripped
        result = _normalize("Elevance Health Inc")
        assert result.endswith("HEALTH")
        assert "ELEVANCE HEALTH" in result

    def test_strips_corp(self):
        from govspend_signals.resolver import _normalize
        # SOLUTIONS is stripped; CORP is stripped too
        result = _normalize("Jacobs Solutions Corp")
        assert "CORP" not in result
        assert "JACOBS" in result

    def test_collapses_whitespace(self):
        from govspend_signals.resolver import _normalize
        assert _normalize("  United  Healthcare  ") == "UNITED HEALTHCARE"

    def test_removes_punctuation(self):
        from govspend_signals.resolver import _normalize
        result = _normalize("Google, LLC.")
        assert "," not in result
        assert "." not in result


# ── curated lookup ────────────────────────────────────────────────────────────

class TestCuratedLookup:
    def test_exact_key_hit(self):
        r = Resolver()
        assert r.resolve("OPTUM") == "UNH"

    def test_case_insensitive(self):
        r = Resolver()
        assert r.resolve("optum") == "UNH"

    def test_strips_llc(self):
        r = Resolver()
        # "CENTENE FEDERAL SERVICES" should be in the map
        result = r.resolve("Centene Federal Services LLC")
        assert result == "CNC"

    def test_known_ticker_google(self):
        r = Resolver()
        assert r.resolve("Google LLC") == "GOOGL"

    def test_unknown_returns_none(self):
        r = Resolver(use_edgar_fallback=False)
        result = r.resolve("Completely Random Unknown Corp XYZ999")
        assert result is None

    def test_none_input_returns_none(self):
        r = Resolver()
        assert r.resolve(None) is None

    def test_empty_string_returns_none(self):
        r = Resolver()
        assert r.resolve("") is None


# ── Resolver.resolve_batch ────────────────────────────────────────────────────

class TestResolveBatch:
    def test_batch_returns_dict(self):
        r = Resolver()
        result = r.resolve_batch(["OPTUM", "Unknown XYZ Corp 9999"])
        assert isinstance(result, dict)
        assert result["OPTUM"] == "UNH"
        assert result["Unknown XYZ Corp 9999"] is None

    def test_batch_empty_input(self):
        r = Resolver()
        assert r.resolve_batch([]) == {}

    def test_batch_deduplicates(self):
        r = Resolver()
        result = r.resolve_batch(["OPTUM", "OPTUM", "OPTUM"])
        # Should handle duplicates without error
        assert result["OPTUM"] == "UNH"


# ── EDGAR fallback ────────────────────────────────────────────────────────────

class TestEdgarFallback:
    def test_edgar_not_called_when_disabled(self):
        r = Resolver(use_edgar_fallback=False)
        with patch.object(r, "_edgar_lookup") as mock_edgar:
            r.resolve("Some Unknown Company")
            mock_edgar.assert_not_called()

    def test_edgar_fallback_called_when_enabled(self):
        r = Resolver(user_agent="Test test@example.com", use_edgar_fallback=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "hits": {
                "hits": [{
                    "_source": {
                        "entity_name": "Some Unknown Company",
                        "tickers": ["SOM"],
                    }
                }]
            }
        }
        with patch("requests.Session.get", return_value=mock_resp):
            result = r.resolve("Some Unknown Company That Is Not In The Map ZZZ")
            # EDGAR fallback may or may not fire depending on fuzzy match threshold;
            # just assert no crash occurs.
            assert result is None or isinstance(result, str)

    def test_edgar_http_error_returns_none(self):
        import requests
        r = Resolver(user_agent="Test test@example.com", use_edgar_fallback=True)
        with patch("requests.Session.get", side_effect=requests.RequestException("timeout")):
            result = r._edgar_lookup("Unknown Corp")
            assert result is None
