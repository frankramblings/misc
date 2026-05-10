"""Federal Register ingestor — rule, proposed-rule, and notice signals."""
from __future__ import annotations

import re
import sys
import time
from datetime import date, timedelta

import requests

from govspend_signals.signal import Signal

_BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"
_MAX_PAGES = 3


def _agency_to_slug(name: str) -> str:
    """Convert a human-readable agency name to the FR API slug format.

    Examples
    --------
    "Centers for Medicare & Medicaid Services"
        → "centers-for-medicare-medicaid-services"
    "Environmental Protection Agency"
        → "environmental-protection-agency"
    """
    slug = name.lower()
    # Remove ampersands (and surrounding spaces)
    slug = re.sub(r"\s*&\s*", "-", slug)
    # Replace runs of whitespace / punctuation with hyphens
    slug = re.sub(r"[\s,./]+", "-", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


def ingest(
    agencies: list[str],
    doc_types: list[str],
    lookback_days: int,
    rate_per_second: float = 5.0,
) -> list[Signal]:
    """Fetch documents from the Federal Register API.

    Parameters
    ----------
    agencies:
        Agency names (full or slug form).  Will be slug-converted automatically.
    doc_types:
        Federal Register document type filters, e.g. ``["RULE", "PROPOSED_RULE", "NOTICE"]``.
    lookback_days:
        How many calendar days back to search.
    rate_per_second:
        API call rate limit.

    Returns
    -------
    list[Signal]
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    sleep_s = 1.0 / rate_per_second
    session = requests.Session()
    signals: list[Signal] = []
    seen_urls: set[str] = set()

    agency_slugs = [_agency_to_slug(a) for a in agencies]

    # Build the initial params — requests encodes list params as repeated keys
    base_params: list[tuple[str, str]] = []
    for slug in agency_slugs:
        base_params.append(("conditions[agencies][]", slug))
    for dt in doc_types:
        base_params.append(("conditions[type][]", dt))
    base_params.append(("conditions[publication_date][gte]", cutoff))
    for f in ["title", "document_number", "publication_date", "agencies", "html_url", "abstract", "type"]:
        base_params.append(("fields[]", f))
    base_params.append(("per_page", "100"))

    next_url: str | None = _BASE_URL

    for _page in range(_MAX_PAGES):
        if next_url is None:
            break

        try:
            if _page == 0:
                resp = session.get(next_url, params=base_params, timeout=30)
            else:
                resp = session.get(next_url, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(f"[fedregister] HTTP error: {exc}", file=sys.stderr)
            break
        except requests.RequestException as exc:
            print(f"[fedregister] Request error: {exc}", file=sys.stderr)
            break

        try:
            payload = resp.json()
        except ValueError as exc:
            print(f"[fedregister] JSON parse error: {exc}", file=sys.stderr)
            break

        for doc in payload.get("results", []):
            html_url = doc.get("html_url") or ""
            if not html_url or html_url in seen_urls:
                continue
            seen_urls.add(html_url)

            doc_type = (doc.get("type") or "").upper()
            signal_type = doc_type.lower()  # "rule", "proposed_rule", "notice"

            raw_title = (doc.get("title") or "").strip()

            # Best agency name: take the first listed agency display name
            doc_agencies = doc.get("agencies") or []
            if doc_agencies and isinstance(doc_agencies[0], dict):
                agency_display = doc_agencies[0].get("name") or agencies[0] if agencies else ""
            else:
                agency_display = agencies[0] if agencies else ""

            title = f"[{doc_type}] {raw_title} ({agency_display})"

            pub_date = doc.get("publication_date") or date.today().isoformat()
            try:
                pub = date.fromisoformat(str(pub_date)[:10]).isoformat()
            except ValueError:
                pub = date.today().isoformat()

            signals.append(
                Signal(
                    source="fedregister",
                    signal_type=signal_type,
                    title=title,
                    url=html_url,
                    published=pub,
                    ticker=None,
                    company=None,
                    amount_usd=None,
                    data={
                        "document_number": doc.get("document_number"),
                        "abstract": doc.get("abstract"),
                        "type": doc_type,
                        "agencies": [
                            a.get("name") if isinstance(a, dict) else a
                            for a in doc_agencies
                        ],
                    },
                )
            )

        next_url = payload.get("next_page_url") or None
        time.sleep(sleep_s)

    return signals
