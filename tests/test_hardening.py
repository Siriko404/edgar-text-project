"""Regression tests for the security fixes: each fails on the code it replaced."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth_store.json"))
    monkeypatch.delenv("ENABLE_DEMO_ACCOUNT", raising=False)
    import api

    importlib.reload(api)
    return TestClient(api.app)


def signup(client, email, password="pw-123456"):
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()["user_id"]


def test_same_local_part_does_not_share_an_identity(client):
    _, a = signup(client, "alice@one.example")
    _, b = signup(client, "alice@two.example")
    assert a != b


def test_one_account_cannot_revoke_another_accounts_key_by_short_id(client):
    headers_a, _ = signup(client, "owner@one.example")
    headers_b, _ = signup(client, "owner@two.example")
    key_id = client.post(
        "/auth/api-key", json={"tier": "free"}, headers=headers_a
    ).json()["key_id"]
    assert len(key_id) >= 8
    assert (
        client.delete(f"/auth/api-key/{key_id}", headers=headers_b).status_code == 404
    )
    assert (
        client.delete(f"/auth/api-key/{key_id[:1]}", headers=headers_a).status_code
        == 404
    )
    assert (
        client.delete(f"/auth/api-key/{key_id}", headers=headers_a).status_code == 200
    )


def test_demo_account_is_off_unless_enabled(client, monkeypatch):
    import auth
    import auth_store

    assert auth.initialize_demo_keys() == []
    assert auth_store.get_user_by_email("demo@example.com") is None
    monkeypatch.setenv("ENABLE_DEMO_ACCOUNT", "1")
    assert len(auth.initialize_demo_keys()) == 3
    assert auth_store.get_user_by_email("demo@example.com") is not None


def test_metrics_requires_authentication(client):
    assert client.get("/metrics").status_code == 401
    headers, _ = signup(client, "metrics@example.com")
    assert client.get("/metrics", headers=headers).status_code == 200


def test_short_password_rejected_at_signup(client):
    r = client.post(
        "/auth/signup", json={"email": "short@example.com", "password": "abc"}
    )
    assert r.status_code == 422


def test_password_hash_uses_600k_rounds_and_reads_old_hashes():
    import hashlib

    import auth_store

    stored = auth_store.hash_password("correct horse")
    assert stored.startswith("pbkdf2_sha256$600000$")
    assert auth_store.check_password("correct horse", stored)
    assert not auth_store.check_password("wrong", stored)
    salt = "ab" * 8
    legacy = (
        salt
        + "$"
        + hashlib.pbkdf2_hmac("sha256", b"old-pw", salt.encode(), 100_000).hex()
    )
    assert auth_store.check_password("old-pw", legacy)
    assert not auth_store.check_password("x", "pbkdf2_sha256$999999999$s$d")


def test_placeholder_jwt_secret_is_not_used(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "change_me_to_a_stable_secret")
    import auth

    importlib.reload(auth)
    assert auth.JWT_SECRET_KEY != "change_me_to_a_stable_secret"
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    importlib.reload(auth)
    assert auth.JWT_SECRET_KEY == "x" * 40
