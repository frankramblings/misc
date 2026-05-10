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
