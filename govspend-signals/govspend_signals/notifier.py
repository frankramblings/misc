from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from .edgar import Filing


class Notifier(Protocol):
    def emit(self, filing: Filing) -> None: ...


class StdoutNotifier:
    def emit(self, filing: Filing) -> None:
        line = (
            f"[{filing.filing_date}] {filing.form:<10} "
            f"{filing.ticker:<6} {filing.company} -- {filing.url}"
        )
        print(line, flush=True)


class JsonlNotifier:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def emit(self, filing: Filing) -> None:
        record = asdict(filing)
        record["url"] = filing.url
        record["index_url"] = filing.index_url
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


class FanoutNotifier:
    def __init__(self, *children: Notifier):
        self._children = children

    def emit(self, filing: Filing) -> None:
        for child in self._children:
            try:
                child.emit(filing)
            except Exception as exc:  # noqa: BLE001
                print(f"notifier error: {exc}", file=sys.stderr, flush=True)


# ── Signal-aware notifiers ────────────────────────────────────────────────────

from .signal import Signal  # noqa: E402 (after Filing import to avoid circular)


class SignalNotifier(Protocol):
    def emit(self, signal: Signal) -> None: ...


class SignalStdoutNotifier:
    """Prints Signal objects in a human-readable format."""

    def emit(self, signal: Signal) -> None:
        amount_str = f" ${signal.amount_usd:,.0f}" if signal.amount_usd else ""
        ticker_str = f" [{signal.ticker}]" if signal.ticker else ""
        line = (
            f"[{signal.published}] [{signal.source.upper():<12}] "
            f"{signal.signal_type:<15}{ticker_str}{amount_str}\n  {signal.title}\n  {signal.url}"
        )
        print(line, flush=True)


class SignalJsonlNotifier:
    """Writes Signal objects as JSONL."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def emit(self, signal: Signal) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(signal.to_json() + "\n")


class SignalFanoutNotifier:
    """Fans out to multiple SignalNotifiers."""

    def __init__(self, *children: SignalNotifier) -> None:
        self._children = children

    def emit(self, signal: Signal) -> None:
        for child in self._children:
            try:
                child.emit(signal)
            except Exception as exc:  # noqa: BLE001
                print(f"notifier error: {exc}", file=sys.stderr, flush=True)
