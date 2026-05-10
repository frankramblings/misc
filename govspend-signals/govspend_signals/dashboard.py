"""Rich terminal dashboard for govspend-signals.

Renders a live, auto-refreshing terminal view showing:
  - Signal feed across all sources (most recent first)
  - Source breakdown panel
  - Upcoming catalyst calendar
  - Watchlist ticker count panel
  - Database stats footer

Usage:
    govspend dashboard [--hours 24] [--refresh 60] [--no-live]
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from .storage import Storage

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    from rich.style import Style
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


# ── Source colour coding ───────────────────────────────────────────────────────

SOURCE_STYLES: dict[str, str] = {
    "edgar": "bold cyan",
    "usaspending": "bold green",
    "fedregister": "bold yellow",
    "congress": "bold magenta",
    "sbir": "bold blue",
    "norway": "bold white",
    "catalyst": "bold red",
    "grants_gov": "bold bright_green",
    "propublica": "bold bright_yellow",
    "lobbying": "bold bright_magenta",
}

SOURCE_ICONS: dict[str, str] = {
    "edgar": "📋",
    "usaspending": "💰",
    "fedregister": "📜",
    "congress": "🏛️",
    "sbir": "🔬",
    "norway": "🇳🇴",
    "catalyst": "📅",
    "grants_gov": "🏆",
    "propublica": "⚖️",
    "lobbying": "💼",
}


def _make_signal_table(rows, max_rows: int = 30) -> "Table":
    """Build the main signal feed table."""
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold white on dark_blue",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Date", style="dim", width=10, no_wrap=True)
    table.add_column("Source", width=12, no_wrap=True)
    table.add_column("Type", width=16, no_wrap=True)
    table.add_column("Ticker", width=7, no_wrap=True)
    table.add_column("Amount", width=12, justify="right", no_wrap=True)
    table.add_column("Title", ratio=1)

    for row in rows[:max_rows]:
        source_style = SOURCE_STYLES.get(row.source, "white")
        icon = SOURCE_ICONS.get(row.source, "•")
        amount_str = f"${row.amount_usd:>10,.0f}" if row.amount_usd else "         —"
        ticker_str = row.ticker or "—"
        table.add_row(
            row.published or "—",
            Text(f"{icon} {row.source}", style=source_style),
            row.signal_type or "—",
            Text(ticker_str, style="bold cyan" if row.ticker else "dim"),
            amount_str,
            (row.title or "")[:120],
        )

    if not rows:
        table.add_row("—", "—", "—", "—", "—", "[dim]No signals in this window[/dim]")

    return table


def _make_source_panel(by_source: dict[str, int]) -> "Panel":
    """Build the source breakdown panel."""
    lines = []
    for source in [
        "edgar", "usaspending", "fedregister", "congress",
        "sbir", "norway", "catalyst", "grants_gov", "propublica", "lobbying"
    ]:
        n = by_source.get(source, 0)
        icon = SOURCE_ICONS.get(source, "•")
        style = SOURCE_STYLES.get(source, "white")
        bar = "█" * min(n, 20) if n else "·"
        lines.append(
            Text.assemble(
                (f"{icon} {source:<14}", style),
                (f" {n:>4}  ", "bold white"),
                (bar, style if n else "dim"),
            )
        )

    from rich.columns import Columns
    return Panel(
        "\n".join(str(l) for l in lines),
        title="[bold]Sources[/bold]",
        border_style="dim blue",
        padding=(0, 1),
    )


def _make_catalyst_panel(store: Storage) -> "Panel":
    """Show upcoming catalyst events from the catalyst ingestor."""
    since_ts = int(time.time()) - 7 * 86400  # last 7 days
    upcoming_ts = int(time.time()) + 30 * 86400  # next 30 days

    catalyst_rows = store.get_signals_since(since_ts, source="catalyst")

    today = dt.date.today().isoformat()

    table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    table.add_column("Date", width=10, no_wrap=True)
    table.add_column("Event", ratio=1)

    upcoming = [r for r in catalyst_rows if r.published >= today and r.signal_type == "upcoming_event"]
    recent = [r for r in catalyst_rows if r.published < today and r.signal_type == "recent_event"]

    for row in sorted(upcoming, key=lambda r: r.published)[:8]:
        days_out = (dt.date.fromisoformat(row.published) - dt.date.today()).days
        event_name = row.data.get("event_name", row.title.replace("[CATALYST] ", "").split(" — ")[0])
        table.add_row(
            Text(f"{row.published}", style="bold yellow"),
            Text(f"[{days_out}d] {event_name}", style="yellow"),
        )

    for row in sorted(recent, key=lambda r: r.published, reverse=True)[:3]:
        event_name = row.data.get("event_name", row.title.replace("[CATALYST] ", "").split(" — ")[0])
        table.add_row(
            Text(f"{row.published}", style="dim"),
            Text(f"(past) {event_name}", style="dim"),
        )

    if not upcoming and not recent:
        table.add_row("—", "[dim]Run `govspend ingest` to populate catalyst calendar[/dim]")

    return Panel(table, title="[bold]Catalyst Calendar[/bold]", border_style="dim yellow", padding=(0, 0))


def _make_ticker_panel(rows) -> "Panel":
    """Show tickers that have resolved signals."""
    ticker_counts: dict[str, int] = {}
    ticker_amounts: dict[str, float] = {}
    for row in rows:
        if row.ticker:
            ticker_counts[row.ticker] = ticker_counts.get(row.ticker, 0) + 1
            ticker_amounts[row.ticker] = ticker_amounts.get(row.ticker, 0.0) + (row.amount_usd or 0.0)

    table = Table(box=box.SIMPLE, show_header=True, expand=True, padding=(0, 1))
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Signals", width=8, justify="right")
    table.add_column("Total $", justify="right")

    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: ticker_amounts.get(x[0], 0), reverse=True)
    for ticker, count in sorted_tickers[:12]:
        total = ticker_amounts.get(ticker, 0)
        amount_str = f"${total:,.0f}" if total else "—"
        table.add_row(ticker, str(count), amount_str)

    if not sorted_tickers:
        table.add_row("—", "—", "[dim]No resolved tickers[/dim]")

    return Panel(table, title="[bold]Watchlist Activity[/bold]", border_style="dim cyan", padding=(0, 0))


def render_static(store: Storage, period_hours: int = 24) -> None:
    """Render a one-shot dashboard snapshot (no Live refresh)."""
    if not _RICH_AVAILABLE:
        print("Install 'rich' to use the dashboard: pip install rich")
        return

    console = Console()
    since_ts = int(time.time()) - period_hours * 3600
    rows = store.get_signals_since(since_ts)
    by_source = store.signal_count_since(since_ts)
    total = len(rows)

    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.rule(f"[bold white]govspend-signals dashboard — {now_str} (last {period_hours}h)[/bold white]")

    # Top row: source breakdown + catalyst panel
    from rich.columns import Columns

    # Signal feed
    console.print()
    console.print(Panel(
        _make_signal_table(rows, max_rows=40),
        title=f"[bold]Signal Feed[/bold]  [dim]({total} signals, last {period_hours}h)[/dim]",
        border_style="dim white",
    ))

    # Bottom row side by side
    console.print(Columns([
        _make_source_panel(by_source),
        _make_ticker_panel(rows),
        _make_catalyst_panel(store),
    ], expand=True, equal=True))

    console.rule("[dim]govspend-signals[/dim]")


def render_live(store: Storage, period_hours: int = 24, refresh_seconds: int = 60) -> None:
    """Render a live auto-refreshing dashboard (requires a real TTY)."""
    if not _RICH_AVAILABLE:
        print("Install 'rich' to use the dashboard: pip install rich")
        return

    console = Console()

    def _build() -> "Layout":
        from rich.columns import Columns

        since_ts = int(time.time()) - period_hours * 3600
        rows = store.get_signals_since(since_ts)
        by_source = store.signal_count_since(since_ts)
        total = len(rows)
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="feed", ratio=2),
            Layout(name="bottom", size=20),
        )
        layout["header"].update(
            Text(
                f" govspend-signals  {now_str}  |  {total} signals (last {period_hours}h)  |  refresh={refresh_seconds}s",
                style="bold white on dark_blue",
            )
        )
        layout["feed"].update(Panel(
            _make_signal_table(rows, max_rows=30),
            title="[bold]Signal Feed[/bold]",
            border_style="dim white",
        ))

        bottom = Layout()
        bottom.split_row(
            Layout(_make_source_panel(by_source), name="sources"),
            Layout(_make_ticker_panel(rows), name="tickers"),
            Layout(_make_catalyst_panel(store), name="catalysts"),
        )
        layout["bottom"].update(bottom)
        return layout

    try:
        with Live(
            _build(),
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                time.sleep(refresh_seconds)
                live.update(_build())
    except KeyboardInterrupt:
        pass
