"""Static + computed catalyst calendar ingestor.

Emits upcoming (next 30 days) and recent (past lookback_days) calendar events
as Signals. Events include FOMC meeting dates, CMS annual rate notices, and
Federal Reserve Beige Book publication dates.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from govspend_signals.signal import Signal

# ---------------------------------------------------------------------------
# Hardcoded FOMC meeting dates for 2026
# ---------------------------------------------------------------------------
_FOMC_DATES_2026: list[str] = [
    "2026-01-28",
    "2026-03-18",
    "2026-05-06",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-16",
]

# ---------------------------------------------------------------------------
# CMS annual event schedule (month, day) for recurring notices
# ---------------------------------------------------------------------------
class _CmsEvent(NamedTuple):
    name: str
    month: int
    day: int
    description: str
    url: str


_CMS_EVENTS: list[_CmsEvent] = [
    _CmsEvent(
        name="CMS Medicare Advantage Final Rate Notice",
        month=4,
        day=7,
        description=(
            "CMS releases the annual Medicare Advantage and Part D final rate announcement, "
            "setting benchmark payment rates for the upcoming plan year."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Advantage/MedicareAdvantageApps",
    ),
    _CmsEvent(
        name="CMS IPPS Proposed Rule",
        month=4,
        day=10,
        description=(
            "CMS releases the proposed Inpatient Prospective Payment System rule, "
            "setting hospital inpatient payment rates and policies for the next fiscal year."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/AcuteInpatientPPS",
    ),
    _CmsEvent(
        name="CMS OPPS Proposed Rule",
        month=7,
        day=1,
        description=(
            "CMS releases the proposed Outpatient Prospective Payment System rule, "
            "setting hospital outpatient payment rates for the next calendar year."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/HospitalOutpatientPPS",
    ),
    _CmsEvent(
        name="CMS IPPS Final Rule",
        month=8,
        day=1,
        description=(
            "CMS finalises the Inpatient Prospective Payment System rule, "
            "locking in hospital inpatient payment rates for the new fiscal year."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/AcuteInpatientPPS",
    ),
    _CmsEvent(
        name="CMS Physician Fee Schedule Proposed Rule",
        month=7,
        day=8,
        description=(
            "CMS releases the proposed Physician Fee Schedule, covering physician "
            "payment rates, coding, and quality program changes."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/PhysicianFeeSched",
    ),
    _CmsEvent(
        name="CMS Physician Fee Schedule Final Rule",
        month=11,
        day=1,
        description=(
            "CMS finalises the Physician Fee Schedule, locking in physician payment "
            "rates for the next calendar year."
        ),
        url="https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/PhysicianFeeSched",
    ),
]

_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_BEIGE_BOOK_URL = "https://www.federalreserve.gov/monetarypolicy/beigebook.htm"


def _cms_dates_for_years(years: list[int]) -> list[tuple[str, _CmsEvent]]:
    """Return (ISO date, event) pairs for all CMS events in the given years."""
    results: list[tuple[str, _CmsEvent]] = []
    for year in years:
        for ev in _CMS_EVENTS:
            try:
                d = date(year, ev.month, ev.day)
                results.append((d.isoformat(), ev))
            except ValueError:
                pass  # e.g. Feb 30 — skip
    return results


def _beige_book_date(fomc_date: date) -> date:
    """Beige Book is published approximately 2 weeks before FOMC."""
    return fomc_date - timedelta(weeks=2)


def ingest(lookback_days: int) -> list[Signal]:
    """Build a catalyst calendar from hardcoded and computed event dates.

    Parameters
    ----------
    lookback_days:
        How far back (in days) to look for recent events.

    Returns
    -------
    list[Signal]
        Signals for events within the next 30 days OR within the past lookback_days.
    """
    today = date.today()
    lookback_cutoff = today - timedelta(days=lookback_days)
    upcoming_cutoff = today + timedelta(days=30)

    signals: list[Signal] = []

    def _maybe_add(event_date: date, name: str, url: str, category: str, description: str) -> None:
        is_upcoming = today <= event_date <= upcoming_cutoff
        is_recent = lookback_cutoff <= event_date < today
        if not (is_upcoming or is_recent):
            return

        signal_type = "upcoming_event" if is_upcoming else "recent_event"
        title = f"[CATALYST] {name} — {event_date.isoformat()}"

        signals.append(
            Signal(
                source="catalyst",
                signal_type=signal_type,
                title=title,
                url=url,
                published=event_date.isoformat(),
                ticker=None,
                company=None,
                amount_usd=None,
                data={
                    "event_name": name,
                    "category": category,
                    "description": description,
                },
            )
        )

    # --- FOMC meeting dates (hardcoded 2026) ---
    for iso in _FOMC_DATES_2026:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        _maybe_add(
            d,
            name="FOMC Meeting",
            url=_FOMC_URL,
            category="fomc",
            description="Federal Open Market Committee interest rate decision meeting.",
        )

        # Beige Book — 2 weeks before each FOMC
        bb = _beige_book_date(d)
        _maybe_add(
            bb,
            name="Federal Reserve Beige Book",
            url=_BEIGE_BOOK_URL,
            category="fed",
            description=(
                "Federal Reserve publishes the Beige Book (Summary of Commentary on "
                "Current Economic Conditions), released ~2 weeks before each FOMC meeting."
            ),
        )

    # --- CMS annual events (current year + next year) ---
    years = [today.year, today.year + 1]
    for iso_date, ev in _cms_dates_for_years(years):
        try:
            d = date.fromisoformat(iso_date)
        except ValueError:
            continue
        _maybe_add(
            d,
            name=ev.name,
            url=ev.url,
            category="cms",
            description=ev.description,
        )

    # Sort by published date
    signals.sort(key=lambda s: s.published)
    return signals
