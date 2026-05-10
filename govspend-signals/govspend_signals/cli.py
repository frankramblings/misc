from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import load as load_config
from .edgar import EdgarClient
from .notifier import FanoutNotifier, JsonlNotifier, StdoutNotifier
from .poller import poll_once
from .storage import Storage


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="govspend",
        description="SEC EDGAR signal box for the govspend-signals command center.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Scaffold config.toml and data/ in the current directory.")

    poll = sub.add_parser("poll", help="Run a single poll cycle.")
    poll.add_argument("--config", type=Path, default=None)
    poll.add_argument("--quiet", action="store_true", help="Suppress stdout notifier; only write JSONL.")

    watch = sub.add_parser("watch", help="Run poll cycles on a loop until interrupted.")
    watch.add_argument("--config", type=Path, default=None)
    watch.add_argument("--quiet", action="store_true")

    tk = sub.add_parser("tickers", help="Ticker map utilities.")
    tk_sub = tk.add_subparsers(dest="tickers_cmd", required=True)
    tk_update = tk_sub.add_parser("update", help="Force-refresh the SEC ticker map.")
    tk_update.add_argument("--config", type=Path, default=None)
    tk_lookup = tk_sub.add_parser("lookup", help="Look up a single ticker.")
    tk_lookup.add_argument("--config", type=Path, default=None)
    tk_lookup.add_argument("ticker")

    return p


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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
