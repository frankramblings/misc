"""Tests for govspend_signals.config — load() and Config dataclass."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from govspend_signals.config import load, Config


# ── helpers ───────────────────────────────────────────────────────────────────

def _config_example_path() -> Path:
    return Path(__file__).parent.parent / "config.example.toml"


# ── valid load tests ──────────────────────────────────────────────────────────

class TestLoadValidConfig:
    def test_load_valid_config(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert isinstance(config, Config)

    def test_load_returns_config_with_watchlist(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        # config.example.toml has 47 tickers across 6 categories
        assert len(config.watchlist) >= 40

    def test_load_config_path_stored(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.config_path == tmp_config_file.resolve()

    def test_load_user_agent_from_env(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Frank frank@example.com")
        config = load(tmp_config_file)
        assert config.user_agent == "Frank frank@example.com"

    def test_load_interval_seconds(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.interval_seconds == 900

    def test_load_scan_limit(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.scan_limit == 100

    def test_load_max_age_days(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.max_age_days == 7

    def test_watchlist_contains_known_tickers(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert "UNH" in config.watchlist
        assert "MSFT" in config.watchlist
        assert "NEE" in config.watchlist


# ── error path tests ──────────────────────────────────────────────────────────

class TestLoadErrors:
    def test_load_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        missing = tmp_path / "does_not_exist.toml"
        with pytest.raises(FileNotFoundError):
            load(missing)

    def test_load_missing_user_agent(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "")
        with pytest.raises(RuntimeError, match="EDGAR_USER_AGENT"):
            load(tmp_config_file)

    def test_load_invalid_user_agent_no_email(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "NoEmail")
        with pytest.raises(RuntimeError, match="EDGAR_USER_AGENT"):
            load(tmp_config_file)

    def test_load_user_agent_whitespace_only(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "   ")
        with pytest.raises(RuntimeError, match="EDGAR_USER_AGENT"):
            load(tmp_config_file)


# ── forms_set tests ───────────────────────────────────────────────────────────

class TestFormsSet:
    def test_forms_set_is_set(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert isinstance(config.forms_set, set)

    def test_forms_set_contains_forms(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        # config.example.toml defines: ["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "8-K", "4"]
        assert "SC 13D" in config.forms_set
        assert "8-K" in config.forms_set
        assert "4" in config.forms_set

    def test_forms_set_matches_forms_tuple(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.forms_set == set(config.forms)


# ── ingestor defaults tests ───────────────────────────────────────────────────

class TestIngestorDefaults:
    def _load(self, tmp_config_file, monkeypatch) -> Config:
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        return load(tmp_config_file)

    def test_usaspending_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.usaspending_enabled is True

    def test_fedregister_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.fedregister_enabled is True

    def test_congress_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.congress_enabled is True

    def test_sbir_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.sbir_enabled is True

    def test_norway_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.norway_enabled is True

    def test_catalyst_enabled(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.catalyst_enabled is True

    def test_lookback_days(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.lookback_days == 7

    def test_usaspending_min_award(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert config.usaspending_min_award == 1_000_000.0

    def test_usaspending_agencies_nonempty(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert len(config.usaspending_agencies) > 0

    def test_fedregister_doc_types(self, tmp_config_file, monkeypatch):
        config = self._load(tmp_config_file, monkeypatch)
        assert "RULE" in config.fedregister_doc_types
        assert "NOTICE" in config.fedregister_doc_types


# ── telegram / notifier defaults ─────────────────────────────────────────────

class TestTelegramConfig:
    def test_telegram_config_disabled(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        # Ensure no telegram env vars are set
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        config = load(tmp_config_file)
        assert config.telegram.enabled is False

    def test_webhook_disabled_by_default(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        monkeypatch.delenv("WEBHOOK_URL", raising=False)
        config = load(tmp_config_file)
        assert config.webhook.enabled is False

    def test_smtp_disabled_by_default(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        config = load(tmp_config_file)
        assert config.smtp.enabled is False

    def test_smtp_host_default(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.smtp.host == "smtp.gmail.com"

    def test_smtp_port_default(self, tmp_config_file, monkeypatch):
        monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@example.com")
        config = load(tmp_config_file)
        assert config.smtp.port == 587
