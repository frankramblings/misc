"""Historical price reaction analysis around known catalyst dates.

Uses yfinance to fetch OHLCV history and computes returns in the windows
before and after each catalyst event. Gives you a quick read on how the
market has historically priced these recurring events.

Usage:
    govspend price-history [--ticker TICKER] [--days-before 5] [--days-after 10]

Requires:
    pip install "govspend-signals[price]"   (pulls yfinance>=0.2)
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class CatalystReaction:
    ticker: str
    catalyst_date: str
    catalyst_title: str
    return_before: float | None   # % return in the N days BEFORE catalyst
    return_after: float | None    # % return in the N days AFTER catalyst
    days_before: int
    days_after: int


def _fetch_prices(ticker: str, start: dt.date, end: dt.date) -> dict[str, float]:
    """Return {date_str: adjusted_close} for the given range."""
    try:
        import yfinance as yf
    except ImportError:
        print(
            "[price-history] yfinance not installed. Run: pip install 'govspend-signals[price]'",
            file=sys.stderr,
        )
        return {}

    try:
        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + dt.timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[price-history] yfinance error for {ticker}: {exc}", file=sys.stderr)
        return {}

    result: dict[str, float] = {}
    if hist is None or hist.empty:
        return result

    close_col = "Close"
    if close_col not in hist.columns:
        # yfinance multi-level columns when fetching single ticker
        cols = [c for c in hist.columns if "Close" in str(c)]
        if not cols:
            return result
        close_col = cols[0]

    for idx, row in hist.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        val = row[close_col]
        if val and val == val:  # not NaN
            result[date_str] = float(val)

    return result


def _nearest_price(prices: dict[str, float], target: dt.date, direction: int) -> tuple[str, float] | None:
    """Find the nearest trading day price in `direction` (+1=forward, -1=backward)."""
    for delta in range(0, 10):
        candidate = target + dt.timedelta(days=delta * direction)
        date_str = candidate.isoformat()
        if date_str in prices:
            return date_str, prices[date_str]
    return None


def analyse_catalyst_reactions(
    events: list,
    tickers: list[str],
    days_before: int = 5,
    days_after: int = 10,
) -> list[CatalystReaction]:
    """Compute price reactions for a list of catalyst Signal objects.

    Parameters
    ----------
    events:
        List of Signal-like objects with `.published` and `.title` attributes.
    tickers:
        List of ticker symbols to analyse.
    days_before:
        Number of calendar days before the catalyst to compute the pre-return.
    days_after:
        Number of calendar days after the catalyst to compute the post-return.

    Returns
    -------
    list[CatalystReaction]
        One entry per (ticker, event) pair.
    """
    results: list[CatalystReaction] = []

    # Build a set of unique dates to fetch
    dates: list[dt.date] = []
    for ev in events:
        try:
            dates.append(dt.date.fromisoformat(ev.published))
        except (ValueError, TypeError):
            pass

    if not dates:
        return results

    earliest = min(dates) - dt.timedelta(days=days_before + 15)
    latest = max(dates) + dt.timedelta(days=days_after + 15)

    for ticker in tickers:
        prices = _fetch_prices(ticker, earliest, latest)
        if not prices:
            continue

        for ev, catalyst_date in zip(events, dates):
            # Price at catalyst date (or nearest trading day)
            at_pair = _nearest_price(prices, catalyst_date, direction=1)
            if at_pair is None:
                at_pair = _nearest_price(prices, catalyst_date, direction=-1)
            if at_pair is None:
                continue
            at_price = at_pair[1]

            # Price N days before
            before_date = catalyst_date - dt.timedelta(days=days_before)
            before_pair = _nearest_price(prices, before_date, direction=-1)
            return_before: float | None = None
            if before_pair and before_pair[1]:
                return_before = (at_price / before_pair[1] - 1.0) * 100.0

            # Price N days after
            after_date = catalyst_date + dt.timedelta(days=days_after)
            after_pair = _nearest_price(prices, after_date, direction=1)
            return_after: float | None = None
            if after_pair and after_pair[1]:
                return_after = (after_pair[1] / at_price - 1.0) * 100.0

            results.append(CatalystReaction(
                ticker=ticker,
                catalyst_date=ev.published,
                catalyst_title=ev.title or "",
                return_before=return_before,
                return_after=return_after,
                days_before=days_before,
                days_after=days_after,
            ))

    return results


def print_reactions(results: list[CatalystReaction]) -> None:
    """Print catalyst reactions to stdout in a human-readable table."""
    if not results:
        print("No price history data available. Ensure catalysts are in the database and yfinance is installed.")
        return

    # Group by ticker
    by_ticker: dict[str, list[CatalystReaction]] = {}
    for r in results:
        by_ticker.setdefault(r.ticker, []).append(r)

    sep = "─" * 90
    for ticker, rows in sorted(by_ticker.items()):
        print(sep)
        print(f"  {ticker}  —  {len(rows)} catalyst event(s)")
        print(sep)
        print(f"  {'Date':<12}  {'Pre':>7}  {'Post':>7}  Event")
        print(f"  {'────':<12}  {'───':>7}  {'────':>7}  ─────")

        for r in sorted(rows, key=lambda x: x.catalyst_date):
            pre_str = f"{r.return_before:+.1f}%" if r.return_before is not None else "   n/a"
            post_str = f"{r.return_after:+.1f}%" if r.return_after is not None else "   n/a"
            title = r.catalyst_title[:55]
            print(f"  {r.catalyst_date:<12}  {pre_str:>7}  {post_str:>7}  {title}")

        # Summary stats
        before_vals = [r.return_before for r in rows if r.return_before is not None]
        after_vals = [r.return_after for r in rows if r.return_after is not None]
        if before_vals:
            avg_pre = sum(before_vals) / len(before_vals)
            avg_post = sum(after_vals) / len(after_vals) if after_vals else float("nan")
            print()
            print(
                f"  avg pre-catalyst ({rows[0].days_before}d):  {avg_pre:+.1f}%  |  "
                f"avg post-catalyst ({rows[0].days_after}d):  {avg_post:+.1f}%"
            )
        print()

    print(sep)
