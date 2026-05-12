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
