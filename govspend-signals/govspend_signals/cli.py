from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import load as load_config
from .edgar import EdgarClient
from .notifier import (
    FanoutNotifier,
    JsonlNotifier,
    SignalFanoutNotifier,
    SignalJsonlNotifier,
    SignalStdoutNotifier,
    StdoutNotifier,
)
from .poller import poll_once
from .storage import Storage


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="govspend",
        description="Government-spending signal box: SEC EDGAR + USASpending + Federal Register + more.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    # ── init ──────────────────────────────────────────────────────────────────
    sub.add_parser("init", help="Scaffold config.toml and data/ in the current directory.")

    # ── poll (EDGAR only) ─────────────────────────────────────────────────────
    poll = sub.add_parser("poll", help="Run a single EDGAR poll cycle.")
    poll.add_argument("--config", type=Path, default=None)
    poll.add_argument("--quiet", action="store_true", help="Suppress stdout notifier; only write JSONL.")

    # ── watch (EDGAR loop) ───────────────────────────────────────────────────
    watch = sub.add_parser("watch", help="Run EDGAR poll cycles on a loop until interrupted.")
    watch.add_argument("--config", type=Path, default=None)
    watch.add_argument("--quiet", action="store_true")

    # ── tickers ───────────────────────────────────────────────────────────────
    tk = sub.add_parser("tickers", help="Ticker map utilities.")
    tk_sub = tk.add_subparsers(dest="tickers_cmd", required=True)
    tk_update = tk_sub.add_parser("update", help="Force-refresh the SEC ticker map.")
    tk_update.add_argument("--config", type=Path, default=None)
    tk_lookup = tk_sub.add_parser("lookup", help="Look up a single ticker.")
    tk_lookup.add_argument("--config", type=Path, default=None)
    tk_lookup.add_argument("ticker")

    # ── ingest (all sources, one shot) ───────────────────────────────────────
    _SOURCES = [
        "edgar", "usaspending", "fedregister", "congress", "sbir",
        "norway", "catalyst", "grants_gov", "propublica", "lobbying",
    ]

    ingest_cmd = sub.add_parser(
        "ingest",
        help="Run all enabled ingestors once and emit new signals.",
    )
    ingest_cmd.add_argument("--config", type=Path, default=None)
    ingest_cmd.add_argument("--quiet", action="store_true", help="Suppress stdout notifier.")
    ingest_cmd.add_argument(
        "--source",
        choices=_SOURCES,
        default=None,
        help="Only run a specific ingestor.",
    )

    # ── watch-ingest (all sources, loop) ─────────────────────────────────────
    wi_cmd = sub.add_parser(
        "watch-ingest",
        help="Run all ingestors on a loop (default: every 15 min) until interrupted.",
    )
    wi_cmd.add_argument("--config", type=Path, default=None)
    wi_cmd.add_argument("--quiet", action="store_true")
    wi_cmd.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override poll interval in seconds.",
    )

    # ── digest ────────────────────────────────────────────────────────────────
    digest_cmd = sub.add_parser("digest", help="Generate and print the morning digest.")
    digest_cmd.add_argument("--config", type=Path, default=None)
    digest_cmd.add_argument(
        "--hours", type=int, default=24,
        help="Lookback window in hours (default: 24).",
    )
    digest_cmd.add_argument(
        "--email", action="store_true",
        help="Send digest via SMTP (if enabled in config).",
    )
    digest_cmd.add_argument(
        "--telegram", action="store_true",
        help="Send digest via Telegram (if enabled in config).",
    )
    digest_cmd.add_argument(
        "--html-out", type=Path, default=None,
        help="Write HTML digest to this file.",
    )

    # ── signals ───────────────────────────────────────────────────────────────
    sig_cmd = sub.add_parser("signals", help="Query stored signals from the database.")
    sig_cmd.add_argument("--config", type=Path, default=None)
    sig_cmd.add_argument(
        "--hours", type=int, default=24,
        help="How many hours back to show (default: 24).",
    )
    sig_cmd.add_argument("--source", choices=_SOURCES, default=None)
    sig_cmd.add_argument("--ticker", default=None, help="Filter by ticker symbol.")
    sig_cmd.add_argument(
        "--limit", type=int, default=50,
        help="Maximum number of signals to display (default: 50).",
    )
    sig_cmd.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output one JSON object per line instead of human-readable.",
    )

    # ── export ────────────────────────────────────────────────────────────────
    exp_cmd = sub.add_parser("export", help="Export signals to a CSV file.")
    exp_cmd.add_argument("--config", type=Path, default=None)
    exp_cmd.add_argument(
        "--hours", type=int, default=168,
        help="How many hours back to export (default: 168 = 7 days).",
    )
    exp_cmd.add_argument(
        "--out", type=Path, default=Path("signals_export.csv"),
        help="Output CSV path (default: signals_export.csv).",
    )
    exp_cmd.add_argument("--source", choices=_SOURCES, default=None)

    # ── status ────────────────────────────────────────────────────────────────
    status_cmd = sub.add_parser("status", help="Show config summary and database stats.")
    status_cmd.add_argument("--config", type=Path, default=None)

    # ── dashboard ─────────────────────────────────────────────────────────────
    dash_cmd = sub.add_parser(
        "dashboard",
        help="Open the Rich terminal dashboard (live auto-refresh).",
    )
    dash_cmd.add_argument("--config", type=Path, default=None)
    dash_cmd.add_argument(
        "--hours", type=int, default=24,
        help="Lookback window in hours (default: 24).",
    )
    dash_cmd.add_argument(
        "--refresh", type=int, default=60,
        help="Auto-refresh interval in seconds (default: 60).",
    )
    dash_cmd.add_argument(
        "--no-live", action="store_true",
        help="Render a static one-shot snapshot instead of live mode.",
    )

    # ── price-history ─────────────────────────────────────────────────────────
    price_cmd = sub.add_parser(
        "price-history",
        help="Show historical price reactions around catalyst dates for watchlist tickers.",
    )
    price_cmd.add_argument("--config", type=Path, default=None)
    price_cmd.add_argument(
        "--ticker",
        default=None,
        help="Specific ticker to analyse (default: all watchlist tickers).",
    )
    price_cmd.add_argument(
        "--days-before", type=int, default=5,
        help="Trading days before catalyst to measure (default: 5).",
    )
    price_cmd.add_argument(
        "--days-after", type=int, default=10,
        help="Trading days after catalyst to measure (default: 10).",
    )
    price_cmd.add_argument(
        "--limit", type=int, default=20,
        help="Max catalyst events to analyse (default: 20).",
    )

    # ── sector-rotation ───────────────────────────────────────────────────────
    rot_cmd = sub.add_parser(
        "sector-rotation",
        help="Show which investment sectors are getting the most signal velocity.",
    )
    rot_cmd.add_argument("--config", type=Path, default=None)
    rot_cmd.add_argument(
        "--hours", type=int, default=24,
        help="Current window in hours (default: 24).",
    )
    rot_cmd.add_argument(
        "--compare-hours", type=int, default=168,
        help="Prior comparison window in hours (default: 168 = 7 days).",
    )

    # ── options ───────────────────────────────────────────────────────────────
    opts_cmd = sub.add_parser(
        "options",
        help="Generate options play suggestions around upcoming catalyst events.",
    )
    opts_cmd.add_argument("--config", type=Path, default=None)
    opts_cmd.add_argument(
        "--ticker", default=None,
        help="Specific ticker (default: catalyst-matched watchlist tickers).",
    )
    opts_cmd.add_argument(
        "--days-before", type=int, default=7,
        help="Ideal entry days before catalyst (default: 7).",
    )
    opts_cmd.add_argument(
        "--max-days", type=int, default=90,
        help="Skip catalysts more than this many days out (default: 90).",
    )

    # ── basket ────────────────────────────────────────────────────────────────
    basket_cmd = sub.add_parser(
        "basket",
        help="Build ethical-screen portfolio basket (no defense/fossil fuel).",
    )
    basket_cmd.add_argument("--config", type=Path, default=None)
    basket_cmd.add_argument(
        "--equal-weight", action="store_true",
        help="Equal-weight positions instead of contract-weighted.",
    )
    basket_cmd.add_argument(
        "--hours", type=int, default=720,
        help="Lookback window for contract amounts (default: 720h = 30 days).",
    )
    basket_cmd.add_argument(
        "--min-weight", type=float, default=1.0,
        help="Drop positions below this weight %% (default: 1.0).",
    )

    # ── web (FastAPI dashboard) ───────────────────────────────────────────────
    web_cmd = sub.add_parser(
        "web",
        help="Start the web dashboard (http://localhost:8000 by default).",
    )
    web_cmd.add_argument("--config", type=Path, default=None)
    web_cmd.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    web_cmd.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    web_cmd.add_argument("--db", type=Path, default=None, help="Explicit DB path (overrides config)")

    return p


# ── init ──────────────────────────────────────────────────────────────────────

def _cmd_init() -> int:
    here = Path.cwd()
    target_cfg = here / "config.toml"
    src_cfg = Path(__file__).resolve().parent.parent / "config.example.toml"

    if target_cfg.exists():
        print(f"config.toml already exists at {target_cfg}", file=sys.stderr)
    elif src_cfg.exists():
        shutil.copy(src_cfg, target_cfg)
        print(f"Wrote {target_cfg}")
    else:
        print(
            "config.example.toml not found; cannot scaffold config.toml. "
            "Run from the repo, or create config.toml manually.",
            file=sys.stderr,
        )
        return 1

    (here / "data").mkdir(exist_ok=True)
    print("Scaffold complete. Set EDGAR_USER_AGENT then run: govspend poll")
    return 0


# ── EDGAR poll / watch ────────────────────────────────────────────────────────

def _build_notifier(quiet: bool, events_path: Path):
    jsonl = JsonlNotifier(events_path)
    if quiet:
        return jsonl
    return FanoutNotifier(StdoutNotifier(), jsonl)


def _cmd_poll(args) -> int:
    cfg = load_config(args.config)
    client = EdgarClient(user_agent=cfg.user_agent)
    notifier = _build_notifier(args.quiet, cfg.events_path)

    with Storage(cfg.db_path) as store:
        result = poll_once(cfg, client, store, notifier)

    print(
        f"scanned={result.scanned_tickers} "
        f"new_filings={result.new_filings} "
        f"unresolved={len(result.unresolved_tickers)} "
        f"errors={len(result.errors)}",
        file=sys.stderr,
    )
    if result.unresolved_tickers:
        print(f"unresolved: {', '.join(result.unresolved_tickers)}", file=sys.stderr)
    for err in result.errors:
        print(f"  err: {err}", file=sys.stderr)
    return 0


def _cmd_watch(args) -> int:
    cfg = load_config(args.config)
    client = EdgarClient(user_agent=cfg.user_agent)
    notifier = _build_notifier(args.quiet, cfg.events_path)

    print(
        f"watching {len(cfg.watchlist)} tickers, "
        f"interval={cfg.interval_seconds}s, forms={list(cfg.forms)}",
        file=sys.stderr,
    )
    with Storage(cfg.db_path) as store:
        while True:
            try:
                result = poll_once(cfg, client, store, notifier)
                print(
                    f"[cycle] new_filings={result.new_filings} "
                    f"errors={len(result.errors)}",
                    file=sys.stderr,
                )
            except KeyboardInterrupt:
                print("interrupted; exiting", file=sys.stderr)
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"cycle failed: {exc}", file=sys.stderr)
            try:
                time.sleep(cfg.interval_seconds)
            except KeyboardInterrupt:
                return 0


# ── tickers ───────────────────────────────────────────────────────────────────

def _cmd_tickers_update(args) -> int:
    cfg = load_config(args.config)
    client = EdgarClient(user_agent=cfg.user_agent)
    with Storage(cfg.db_path) as store:
        mapping = client.fetch_ticker_map()
        for ticker, (cik, company) in mapping.items():
            store.upsert_ticker(ticker, cik, company)
    print(f"upserted {len(mapping)} tickers")
    return 0


def _cmd_tickers_lookup(args) -> int:
    cfg = load_config(args.config)
    with Storage(cfg.db_path) as store:
        rec = store.lookup_ticker(args.ticker)
    if rec is None:
        print(f"{args.ticker.upper()}: not found (run `govspend tickers update`)", file=sys.stderr)
        return 1
    print(f"{rec.ticker}\tCIK={rec.cik:010d}\t{rec.company}")
    return 0


# ── ingest helpers ────────────────────────────────────────────────────────────

def _build_signal_notifier(quiet: bool, events_path: Path, cfg):
    """Build a SignalFanoutNotifier from config.

    Always writes to JSONL. Adds stdout unless --quiet.
    Adds Telegram and Webhook if enabled in config.
    """
    children = []
    if not quiet:
        children.append(SignalStdoutNotifier())
    children.append(SignalJsonlNotifier(events_path))

    if cfg.telegram.enabled:
        from .notifiers.telegram import TelegramNotifier
        children.append(TelegramNotifier(cfg.telegram))

    if cfg.webhook.enabled:
        from .notifiers.webhook import WebhookNotifier
        children.append(WebhookNotifier(cfg.webhook))

    return SignalFanoutNotifier(*children)


def _run_ingestors(cfg, store, notifier, source_filter: str | None) -> dict[str, int]:
    """Run all enabled ingestors (or the one specified by source_filter).

    Returns {source: new_signal_count}.
    """
    from .ingestors import usaspending, fedregister, congress, sbir, norway, catalyst
    from .ingestors import grants_gov, propublica, lobbying
    from .resolver import Resolver
    resolver = Resolver(user_agent=cfg.user_agent)

    counts: dict[str, int] = {}

    def _process(source: str, signals: list) -> int:
        n = 0
        for sig in signals:
            if store.is_signal_seen(sig.id):
                continue
            store.mark_signal_seen(sig)
            notifier.emit(sig)
            n += 1
        return n

    # ── EDGAR (delegates to poll_once when --source edgar is requested) ──────
    if source_filter == "edgar":
        from .poller import poll_once
        client = EdgarClient(user_agent=cfg.user_agent)
        result = poll_once(cfg, client, store, notifier)
        counts["edgar"] = result.new_filings
        for err in result.errors:
            print(f"[ingest] edgar error: {err}", file=sys.stderr)
        return counts

    # ── USASpending ──────────────────────────────────────────────────────────
    if (source_filter is None or source_filter == "usaspending") and cfg.usaspending_enabled:
        try:
            sigs = usaspending.ingest(
                agencies=list(cfg.usaspending_agencies),
                lookback_days=cfg.lookback_days,
                min_award_usd=cfg.usaspending_min_award,
                resolver=resolver,
            )
            counts["usaspending"] = _process("usaspending", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] usaspending error: {exc}", file=sys.stderr)
            counts["usaspending"] = 0

    # ── Federal Register ─────────────────────────────────────────────────────
    if (source_filter is None or source_filter == "fedregister") and cfg.fedregister_enabled:
        try:
            sigs = fedregister.ingest(
                agencies=list(cfg.fedregister_agencies),
                doc_types=list(cfg.fedregister_doc_types),
                lookback_days=cfg.lookback_days,
            )
            counts["fedregister"] = _process("fedregister", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] fedregister error: {exc}", file=sys.stderr)
            counts["fedregister"] = 0

    # ── Congressional trades ─────────────────────────────────────────────────
    if (source_filter is None or source_filter == "congress") and cfg.congress_enabled:
        try:
            sigs = congress.ingest(lookback_days=cfg.lookback_days)
            counts["congress"] = _process("congress", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] congress error: {exc}", file=sys.stderr)
            counts["congress"] = 0

    # ── SBIR / STTR grants ───────────────────────────────────────────────────
    if (source_filter is None or source_filter == "sbir") and cfg.sbir_enabled:
        try:
            sigs = sbir.ingest(
                agencies=list(cfg.sbir_agencies),
                lookback_days=cfg.lookback_days,
                resolver=resolver,
            )
            counts["sbir"] = _process("sbir", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] sbir error: {exc}", file=sys.stderr)
            counts["sbir"] = 0

    # ── Norway SWF ───────────────────────────────────────────────────────────
    if (source_filter is None or source_filter == "norway") and cfg.norway_enabled:
        try:
            sigs = norway.ingest(
                user_agent=cfg.user_agent,
                lookback_days=cfg.lookback_days,
            )
            counts["norway"] = _process("norway", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] norway error: {exc}", file=sys.stderr)
            counts["norway"] = 0

    # ── Catalyst calendar ────────────────────────────────────────────────────
    if (source_filter is None or source_filter == "catalyst") and cfg.catalyst_enabled:
        try:
            sigs = catalyst.ingest(lookback_days=cfg.lookback_days)
            counts["catalyst"] = _process("catalyst", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] catalyst error: {exc}", file=sys.stderr)
            counts["catalyst"] = 0

    # ── Grants.gov NOFOs ─────────────────────────────────────────────────────
    if (source_filter is None or source_filter == "grants_gov") and cfg.grants_gov_enabled:
        try:
            sigs = grants_gov.ingest(
                lookback_days=cfg.lookback_days,
                max_results=cfg.grants_gov_max_results,
            )
            counts["grants_gov"] = _process("grants_gov", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] grants_gov error: {exc}", file=sys.stderr)
            counts["grants_gov"] = 0

    # ── ProPublica Congress bills ─────────────────────────────────────────────
    if (source_filter is None or source_filter == "propublica") and cfg.propublica_enabled:
        try:
            sigs = propublica.ingest(
                lookback_days=cfg.lookback_days,
                api_key=cfg.propublica_api_key or None,
            )
            counts["propublica"] = _process("propublica", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] propublica error: {exc}", file=sys.stderr)
            counts["propublica"] = 0

    # ── Senate LDA lobbying spikes ───────────────────────────────────────────
    if (source_filter is None or source_filter == "lobbying") and cfg.lobbying_enabled:
        try:
            sigs = lobbying.ingest(
                lookback_days=cfg.lookback_days,
                api_key=cfg.lobbying_api_key or None,
                min_amount=cfg.lobbying_min_amount,
                resolver=resolver,
            )
            counts["lobbying"] = _process("lobbying", sigs)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] lobbying error: {exc}", file=sys.stderr)
            counts["lobbying"] = 0

    return counts


def _cmd_ingest(args) -> int:
    cfg = load_config(args.config)
    notifier = _build_signal_notifier(args.quiet, cfg.events_path, cfg)

    with Storage(cfg.db_path) as store:
        counts = _run_ingestors(cfg, store, notifier, args.source)

    total = sum(counts.values())
    parts = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"new_signals={total} {parts}", file=sys.stderr)
    return 0


def _cmd_watch_ingest(args) -> int:
    cfg = load_config(args.config)
    interval = args.interval or cfg.interval_seconds
    notifier = _build_signal_notifier(args.quiet, cfg.events_path, cfg)

    print(f"watch-ingest: interval={interval}s, lookback={cfg.lookback_days}d", file=sys.stderr)

    with Storage(cfg.db_path) as store:
        while True:
            try:
                counts = _run_ingestors(cfg, store, notifier, None)
                total = sum(counts.values())
                print(f"[cycle] new_signals={total}", file=sys.stderr)
            except KeyboardInterrupt:
                print("interrupted; exiting", file=sys.stderr)
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"[cycle] error: {exc}", file=sys.stderr)
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                return 0


# ── digest ────────────────────────────────────────────────────────────────────

def _cmd_digest(args) -> int:
    from . import digest as digest_mod

    cfg = load_config(args.config)

    with Storage(cfg.db_path) as store:
        result = digest_mod.generate(store, period_hours=args.hours)

    # Always print to stdout
    print(result.text)

    # Optionally write HTML
    if args.html_out:
        args.html_out.parent.mkdir(parents=True, exist_ok=True)
        args.html_out.write_text(result.html, encoding="utf-8")
        print(f"HTML digest written to {args.html_out}", file=sys.stderr)

    # Telegram
    if args.telegram:
        if not cfg.telegram.enabled:
            print(
                "[digest] Telegram not enabled — set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID",
                file=sys.stderr,
            )
        else:
            from .notifiers.telegram import TelegramNotifier
            tg = TelegramNotifier(cfg.telegram)
            tg.emit_digest(result.text)
            print("[digest] sent via Telegram", file=sys.stderr)

    # Email
    if args.email:
        if not cfg.smtp.enabled:
            print(
                "[digest] SMTP not enabled — set SMTP_PASSWORD and configure [notifiers.smtp]",
                file=sys.stderr,
            )
        else:
            from .notifiers.smtp import SmtpNotifier
            import datetime as dt
            smtp = SmtpNotifier(cfg.smtp)
            subject = f"govspend digest — {dt.date.today().isoformat()} ({result.total_signals} signals)"
            smtp.emit_digest(subject, result.text)
            print("[digest] sent via email", file=sys.stderr)

    return 0


# ── signals query ─────────────────────────────────────────────────────────────

def _cmd_signals(args) -> int:
    import json as json_mod

    cfg = load_config(args.config)
    since_ts = int(time.time()) - args.hours * 3600

    with Storage(cfg.db_path) as store:
        rows = store.get_signals_since(since_ts, source=args.source)

    # Ticker filter (post-query)
    if args.ticker:
        ticker_upper = args.ticker.upper()
        rows = [r for r in rows if r.ticker and r.ticker.upper() == ticker_upper]

    # Limit
    rows = rows[: args.limit]

    if not rows:
        print(f"No signals in the last {args.hours}h.", file=sys.stderr)
        return 0

    if args.as_json:
        for row in rows:
            print(json_mod.dumps({
                "id": row.id,
                "source": row.source,
                "signal_type": row.signal_type,
                "ticker": row.ticker,
                "company": row.company,
                "title": row.title,
                "url": row.url,
                "published": row.published,
                "amount_usd": row.amount_usd,
                "data": row.data,
            }))
    else:
        for row in rows:
            amount_str = f" ${row.amount_usd:,.0f}" if row.amount_usd is not None else ""
            ticker_str = f" [{row.ticker}]" if row.ticker else ""
            print(
                f"[{row.published}] [{row.source.upper():<12}] "
                f"{row.signal_type:<16}{ticker_str}{amount_str}\n"
                f"  {row.title}\n"
                f"  {row.url}"
            )

    return 0


# ── export ────────────────────────────────────────────────────────────────────

def _cmd_export(args) -> int:
    cfg = load_config(args.config)
    since_ts = int(time.time()) - args.hours * 3600

    with Storage(cfg.db_path) as store:
        rows = store.get_signals_since(since_ts, source=args.source)

    if not rows:
        print(f"No signals in the last {args.hours}h to export.", file=sys.stderr)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "source", "signal_type", "ticker", "company", "title",
                  "url", "published", "amount_usd"]

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row.id,
                "source": row.source,
                "signal_type": row.signal_type,
                "ticker": row.ticker or "",
                "company": row.company or "",
                "title": row.title,
                "url": row.url,
                "published": row.published,
                "amount_usd": row.amount_usd if row.amount_usd is not None else "",
            })

    print(f"Exported {len(rows)} signals to {args.out}", file=sys.stderr)
    return 0


# ── status ────────────────────────────────────────────────────────────────────

def _cmd_status(args) -> int:
    cfg = load_config(args.config)

    with Storage(cfg.db_path) as store:
        ticker_age = store.ticker_map_age_seconds()
        counts_24h = store.signal_count_since(int(time.time()) - 86400)
        counts_7d = store.signal_count_since(int(time.time()) - 7 * 86400)
        # Count EDGAR filings seen
        edgar_count = store._conn.execute(
            "SELECT COUNT(*) FROM filings_seen"
        ).fetchone()[0]

    sep = "─" * 55
    print(sep)
    print(f" govspend-signals  v{__version__}  status")
    print(sep)
    print(f"  config           {cfg.config_path}")
    print(f"  database         {cfg.db_path}")
    print(f"  events           {cfg.events_path}")
    print(f"  watchlist        {len(cfg.watchlist)} tickers")
    print(f"  EDGAR forms      {', '.join(cfg.forms)}")
    print(f"  poll interval    {cfg.interval_seconds}s")
    if ticker_age is None:
        print("  ticker map       NOT SEEDED (run: govspend tickers update)")
    else:
        h, m = divmod(ticker_age, 3600)
        m //= 60
        print(f"  ticker map       {h}h {m}m old")
    print()
    print("  EDGAR filings seen (all time):", edgar_count)
    print()
    print("  Signals last 24h:")
    if counts_24h:
        for src, n in sorted(counts_24h.items()):
            print(f"    {src:<14} {n}")
    else:
        print("    (none)")
    print()
    print("  Signals last 7d:")
    if counts_7d:
        for src, n in sorted(counts_7d.items()):
            print(f"    {src:<14} {n}")
    else:
        print("    (none — run `govspend ingest` to populate)")
    print()
    print("  Notifiers enabled:")
    print(f"    telegram         {'YES' if cfg.telegram.enabled else 'no'}")
    print(f"    webhook          {'YES' if cfg.webhook.enabled else 'no'}")
    print(f"    smtp             {'YES' if cfg.smtp.enabled else 'no'}")
    print(sep)
    return 0


# ── dashboard ─────────────────────────────────────────────────────────────────

def _cmd_dashboard(args) -> int:
    from . import dashboard as dash_mod

    cfg = load_config(args.config)
    with Storage(cfg.db_path) as store:
        if args.no_live:
            dash_mod.render_static(store, period_hours=args.hours)
        else:
            dash_mod.render_live(store, period_hours=args.hours, refresh_seconds=args.refresh)
    return 0


# ── price-history ──────────────────────────────────────────────────────────────

def _cmd_price_history(args) -> int:
    from . import price_context as pc

    cfg = load_config(args.config)
    tickers = [args.ticker.upper()] if args.ticker else list(cfg.watchlist)

    with Storage(cfg.db_path) as store:
        catalyst_rows = store.get_signals_since(
            int(time.time()) - 365 * 86400,  # last year of catalysts
            source="catalyst",
        )

    if not catalyst_rows:
        print(
            "No catalyst events found. Run `govspend ingest` first.",
            file=sys.stderr,
        )
        return 1

    events = catalyst_rows[: args.limit]
    results = pc.analyse_catalyst_reactions(
        events=events,
        tickers=tickers,
        days_before=args.days_before,
        days_after=args.days_after,
    )
    pc.print_reactions(results)
    return 0


# ── sector-rotation ───────────────────────────────────────────────────────────

def _cmd_sector_rotation(args) -> int:
    from . import sector_rotation as sr

    cfg = load_config(args.config)
    with Storage(cfg.db_path) as store:
        snapshots = sr.compute_rotation(
            store,
            window_hours=args.hours,
            compare_hours=args.compare_hours,
        )

    print(sr.format_rotation_table(snapshots, args.hours, args.compare_hours))
    return 0


# ── options ───────────────────────────────────────────────────────────────────

def _cmd_options(args) -> int:
    from . import options_strategy as opts_mod

    cfg = load_config(args.config)
    tickers = [args.ticker.upper()] if args.ticker else list(cfg.watchlist)

    with Storage(cfg.db_path) as store:
        catalyst_rows = store.get_signals_since(
            int(time.time()) - 90 * 86400,
            source="catalyst",
        )

    upcoming = [r for r in catalyst_rows if r.signal_type == "upcoming_event"]

    if not upcoming:
        print("No upcoming catalyst events. Run `govspend ingest` first.")
        return 0

    plays = opts_mod.generate_plays(
        upcoming,
        tickers=tickers,
        days_before_catalyst=args.days_before,
        max_days_ahead=args.max_days,
    )
    print(opts_mod.format_plays(plays))
    return 0


# ── basket ────────────────────────────────────────────────────────────────────

def _cmd_basket(args) -> int:
    from . import basket as basket_mod

    cfg = load_config(args.config)
    since_ts = int(time.time()) - args.hours * 3600

    with Storage(cfg.db_path) as store:
        rows = store.get_signals_since(since_ts, source="usaspending")

    contract_amounts: dict[str, float] = {}
    for row in rows:
        if row.ticker and row.amount_usd:
            contract_amounts[row.ticker] = (
                contract_amounts.get(row.ticker, 0.0) + row.amount_usd
            )

    positions = basket_mod.build_basket(
        watchlist=list(cfg.watchlist),
        contract_amounts=contract_amounts,
        contract_weighted=not args.equal_weight,
        min_weight_pct=args.min_weight,
    )
    print(basket_mod.format_basket(positions))
    return 0


# ── web ───────────────────────────────────────────────────────────────────────

def _cmd_web(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn not installed. Run: pip install 'govspend-signals[web]'",
            file=sys.stderr,
        )
        return 1

    from .web import create_app

    cfg = load_config(args.config)
    db_path = args.db or cfg.db_path
    store = Storage(db_path)

    origin = os.environ.get(
        "DASHBOARD_ORIGIN", f"http://{args.host}:{args.port}"
    )
    app = create_app(store=store, config=cfg, origin=origin)

    print(f"govspend web  →  {origin}")
    print("Register a passkey on first visit.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    store.close()
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "init":
        return _cmd_init()
    if args.cmd == "poll":
        return _cmd_poll(args)
    if args.cmd == "watch":
        return _cmd_watch(args)
    if args.cmd == "tickers":
        if args.tickers_cmd == "update":
            return _cmd_tickers_update(args)
        if args.tickers_cmd == "lookup":
            return _cmd_tickers_lookup(args)
    if args.cmd == "ingest":
        return _cmd_ingest(args)
    if args.cmd == "watch-ingest":
        return _cmd_watch_ingest(args)
    if args.cmd == "digest":
        return _cmd_digest(args)
    if args.cmd == "signals":
        return _cmd_signals(args)
    if args.cmd == "export":
        return _cmd_export(args)
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "dashboard":
        return _cmd_dashboard(args)
    if args.cmd == "price-history":
        return _cmd_price_history(args)
    if args.cmd == "sector-rotation":
        return _cmd_sector_rotation(args)
    if args.cmd == "options":
        return _cmd_options(args)
    if args.cmd == "basket":
        return _cmd_basket(args)
    if args.cmd == "web":
        return _cmd_web(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
