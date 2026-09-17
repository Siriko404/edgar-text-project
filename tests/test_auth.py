"""Tests for persisted auth: signup/login/keys survive and verify correctly."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    """App client with an isolated auth store file."""
    store = str(tmp_path / "auth_store.json")
    monkeypatch.setenv("AUTH_STORE_PATH", store)
    import importlib

    import api

    importlib.reload(api)
    return TestClient(api.app)


class TestDurableAuth:
    def test_signup_login_key_roundtrip(self, isolated_client):
        email = "roundtrip@example.com"
        signup = isolated_client.post(
            "/auth/signup",
            json={"email": email, "password": "s3cret-pw", "tier": "free"},
        )
        assert signup.status_code == 200, signup.text
        assert signup.json()["tier"] == "free"

        login = isolated_client.post(
            "/auth/login", json={"email": email, "password": "s3cret-pw"}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        key_resp = isolated_client.post(
            "/auth/api-key",
            json={"tier": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert key_resp.status_code == 200, key_resp.text
        api_key = key_resp.json()["api_key"]

        me = isolated_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {api_key}"}
        )
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["tier"] == "free"
        assert body["auth_type"] == "api_key"

    def test_signup_duplicate_conflicts(self, isolated_client):
        email = "dupe@example.com"
        first = isolated_client.post(
            "/auth/signup",
            json={"email": email, "password": "pw-one-123", "tier": "free"},
        )
        assert first.status_code == 200
        second = isolated_client.post(
            "/auth/signup",
            json={"email": email, "password": "pw-two-123", "tier": "free"},
        )
        assert second.status_code == 409

    def test_login_wrong_password_rejected(self, isolated_client):
        email = "wrongpw@example.com"
        assert (
            isolated_client.post(
                "/auth/signup",
                json={"email": email, "password": "right-pw-1", "tier": "free"},
            ).status_code
            == 200
        )
        bad = isolated_client.post(
            "/auth/login", json={"email": email, "password": "wrong-pw-1"}
        )
        assert bad.status_code == 401

    def test_store_file_written(self, isolated_client, tmp_path):
        import json

        isolated_client.post(
            "/auth/signup",
            json={
                "email": "filecheck@example.com",
                "password": "pw-123456",
                "tier": "basic",
            },
        )
        store_file = os.getenv("AUTH_STORE_PATH")
        assert store_file and os.path.isfile(store_file)
        key_resp = isolated_client.post(
            "/auth/login",
            json={"email": "filecheck@example.com", "password": "pw-123456"},
        )
        token = key_resp.json()["access_token"]
        created = isolated_client.post(
            "/auth/api-key",
            json={"tier": "basic"},
            headers={"Authorization": f"Bearer {token}"},
        )
        full_key = created.json()["api_key"]
        with open(store_file, encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        assert "filecheck@example.com" in data["users"]
        assert data["users"]["filecheck@example.com"]["tier"] == "basic"
        stored_hash = data["users"]["filecheck@example.com"]["password_hash"]
        assert "pw-123456" not in stored_hash
        # Plaintext secrets never touch disk
        assert "pw-123456" not in raw
        assert full_key not in raw

    def test_revoke_own_key(self, isolated_client):
        isolated_client.post(
            "/auth/signup",
            json={
                "email": "owner@example.com",
                "password": "pw-123456",
                "tier": "free",
            },
        )
        token = isolated_client.post(
            "/auth/login",
            json={"email": "owner@example.com", "password": "pw-123456"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        key_id = isolated_client.post(
            "/auth/api-key", json={"tier": "free"}, headers=headers
        ).json()["key_id"]
        revoked = isolated_client.delete(f"/auth/api-key/{key_id}", headers=headers)
        assert revoked.status_code == 200
        again = isolated_client.delete(f"/auth/api-key/{key_id}", headers=headers)
        assert again.status_code == 404

    def test_revoke_foreign_key_denied(self, isolated_client):
        isolated_client.post(
            "/auth/signup",
            json={
                "email": "victim@example.com",
                "password": "pw-123456",
                "tier": "free",
            },
        )
        victim_token = isolated_client.post(
            "/auth/login",
            json={"email": "victim@example.com", "password": "pw-123456"},
        ).json()["access_token"]
        victim_key = isolated_client.post(
            "/auth/api-key",
            json={"tier": "free"},
            headers={"Authorization": f"Bearer {victim_token}"},
        ).json()["key_id"]
        isolated_client.post(
            "/auth/signup",
            json={
                "email": "attacker@example.com",
                "password": "pw-123456",
                "tier": "free",
            },
        )
        attacker_token = isolated_client.post(
            "/auth/login",
            json={"email": "attacker@example.com", "password": "pw-123456"},
        ).json()["access_token"]
        denied = isolated_client.delete(
            f"/auth/api-key/{victim_key}",
            headers={"Authorization": f"Bearer {attacker_token}"},
        )
        assert denied.status_code == 404
        # Victim key still works
        me = isolated_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {victim_token}"}
        )
        assert me.status_code == 200
