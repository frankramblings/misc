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
