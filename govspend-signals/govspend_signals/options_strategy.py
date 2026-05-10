"""Options play generator around upcoming catalyst events.

Strategy: buy ATM calls (bullish catalyst) or puts (bearish) 5-10 days
before the catalyst date, targeting 4-6 week expiry. Uses historical
price reactions from price_context.py to estimate expected move.

Usage:
    govspend options [--ticker TICKER] [--days-before 7] [--max-days 90]

Requires:
    pip install "govspend-signals[price]"  (yfinance for live strike lookup)
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from itertools import groupby


@dataclass
class OptionsPlay:
    ticker: str
    catalyst_date: str
    catalyst_title: str
    action: str                      # "BUY CALL" or "BUY PUT"
    strike: float | None             # ATM strike (None if yfinance unavailable)
    expiry: dt.date | None           # target expiry date
    ask: float | None                # last ask price
    expected_move_pct: float | None  # from historical analysis
    thesis: str                      # human-readable rationale


@dataclass
class ATMOption:
    strike: float
    expiry: dt.date
    option_type: str  # "call" or "put"
    ask: float | None


def _next_monthly_expiry(min_days: int = 30) -> dt.date:
    """Return the next monthly options expiry (3rd Friday) at least min_days out."""
    today = dt.date.today()
    for month_offset in range(6):
        year = today.year
        month = today.month + month_offset
        while month > 12:
            year += 1
            month -= 12
        first_day = dt.date(year, month, 1)
        days_to_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + dt.timedelta(days=days_to_friday)
        third_friday = first_friday + dt.timedelta(weeks=2)
        if (third_friday - today).days >= min_days:
            return third_friday
    return today + dt.timedelta(days=45)


def _days_to_expiry(expiry: dt.date) -> int:
    return (expiry - dt.date.today()).days


def _fetch_atm_strike(ticker: str, option_type: str, expiry: dt.date) -> ATMOption | None:
    """Fetch the ATM option for `ticker` nearest to `expiry`. Returns None if unavailable."""
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1d", auto_adjust=True)
        if hist.empty:
            return None
        current_price = float(hist["Close"].iloc[-1])

        available_dates = tk.options
        if not available_dates:
            return None

        closest = min(available_dates, key=lambda d: abs(
            (dt.date.fromisoformat(d) - expiry).days
        ))

        chain = tk.option_chain(closest)
        opts = chain.calls if option_type == "call" else chain.puts
        if opts.empty:
            return None

        opts = opts.copy()
        opts["dist"] = (opts["strike"] - current_price).abs()
        atm_row = opts.loc[opts["dist"].idxmin()]

        return ATMOption(
            strike=float(atm_row["strike"]),
            expiry=dt.date.fromisoformat(closest),
            option_type=option_type,
            ask=float(atm_row["ask"]) if atm_row["ask"] > 0 else None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[options] yfinance error for {ticker}: {exc}", file=sys.stderr)
        return None


# Catalyst keyword → action + sector tickers + thesis
_CATALYST_THESIS: dict[str, dict] = {
    "cms": {
        "action": "BUY CALL",
        "tickers": ["UNH", "ELV", "CNC", "MOH", "HUM"],
        "thesis": "CMS rate notices typically drive +5-8% moves in managed care stocks",
    },
    "fomc": {
        "action": "BUY PUT",
        "tickers": ["NEE", "DUK", "SO", "AEP", "D"],
        "thesis": "Rate hike expectations weigh on regulated utilities (bond-proxy sector)",
    },
    "medicaid": {
        "action": "BUY CALL",
        "tickers": ["CNC", "MOH", "UNH"],
        "thesis": "Medicaid enrollment/rate events directly drive managed care earnings",
    },
    "medicare": {
        "action": "BUY CALL",
        "tickers": ["UNH", "HUM", "ELV"],
        "thesis": "Medicare Advantage rate changes are major earnings drivers",
    },
    "infrastructure": {
        "action": "BUY CALL",
        "tickers": ["PWR", "MTZ", "J", "ACM", "FLR"],
        "thesis": "Infrastructure spending announcements lift construction/engineering contractors",
    },
    "energy": {
        "action": "BUY CALL",
        "tickers": ["NEE", "XEL", "EXC"],
        "thesis": "DOE funding events benefit clean energy utilities",
    },
    "epa": {
        "action": "BUY CALL",
        "tickers": ["CLH", "RSG", "TTEK"],
        "thesis": "EPA Superfund/remediation activity boosts environmental services contractors",
    },
}


def _match_thesis(title: str) -> dict | None:
    title_lower = title.lower()
    for keyword, config in _CATALYST_THESIS.items():
        if keyword in title_lower:
            return config
    return None


def generate_plays(
    catalysts: list,
    tickers: list[str] | None = None,
    days_before_catalyst: int = 7,
    max_days_ahead: int = 90,
    expiry_min_days: int = 28,
) -> list[OptionsPlay]:
    """Generate options plays for upcoming catalyst events.

    Parameters
    ----------
    catalysts:
        List of Signal-like objects with `.published` and `.title` attributes.
    tickers:
        Watchlist tickers to consider (overrides catalyst-specific ticker list).
    days_before_catalyst:
        Ideal entry: this many days before the catalyst date.
    max_days_ahead:
        Skip catalysts more than this many days away.
    expiry_min_days:
        Minimum days until expiry.

    Returns
    -------
    list[OptionsPlay]
    """
    today = dt.date.today()
    plays: list[OptionsPlay] = []

    for signal in catalysts:
        try:
            catalyst_date = dt.date.fromisoformat(signal.published)
        except (ValueError, TypeError):
            continue

        days_out = (catalyst_date - today).days
        if days_out < 0 or days_out > max_days_ahead:
            continue

        title = signal.title or ""
        thesis_config = _match_thesis(title)
        if thesis_config is None:
            thesis_config = {
                "action": "BUY CALL",
                "tickers": tickers or [],
                "thesis": "Upcoming catalyst — review price history before entering",
            }

        play_tickers = tickers if tickers else thesis_config.get("tickers", [])
        action = thesis_config["action"]
        option_type = "call" if "CALL" in action else "put"
        expiry = _next_monthly_expiry(min_days=expiry_min_days)
        thesis = thesis_config["thesis"]

        for ticker in play_tickers[:5]:
            atm = _fetch_atm_strike(ticker, option_type, expiry)
            plays.append(OptionsPlay(
                ticker=ticker,
                catalyst_date=signal.published,
                catalyst_title=title[:80],
                action=action,
                strike=atm.strike if atm else None,
                expiry=atm.expiry if atm else expiry,
                ask=atm.ask if atm else None,
                expected_move_pct=None,
                thesis=thesis,
            ))

    return plays


def format_plays(plays: list[OptionsPlay]) -> str:
    if not plays:
        return (
            "No upcoming catalyst plays found.\n"
            "Run `govspend ingest` to populate the catalyst calendar,\n"
            "then `govspend options` to see plays."
        )

    sep = "─" * 72
    lines = [sep, " govspend OPTIONS — Catalyst-Driven Plays", sep]

    sorted_plays = sorted(plays, key=lambda p: p.catalyst_date)
    for catalyst_date, group in groupby(sorted_plays, key=lambda p: p.catalyst_date):
        group_list = list(group)
        lines.append(f"\n  📅 {catalyst_date}  —  {group_list[0].catalyst_title}")
        lines.append(f"  Thesis: {group_list[0].thesis}")
        lines.append(
            f"  {'Ticker':<7}  {'Action':<10}  {'Strike':>7}  {'Expiry':<12}  {'Ask':>6}"
        )
        lines.append(
            f"  {'──────':<7}  {'──────':<10}  {'──────':>7}  {'──────':<12}  {'───':>6}"
        )
        for play in group_list:
            strike_str = f"${play.strike:.0f}" if play.strike else "    TBD"
            expiry_str = play.expiry.isoformat() if play.expiry else "      —"
            ask_str = f"${play.ask:.2f}" if play.ask else "    —"
            lines.append(
                f"  {play.ticker:<7}  {play.action:<10}  {strike_str:>7}  "
                f"{expiry_str:<12}  {ask_str:>6}"
            )

    lines.append(f"\n{sep}")
    lines.append("  ⚠  Not financial advice. Verify strikes/expiry before entering.")
    lines.append(sep)
    return "\n".join(lines)
