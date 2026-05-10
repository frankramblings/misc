"""Ethical screen basket builder.

Filters the configured watchlist to non-defense, non-fossil-fuel names.
Weights survivors by their trailing government contract dollar value from
the signals database. Outputs a proposed allocation table.

Usage:
    govspend basket [--equal-weight] [--hours 720] [--min-weight 1.0]
"""
from __future__ import annotations

from dataclasses import dataclass

# Tickers excluded from the basket (defense contractors + fossil fuels)
EXCLUDED_TICKERS: set[str] = {
    # ── Defense contractors ───────────────────────────────────────────────────
    "LMT",   # Lockheed Martin
    "RTX",   # Raytheon Technologies
    "NOC",   # Northrop Grumman
    "GD",    # General Dynamics
    "BA",    # Boeing (primary defense)
    "HII",   # Huntington Ingalls Industries
    "LDOS",  # Leidos (primarily defense IT)
    "SAIC",  # SAIC (primarily defense IT)
    "CACI",  # CACI International (defense)
    "MANT",  # ManTech International (defense)
    "DRS",   # Leonardo DRS
    "KTOS",  # Kratos Defense
    "AVAV",  # AeroVironment
    "HEICO", # HEICO (aerospace parts)
    "TDG",   # TransDigm (aerospace parts)
    "L3",    # L3Harris Technologies
    "LHX",   # L3Harris
    "SPR",   # Spirit AeroSystems

    # ── Fossil fuels ──────────────────────────────────────────────────────────
    "XOM",   # ExxonMobil
    "CVX",   # Chevron
    "COP",   # ConocoPhillips
    "SLB",   # SLB (Schlumberger)
    "HAL",   # Halliburton
    "BKR",   # Baker Hughes
    "VLO",   # Valero Energy
    "MPC",   # Marathon Petroleum
    "PSX",   # Phillips 66
    "OXY",   # Occidental Petroleum
    "PXD",   # Pioneer Natural Resources
    "DVN",   # Devon Energy
    "FANG",  # Diamondback Energy
    "EOG",   # EOG Resources
    "HES",   # Hess Corporation
    "MRO",   # Marathon Oil
    "APA",   # APA Corporation
    "CTRA",  # Coterra Energy
    "CNX",   # CNX Resources
    "AR",    # Antero Resources
    "RRC",   # Range Resources
    "SM",    # SM Energy
}

# Ticker → investment sector label
_TICKER_SECTORS: dict[str, str] = {
    # Healthcare / managed care
    "UNH": "healthcare", "ELV": "healthcare", "HUM": "healthcare",
    "CNC": "healthcare", "MOH": "healthcare", "CVS": "healthcare",
    "CI": "healthcare",  "MCK": "healthcare", "ABC": "healthcare",
    "CAH": "healthcare", "LH": "healthcare",  "DGX": "healthcare",
    "HCA": "healthcare", "UHS": "healthcare",  "THC": "healthcare",
    "ACCD": "healthcare",
    # Regulated utilities
    "NEE": "utilities",  "DUK": "utilities",  "SO": "utilities",
    "AEP": "utilities",  "D": "utilities",    "XEL": "utilities",
    "EXC": "utilities",  "PCG": "utilities",  "AWK": "utilities",
    "CMS": "utilities",  "WEC": "utilities",  "ES": "utilities",
    "ETR": "utilities",  "PPL": "utilities",  "NI": "utilities",
    "EVRG": "utilities", "IDA": "utilities",  "PNW": "utilities",
    # Civil infrastructure
    "PWR": "infrastructure", "MTZ": "infrastructure", "J": "infrastructure",
    "ACM": "infrastructure", "FLR": "infrastructure", "URI": "infrastructure",
    "STRL": "infrastructure","ROAD": "infrastructure","DY": "infrastructure",
    "GVA": "infrastructure","PRIM": "infrastructure","TTEK": "infrastructure",
    "NV5": "infrastructure",
    # Government IT (non-defense)
    "MSFT": "gov_software", "ORCL": "gov_software", "PLTR": "gov_software",
    "CRM": "gov_software",  "BAH": "gov_software",  "ICF": "gov_software",
    "ACN": "gov_software",  "CSCO": "gov_software", "MMS": "gov_software",
    "VRNS": "gov_software", "S": "gov_software",    "PANW": "gov_software",
    # Environmental services
    "CLH": "environmental", "RSG": "environmental", "WM": "environmental",
    "CWST": "environmental","NVEE": "environmental", "ERII": "environmental",
}


@dataclass
class BasketPosition:
    ticker: str
    sector: str
    weight_pct: float
    contract_usd: float  # trailing contract value from signals store


def build_basket(
    watchlist: list[str],
    contract_amounts: dict[str, float],
    contract_weighted: bool = True,
    min_weight_pct: float = 1.0,
) -> list[BasketPosition]:
    """Build an ethical-screen basket from the watchlist.

    Parameters
    ----------
    watchlist:
        All tickers from the config.
    contract_amounts:
        {ticker: total_contract_usd} from trailing signals. May be empty.
    contract_weighted:
        If True, weight by contract_usd. If False, equal-weight.
    min_weight_pct:
        Drop positions below this weight after normalization.

    Returns
    -------
    list[BasketPosition]
        Sorted by weight_pct descending.
    """
    eligible = [t for t in watchlist if t not in EXCLUDED_TICKERS]
    if not eligible:
        return []

    # Raw weights
    if contract_weighted and any(contract_amounts.get(t, 0) > 0 for t in eligible):
        raw_weights = {t: max(contract_amounts.get(t, 0), 1.0) for t in eligible}
    else:
        raw_weights = {t: 1.0 for t in eligible}

    total = sum(raw_weights.values())
    positions: list[BasketPosition] = []
    for ticker in eligible:
        weight = raw_weights[ticker] / total * 100.0
        if weight < min_weight_pct:
            continue
        positions.append(BasketPosition(
            ticker=ticker,
            sector=_TICKER_SECTORS.get(ticker, "other"),
            weight_pct=weight,
            contract_usd=contract_amounts.get(ticker, 0.0),
        ))

    # Re-normalize after dropping sub-minimum positions
    renorm_total = sum(p.weight_pct for p in positions)
    if renorm_total and abs(renorm_total - 100.0) > 0.01:
        factor = 100.0 / renorm_total
        for p in positions:
            p.weight_pct = round(p.weight_pct * factor, 4)

    return sorted(positions, key=lambda p: p.weight_pct, reverse=True)


def _fmt_usd(amount: float) -> str:
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return "$0"


def format_basket(positions: list[BasketPosition]) -> str:
    if not positions:
        return (
            "No eligible positions after applying ethical screen.\n"
            "Check that your watchlist contains non-defense, non-fossil tickers.\n"
            f"Excluded: {len(EXCLUDED_TICKERS)} defense contractor + fossil fuel tickers."
        )

    sep = "─" * 64
    lines = [
        sep,
        " govspend BASKET — Ethical-Screen Government-Spending Portfolio",
        " (excludes defense contractors + fossil fuels)",
        sep,
        f"  {'Ticker':<7}  {'Sector':<16}  {'Weight':>7}  {'Gov Contracts':>14}",
        f"  {'──────':<7}  {'──────':<16}  {'──────':>7}  {'─────────────':>14}",
    ]

    for pos in positions:
        bar = "█" * max(1, int(pos.weight_pct / 2))
        contract_str = _fmt_usd(pos.contract_usd) if pos.contract_usd else "—"
        lines.append(
            f"  {pos.ticker:<7}  {pos.sector:<16}  {pos.weight_pct:>6.1f}%  "
            f"{contract_str:>14}  {bar}"
        )

    total_weight = sum(p.weight_pct for p in positions)
    total_contracts = sum(p.contract_usd for p in positions)
    lines += [
        sep,
        f"  {'TOTAL':<7}  {'':<16}  {total_weight:>6.1f}%  {_fmt_usd(total_contracts):>14}",
        sep,
        f"  {len(positions)} positions  |  Excluded: {len(EXCLUDED_TICKERS)} defense/fossil tickers",
        sep,
    ]
    return "\n".join(lines)
