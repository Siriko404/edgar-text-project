"""Tests for payment entitlement: checkout metadata, webhook provisioning."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    """App client with an isolated auth store file."""
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth_store.json"))
    import importlib

    import api

    importlib.reload(api)
    return TestClient(api.app)


class TestPaymentEntitlement:
    def test_signup_premium_blocked_without_payment(self, isolated_client):
        response = isolated_client.post(
            "/auth/signup",
            json={"email": "rich@example.com", "password": "pw-123456", "tier": "premium"},
        )
        assert response.status_code == 403
        assert "payment" in response.json()["detail"].lower()

    @patch("api.stripe.checkout.Session.create")
    def test_checkout_includes_tier_metadata(self, mock_create, isolated_client):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session123"
        mock_create.return_value = mock_session

        signup = isolated_client.post(
            "/auth/signup",
            json={"email": "buyer@example.com", "password": "pw-123456", "tier": "free"},
        )
        assert signup.status_code == 200
        token = isolated_client.post(
            "/auth/login",
            json={"email": "buyer@example.com", "password": "pw-123456"},
        ).json()["access_token"]

        response = isolated_client.post(
            "/create-checkout-session",
            json={"tier": "premium"},
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        _, kwargs = mock_create.call_args
        assert kwargs["metadata"]["tier"] == "premium"
        assert kwargs["metadata"]["email"] == "buyer@example.com"

    @patch("api.stripe.Webhook.construct_event")
    def test_webhook_provisions_paid_tier_once(self, mock_construct, isolated_client):
        import auth_store

        isolated_client.post(
            "/auth/signup",
            json={"email": "paying@example.com", "password": "pw-123456", "tier": "free"},
        )
        assert auth_store.get_user_by_email("paying@example.com")["tier"] == "free"

        mock_construct.return_value = {
            "id": "evt_provision_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_123",
                    "metadata": {"email": "paying@example.com", "tier": "premium"},
                }
            },
        }
        headers = {"stripe-signature": "test_signature"}
        first = isolated_client.post(
            "/webhook", content=b"payload", headers=headers
        )
        assert first.status_code == 200
        assert first.json()["status"] == "success"
        assert auth_store.get_user_by_email("paying@example.com")["tier"] == "premium"

        second = isolated_client.post(
            "/webhook", content=b"payload", headers=headers
        )
        assert second.status_code == 200
        assert second.json()["status"] == "already processed"
