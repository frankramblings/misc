"""Telegram Bot API notifier — no external library, uses raw requests."""
from __future__ import annotations

import sys

import requests

from ..config import TelegramConfig
from ..signal import Signal

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_MESSAGE_LEN = 4096


def _build_message(signal: Signal) -> str:
    ticker_prefix = f"${signal.ticker} " if signal.ticker else ""
    lines = [
        f"*{signal.signal_type.upper()}* — {signal.published}",
        f"{ticker_prefix}{signal.title}",
        signal.url,
    ]
    if signal.amount_usd is not None:
        lines.append(f"\U0001f4b0 ${signal.amount_usd:,.0f}")
    return "\n".join(lines)


class TelegramNotifier:
    """Sends each signal as a Telegram message via Bot API."""

    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._session = requests.Session()

    def _post(self, text: str) -> None:
        url = _API_BASE.format(token=self._config.bot_token)
        payload = {
            "chat_id": self._config.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            resp = self._session.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] error: {exc}", file=sys.stderr, flush=True)

    def emit(self, signal: Signal) -> None:
        """Send signal as Telegram message. Silently logs errors."""
        self._post(_build_message(signal))

    def emit_digest(self, text: str) -> None:
        """Send a freeform text message (used by morning digest).

        Splits into chunks if the text exceeds Telegram's 4096-char limit.
        """
        if not text:
            return
        # Split on chunk boundaries, respecting the max length
        start = 0
        while start < len(text):
            chunk = text[start : start + _MAX_MESSAGE_LEN]
            self._post(chunk)
            start += _MAX_MESSAGE_LEN
