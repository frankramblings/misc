"""Tests for govspend_signals.notifiers.smtp — SmtpNotifier."""
from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch, call

import pytest

from govspend_signals.config import SmtpConfig
from govspend_signals.notifiers.smtp import SmtpNotifier, _build_subject, _build_body
from govspend_signals.signal import Signal


def _make_config(port: int = 587) -> SmtpConfig:
    return SmtpConfig(
        enabled=True,
        host="smtp.gmail.com",
        port=port,
        username="govspend@example.com",
        password="app_password",
        to="frank@example.com",
        from_addr="govspend@example.com",
    )


def _make_signal(**kwargs) -> Signal:
    defaults = dict(
        source="usaspending",
        signal_type="contract_award",
        title="$5M contract — Acme Health (HHS)",
        url="https://www.usaspending.gov/award/CONT_AWD_ABC123/",
        published="2026-05-09",
        ticker="UNH",
        company="Acme Health Corp",
        amount_usd=5_000_000.0,
    )
    defaults.update(kwargs)
    return Signal(**defaults)


class TestBuildSubject:
    def test_subject_includes_signal_type(self):
        s = _make_signal()
        subj = _build_subject(s)
        assert "CONTRACT_AWARD" in subj

    def test_subject_includes_govspend_prefix(self):
        s = _make_signal()
        assert "[govspend]" in _build_subject(s)

    def test_subject_max_length_80_chars_for_title(self):
        long_title = "X" * 200
        s = _make_signal(title=long_title)
        subj = _build_subject(s)
        # Title portion is capped at 80 chars
        assert len(subj) < 200


class TestBuildBody:
    def test_body_includes_all_fields(self):
        s = _make_signal()
        body = _build_body(s)
        assert "usaspending" in body
        assert "contract_award" in body
        assert "Acme Health Corp" in body
        assert "UNH" in body
        assert "5,000,000" in body
        assert s.url in body

    def test_body_na_when_amount_none(self):
        s = _make_signal(amount_usd=None)
        body = _build_body(s)
        assert "N/A" in body

    def test_body_na_when_ticker_none(self):
        s = _make_signal(ticker=None)
        body = _build_body(s)
        assert "N/A" in body


class TestSmtpNotifierEmitStarttls:
    """Tests for STARTTLS path (port 587)."""

    def test_emit_calls_smtp_starttls(self):
        config = _make_config(port=587)
        notifier = SmtpNotifier(config)
        s = _make_signal()

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp) as mock_cls:
            mock_cls.return_value.__enter__ = lambda _: mock_smtp
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            notifier.emit(s)

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with(config.username, config.password)
        mock_smtp.sendmail.assert_called_once()

    def test_emit_does_not_raise_on_smtp_error(self, capsys):
        config = _make_config(port=587)
        notifier = SmtpNotifier(config)

        with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("connection refused")):
            notifier.emit(_make_signal())  # should not raise

        captured = capsys.readouterr()
        assert "smtp" in captured.err.lower() or "error" in captured.err.lower()


class TestSmtpNotifierEmitSsl:
    """Tests for SMTP_SSL path (port 465)."""

    def test_emit_calls_smtp_ssl(self):
        config = _make_config(port=465)
        notifier = SmtpNotifier(config)
        s = _make_signal()

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP_SSL", return_value=mock_smtp) as mock_cls:
            mock_cls.return_value.__enter__ = lambda _: mock_smtp
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            notifier.emit(s)

        mock_smtp.login.assert_called_once_with(config.username, config.password)
        mock_smtp.sendmail.assert_called_once()


class TestSmtpNotifierEmitDigest:
    def test_emit_digest_sends_email(self):
        config = _make_config(port=587)
        notifier = SmtpNotifier(config)

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp) as mock_cls:
            mock_cls.return_value.__enter__ = lambda _: mock_smtp
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            notifier.emit_digest(
                subject="govspend digest — 2026-05-09 (42 signals)",
                body="Signal summary here.",
            )

        mock_smtp.sendmail.assert_called_once()
        args = mock_smtp.sendmail.call_args[0]
        assert config.from_addr in args[0]
        assert config.to in args[1]
