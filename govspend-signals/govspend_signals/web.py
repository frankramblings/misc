"""FastAPI web dashboard for govspend-signals.

Start with:
    govspend web                       # http://localhost:8000
    govspend web --host 0.0.0.0        # expose on network

Requires:
    pip install "govspend-signals[web]"
"""
from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Module-level imports so tests can patch them
try:
    from webauthn import (  # noqa: F401
        verify_registration_response,
        verify_authentication_response,
    )
except ImportError:
    verify_registration_response = None  # type: ignore[assignment]
    verify_authentication_response = None  # type: ignore[assignment]

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
    """Register WebAuthn passkey auth endpoints."""
    import sys as _sys
    _this_module = _sys.modules[__name__]
    try:
        from webauthn import (
            generate_authentication_options,
            generate_registration_options,
            options_to_json,
        )
        from webauthn.helpers.exceptions import WebAuthnException
        from webauthn.helpers.structs import (
            AuthenticationCredential,
            AuthenticatorAssertionResponse,
            AuthenticatorAttestationResponse,
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            RegistrationCredential,
            UserVerificationRequirement,
        )
    except ImportError:
        # If webauthn isn't installed, register stub endpoints
        @app.get("/api/auth/status")
        async def auth_status_stub(request: Request):
            return {"registered": False, "authenticated": False, "error": "py-webauthn not installed"}

        @app.post("/api/auth/logout")
        async def auth_logout_stub():
            response = JSONResponse({"ok": True})
            response.delete_cookie("session")
            return response
        return

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

    @app.post("/api/auth/register/begin")
    async def register_begin(request: Request):
        store = request.app.state.store
        if store.has_credentials():
            raise HTTPException(409, "Already registered. Use /api/auth/login/begin to authenticate.")
        options = generate_registration_options(
            rp_id=request.app.state.rp_id,
            rp_name="govspend",
            user_id=b"govspend-user",
            user_name="govspend",
            user_display_name="govspend dashboard",
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        request.app.state.pending_challenge = options.challenge
        return json.loads(options_to_json(options))

    @app.post("/api/auth/register/finish")
    async def register_finish(request: Request):
        challenge = request.app.state.pending_challenge
        if challenge is None:
            raise HTTPException(400, "No pending registration. Call /register/begin first.")
        body = await request.json()
        import base64

        def _b64_decode(s: str) -> bytes:
            padded = s + "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(padded)

        try:
            resp_data = body.get("response", {})
            credential = RegistrationCredential(
                id=body["id"],
                raw_id=_b64_decode(body["rawId"]),
                response=AuthenticatorAttestationResponse(
                    client_data_json=_b64_decode(resp_data["clientDataJSON"]),
                    attestation_object=_b64_decode(resp_data["attestationObject"]),
                ),
            )
            verification = _this_module.verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=request.app.state.rp_id,
                expected_origin=request.app.state.origin,
            )
        except (WebAuthnException, Exception) as exc:
            raise HTTPException(400, f"Registration failed: {exc}")
        cred_id = base64.urlsafe_b64encode(verification.credential_id).rstrip(b"=").decode()
        request.app.state.store.store_credential(
            credential_id=cred_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
        )
        request.app.state.pending_challenge = None
        response = JSONResponse({"ok": True})
        _set_session(response, request.app.state.signer)
        return response

    @app.post("/api/auth/login/begin")
    async def login_begin(request: Request):
        store = request.app.state.store
        credentials = store.get_credentials()
        if not credentials:
            raise HTTPException(404, "No credentials registered. Register a passkey first.")
        import base64

        def _decode_cred_id(cred_id: str) -> bytes:
            try:
                padded = cred_id + "=" * (-len(cred_id) % 4)
                return base64.urlsafe_b64decode(padded)
            except Exception:
                return cred_id.encode()

        options = generate_authentication_options(
            rp_id=request.app.state.rp_id,
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=_decode_cred_id(c["id"]),
                )
                for c in credentials
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        request.app.state.pending_challenge = options.challenge
        return json.loads(options_to_json(options))

    @app.post("/api/auth/login/finish")
    async def login_finish(request: Request):
        challenge = request.app.state.pending_challenge
        if challenge is None:
            raise HTTPException(400, "No pending login. Call /login/begin first.")
        body = await request.json()
        stored_cred = request.app.state.store.get_credential(body.get("id", ""))
        if stored_cred is None:
            raise HTTPException(400, "Unknown credential.")
        import base64

        def _b64_decode_login(s: str) -> bytes:
            padded = s + "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(padded)

        try:
            resp_data = body.get("response", {})
            user_handle_raw = resp_data.get("userHandle")
            credential = AuthenticationCredential(
                id=body["id"],
                raw_id=_b64_decode_login(body["rawId"]),
                response=AuthenticatorAssertionResponse(
                    client_data_json=_b64_decode_login(resp_data["clientDataJSON"]),
                    authenticator_data=_b64_decode_login(resp_data["authenticatorData"]),
                    signature=_b64_decode_login(resp_data["signature"]),
                    user_handle=_b64_decode_login(user_handle_raw) if user_handle_raw else None,
                ),
            )
            verification = _this_module.verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=request.app.state.rp_id,
                expected_origin=request.app.state.origin,
                credential_public_key=stored_cred["public_key"],
                credential_current_sign_count=stored_cred["sign_count"],
            )
        except (WebAuthnException, Exception) as exc:
            raise HTTPException(400, f"Authentication failed: {exc}")
        request.app.state.store.update_sign_count(body["id"], verification.new_sign_count)
        request.app.state.pending_challenge = None
        response = JSONResponse({"ok": True})
        _set_session(response, request.app.state.signer)
        return response
