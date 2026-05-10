from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    user_agent: str
    db_path: Path
    events_path: Path
    interval_seconds: int
    forms: tuple[str, ...]
    max_age_days: int
    scan_limit: int
    watchlist: tuple[str, ...]
    config_path: Path

    @property
    def forms_set(self) -> set[str]:
        return set(self.forms)


def _flatten_watchlist(raw: dict) -> list[str]:
    tickers: list[str] = []
    for value in raw.values():
        if isinstance(value, list):
            tickers.extend(str(t).strip().upper() for t in value if str(t).strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def load(config_path: Path | None = None) -> Config:
    cfg_path = Path(
        config_path
        or os.environ.get("GOVSPEND_CONFIG")
        or "config.toml"
    ).resolve()

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config not found at {cfg_path}. "
            "Copy config.example.toml to config.toml and edit it."
        )

    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)

    user_agent = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent:
        raise RuntimeError(
            "EDGAR_USER_AGENT env var must be set to 'Your Name your_email@example.com'. "
            "SEC blocks unidentified clients."
        )

    poller = raw.get("poller", {})
    watchlist_raw = raw.get("watchlist", {})

    db_path = Path(os.environ.get("GOVSPEND_DB") or "data/state.db").resolve()
    events_path = Path(os.environ.get("GOVSPEND_EVENTS") or "data/events.jsonl").resolve()

    return Config(
        user_agent=user_agent,
        db_path=db_path,
        events_path=events_path,
        interval_seconds=int(poller.get("interval_seconds", 900)),
        forms=tuple(poller.get("forms", ["SC 13D", "8-K", "4"])),
        max_age_days=int(poller.get("max_age_days", 7)),
        scan_limit=int(poller.get("scan_limit", 100)),
        watchlist=tuple(_flatten_watchlist(watchlist_raw)),
        config_path=cfg_path,
    )
