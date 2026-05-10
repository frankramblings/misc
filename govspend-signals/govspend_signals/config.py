from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class WebhookConfig:
    enabled: bool
    url: str
    secret: str


@dataclass(frozen=True)
class SmtpConfig:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    to: str
    from_addr: str


@dataclass(frozen=True)
class Config:
    # Core
    user_agent: str
    db_path: Path
    events_path: Path
    config_path: Path

    # EDGAR poller
    interval_seconds: int
    forms: tuple[str, ...]
    max_age_days: int
    scan_limit: int
    watchlist: tuple[str, ...]

    # Ingestors
    lookback_days: int

    usaspending_enabled: bool
    usaspending_agencies: tuple[str, ...]
    usaspending_min_award: float

    fedregister_enabled: bool
    fedregister_agencies: tuple[str, ...]
    fedregister_doc_types: tuple[str, ...]

    congress_enabled: bool

    sbir_enabled: bool
    sbir_agencies: tuple[str, ...]

    norway_enabled: bool

    catalyst_enabled: bool

    # Notifiers
    telegram: TelegramConfig
    webhook: WebhookConfig
    smtp: SmtpConfig

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

    # Ingestors
    ingestors = raw.get("ingestors", {})
    lookback_days = int(ingestors.get("lookback_days", 7))

    usa = ingestors.get("usaspending", {})
    fed = ingestors.get("fedregister", {})
    cong = ingestors.get("congress", {})
    sbir = ingestors.get("sbir", {})
    norway = ingestors.get("norway", {})
    catalyst = ingestors.get("catalyst", {})

    # Notifiers
    notifiers = raw.get("notifiers", {})
    tg = notifiers.get("telegram", {})
    wh = notifiers.get("webhook", {})
    smtp_raw = notifiers.get("smtp", {})

    # Allow env-var overrides for secrets
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token", ""))
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", tg.get("chat_id", ""))
    wh_url = os.environ.get("WEBHOOK_URL", wh.get("url", ""))
    wh_secret = os.environ.get("WEBHOOK_SECRET", wh.get("secret", ""))
    smtp_pass = os.environ.get("SMTP_PASSWORD", smtp_raw.get("password", ""))

    return Config(
        user_agent=user_agent,
        db_path=db_path,
        events_path=events_path,
        config_path=cfg_path,
        interval_seconds=int(poller.get("interval_seconds", 900)),
        forms=tuple(poller.get("forms", ["SC 13D", "8-K", "4"])),
        max_age_days=int(poller.get("max_age_days", 7)),
        scan_limit=int(poller.get("scan_limit", 100)),
        watchlist=tuple(_flatten_watchlist(watchlist_raw)),
        lookback_days=lookback_days,
        usaspending_enabled=bool(usa.get("enabled", True)),
        usaspending_agencies=tuple(usa.get("agencies", [
            "HHS", "CMS-CMMI", "EPA", "DOE", "DOT", "USACE",
        ])),
        usaspending_min_award=float(usa.get("min_award_amount", 1_000_000)),
        fedregister_enabled=bool(fed.get("enabled", True)),
        fedregister_agencies=tuple(fed.get("agencies", [
            "Centers for Medicare & Medicaid Services",
            "Environmental Protection Agency",
            "Federal Energy Regulatory Commission",
            "Department of Transportation",
            "Health and Human Services Department",
        ])),
        fedregister_doc_types=tuple(fed.get("document_types", ["RULE", "PROPOSED_RULE", "NOTICE"])),
        congress_enabled=bool(cong.get("enabled", True)),
        sbir_enabled=bool(sbir.get("enabled", True)),
        sbir_agencies=tuple(sbir.get("agencies", ["DARPA", "ARPA-H", "BARDA", "NIH", "NSF"])),
        norway_enabled=bool(norway.get("enabled", True)),
        catalyst_enabled=bool(catalyst.get("enabled", True)),
        telegram=TelegramConfig(
            enabled=bool(tg.get("enabled", False)) and bool(tg_token) and bool(tg_chat),
            bot_token=tg_token,
            chat_id=tg_chat,
        ),
        webhook=WebhookConfig(
            enabled=bool(wh.get("enabled", False)) and bool(wh_url),
            url=wh_url,
            secret=wh_secret,
        ),
        smtp=SmtpConfig(
            enabled=bool(smtp_raw.get("enabled", False)) and bool(smtp_pass),
            host=smtp_raw.get("host", "smtp.gmail.com"),
            port=int(smtp_raw.get("port", 587)),
            username=smtp_raw.get("username", ""),
            password=smtp_pass,
            to=smtp_raw.get("to", ""),
            from_addr=smtp_raw.get("from", smtp_raw.get("username", "")),
        ),
    )
