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
