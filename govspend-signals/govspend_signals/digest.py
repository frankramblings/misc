"""Morning digest generator — summarises recent signals from all sources."""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

from .storage import Storage, SignalRow

_ALL_SOURCES = (
    "edgar", "usaspending", "fedregister", "congress", "sbir",
    "norway", "catalyst", "grants_gov", "propublica", "lobbying",
)

_SOURCE_LABELS = {
    "edgar": ("edgar", "filings"),
    "usaspending": ("usaspending", "contracts"),
    "fedregister": ("fedregister", "rules/notices"),
    "congress": ("congress", "trades"),
    "sbir": ("sbir", "grants"),
    "norway": ("norway", "filings"),
    "catalyst": ("catalyst", "events"),
    "grants_gov": ("grants_gov", "NOFOs"),
    "propublica": ("propublica", "bills"),
    "lobbying": ("lobbying", "filings"),
}


@dataclass
class DigestResult:
    period_hours: int
    total_signals: int
    by_source: dict[str, int]
    top_signals: list[SignalRow]   # up to 20, sorted by amount_usd desc then published desc
    text: str                       # formatted plain-text digest
    html: str                       # formatted HTML digest


def _sort_key(row: SignalRow):
    """Sort by amount_usd desc (None last), then published desc."""
    amount = row.amount_usd if row.amount_usd is not None else -1.0
    return (-amount, "" if row.published is None else "".join(reversed(row.published)))


def _build_text(
    date_str: str,
    period_hours: int,
    total: int,
    by_source: dict[str, int],
    top_signals: list[SignalRow],
    all_signals: list[SignalRow],
) -> str:
    n_sources = len(by_source)
    sep_heavy = "═" * 51
    sep_light = "─" * 49

    # Summary header
    lines: list[str] = [
        sep_heavy,
        f" govspend-signals MORNING DIGEST — {date_str} ({period_hours}h)",
        sep_heavy,
        "",
        f"SUMMARY: {total} new signals across {n_sources} sources",
        "",
    ]

    for src in _ALL_SOURCES:
        label, unit = _SOURCE_LABELS[src]
        n = by_source.get(src, 0)
        lines.append(f"  {label:<12} {n} {unit}")

    lines += ["", "TOP SIGNALS BY SIZE:", sep_light]

    if top_signals:
        for row in top_signals:
            amount_str = f"${row.amount_usd:,.0f}" if row.amount_usd is not None else "N/A"
            ticker_company = " ".join(
                part for part in [row.ticker or "", row.company or ""] if part
            )
            lines += [
                f"  [{row.source.upper()}] {row.signal_type.upper()} | {row.published}",
                f"  {row.title}",
                f"  {amount_str} | {ticker_company}",
                f"  {row.url}",
            ]
    else:
        lines.append("  (no signals)")

    lines += [sep_light, "", f"ALL SIGNALS ({total}):"]

    # Group by source
    from itertools import groupby
    sorted_all = sorted(all_signals, key=lambda r: r.source)
    for source, group in groupby(sorted_all, key=lambda r: r.source):
        lines.append(f"\n  [{source.upper()}]")
        for row in group:
            lines.append(f"    • {row.title}")
            lines.append(f"      {row.url}")

    lines += ["", sep_heavy]
    return "\n".join(lines)


def _build_html(
    date_str: str,
    period_hours: int,
    total: int,
    by_source: dict[str, int],
    top_signals: list[SignalRow],
    all_signals: list[SignalRow],
) -> str:
    n_sources = len(by_source)

    # Summary rows
    source_rows_html = ""
    for src in _ALL_SOURCES:
        label, unit = _SOURCE_LABELS[src]
        n = by_source.get(src, 0)
        source_rows_html += f"    <tr><td>{label}</td><td>{n} {unit}</td></tr>\n"

    # Top signals rows
    top_rows_html = ""
    if top_signals:
        for row in top_signals:
            amount_str = f"${row.amount_usd:,.0f}" if row.amount_usd is not None else "N/A"
            ticker_company = " ".join(
                part for part in [row.ticker or "", row.company or ""] if part
            )
            top_rows_html += (
                f"    <tr>"
                f"<td>[{row.source.upper()}]</td>"
                f"<td>{row.signal_type.upper()}</td>"
                f"<td>{row.published}</td>"
                f"<td><a href=\"{row.url}\">{row.title}</a></td>"
                f"<td>{amount_str}</td>"
                f"<td>{ticker_company}</td>"
                f"</tr>\n"
            )
    else:
        top_rows_html = "    <tr><td colspan='6'>(no signals)</td></tr>\n"

    # All signals grouped
    from itertools import groupby
    sorted_all = sorted(all_signals, key=lambda r: r.source)
    all_sections_html = ""
    for source, group in groupby(sorted_all, key=lambda r: r.source):
        items = "".join(
            f"      <li><a href=\"{row.url}\">{row.title}</a></li>\n"
            for row in group
        )
        all_sections_html += f"  <h3>{source.upper()}</h3>\n  <ul>\n{items}  </ul>\n"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>govspend-signals Digest — {date_str}</title>
  <style>
    body {{ font-family: monospace; max-width: 900px; margin: 2rem auto; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
    th {{ background: #f0f0f0; }}
    h1 {{ border-bottom: 3px double #333; }}
    h2 {{ border-bottom: 1px solid #aaa; margin-top: 2rem; }}
  </style>
</head>
<body>
<h1>govspend-signals Morning Digest</h1>
<p><strong>Date:</strong> {date_str} &nbsp; <strong>Period:</strong> {period_hours}h &nbsp; <strong>Total signals:</strong> {total} across {n_sources} sources</p>

<h2>Summary by Source</h2>
<table>
  <tr><th>Source</th><th>Count</th></tr>
{source_rows_html}</table>

<h2>Top Signals by Size</h2>
<table>
  <tr><th>Source</th><th>Type</th><th>Published</th><th>Title</th><th>Amount</th><th>Ticker / Company</th></tr>
{top_rows_html}</table>

<h2>All Signals ({total})</h2>
{all_sections_html}
</body>
</html>"""


def generate(
    store: Storage,
    period_hours: int = 24,
) -> DigestResult:
    """Generate a digest of signals seen in the last `period_hours` hours."""
    since_ts = int(time.time()) - period_hours * 3600
    date_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    signals = store.get_signals_since(since_ts)
    by_source = store.signal_count_since(since_ts)
    total = len(signals)

    # Sort: amount_usd desc (None last), then published desc
    sorted_signals = sorted(signals, key=_sort_key)
    top_signals = sorted_signals[:20]

    text = _build_text(date_str, period_hours, total, by_source, top_signals, signals)
    html = _build_html(date_str, period_hours, total, by_source, top_signals, signals)

    return DigestResult(
        period_hours=period_hours,
        total_signals=total,
        by_source=by_source,
        top_signals=top_signals,
        text=text,
        html=html,
    )
