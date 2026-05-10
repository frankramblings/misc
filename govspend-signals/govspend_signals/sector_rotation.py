"""Sector money-flow velocity tracker.

Computes how many signals each investment sector produced in two windows
(current and prior) and ranks by signal volume + acceleration.

Usage:
    govspend sector-rotation [--hours 24] [--compare-hours 168]
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .storage import Storage


@dataclass
class SectorSnapshot:
    sector: str
    current_count: int        # signals in the current window
    prior_count: int          # signals in the prior comparison window
    pct_change: float | None  # None when prior_count == 0


_SECTOR_EMOJIS: dict[str, str] = {
    "healthcare": "🏥",
    "energy_utilities": "⚡",
    "infrastructure": "🏗️",
    "environmental": "🌿",
    "gov_software": "💻",
    "appropriations": "💵",
    "contracts": "📋",
    "regulation": "📜",
    "congressional_trades": "🏛️",
    "sbir_grants": "🔬",
    "sovereign_wealth": "🇳🇴",
    "catalyst": "📅",
    "edgar_filings": "📄",
    "lobbying": "💼",
    "other": "•",
}


def compute_rotation(
    store: Storage,
    window_hours: int = 24,
    compare_hours: int = 168,
) -> list[SectorSnapshot]:
    """Compute sector signal velocity for the current vs prior window.

    Parameters
    ----------
    store:
        Open Storage instance.
    window_hours:
        Current period to measure (default: last 24h).
    compare_hours:
        Prior period to compare against (default: last 7 days).

    Returns
    -------
    list[SectorSnapshot]
        Sorted by current_count descending.
    """
    now = int(time.time())
    current_since = now - window_hours * 3600
    prior_since = now - compare_hours * 3600

    current = store.get_signal_counts_by_sector(current_since)
    prior = store.get_signal_counts_by_sector(prior_since)

    all_sectors = set(current) | set(prior)
    snapshots: list[SectorSnapshot] = []

    for sector in all_sectors:
        cur = current.get(sector, 0)
        pri = prior.get(sector, 0)
        pct: float | None = None
        if pri > 0:
            pct = (cur - pri) / pri * 100.0
        snapshots.append(SectorSnapshot(
            sector=sector,
            current_count=cur,
            prior_count=pri,
            pct_change=pct,
        ))

    return sorted(snapshots, key=lambda s: s.current_count, reverse=True)


def format_rotation_table(
    snapshots: list[SectorSnapshot],
    window_hours: int,
    compare_hours: int,
) -> str:
    if not snapshots:
        return (
            f"No signals in the last {window_hours}h. "
            "Run `govspend ingest` first."
        )

    sep = "─" * 68
    lines = [
        sep,
        f" Sector Rotation  —  last {window_hours}h vs last {compare_hours}h",
        sep,
        f"  {'Sector':<22}  {'Now':>5}  {'Prior':>5}  {'Change':>8}  Bar",
        f"  {'──────':<22}  {'───':>5}  {'─────':>5}  {'──────':>8}  ───",
    ]

    max_count = max((s.current_count for s in snapshots), default=1) or 1

    for snap in snapshots:
        emoji = _SECTOR_EMOJIS.get(snap.sector, "•")
        sector_str = f"{emoji} {snap.sector}"[:22]
        if snap.pct_change is None:
            change_str = "   new"
        else:
            sign = "+" if snap.pct_change >= 0 else ""
            change_str = f"{sign}{snap.pct_change:.0f}%"
        bar_len = max(1, int(snap.current_count / max_count * 20)) if snap.current_count else 0
        bar = "█" * bar_len + "·" * (20 - bar_len)
        lines.append(
            f"  {sector_str:<22}  {snap.current_count:>5}  "
            f"{snap.prior_count:>5}  {change_str:>8}  {bar}"
        )

    lines.append(sep)
    return "\n".join(lines)
