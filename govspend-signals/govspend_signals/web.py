"""FastAPI web dashboard for govspend-signals.

Start with:
    govspend web                       # http://localhost:8000
    govspend web --host 0.0.0.0        # expose on network

Requires:
    pip install "govspend-signals[web]"
"""
from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .basket import build_basket, EXCLUDED_TICKERS
from .config import Config
from .options_strategy import generate_plays
from .sector_rotation import compute_rotation
from .storage import Storage

_STATIC_DIR = Path(__file__).parent / "web_static"
_SESSION_MAX_AGE = 86400 * 30  # 30 days


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _check_session(request: Request) -> bool:
    signer: URLSafeTimedSerializer = request.app.state.signer
    token = request.cookies.get("session", "")
    if not token:
        return False
    try:
        signer.loads(token, max_age=_SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _set_session(response: Response, signer: URLSafeTimedSerializer) -> None:
    token = signer.dumps("authenticated")
    response.set_cookie(
        "session", token, httponly=True, samesite="lax", max_age=_SESSION_MAX_AGE
    )


def _require_auth(request: Request) -> None:
    if not _check_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


def _hours_to_since_ts(hours: int) -> int:
    return int(time.time()) - hours * 3600


def _days_until(date_str: str, today_dt: datetime.date) -> int | None:
    try:
        return (datetime.date.fromisoformat(date_str) - today_dt).days
    except (ValueError, TypeError):
        return None


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    store: Storage,
    config: Config,
    origin: str = "http://localhost:8000",
    secret: str | None = None,
) -> FastAPI:
    """Create and return the FastAPI application."""
    app = FastAPI(title="govspend-signals", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.config = config
    app.state.origin = origin
    app.state.rp_id = urlparse(origin).hostname or "localhost"
    app.state.signer = URLSafeTimedSerializer(
        secret or os.environ.get("DASHBOARD_SECRET") or store.get_or_create_secret()
    )
    app.state.pending_challenge = None  # in-memory challenge for WebAuthn flow

    # ── Data endpoints ────────────────────────────────────────────────────────

    @app.get("/api/signals")
    async def api_signals(request: Request, hours: int = 24, page: int = 1):
        _require_auth(request)
        since_ts = _hours_to_since_ts(hours)
        all_sigs = request.app.state.store.get_signals_since(since_ts)
        page_size = 100
        page = max(1, page)  # clamp to minimum 1
        start = (page - 1) * page_size
        page_sigs = all_sigs[start: start + page_size]
        return {
            "signals": [
                {
                    "id": s.id,
                    "source": s.source,
                    "signal_type": s.signal_type,
                    "ticker": s.ticker,
                    "company": s.company,
                    "title": s.title,
                    "url": s.url,
                    "published": s.published,
                    "amount_usd": s.amount_usd,
                }
                for s in page_sigs
            ],
            "total": len(all_sigs),
            "page": page,
            "hours": hours,
        }

    @app.get("/api/sources")
    async def api_sources(request: Request, hours: int = 24):
        _require_auth(request)
        since_ts = _hours_to_since_ts(hours)
        counts = request.app.state.store.signal_count_since(since_ts)
        all_sources = [
            "edgar", "usaspending", "fedregister", "congress", "sbir",
            "norway", "catalyst", "grants_gov", "propublica", "lobbying",
        ]
        return {
            "sources": {src: counts.get(src, 0) for src in all_sources},
            "hours": hours,
        }

    @app.get("/api/sector-rotation")
    async def api_sector_rotation(request: Request, hours: int = 24, compare_hours: int = 168):
        _require_auth(request)
        snapshots = compute_rotation(
            request.app.state.store,
            window_hours=hours,
            compare_hours=compare_hours,
        )
        return {
            "sectors": [
                {
                    "sector": s.sector,
                    "current_count": s.current_count,
                    "prior_count": s.prior_count,
                    "pct_change": s.pct_change,
                }
                for s in snapshots
            ],
            "window_hours": hours,
            "compare_hours": compare_hours,
        }

    @app.get("/api/watchlist")
    async def api_watchlist(request: Request, hours: int = 24):
        _require_auth(request)
        since_ts = _hours_to_since_ts(hours)
        signals = request.app.state.store.get_signals_since(since_ts)
        ticker_data: dict[str, dict] = {}
        for sig in signals:
            if sig.ticker:
                if sig.ticker not in ticker_data:
                    ticker_data[sig.ticker] = {"signal_count": 0, "total_contract_usd": 0.0}
                ticker_data[sig.ticker]["signal_count"] += 1
                if sig.amount_usd:
                    ticker_data[sig.ticker]["total_contract_usd"] += sig.amount_usd
        tickers = sorted(
            [{"ticker": t, **d} for t, d in ticker_data.items()],
            key=lambda x: x["total_contract_usd"],
            reverse=True,
        )
        return {"tickers": tickers, "hours": hours}

    @app.get("/api/catalysts")
    async def api_catalysts(request: Request):
        _require_auth(request)
        all_sigs = request.app.state.store.get_signals_since(0, source="catalyst")
        today = datetime.date.today().isoformat()
        upcoming = [s for s in all_sigs if s.published >= today]
        upcoming.sort(key=lambda s: s.published)
        today_dt = datetime.date.today()
        return {
            "catalysts": [
                {
                    "title": s.title,
                    "date": s.published,
                    "days_until": _days_until(s.published, today_dt),
                    "source": s.source,
                }
                for s in upcoming
            ]
        }

    @app.get("/api/basket")
    async def api_basket(request: Request, hours: int = 720):
        _require_auth(request)
        cfg = request.app.state.config
        store = request.app.state.store
        since_ts = _hours_to_since_ts(hours)
        signals = store.get_signals_since(since_ts)
        contract_amounts: dict[str, float] = {}
        for sig in signals:
            if sig.ticker and sig.amount_usd and sig.source == "usaspending":
                contract_amounts[sig.ticker] = (
                    contract_amounts.get(sig.ticker, 0.0) + sig.amount_usd
                )
        positions = build_basket(
            watchlist=list(cfg.watchlist),
            contract_amounts=contract_amounts,
        )
        return {
            "positions": [
                {
                    "ticker": p.ticker,
                    "sector": p.sector,
                    "weight_pct": p.weight_pct,
                    "contract_usd": p.contract_usd,
                }
                for p in positions
            ],
            "excluded_count": len(EXCLUDED_TICKERS),
            "hours": hours,
        }

    @app.get("/api/options")
    async def api_options(request: Request, hours: int = 24, max_days: int = 90):
        _require_auth(request)
        cfg = request.app.state.config
        store = request.app.state.store
        catalysts = store.get_signals_since(0, source="catalyst")
        plays = generate_plays(
            catalysts=catalysts,
            tickers=list(cfg.watchlist),
            max_days_ahead=max_days,
        )
        return {
            "plays": [
                {
                    "ticker": p.ticker,
                    "catalyst_date": p.catalyst_date,
                    "catalyst_title": p.catalyst_title,
                    "action": p.action,
                    "strike": p.strike,
                    "expiry": p.expiry.isoformat() if p.expiry else None,
                    "ask": p.ask,
                    "thesis": p.thesis,
                }
                for p in plays
            ]
        }

    # ── Auth endpoints (added in Task 4) ─────────────────────────────────────

    _register_auth_routes(app)

    # ── Static files ──────────────────────────────────────────────────────────

    @app.get("/")
    async def root():
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text())
        return HTMLResponse("<h1>govspend web</h1><p>Run govspend web to serve the dashboard.</p>")

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


def _register_auth_routes(app: FastAPI) -> None:
    """Placeholder — replaced by Task 4 implementation."""

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return {
            "registered": request.app.state.store.has_credentials(),
            "authenticated": _check_session(request),
        }

    @app.post("/api/auth/logout")
    async def auth_logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie("session")
        return response
