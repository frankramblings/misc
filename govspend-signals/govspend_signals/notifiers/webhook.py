"""HTTP POST webhook notifier."""
from __future__ import annotations

import sys

import requests

from ..config import WebhookConfig
from ..signal import Signal


class WebhookNotifier:
    """POSTs signal JSON to a configurable webhook URL."""

    def __init__(self, config: WebhookConfig) -> None:
        self._config = config
        self._session = requests.Session()

    def emit(self, signal: Signal) -> None:
        headers = {"Content-Type": "application/json"}
        if self._config.secret:
            headers["X-Govspend-Secret"] = self._config.secret

        try:
            resp = self._session.post(
                self._config.url,
                json=signal.to_dict(),
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"[webhook] error: {exc}", file=sys.stderr, flush=True)
