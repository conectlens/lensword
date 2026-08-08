"""Tests for the user-scoped BYOK AI credential API
(/api/v1/me/ai-credentials) — the never-leak-a-secret contract, rate
limiting, and unknown-provider handling. Every test runs with a real
AI_CREDENTIAL_ENCRYPTION_KEY configured via monkeypatch; encryption itself
is covered separately in tests/test_credential_vault.py.
"""
from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from app.api.deps import get_settings
from app.config import Settings


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    """A real Fernet key for every test in this file — without one, every
    write would 503 by design (see credential_vault.py), which is exactly
    right for a deploy that forgot to configure it, but not what most
    tests here are checking."""
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


def test_listing_credentials_requires_authentication(client):
    assert client.get("/api/v1/me/ai-credentials").status_code == 401


def test_a_new_account_has_no_configured_credentials(client, auth_headers):
    resp = client.get("/api/v1/me/ai-credentials", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == []


def test_putting_a_valid_gemini_credential_succeeds_and_never_echoes_the_key(client, auth_headers):
    headers = auth_headers()
    resp = client.put(
        "/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-a-very-distinctive-secret-abc123"}, headers=headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "gemini"
    assert body["details"] == {}
    assert "sk-a-very-distinctive-secret-abc123" not in resp.text


def test_a_configured_credential_then_appears_in_the_list(client, auth_headers):
    headers = auth_headers()
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-secret"}, headers=headers)

    resp = client.get("/api/v1/me/ai-credentials", headers=headers)

    assert resp.status_code == 200
    providers = [item["provider"] for item in resp.json()]
    assert providers == ["gemini"]
    assert "sk-secret" not in resp.text


def test_putting_an_invalid_payload_is_rejected_with_no_row_created(client, auth_headers):
    headers = auth_headers()
    resp = client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "   "}, headers=headers)

    assert resp.status_code == 422
    assert client.get("/api/v1/me/ai-credentials", headers=headers).json() == []


def test_putting_an_unknown_provider_returns_404(client, auth_headers):
    resp = client.put("/api/v1/me/ai-credentials/mistral", json={"api_key": "sk-x"}, headers=auth_headers())
    assert resp.status_code == 404
    assert "mistral" in resp.text


def test_a_second_put_for_the_same_provider_replaces_the_first(client, auth_headers):
    headers = auth_headers()
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-first"}, headers=headers)
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-second"}, headers=headers)

    assert len(client.get("/api/v1/me/ai-credentials", headers=headers).json()) == 1


def test_vertex_credential_reports_project_and_location_but_never_the_service_account_key(client, auth_headers):
    headers = auth_headers()
    service_account_json = json.dumps(
        {
            "type": "service_account",
            "project_id": "my-project",
            "private_key_id": "abc123",
            "private_key": "-----BEGIN PRIVATE KEY-----\nSUPER-SECRET-MARKER\n-----END PRIVATE KEY-----\n",
            "client_email": "test@my-project.iam.gserviceaccount.com",
            "client_id": "12345",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    resp = client.put(
        "/api/v1/me/ai-credentials/vertex",
        json={"service_account_json": service_account_json, "project_id": "my-project", "location": "us-central1"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["details"] == {"project_id": "my-project", "location": "us-central1"}
    assert "SUPER-SECRET-MARKER" not in resp.text
    assert "private_key" not in resp.text


def test_deleting_a_configured_credential_removes_it(client, auth_headers):
    headers = auth_headers()
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-secret"}, headers=headers)

    delete_resp = client.delete("/api/v1/me/ai-credentials/gemini", headers=headers)

    assert delete_resp.status_code == 204
    assert client.get("/api/v1/me/ai-credentials", headers=headers).json() == []


def test_deleting_a_credential_that_was_never_configured_returns_404(client, auth_headers):
    resp = client.delete("/api/v1/me/ai-credentials/gemini", headers=auth_headers())
    assert resp.status_code == 404


def test_deleting_an_unknown_provider_returns_404(client, auth_headers):
    resp = client.delete("/api/v1/me/ai-credentials/mistral", headers=auth_headers())
    assert resp.status_code == 404
    assert "mistral" in resp.text


def test_one_users_credentials_are_invisible_to_another(client, auth_headers):
    alex = auth_headers()
    sam = auth_headers(username="sam", email="sam@example.com")
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-alex-secret"}, headers=alex)

    assert client.get("/api/v1/me/ai-credentials", headers=sam).json() == []


def test_a_user_cannot_delete_another_users_credential(client, auth_headers):
    alex = auth_headers()
    sam = auth_headers(username="sam", email="sam@example.com")
    client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-alex-secret"}, headers=alex)

    resp = client.delete("/api/v1/me/ai-credentials/gemini", headers=sam)

    assert resp.status_code == 404
    assert client.get("/api/v1/me/ai-credentials", headers=alex).json() != []


def test_writing_a_credential_without_a_configured_encryption_key_returns_503(client, auth_headers, monkeypatch):
    monkeypatch.delenv("AI_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()

    resp = client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": "sk-secret"}, headers=auth_headers())

    assert resp.status_code == 503
    get_settings.cache_clear()


def test_writing_a_credential_is_rate_limited(client, auth_headers, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AI_CREDENTIAL_WRITES", "2")
    monkeypatch.setenv("RATE_LIMIT_AI_CREDENTIAL_WRITE_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    headers = auth_headers()

    statuses = [
        client.put("/api/v1/me/ai-credentials/gemini", json={"api_key": f"sk-{i}"}, headers=headers).status_code
        for i in range(3)
    ]

    assert statuses == [200, 200, 429]
    get_settings.cache_clear()
