"""Tests for govspend_signals.notifiers.telegram — TelegramNotifier."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.config import TelegramConfig
from govspend_signals.notifiers.telegram import TelegramNotifier, _build_message
from govspend_signals.signal import Signal


def _make_config(enabled: bool = True) -> TelegramConfig:
    return TelegramConfig(
        enabled=enabled,
        bot_token="1234567890:ABCxyz",
        chat_id="-1001234567890",
    )


def _make_signal(**kwargs) -> Signal:
    defaults = dict(
        source="sbir",
        signal_type="grant_award",
        title="DARPA grants $2.5M to QuantumCo",
        url="https://www.sbir.gov/sbc/detail/DARPA-D123",
        published="2026-05-09",
        ticker="QNTM",
        amount_usd=2_500_000.0,
    )
    defaults.update(kwargs)
    return Signal(**defaults)


class TestBuildMessage:
    def test_includes_signal_type(self):
        s = _make_signal()
        msg = _build_message(s)
        assert "GRANT_AWARD" in msg

    def test_includes_published_date(self):
        s = _make_signal()
        msg = _build_message(s)
        assert "2026-05-09" in msg

    def test_includes_title(self):
        s = _make_signal()
        msg = _build_message(s)
        assert "DARPA grants $2.5M to QuantumCo" in msg

    def test_includes_url(self):
        s = _make_signal()
        msg = _build_message(s)
        assert "https://www.sbir.gov/" in msg

    def test_includes_amount_when_present(self):
        s = _make_signal(amount_usd=2_500_000.0)
        msg = _build_message(s)
        assert "2,500,000" in msg

    def test_includes_ticker_with_dollar_prefix(self):
        s = _make_signal(ticker="QNTM")
        msg = _build_message(s)
        assert "$QNTM" in msg

    def test_omits_amount_when_none(self):
        s = _make_signal(amount_usd=None)
        msg = _build_message(s)
        # Should still build a message without an amount line
        assert "GRANT_AWARD" in msg

    def test_omits_ticker_when_none(self):
        s = _make_signal(ticker=None, title="No ticker here")
        msg = _build_message(s)
        # With no ticker the second line should not start with $SYMBOL
        title_line = msg.split("\n")[1]
        assert not title_line.startswith("$")


class TestTelegramNotifierEmit:
    def test_emit_calls_telegram_api(self):
        config = _make_config()
        notifier = TelegramNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        url = call_kwargs[0][0]
        assert "sendMessage" in url
        assert config.bot_token in url

    def test_emit_sends_correct_chat_id(self):
        config = _make_config()
        notifier = TelegramNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        json_payload = mock_post.call_args[1]["json"]
        assert json_payload["chat_id"] == config.chat_id

    def test_emit_does_not_raise_on_network_error(self, capsys):
        """Network errors are caught and logged to stderr."""
        config = _make_config()
        notifier = TelegramNotifier(config)

        with patch.object(
            notifier._session,
            "post",
            side_effect=requests.ConnectionError("unreachable"),
        ):
            notifier.emit(_make_signal())  # should not raise

        captured = capsys.readouterr()
        assert "telegram" in captured.err.lower() or "error" in captured.err.lower()

    def test_emit_does_not_raise_on_http_error(self, capsys):
        config = _make_config()
        notifier = TelegramNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")

        with patch.object(notifier._session, "post", return_value=mock_resp):
            notifier.emit(_make_signal())  # should not raise


class TestTelegramNotifierEmitDigest:
    def test_emit_digest_sends_text(self):
        config = _make_config()
        notifier = TelegramNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit_digest("Hello from digest")

        mock_post.assert_called_once()

    def test_emit_digest_empty_string_does_nothing(self):
        config = _make_config()
        notifier = TelegramNotifier(config)

        with patch.object(notifier._session, "post") as mock_post:
            notifier.emit_digest("")

        mock_post.assert_not_called()

    def test_emit_digest_long_message_is_chunked(self):
        """Messages over 4096 chars should be split into multiple posts."""
        config = _make_config()
        notifier = TelegramNotifier(config)
        long_text = "x" * 9000  # > 4096 * 2
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit_digest(long_text)

        assert mock_post.call_count >= 3  # ceil(9000 / 4096) = 3
