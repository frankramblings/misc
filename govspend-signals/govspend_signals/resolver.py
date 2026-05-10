"""Subsidiary → parent company → CIK → ticker resolver.

The "moat" of this system. A government contract is awarded to
"Centene Federal Services LLC" — that needs to resolve to CNC.
A DARPA grant goes to "Google LLC" — that resolves to GOOGL.

Resolution pipeline (in order of preference):
  1. Exact match in SUBSIDIARY_MAP (curated, always wins)
  2. Normalized name match in SUBSIDIARY_MAP (uppercase, strip punctuation)
  3. Token-based fuzzy match against watchlist company names (rapidfuzz)
  4. EDGAR company search API (fallback for unrecognized names)

Usage:
    from govspend_signals.resolver import Resolver
    r = Resolver()
    ticker = r.resolve("Centene Federal Services LLC")  # → "CNC"
    ticker = r.resolve("UnitedHealth Group Inc")        # → "UNH"
    ticker = r.resolve("Random Co")                     # → None
"""
from __future__ import annotations

import re
import sys
import time
from functools import lru_cache
from typing import Optional

import requests

# ── Curated subsidiary → parent ticker map ────────────────────────────────────
# Keys are uppercase, stripped of punctuation. Add entries as you discover them.
# This is the "moat" — build it up over time.

SUBSIDIARY_MAP: dict[str, str] = {
    # ── Healthcare managed care ───────────────────────────────────────────────
    # UNH / UnitedHealth Group
    "UNITEDHEALTH GROUP": "UNH",
    "UNITEDHEALTH GROUP INC": "UNH",
    "UNITEDHEALTHCARE": "UNH",
    "UNITED HEALTHCARE": "UNH",
    "UNITED HEALTHCARE SERVICES": "UNH",
    "OPTUM": "UNH",
    "OPTUMRX": "UNH",
    "OPTUM HEALTH": "UNH",
    "OPTUM INSIGHT": "UNH",
    "OPTUMCARE": "UNH",
    "AMERIGROUP": "UNH",
    "PEACH STATE HEALTH MANAGEMENT": "UNH",

    # ELV / Elevance Health (Anthem)
    "ELEVANCE HEALTH": "ELV",
    "ELEVANCE HEALTH INC": "ELV",
    "ANTHEM INC": "ELV",
    "ANTHEM": "ELV",
    "AMERIHEALTH CARITAS": "ELV",
    "WELLPOINT": "ELV",
    "CAREMORE HEALTH": "ELV",
    "AMERIHEALTH": "ELV",

    # HUM / Humana
    "HUMANA": "HUM",
    "HUMANA INC": "HUM",
    "HUMANA GOVERNMENT BUSINESS": "HUM",
    "MILITARY HEALTHCARE SYSTEM": "HUM",
    "TRICARE": "HUM",
    "HUMANA MILITARY": "HUM",

    # CNC / Centene
    "CENTENE": "CNC",
    "CENTENE CORPORATION": "CNC",
    "CENTENE MANAGEMENT COMPANY": "CNC",
    "CENTENE FEDERAL SERVICES": "CNC",
    "WELLCARE": "CNC",
    "WELLCARE HEALTH PLANS": "CNC",
    "HEALTH NET": "CNC",
    "HEALTH NET INC": "CNC",
    "MERIDIAN HEALTH PLAN": "CNC",
    "AMBETTER": "CNC",
    "SUPERIOR HEALTHPLAN": "CNC",
    "SUNSHINE HEALTH": "CNC",
    "BUCKEYE COMMUNITY HEALTH PLAN": "CNC",
    "COORDINATED CARE": "CNC",

    # MOH / Molina Healthcare
    "MOLINA HEALTHCARE": "MOH",
    "MOLINA HEALTHCARE INC": "MOH",
    "MOLINA MEDICAID SOLUTIONS": "MOH",

    # CVS Health
    "CVS HEALTH": "CVS",
    "CVS HEALTH CORPORATION": "CVS",
    "CVS CAREMARK": "CVS",
    "CAREMARK": "CVS",
    "AETNA": "CVS",
    "AETNA INC": "CVS",
    "MINUTE CLINIC": "CVS",
    "SIGNIFY HEALTH": "CVS",

    # CI / Cigna
    "CIGNA": "CI",
    "CIGNA CORPORATION": "CI",
    "CIGNA GOVERNMENT SERVICES": "CI",
    "EVERNORTH": "CI",
    "EXPRESS SCRIPTS": "CI",

    # MCK / McKesson
    "MCKESSON": "MCK",
    "MCKESSON CORPORATION": "MCK",

    # ABC / AmerisourceBergen / Cencora
    "AMERISOURCEBERGEN": "ABC",
    "AMERISOURCEBERGEN CORPORATION": "ABC",
    "CENCORA": "ABC",
    "CENCORA INC": "ABC",

    # CAH / Cardinal Health
    "CARDINAL HEALTH": "CAH",
    "CARDINAL HEALTH INC": "CAH",

    # LH / LabCorp
    "LABCORP": "LH",
    "LABORATORY CORPORATION OF AMERICA": "LH",
    "LABORATORY CORP": "LH",

    # DGX / Quest Diagnostics
    "QUEST DIAGNOSTICS": "DGX",
    "QUEST DIAGNOSTICS INC": "DGX",

    # ── Utilities ─────────────────────────────────────────────────────────────
    "NEXTERA ENERGY": "NEE",
    "NEXTERA ENERGY INC": "NEE",
    "FLORIDA POWER AND LIGHT": "NEE",
    "FPL GROUP": "NEE",

    "DUKE ENERGY": "DUK",
    "DUKE ENERGY CORPORATION": "DUK",
    "DUKE ENERGY CAROLINAS": "DUK",
    "DUKE ENERGY INDIANA": "DUK",
    "DUKE ENERGY OHIO": "DUK",

    "SOUTHERN COMPANY": "SO",
    "GEORGIA POWER": "SO",
    "ALABAMA POWER": "SO",
    "MISSISSIPPI POWER": "SO",
    "SOUTHERN POWER": "SO",

    "AMERICAN ELECTRIC POWER": "AEP",
    "AEP TEXAS": "AEP",
    "APPALACHIAN POWER": "AEP",
    "INDIANA MICHIGAN POWER": "AEP",

    "DOMINION ENERGY": "D",
    "DOMINION ENERGY INC": "D",
    "VIRGINIA ELECTRIC AND POWER": "D",
    "DOMINION VIRGINIA POWER": "D",

    "XCEL ENERGY": "XEL",
    "XCEL ENERGY INC": "XEL",
    "PUBLIC SERVICE COMPANY OF COLORADO": "XEL",
    "NORTHERN STATES POWER": "XEL",

    "EXELON": "EXC",
    "EXELON CORPORATION": "EXC",
    "COMMONWEALTH EDISON": "EXC",
    "PECO ENERGY": "EXC",
    "BGE": "EXC",
    "PEPCO": "EXC",
    "DELMARVA POWER": "EXC",
    "ATLANTIC CITY ELECTRIC": "EXC",

    "PGE": "PCG",
    "PACIFIC GAS AND ELECTRIC": "PCG",
    "PACIFIC GAS ELECTRIC": "PCG",
    "PGE CORPORATION": "PCG",

    "AMERICAN WATER WORKS": "AWK",
    "AMERICAN WATER": "AWK",

    "CMS ENERGY": "CMS",
    "CONSUMERS ENERGY": "CMS",

    # ── Infrastructure / Engineering ──────────────────────────────────────────
    "QUANTA SERVICES": "PWR",
    "QUANTA SERVICES INC": "PWR",

    "MASTEC": "MTZ",
    "MASTEC INC": "MTZ",

    "JACOBS SOLUTIONS": "J",
    "JACOBS ENGINEERING": "J",
    "JACOBS ENGINEERING GROUP": "J",

    "AECOM": "ACM",
    "AECOM TECHNICAL SERVICES": "ACM",

    "FLUOR": "FLR",
    "FLUOR CORPORATION": "FLR",
    "FLUOR ENTERPRISES": "FLR",

    "UNITED RENTALS": "URI",
    "UNITED RENTALS INC": "URI",

    "STERLING INFRASTRUCTURE": "STRL",
    "STERLING CONSTRUCTION": "STRL",

    "DYCOM INDUSTRIES": "DY",
    "DYCOM INDUSTRIES INC": "DY",

    "GRANITE CONSTRUCTION": "GVA",
    "GRANITE CONSTRUCTION INC": "GVA",

    # ── Government IT / Services ──────────────────────────────────────────────
    "MICROSOFT": "MSFT",
    "MICROSOFT CORPORATION": "MSFT",
    "MICROSOFT FEDERAL": "MSFT",
    "NUANCE COMMUNICATIONS": "MSFT",

    "ORACLE": "ORCL",
    "ORACLE AMERICA": "ORCL",
    "ORACLE CORPORATION": "ORCL",
    "CERNER": "ORCL",
    "CERNER CORPORATION": "ORCL",

    "PALANTIR": "PLTR",
    "PALANTIR TECHNOLOGIES": "PLTR",
    "PALANTIR TECHNOLOGIES INC": "PLTR",

    "SALESFORCE": "CRM",
    "SALESFORCE INC": "CRM",
    "SALESFORCE COM": "CRM",
    "TABLEAU SOFTWARE": "CRM",
    "SLACK TECHNOLOGIES": "CRM",

    "SCIENCE APPLICATIONS INTERNATIONAL": "SAIC",
    "SAIC": "SAIC",

    "CACI INTERNATIONAL": "CACI",
    "CACI INC": "CACI",
    "CACI": "CACI",

    "LEIDOS": "LDOS",
    "LEIDOS HOLDINGS": "LDOS",
    "LEIDOS INC": "LDOS",

    "BOOZ ALLEN HAMILTON": "BAH",
    "BOOZ ALLEN": "BAH",
    "BOOZ ALLEN HAMILTON HOLDING": "BAH",

    "ICF INTERNATIONAL": "ICFI",
    "ICF INC": "ICFI",

    "MANTECH INTERNATIONAL": "MANT",
    "MANTECH": "MANT",

    # ── Environmental ─────────────────────────────────────────────────────────
    "CLEAN HARBORS": "CLH",
    "CLEAN HARBORS INC": "CLH",
    "CLEAN HARBORS ENVIRONMENTAL SERVICES": "CLH",

    "REPUBLIC SERVICES": "RSG",
    "REPUBLIC SERVICES INC": "RSG",

    "WASTE MANAGEMENT": "WM",
    "WASTE MANAGEMENT INC": "WM",
    "WM CORPORATE SERVICES": "WM",

    "CASELLA WASTE SYSTEMS": "CWST",
    "CASELLA WASTE": "CWST",

    "NV5 GLOBAL": "NVEE",
    "NV5": "NVEE",
    "NV5 INC": "NVEE",

    # ── Big tech with significant gov revenue ─────────────────────────────────
    "AMAZON": "AMZN",
    "AMAZON WEB SERVICES": "AMZN",
    "AWS": "AMZN",
    "AMAZON COM SERVICES": "AMZN",

    "GOOGLE": "GOOGL",
    "GOOGLE LLC": "GOOGL",
    "ALPHABET": "GOOGL",

    "IBM": "IBM",
    "IBM CORPORATION": "IBM",

    "ACCENTURE": "ACN",
    "ACCENTURE FEDERAL SERVICES": "ACN",
    "ACCENTURE LLP": "ACN",

    "DELOITTE": None,  # private — no ticker
    "MCKINSEY": None,  # private — no ticker
    "BAIN": None,

    # ── Additional small/mid-cap gov contractors ──────────────────────────────
    "MAXIMUS": "MMS",
    "MAXIMUS INC": "MMS",
    "MAXIMUS FEDERAL SERVICES": "MMS",

    "PERATON": None,  # private (Veritas Capital)
    "PERSPECTA": None,  # merged into Peraton (private)

    "GENERAL DYNAMICS": "GD",
    "GENERAL DYNAMICS INFORMATION TECHNOLOGY": "GD",
    "GDIT": "GD",
}


def _normalize(name: str) -> str:
    """Uppercase and strip punctuation for map lookups."""
    name = name.upper()
    # Remove common legal suffixes for better matching
    for suffix in [" LLC", " INC", " CORP", " CORPORATION", " LLP",
                   " LP", " LTD", " CO", " COMPANY", " GROUP",
                   " HOLDINGS", " HOLDING", " SERVICES", " SOLUTIONS"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    # Collapse whitespace and remove non-alpha/space
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _curated_lookup(name: str) -> str | None:
    """Check SUBSIDIARY_MAP with exact and normalized lookups."""
    upper = name.upper().strip()
    if upper in SUBSIDIARY_MAP:
        return SUBSIDIARY_MAP[upper]
    norm = _normalize(upper)
    if norm in SUBSIDIARY_MAP:
        return SUBSIDIARY_MAP[norm]
    # Also try stripped version against map keys
    for key, ticker in SUBSIDIARY_MAP.items():
        if _normalize(key) == norm:
            return ticker
    return None


def _fuzzy_lookup(name: str, threshold: float = 75.0) -> str | None:
    """Fuzzy-match against known company names using rapidfuzz (if installed)."""
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        return None

    candidates = list(SUBSIDIARY_MAP.keys())
    result = process.extractOne(
        name.upper(),
        candidates,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold,
    )
    if result:
        matched_key, score, _ = result
        return SUBSIDIARY_MAP[matched_key]
    return None


_EDGAR_COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{query}%22&dateRange=custom&startdt=2020-01-01&forms=10-K&hits.hits.total.value=true&hits.hits._source.period_of_report=true"
_EDGAR_COMPANY_SEARCH_V2 = "https://efts.sec.gov/LATEST/search-index?q={query}&forms=10-K&hits.hits._source.entity_name=true"
_EDGAR_FULL_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{query}%22&forms=10-K"
_SEC_COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{query}%22&forms=10-K&hits.hits._source.entity_name=true&hits.hits._source.file_num=true"

# Simpler endpoint: EDGAR company search (used by the EDGAR full-text search)
_EDGAR_COMPANY_TICKERS_SEARCH = (
    "https://efts.sec.gov/LATEST/search-index?q=%22{name}%22"
    "&forms=10-K&dateRange=custom&startdt=2018-01-01"
)


class Resolver:
    """Resolve a free-form company name to a watchlist ticker.

    Resolution order:
    1. Curated SUBSIDIARY_MAP (exact + normalized)
    2. rapidfuzz fuzzy match against SUBSIDIARY_MAP keys
    3. EDGAR company search API (rate-limited)
    4. Returns None if nothing matches
    """

    def __init__(
        self,
        user_agent: str = "govspend-signals resolver@govspend.local",
        rate_per_second: float = 3.0,
        fuzzy_threshold: float = 80.0,
        use_edgar_fallback: bool = True,
    ):
        self._user_agent = user_agent
        self._rate_per_second = rate_per_second
        self._fuzzy_threshold = fuzzy_threshold
        self._use_edgar_fallback = use_edgar_fallback
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._last_call: float = 0.0
        self._edgar_cache: dict[str, str | None] = {}

    def _rate_limit(self) -> None:
        gap = 1.0 / self._rate_per_second
        now = time.monotonic()
        wait = gap - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _edgar_lookup(self, name: str) -> str | None:
        """Search EDGAR for company name → try to match against known tickers.

        This is a best-effort fallback; results are cached per session.
        """
        cache_key = _normalize(name)
        if cache_key in self._edgar_cache:
            return self._edgar_cache[cache_key]

        try:
            self._rate_limit()
            url = f"https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(name)}%22&forms=10-K&dateRange=custom&startdt=2020-01-01"
            resp = self._session.get(url, timeout=15)
            if resp.status_code != 200:
                self._edgar_cache[cache_key] = None
                return None

            hits = resp.json().get("hits", {}).get("hits", [])
            for hit in hits[:5]:
                entity = hit.get("_source", {}).get("entity_name", "")
                # Try to match the entity name against our map
                result = _curated_lookup(entity) or _fuzzy_lookup(
                    entity, self._fuzzy_threshold
                )
                if result:
                    self._edgar_cache[cache_key] = result
                    return result

        except Exception:  # noqa: BLE001
            pass

        self._edgar_cache[cache_key] = None
        return None

    def resolve(self, name: str | None) -> str | None:
        """Resolve a company name to a ticker. Returns None if unresolvable."""
        if not name:
            return None
        name = name.strip()

        # 1. Curated map
        result = _curated_lookup(name)
        if result is not None:
            return result  # may be the string ticker OR None (private company)

        # 2. Fuzzy
        result = _fuzzy_lookup(name, self._fuzzy_threshold)
        if result is not None:
            return result

        # 3. EDGAR fallback
        if self._use_edgar_fallback:
            result = self._edgar_lookup(name)
            if result is not None:
                return result

        return None

    def resolve_batch(self, names: list[str]) -> dict[str, str | None]:
        """Resolve multiple names. Returns {name: ticker_or_none}."""
        return {name: self.resolve(name) for name in names}

    @staticmethod
    def add_subsidiary(subsidiary: str, ticker: str | None) -> None:
        """Programmatically extend SUBSIDIARY_MAP at runtime."""
        SUBSIDIARY_MAP[subsidiary.upper().strip()] = ticker

    @staticmethod
    def curated_tickers() -> set[str]:
        """All unique non-None tickers in the curated map."""
        return {t for t in SUBSIDIARY_MAP.values() if t}
