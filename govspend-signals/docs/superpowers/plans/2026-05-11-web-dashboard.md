# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI web dashboard with 7 data panels, 30-second auto-refresh, and WebAuthn passkey authentication, deployable locally (`govspend web`) and to Fly.io.

**Architecture:** A single `web.py` FastAPI app reads from the existing SQLite database. Static files (HTML/CSS/JS) are served from `web_static/`. Passkey credentials are stored in a new `credentials` table in the same SQLite DB. The CLI gains a `web` subcommand that starts uvicorn.

**Tech Stack:** Python 3.11+, FastAPI ≥0.111, uvicorn, py-webauthn ≥2.1 (Pydantic v1), itsdangerous ≥2.1, vanilla JS (no framework).

---

## File Map

### Created
- `govspend_signals/web.py` — FastAPI app factory + all API routes (data + auth)
- `govspend_signals/web_static/index.html` — single page, 7 panels, auth screens
- `govspend_signals/web_static/style.css` — dark theme
- `govspend_signals/web_static/app.js` — fetch, setInterval, WebAuthn
- `Dockerfile` — production container
- `fly.toml` — Fly.io config
- `tests/test_web_storage.py` — credentials table tests
- `tests/test_web_api.py` — data endpoint tests
- `tests/test_web_auth.py` — auth endpoint tests

### Modified
- `govspend_signals/storage.py` — add `credentials` table + 6 auth helper methods
- `govspend_signals/cli.py` — add `web` subcommand
- `pyproject.toml` — add `[web]` optional dep group + httpx to dev

---

## Task 1: Storage — credentials table + auth helpers

**Files:**
- Modify: `govspend_signals/storage.py`
- Test: `tests/test_web_storage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_storage.py`:

```python
"""Tests for web dashboard auth storage methods."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from govspend_signals.storage import Storage


@pytest.fixture
def store(tmp_path):
    s = Storage(tmp_path / "test.db")
    yield s
    s.close()


def test_has_credentials_false_when_empty(store):
    assert store.has_credentials() is False


def test_store_and_retrieve_credential(store):
    store.store_credential(
        credential_id="abc123",
        public_key=b"\x01\x02\x03",
        sign_count=0,
        name="Test Key",
    )
    cred = store.get_credential("abc123")
    assert cred is not None
    assert cred["id"] == "abc123"
    assert cred["public_key"] == b"\x01\x02\x03"
    assert cred["sign_count"] == 0
    assert cred["name"] == "Test Key"


def test_has_credentials_true_after_store(store):
    store.store_credential("cred1", b"\xaa", 0)
    assert store.has_credentials() is True


def test_get_credentials_returns_all(store):
    store.store_credential("cred1", b"\x01", 0)
    store.store_credential("cred2", b"\x02", 5)
    creds = store.get_credentials()
    assert len(creds) == 2
    ids = {c["id"] for c in creds}
    assert ids == {"cred1", "cred2"}


def test_update_sign_count(store):
    store.store_credential("cred1", b"\x01", 0)
    store.update_sign_count("cred1", 42)
    cred = store.get_credential("cred1")
    assert cred["sign_count"] == 42


def test_get_credential_returns_none_for_unknown(store):
    assert store.get_credential("nonexistent") is None


def test_get_or_create_secret_stable(store):
    s1 = store.get_or_create_secret()
    s2 = store.get_or_create_secret()
    assert s1 == s2
    assert len(s1) == 64  # 32 bytes hex


def test_get_or_create_secret_nonempty(store):
    secret = store.get_or_create_secret()
    assert secret
```

- [ ] **Step 2: Run to see them fail**

```bash
.venv/bin/pytest tests/test_web_storage.py -v
```

Expected: `AttributeError: 'Storage' object has no attribute 'has_credentials'`

- [ ] **Step 3: Add credentials table to `_SCHEMA` in `storage.py`**

In `govspend_signals/storage.py`, find `_SCHEMA = """` and add this block before the closing `"""`:

```sql

CREATE TABLE IF NOT EXISTS credentials (
    id          TEXT PRIMARY KEY,
    public_key  BLOB NOT NULL,
    sign_count  INTEGER NOT NULL DEFAULT 0,
    name        TEXT,
    created_ts  INTEGER NOT NULL
);
```

- [ ] **Step 4: Add six methods to the `Storage` class**

At the end of the `Storage` class (after `ticker_map_age_seconds`), add:

```python
    # ── Web dashboard auth methods ─────────────────────────────────────────

    def has_credentials(self) -> bool:
        """Return True if at least one passkey credential is registered."""
        row = self._conn.execute(
            "SELECT 1 FROM credentials LIMIT 1"
        ).fetchone()
        return row is not None

    def store_credential(
        self,
        credential_id: str,
        public_key: bytes,
        sign_count: int,
        name: str | None = None,
    ) -> None:
        """Store a new WebAuthn credential."""
        self._conn.execute(
            "INSERT OR REPLACE INTO credentials "
            "(id, public_key, sign_count, name, created_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (credential_id, public_key, sign_count, name, int(time.time())),
        )
        self._conn.commit()

    def get_credential(self, credential_id: str) -> dict | None:
        """Return credential dict or None if not found."""
        row = self._conn.execute(
            "SELECT id, public_key, sign_count, name FROM credentials WHERE id = ?",
            (credential_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "public_key": bytes(row["public_key"]),
            "sign_count": row["sign_count"],
            "name": row["name"],
        }

    def get_credentials(self) -> list[dict]:
        """Return all registered credentials."""
        rows = self._conn.execute(
            "SELECT id, public_key, sign_count, name FROM credentials"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "public_key": bytes(r["public_key"]),
                "sign_count": r["sign_count"],
                "name": r["name"],
            }
            for r in rows
        ]

    def update_sign_count(self, credential_id: str, new_sign_count: int) -> None:
        """Update the sign count after a successful authentication."""
        self._conn.execute(
            "UPDATE credentials SET sign_count = ? WHERE id = ?",
            (new_sign_count, credential_id),
        )
        self._conn.commit()

    def get_or_create_secret(self) -> str:
        """Return the dashboard session secret, generating one if needed."""
        import secrets as _secrets
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'dashboard_secret'"
        ).fetchone()
        if row:
            return row["value"]
        secret = _secrets.token_hex(32)
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES ('dashboard_secret', ?)",
            (secret,),
        )
        self._conn.commit()
        return secret
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_web_storage.py -v
```

Expected: all 9 pass.

- [ ] **Step 6: Commit**

```bash
git add govspend_signals/storage.py tests/test_web_storage.py
git commit -m "feat: add credentials table and auth helpers to Storage"
```

---

## Task 2: pyproject.toml — web dependency group

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `[web]` extras and `httpx` to dev**

In `pyproject.toml`, find `[project.optional-dependencies]` and add the `web` group. Also add `fastapi` and `httpx` to `dev` so tests can import them:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "responses>=0.25",
    "fastapi>=0.111",
    "httpx>=0.27",
]
telegram = [
    "httpx>=0.27",
]
dashboard = [
    "rich>=13.0",
]
resolver = [
    "rapidfuzz>=3.0",
]
price = [
    "yfinance>=0.2",
]
web = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "py-webauthn>=2.1",
    "itsdangerous>=2.1",
    "httpx>=0.27",
]
full = [
    "httpx>=0.27",
    "rich>=13.0",
    "rapidfuzz>=3.0",
    "yfinance>=0.2",
]
```

- [ ] **Step 2: Install web deps**

```bash
.venv/bin/pip install -e ".[web]"
```

Expected: fastapi, uvicorn, py-webauthn, itsdangerous installed.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add [web] optional dep group (fastapi, uvicorn, py-webauthn, itsdangerous)"
```

---

## Task 3: web.py — app factory + 7 data endpoints

**Files:**
- Create: `govspend_signals/web.py`
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_api.py`:

```python
"""Tests for web dashboard data API endpoints."""
from __future__ import annotations

import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from govspend_signals.storage import Storage, SignalRow
from govspend_signals.signal import Signal


def _make_store(tmp_path):
    s = Storage(tmp_path / "test.db")
    # Seed a signal
    sig = Signal(
        source="usaspending",
        signal_type="contract_award",
        title="$5M contract — ACME Corp",
        url="https://usaspending.gov/award/123",
        published="2026-05-10",
        ticker="ACN",
        company="ACME Corp",
        amount_usd=5_000_000.0,
        data={},
    )
    s.mark_signal_seen(sig)
    return s


def _make_config(watchlist=("ACN", "UNH")):
    cfg = MagicMock()
    cfg.watchlist = watchlist
    cfg.db_path = Path("/tmp/test.db")
    return cfg


@pytest.fixture
def client(tmp_path):
    from govspend_signals.web import create_app
    store = _make_store(tmp_path)
    cfg = _make_config()
    app = create_app(store=store, config=cfg, origin="http://localhost:8000", secret="testsecret")
    # Bypass auth for data endpoint tests
    app.state.authenticated = True
    c = TestClient(app, cookies={"session": app.state.signer.dumps("authenticated")})
    yield c
    store.close()


def test_signals_endpoint_returns_list(client):
    resp = client.get("/api/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert isinstance(data["signals"], list)


def test_signals_contains_seeded_signal(client):
    resp = client.get("/api/signals?hours=8760")
    data = resp.json()
    assert any(s["source"] == "usaspending" for s in data["signals"])


def test_sources_endpoint(client):
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], dict)


def test_sector_rotation_endpoint(client):
    resp = client.get("/api/sector-rotation")
    assert resp.status_code == 200
    data = resp.json()
    assert "sectors" in data
    assert isinstance(data["sectors"], list)


def test_watchlist_endpoint(client):
    resp = client.get("/api/watchlist?hours=8760")
    assert resp.status_code == 200
    data = resp.json()
    assert "tickers" in data


def test_watchlist_shows_acn(client):
    resp = client.get("/api/watchlist?hours=8760")
    tickers = {t["ticker"] for t in resp.json()["tickers"]}
    assert "ACN" in tickers


def test_catalysts_endpoint(client):
    resp = client.get("/api/catalysts")
    assert resp.status_code == 200
    data = resp.json()
    assert "catalysts" in data
    assert isinstance(data["catalysts"], list)


def test_basket_endpoint(client):
    resp = client.get("/api/basket?hours=8760")
    assert resp.status_code == 200
    data = resp.json()
    assert "positions" in data
    assert "excluded_count" in data


def test_options_endpoint(client):
    resp = client.get("/api/options")
    assert resp.status_code == 200
    data = resp.json()
    assert "plays" in data


def test_unauthenticated_returns_401(tmp_path):
    from govspend_signals.web import create_app
    store = Storage(tmp_path / "test.db")
    cfg = _make_config()
    app = create_app(store=store, config=cfg, origin="http://localhost:8000", secret="testsecret")
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/api/signals")
    assert resp.status_code == 401
    store.close()
```

- [ ] **Step 2: Run to see them fail**

```bash
.venv/bin/pytest tests/test_web_api.py -v
```

Expected: `ImportError` or `ModuleNotFoundError: No module named 'govspend_signals.web'`

- [ ] **Step 3: Create `govspend_signals/web.py`**

```python
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
from itsdangerous import BadSignature, URLSafeTimedSerializer

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
    try:
        signer.loads(token, max_age=_SESSION_MAX_AGE)
        return True
    except Exception:
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
                    "days_until": (
                        datetime.date.fromisoformat(s.published) - today_dt
                    ).days,
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_web_api.py -v
```

Expected: all 10 pass.

- [ ] **Step 5: Commit**

```bash
git add govspend_signals/web.py tests/test_web_api.py
git commit -m "feat: web.py — FastAPI app factory + 7 data endpoints"
```

---

## Task 4: web.py — passkey auth endpoints

**Files:**
- Modify: `govspend_signals/web.py` (replace `_register_auth_routes`)
- Test: `tests/test_web_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_auth.py`:

```python
"""Tests for web dashboard passkey auth endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from govspend_signals.storage import Storage


def _make_app(tmp_path):
    from govspend_signals.web import create_app
    store = Storage(tmp_path / "test.db")
    cfg = MagicMock()
    cfg.watchlist = ("UNH",)
    cfg.db_path = tmp_path / "test.db"
    app = create_app(store=store, config=cfg, origin="http://localhost:8000", secret="testsecret")
    return app, store


def test_auth_status_unauthenticated(tmp_path):
    app, store = _make_app(tmp_path)
    c = TestClient(app)
    resp = c.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
    assert data["registered"] is False
    store.close()


def test_auth_status_registered_after_store(tmp_path):
    app, store = _make_app(tmp_path)
    store.store_credential("cred1", b"\x01", 0)
    c = TestClient(app)
    resp = c.get("/api/auth/status")
    assert resp.json()["registered"] is True
    store.close()


def test_logout_clears_session(tmp_path):
    app, store = _make_app(tmp_path)
    signer = app.state.signer
    c = TestClient(app, cookies={"session": signer.dumps("authenticated")})
    resp = c.post("/api/auth/logout")
    assert resp.status_code == 200
    store.close()


def test_register_begin_returns_options(tmp_path):
    app, store = _make_app(tmp_path)
    c = TestClient(app)
    resp = c.post("/api/auth/register/begin")
    assert resp.status_code == 200
    data = resp.json()
    assert "challenge" in data
    assert "rp" in data
    store.close()


def test_register_begin_fails_if_already_registered(tmp_path):
    app, store = _make_app(tmp_path)
    store.store_credential("existing", b"\xff", 0)
    c = TestClient(app)
    resp = c.post("/api/auth/register/begin")
    # Should reject — already registered
    assert resp.status_code == 409
    store.close()


def test_login_begin_returns_options(tmp_path):
    app, store = _make_app(tmp_path)
    store.store_credential("cred1", b"\x01", 0)
    c = TestClient(app)
    resp = c.post("/api/auth/login/begin")
    assert resp.status_code == 200
    data = resp.json()
    assert "challenge" in data
    store.close()


def test_login_begin_fails_if_no_credentials(tmp_path):
    app, store = _make_app(tmp_path)
    c = TestClient(app)
    resp = c.post("/api/auth/login/begin")
    assert resp.status_code == 404
    store.close()


def test_register_finish_stores_credential(tmp_path):
    app, store = _make_app(tmp_path)
    c = TestClient(app)
    # Set a pending challenge manually
    app.state.pending_challenge = b"test-challenge-bytes"

    mock_verification = MagicMock()
    mock_verification.credential_id = b"credid"
    mock_verification.credential_public_key = b"pubkey"
    mock_verification.sign_count = 0

    with patch("govspend_signals.web.verify_registration_response", return_value=mock_verification):
        resp = c.post(
            "/api/auth/register/finish",
            json={
                "id": "Y3JlZGlk",
                "rawId": "Y3JlZGlk",
                "type": "public-key",
                "response": {
                    "clientDataJSON": "dGVzdA",
                    "attestationObject": "dGVzdA",
                },
            },
        )
    assert resp.status_code == 200
    assert store.has_credentials()
    store.close()


def test_login_finish_sets_session_cookie(tmp_path):
    app, store = _make_app(tmp_path)
    store.store_credential("Y3JlZGlk", b"pubkey", 0)
    app.state.pending_challenge = b"test-challenge-bytes"
    c = TestClient(app)

    mock_verification = MagicMock()
    mock_verification.new_sign_count = 1

    with patch("govspend_signals.web.verify_authentication_response", return_value=mock_verification):
        resp = c.post(
            "/api/auth/login/finish",
            json={
                "id": "Y3JlZGlk",
                "rawId": "Y3JlZGlk",
                "type": "public-key",
                "response": {
                    "clientDataJSON": "dGVzdA",
                    "authenticatorData": "dGVzdA",
                    "signature": "dGVzdA",
                    "userHandle": None,
                },
            },
        )
    assert resp.status_code == 200
    assert "session" in resp.cookies
    store.close()
```

- [ ] **Step 2: Run to see them fail**

```bash
.venv/bin/pytest tests/test_web_auth.py -v
```

Expected: `test_register_begin_returns_options` fails (stub doesn't return proper options), others may pass.

- [ ] **Step 3: Replace `_register_auth_routes` in `web.py`**

Replace the entire `_register_auth_routes` function with:

```python
def _register_auth_routes(app: FastAPI) -> None:
    """Register WebAuthn passkey auth endpoints."""
    try:
        from webauthn import (
            generate_authentication_options,
            generate_registration_options,
            options_to_json,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers.exceptions import WebAuthnException
        from webauthn.helpers.structs import (
            AuthenticationCredential,
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            RegistrationCredential,
            UserVerificationRequirement,
        )
    except ImportError:
        # If py-webauthn isn't installed, register stub endpoints
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
        try:
            credential = RegistrationCredential.parse_obj(body)
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=request.app.state.rp_id,
                expected_origin=request.app.state.origin,
            )
        except (WebAuthnException, Exception) as exc:
            raise HTTPException(400, f"Registration failed: {exc}")
        import base64
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
        options = generate_authentication_options(
            rp_id=request.app.state.rp_id,
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=base64.urlsafe_b64decode(c["id"] + "=="),
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
        try:
            credential = AuthenticationCredential.parse_obj(body)
            verification = verify_authentication_response(
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
```

Also add `verify_registration_response` and `verify_authentication_response` to the module-level imports at the top of `web.py` so the test patches work:

Add at the top of `web.py` after the other imports:

```python
# Module-level imports so tests can patch them
try:
    from webauthn import (  # noqa: F401
        verify_registration_response,
        verify_authentication_response,
    )
except ImportError:
    verify_registration_response = None  # type: ignore[assignment]
    verify_authentication_response = None  # type: ignore[assignment]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_web_auth.py -v
```

Expected: all 9 pass.

- [ ] **Step 5: Run full suite to make sure nothing broke**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add govspend_signals/web.py tests/test_web_auth.py
git commit -m "feat: passkey auth endpoints (register/login/logout) with py-webauthn"
```

---

## Task 5: web_static/ — index.html, style.css, app.js

**Files:**
- Create: `govspend_signals/web_static/index.html`
- Create: `govspend_signals/web_static/style.css`
- Create: `govspend_signals/web_static/app.js`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p govspend_signals/web_static
```

- [ ] **Step 2: Create `style.css`**

Create `govspend_signals/web_static/style.css`:

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px;
  line-height: 1.5;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}

header h1 { font-size: 15px; color: var(--accent); letter-spacing: 0.05em; }
#last-updated { color: var(--muted); font-size: 11px; }
#logout-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  font-size: 11px;
}
#logout-btn:hover { border-color: var(--text); color: var(--text); }

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 12px;
  padding: 12px;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.panel-full { grid-column: 1 / -1; }

.panel-header {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.panel-body { padding: 10px 14px; overflow-x: auto; }

/* Signal feed */
#signal-feed { max-height: 340px; overflow-y: auto; }

table { width: 100%; border-collapse: collapse; }
th { color: var(--muted); text-align: left; padding: 4px 8px; font-weight: normal; font-size: 11px; border-bottom: 1px solid var(--border); }
td { padding: 4px 8px; border-bottom: 1px solid #1c2128; white-space: nowrap; }
tr:last-child td { border-bottom: none; }
td.amount { text-align: right; color: var(--green); }
td.ticker { color: var(--accent); font-weight: bold; }
td.source { color: var(--muted); }

/* Bar chart */
.bar-row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
.bar-label { width: 120px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; background: #1c2128; border-radius: 2px; height: 8px; }
.bar-fill { height: 8px; border-radius: 2px; background: var(--accent); transition: width 0.4s; }
.bar-count { width: 40px; text-align: right; }

/* Sector rotation */
.up { color: var(--green); }
.down { color: var(--red); }
.flat { color: var(--muted); }

/* Catalyst calendar */
.catalyst-row { display: flex; gap: 12px; padding: 4px 0; border-bottom: 1px solid #1c2128; }
.catalyst-row:last-child { border-bottom: none; }
.catalyst-date { color: var(--accent); width: 90px; flex-shrink: 0; }
.catalyst-days { color: var(--muted); width: 50px; flex-shrink: 0; }
.catalyst-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Auth screens */
#auth-screen {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  flex-direction: column;
  gap: 20px;
}

.auth-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 32px 40px;
  text-align: center;
  width: 320px;
}

.auth-box h2 { color: var(--accent); margin-bottom: 8px; font-size: 16px; }
.auth-box p { color: var(--muted); margin-bottom: 20px; font-size: 12px; }
.auth-btn {
  width: 100%;
  padding: 10px;
  background: var(--accent);
  color: #000;
  border: none;
  border-radius: 4px;
  font-family: inherit;
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
}
.auth-btn:hover { opacity: 0.9; }
.auth-error { color: var(--red); font-size: 12px; margin-top: 10px; }

#dashboard { display: none; }

@media (max-width: 768px) {
  .grid { grid-template-columns: 1fr; }
  .panel-full { grid-column: 1; }
}
```

- [ ] **Step 3: Create `index.html`**

Create `govspend_signals/web_static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>govspend signals</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>

<!-- Auth screen -->
<div id="auth-screen">
  <div class="auth-box" id="login-box" style="display:none">
    <h2>govspend signals</h2>
    <p>Sign in with your registered passkey</p>
    <button class="auth-btn" onclick="loginPasskey()">Sign in with passkey</button>
    <div class="auth-error" id="login-error"></div>
  </div>
  <div class="auth-box" id="register-box" style="display:none">
    <h2>govspend signals</h2>
    <p>Register a passkey to secure your dashboard</p>
    <button class="auth-btn" onclick="registerPasskey()">Register passkey</button>
    <div class="auth-error" id="register-error"></div>
  </div>
</div>

<!-- Dashboard -->
<div id="dashboard">
  <header>
    <h1>govspend signals</h1>
    <span id="last-updated">loading…</span>
    <button id="logout-btn" onclick="logout()">logout</button>
  </header>

  <div class="grid">
    <!-- Signal Feed (full width) -->
    <div class="panel panel-full">
      <div class="panel-header">Signal Feed <span id="signal-count" style="color:var(--text)"></span></div>
      <div class="panel-body" id="signal-feed">
        <table>
          <thead><tr>
            <th>Date</th><th>Source</th><th>Type</th><th>Ticker</th><th>Title</th><th style="text-align:right">Amount</th>
          </tr></thead>
          <tbody id="signal-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Sources -->
    <div class="panel">
      <div class="panel-header">Sources (24h)</div>
      <div class="panel-body" id="sources-body"></div>
    </div>

    <!-- Sector Rotation -->
    <div class="panel">
      <div class="panel-header">Sector Rotation — 24h vs 7d</div>
      <div class="panel-body">
        <table>
          <thead><tr><th>Sector</th><th>Now</th><th>Prior</th><th>Change</th></tr></thead>
          <tbody id="rotation-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Watchlist -->
    <div class="panel">
      <div class="panel-header">Watchlist Activity (24h)</div>
      <div class="panel-body">
        <table>
          <thead><tr><th>Ticker</th><th>Signals</th><th style="text-align:right">Gov Contracts</th></tr></thead>
          <tbody id="watchlist-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Catalyst Calendar -->
    <div class="panel">
      <div class="panel-header">Catalyst Calendar</div>
      <div class="panel-body" id="catalysts-body"></div>
    </div>

    <!-- Basket -->
    <div class="panel">
      <div class="panel-header">Basket — Ethical Screen Portfolio</div>
      <div class="panel-body">
        <table>
          <thead><tr><th>Ticker</th><th>Sector</th><th style="text-align:right">Weight</th><th style="text-align:right">Contracts</th></tr></thead>
          <tbody id="basket-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Options Plays -->
    <div class="panel">
      <div class="panel-header">Options Plays</div>
      <div class="panel-body">
        <table>
          <thead><tr><th>Ticker</th><th>Action</th><th>Catalyst</th><th style="text-align:right">Strike</th><th style="text-align:right">Ask</th></tr></thead>
          <tbody id="options-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create `app.js`**

Create `govspend_signals/web_static/app.js`:

```javascript
// ── Utility ────────────────────────────────────────────────────────────────

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = '';
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64urlToBuffer(b64url) {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
  const str = atob(b64);
  const buf = new ArrayBuffer(str.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i);
  return buf;
}

function fmtUsd(n) {
  if (!n) return '—';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
  return '$' + n.toFixed(0);
}

function el(id) { return document.getElementById(id); }

// ── Auth ───────────────────────────────────────────────────────────────────

async function checkAuth() {
  const resp = await fetch('/api/auth/status');
  const { registered, authenticated } = await resp.json();
  if (authenticated) {
    showDashboard();
  } else if (registered) {
    el('login-box').style.display = 'block';
  } else {
    el('register-box').style.display = 'block';
  }
}

async function registerPasskey() {
  el('register-error').textContent = '';
  try {
    const beginResp = await fetch('/api/auth/register/begin', { method: 'POST' });
    if (!beginResp.ok) { el('register-error').textContent = await beginResp.text(); return; }
    const options = await beginResp.json();
    options.challenge = base64urlToBuffer(options.challenge);
    options.user.id = base64urlToBuffer(options.user.id);
    if (options.excludeCredentials) {
      options.excludeCredentials = options.excludeCredentials.map(c => ({ ...c, id: base64urlToBuffer(c.id) }));
    }
    const credential = await navigator.credentials.create({ publicKey: options });
    const body = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        attestationObject: bufferToBase64url(credential.response.attestationObject),
      },
    };
    const finishResp = await fetch('/api/auth/register/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (finishResp.ok) { window.location.reload(); }
    else { el('register-error').textContent = 'Registration failed. Try again.'; }
  } catch (e) {
    el('register-error').textContent = e.message || 'Registration failed.';
  }
}

async function loginPasskey() {
  el('login-error').textContent = '';
  try {
    const beginResp = await fetch('/api/auth/login/begin', { method: 'POST' });
    if (!beginResp.ok) { el('login-error').textContent = await beginResp.text(); return; }
    const options = await beginResp.json();
    options.challenge = base64urlToBuffer(options.challenge);
    if (options.allowCredentials) {
      options.allowCredentials = options.allowCredentials.map(c => ({ ...c, id: base64urlToBuffer(c.id) }));
    }
    const credential = await navigator.credentials.get({ publicKey: options });
    const body = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        authenticatorData: bufferToBase64url(credential.response.authenticatorData),
        signature: bufferToBase64url(credential.response.signature),
        userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : null,
      },
    };
    const finishResp = await fetch('/api/auth/login/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (finishResp.ok) { window.location.reload(); }
    else { el('login-error').textContent = 'Login failed. Try again.'; }
  } catch (e) {
    el('login-error').textContent = e.message || 'Login failed.';
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.reload();
}

// ── Dashboard ──────────────────────────────────────────────────────────────

function showDashboard() {
  el('auth-screen').style.display = 'none';
  el('dashboard').style.display = 'block';
  refreshAll();
  setInterval(refreshAll, 30000);
}

async function refreshAll() {
  await Promise.all([
    refreshSignals(),
    refreshSources(),
    refreshRotation(),
    refreshWatchlist(),
    refreshCatalysts(),
    refreshBasket(),
    refreshOptions(),
  ]);
  el('last-updated').textContent = 'updated ' + new Date().toLocaleTimeString();
}

async function refreshSignals() {
  const resp = await fetch('/api/signals?hours=24');
  if (!resp.ok) return;
  const { signals, total } = await resp.json();
  el('signal-count').textContent = `(${total})`;
  const tbody = el('signal-tbody');
  tbody.innerHTML = signals.map(s => `
    <tr>
      <td>${s.published}</td>
      <td class="source">${s.source}</td>
      <td class="source">${s.signal_type}</td>
      <td class="ticker">${s.ticker || '—'}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis">${s.title}</td>
      <td class="amount">${fmtUsd(s.amount_usd)}</td>
    </tr>
  `).join('') || '<tr><td colspan="6" style="color:var(--muted);text-align:center">No signals. Run govspend ingest.</td></tr>';
}

async function refreshSources() {
  const resp = await fetch('/api/sources');
  if (!resp.ok) return;
  const { sources } = await resp.json();
  const maxCount = Math.max(...Object.values(sources), 1);
  const emojis = {
    edgar:'📋', usaspending:'💰', fedregister:'📜', congress:'🏛️',
    sbir:'🔬', norway:'🇳🇴', catalyst:'📅', grants_gov:'🏆',
    propublica:'⚖️', lobbying:'💼',
  };
  el('sources-body').innerHTML = Object.entries(sources).map(([src, count]) => `
    <div class="bar-row">
      <div class="bar-label">${emojis[src] || ''} ${src}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${count / maxCount * 100}%"></div></div>
      <div class="bar-count">${count}</div>
    </div>
  `).join('');
}

async function refreshRotation() {
  const resp = await fetch('/api/sector-rotation');
  if (!resp.ok) return;
  const { sectors } = await resp.json();
  el('rotation-tbody').innerHTML = sectors.map(s => {
    const pct = s.pct_change;
    const cls = pct === null ? 'flat' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    const pctStr = pct === null ? 'new' : (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%';
    return `<tr>
      <td>${s.sector}</td>
      <td>${s.current_count}</td>
      <td style="color:var(--muted)">${s.prior_count}</td>
      <td class="${cls}">${pctStr}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="4" style="color:var(--muted)">No data</td></tr>';
}

async function refreshWatchlist() {
  const resp = await fetch('/api/watchlist?hours=24');
  if (!resp.ok) return;
  const { tickers } = await resp.json();
  el('watchlist-tbody').innerHTML = tickers.map(t => `
    <tr>
      <td class="ticker">${t.ticker}</td>
      <td>${t.signal_count}</td>
      <td class="amount">${fmtUsd(t.total_contract_usd)}</td>
    </tr>
  `).join('') || '<tr><td colspan="3" style="color:var(--muted)">No watchlist matches</td></tr>';
}

async function refreshCatalysts() {
  const resp = await fetch('/api/catalysts');
  if (!resp.ok) return;
  const { catalysts } = await resp.json();
  el('catalysts-body').innerHTML = catalysts.map(c => `
    <div class="catalyst-row">
      <span class="catalyst-date">${c.date}</span>
      <span class="catalyst-days">[${c.days_until}d]</span>
      <span class="catalyst-title">${c.title.replace(/^\[CATALYST\]\s*/, '')}</span>
    </div>
  `).join('') || '<div style="color:var(--muted)">No upcoming catalysts</div>';
}

async function refreshBasket() {
  const resp = await fetch('/api/basket?hours=720');
  if (!resp.ok) return;
  const { positions, excluded_count } = await resp.json();
  el('basket-tbody').innerHTML = positions.map(p => `
    <tr>
      <td class="ticker">${p.ticker}</td>
      <td style="color:var(--muted)">${p.sector}</td>
      <td class="amount">${p.weight_pct.toFixed(1)}%</td>
      <td class="amount">${fmtUsd(p.contract_usd)}</td>
    </tr>
  `).join('') || `<tr><td colspan="4" style="color:var(--muted)">No eligible positions (${excluded_count} excluded)</td></tr>`;
}

async function refreshOptions() {
  const resp = await fetch('/api/options');
  if (!resp.ok) return;
  const { plays } = await resp.json();
  el('options-tbody').innerHTML = plays.map(p => `
    <tr>
      <td class="ticker">${p.ticker}</td>
      <td style="color:${p.action.includes('CALL') ? 'var(--green)' : 'var(--red)'}">${p.action}</td>
      <td style="color:var(--muted);max-width:160px;overflow:hidden;text-overflow:ellipsis">${p.catalyst_date}</td>
      <td class="amount">${p.strike ? '$' + p.strike : '—'}</td>
      <td class="amount">${p.ask ? '$' + p.ask.toFixed(2) : '—'}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:var(--muted)">No plays. Run govspend ingest first.</td></tr>';
}

// ── Boot ───────────────────────────────────────────────────────────────────
checkAuth();
```

- [ ] **Step 5: Verify files exist**

```bash
ls govspend_signals/web_static/
```

Expected: `index.html  style.css  app.js`

- [ ] **Step 6: Commit**

```bash
git add govspend_signals/web_static/
git commit -m "feat: web dashboard frontend — index.html, style.css, app.js"
```

---

## Task 6: cli.py — `govspend web` subcommand

**Files:**
- Modify: `govspend_signals/cli.py`

- [ ] **Step 1: Add parser**

In `govspend_signals/cli.py`, inside `_build_parser()`, after the `basket` subcommand parser block, add:

```python
    # ── web (FastAPI dashboard) ───────────────────────────────────────────────
    web_cmd = sub.add_parser(
        "web",
        help="Start the web dashboard (http://localhost:8000 by default).",
    )
    web_cmd.add_argument("--config", type=Path, default=None)
    web_cmd.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    web_cmd.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    web_cmd.add_argument("--db", type=Path, default=None, help="Explicit DB path (overrides config)")
```

- [ ] **Step 2: Add handler function**

After `_cmd_basket()` in `cli.py`, add:

```python
def _cmd_web(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn not installed. Run: pip install 'govspend-signals[web]'",
            file=sys.stderr,
        )
        return 1

    from .web import create_app

    cfg = load_config(args.config)
    db_path = args.db or cfg.db_path
    store = Storage(db_path)

    origin = os.environ.get(
        "DASHBOARD_ORIGIN", f"http://{args.host}:{args.port}"
    )
    app = create_app(store=store, config=cfg, origin=origin)

    print(f"govspend web  →  {origin}")
    print("Register a passkey on first visit.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    store.close()
    return 0
```

Also add `import os` near the top of `cli.py` if not already present.

- [ ] **Step 3: Wire dispatch**

In the `main()` function, find the block that dispatches `args.cmd` and add:

```python
    if args.cmd == "web":
        return _cmd_web(args)
```

- [ ] **Step 4: Smoke-test the parser**

```bash
.venv/bin/govspend web --help
```

Expected:
```
usage: govspend web [-h] [--config CONFIG] [--host HOST] [--port PORT] [--db DB]
...
```

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add govspend_signals/cli.py
git commit -m "feat: add govspend web subcommand (starts FastAPI dashboard)"
```

---

## Task 7: Dockerfile + fly.toml

**Files:**
- Create: `Dockerfile`
- Create: `fly.toml`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -e ".[full,web]"

ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000

EXPOSE 8000

CMD ["govspend", "web", "--host", "0.0.0.0", "--db", "/data/signals.db"]
```

- [ ] **Step 2: Create `fly.toml`**

```toml
app = "govspend-signals"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[[mounts]]
  source = "govspend_data"
  destination = "/data"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true

[env]
  DASHBOARD_ORIGIN = "https://govspend-signals.fly.dev"
```

- [ ] **Step 3: Verify Dockerfile builds (optional — skip if no Docker)**

```bash
docker build -t govspend-signals . 2>&1 | tail -5
```

Expected: `Successfully built ...` (or skip if Docker not installed)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile fly.toml
git commit -m "chore: add Dockerfile and fly.toml for Fly.io deployment"
```

---

## Task 8: Full test suite green + smoke test

**Files:**
- Whatever needs fixing

- [ ] **Step 1: Run full suite**

```bash
.venv/bin/pytest tests/ -q --tb=short
```

Expected: all pass. Fix any failures before continuing.

- [ ] **Step 2: Smoke-test the web server starts**

```bash
EDGAR_USER_AGENT="test test@test.com" timeout 3 .venv/bin/govspend web 2>&1 || true
```

Expected: prints `govspend web  →  http://127.0.0.1:8000` then exits (timeout kills it).

- [ ] **Step 3: Smoke-test help**

```bash
.venv/bin/govspend web --help
.venv/bin/govspend sector-rotation --help
.venv/bin/govspend basket --help
.venv/bin/govspend options --help
```

Expected: all print usage without errors.

- [ ] **Step 4: Final commit and push**

```bash
git add -A
git commit -m "test: full suite green — 402+ tests passing, web dashboard complete"
git push origin claude/gov-spending-investment-tool-4a4ct
```

---

## Self-Review

**Spec coverage:**
- ✅ Single FastAPI app serving `/api/*` + static files
- ✅ 7 data endpoints (signals, sources, sector-rotation, watchlist, catalysts, basket, options)
- ✅ 6 auth endpoints (status, register/begin+finish, login/begin+finish, logout)
- ✅ WebAuthn passkey with py-webauthn 2.x
- ✅ Signed session cookie with itsdangerous
- ✅ credentials table in existing SQLite DB
- ✅ 30s auto-refresh via setInterval
- ✅ Dark theme matching terminal dashboard
- ✅ `govspend web` subcommand
- ✅ `[web]` optional dep group
- ✅ Dockerfile + fly.toml
- ✅ Tests for storage, data endpoints, auth endpoints

**Placeholder scan:** None found.

**Type consistency:**
- `Storage.store_credential(credential_id: str, ...)` used consistently in auth endpoints and tests
- `create_app(store, config, origin, secret)` signature consistent across all callsites
- `SignalRow.ticker`, `.amount_usd`, `.published` used correctly in data endpoints
