"""Tests for govspend_signals.notifiers.webhook — WebhookNotifier."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from govspend_signals.config import WebhookConfig
from govspend_signals.notifiers.webhook import WebhookNotifier
from govspend_signals.signal import Signal


def _make_config(url: str = "https://hooks.example.com/govspend", secret: str = "") -> WebhookConfig:
    return WebhookConfig(enabled=True, url=url, secret=secret)


def _make_signal(**kwargs) -> Signal:
    defaults = dict(
        source="usaspending",
        signal_type="contract_award",
        title="$5M contract — Acme Health (HHS)",
        url="https://www.usaspending.gov/award/CONT_AWD_ABC123/",
        published="2026-05-09",
        company="Acme Health Corp",
        amount_usd=5_000_000.0,
    )
    defaults.update(kwargs)
    return Signal(**defaults)


class TestWebhookNotifierEmit:
    def test_emit_posts_to_url(self):
        config = _make_config()
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == config.url

    def test_emit_posts_signal_dict_as_json(self):
        config = _make_config()
        notifier = WebhookNotifier(config)
        s = _make_signal()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(s)

        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["source"] == "usaspending"
        assert posted_json["signal_type"] == "contract_award"
        assert posted_json["amount_usd"] == 5_000_000.0

    def test_emit_includes_content_type_header(self):
        config = _make_config()
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        headers = mock_post.call_args[1]["headers"]
        assert headers.get("Content-Type") == "application/json"

    def test_emit_includes_secret_header_when_set(self):
        config = _make_config(secret="supersecret")
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        headers = mock_post.call_args[1]["headers"]
        assert headers.get("X-Govspend-Secret") == "supersecret"

    def test_emit_omits_secret_header_when_empty(self):
        config = _make_config(secret="")
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(_make_signal())

        headers = mock_post.call_args[1]["headers"]
        assert "X-Govspend-Secret" not in headers

    def test_emit_does_not_raise_on_network_error(self, capsys):
        """Network errors are silently logged, not propagated."""
        config = _make_config()
        notifier = WebhookNotifier(config)

        with patch.object(
            notifier._session,
            "post",
            side_effect=requests.ConnectionError("timeout"),
        ):
            notifier.emit(_make_signal())  # should not raise

        captured = capsys.readouterr()
        assert "webhook" in captured.err.lower() or "error" in captured.err.lower()

    def test_emit_does_not_raise_on_http_error(self, capsys):
        config = _make_config()
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch.object(notifier._session, "post", return_value=mock_resp):
            notifier.emit(_make_signal())  # should not raise

    def test_emit_signal_id_included_in_payload(self):
        config = _make_config()
        notifier = WebhookNotifier(config)
        s = _make_signal()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch.object(notifier._session, "post", return_value=mock_resp) as mock_post:
            notifier.emit(s)

        posted_json = mock_post.call_args[1]["json"]
        assert "id" in posted_json
        assert posted_json["id"] == s.id
