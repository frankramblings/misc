from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable

import requests

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


@dataclass(frozen=True)
class Filing:
    cik: int
    ticker: str
    company: str
    accession: str
    form: str
    filing_date: str
    primary_doc: str
    primary_doc_description: str

    @property
    def url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        doc = self.primary_doc or f"{self.accession}-index.htm"
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{self.cik}/{acc_nodash}/{doc}"
        )

    @property
    def index_url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{self.cik}/{acc_nodash}/{self.accession}-index.htm"
        )


class _RateLimiter:
    """Token-bucket-ish gate: at most `rate_per_second` calls per second, thread-safe."""

    def __init__(self, rate_per_second: float):
        self._min_interval = 1.0 / rate_per_second
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class EdgarClient:
    """Minimal SEC EDGAR client. Honors SEC's 10 req/sec limit and User-Agent rule."""

    def __init__(
        self,
        user_agent: str,
        rate_per_second: float = 8.0,
        timeout: float = 15.0,
    ):
        if not user_agent or "@" not in user_agent:
            raise ValueError("EDGAR requires a User-Agent containing a contact email.")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": None,  # let requests fill per-URL
            }
        )
        self._limiter = _RateLimiter(rate_per_second)
        self._timeout = timeout

    def _get_json(self, url: str) -> dict:
        for attempt in range(4):
            self._limiter.wait()
            resp = self._session.get(url, timeout=self._timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"EDGAR request failed after retries: {url}")

    def fetch_ticker_map(self) -> dict[str, tuple[int, str]]:
        """Return {TICKER: (cik_int, company_name)}."""
        data = self._get_json(SEC_TICKERS_URL)
        out: dict[str, tuple[int, str]] = {}
        for entry in data.values():
            ticker = str(entry["ticker"]).upper()
            out[ticker] = (int(entry["cik_str"]), str(entry["title"]))
        return out

    def fetch_recent_filings(
        self,
        cik: int,
        ticker: str,
        company: str,
        scan_limit: int = 100,
    ) -> list[Filing]:
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        data = self._get_json(url)
        recent = data.get("filings", {}).get("recent", {})
        accs = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descs = recent.get("primaryDocDescription", [])

        out: list[Filing] = []
        for i in range(min(scan_limit, len(accs))):
            out.append(
                Filing(
                    cik=cik,
                    ticker=ticker,
                    company=company,
                    accession=accs[i],
                    form=forms[i] if i < len(forms) else "",
                    filing_date=dates[i] if i < len(dates) else "",
                    primary_doc=docs[i] if i < len(docs) else "",
                    primary_doc_description=descs[i] if i < len(descs) else "",
                )
            )
        return out


def filter_filings(
    filings: Iterable[Filing],
    forms: set[str],
    min_date: str | None = None,
) -> list[Filing]:
    out: list[Filing] = []
    for f in filings:
        if f.form not in forms:
            continue
        if min_date is not None and f.filing_date < min_date:
            continue
        out.append(f)
    return out
