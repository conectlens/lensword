from __future__ import annotations

from app.api.deps import _ai_provider
from app.config import get_settings
from app.infrastructure.models import UserModel


def _admin_headers(client, db_session):
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "admin", "email": "admin@example.com", "password": "supersecret1"},
    )
    assert response.status_code == 201
    user = db_session.get(UserModel, response.json()["user"]["id"])
    user.role = "admin"
    db_session.flush()
    return {"Authorization": f"Bearer {response.json()['token']['access_token']}"}


def test_ai_settings_are_admin_only(client, auth_headers):
    response = client.get("/api/v1/ai-settings", headers=auth_headers())
    assert response.status_code == 403


def test_admin_can_update_effective_ai_settings_and_they_persist(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SETTINGS_PATH", str(tmp_path / "ai-settings.json"))
    get_settings.cache_clear()
    _ai_provider.cache_clear()
    try:
        headers = _admin_headers(client, db_session)
        payload = {
            "provider": "ollama",
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
            "max_output_tokens": 240,
            "context_max_chars": 640,
        }
        updated = client.put("/api/v1/ai-settings", json=payload, headers=headers)
        read_back = client.get("/api/v1/ai-settings", headers=headers)
    finally:
        _ai_provider.cache_clear()
        get_settings.cache_clear()

    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "provider": "ollama",
        "model": "llama3.2",
        "base_url": "http://localhost:11434",
        "max_output_tokens": 240,
        "context_max_chars": 640,
        "gemini_model": "gemini-2.5-flash",
        "gemini_api_key_set": False,
        "vertex_project_id": None,
        "vertex_location": "us-central1",
        "vertex_model": "gemini-2.5-flash",
        "openai_model": "gpt-5.6",
        "openai_api_key_set": False,
    }
    assert read_back.json() == updated.json()


def test_admin_can_switch_to_a_cloud_provider_without_the_key_ever_coming_back(
    client, db_session, tmp_path, monkeypatch
):
    """Issue #315 TODO 1: the GET side must report whether a credential is
    configured, never the credential itself."""
    monkeypatch.setenv("AI_SETTINGS_PATH", str(tmp_path / "ai-settings.json"))
    get_settings.cache_clear()
    _ai_provider.cache_clear()
    try:
        headers = _admin_headers(client, db_session)
        payload = {
            "provider": "gemini",
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
            "max_output_tokens": 240,
            "context_max_chars": 640,
            "gemini_api_key": "super-secret-key",
        }
        updated = client.put("/api/v1/ai-settings", json=payload, headers=headers)
        read_back = client.get("/api/v1/ai-settings", headers=headers)
    finally:
        _ai_provider.cache_clear()
        get_settings.cache_clear()

    assert updated.status_code == 200, updated.text
    assert updated.json()["gemini_api_key_set"] is True
    assert "super-secret-key" not in updated.text
    assert "super-secret-key" not in read_back.text
    assert read_back.json()["gemini_api_key_set"] is True


def test_switching_to_a_cloud_provider_without_its_required_field_is_rejected(
    client, db_session, tmp_path, monkeypatch
):
    """Fail at admin-save time, not at the next AI request (issue #315)."""
    monkeypatch.setenv("AI_SETTINGS_PATH", str(tmp_path / "ai-settings.json"))
    get_settings.cache_clear()
    try:
        headers = _admin_headers(client, db_session)
        payload = {
            "provider": "gemini",
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
            "max_output_tokens": 240,
            "context_max_chars": 640,
            # gemini_api_key deliberately omitted
        }
        response = client.put("/api/v1/ai-settings", json=payload, headers=headers)
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert "gemini_api_key" in response.text


def test_ai_settings_reject_invalid_provider_and_non_positive_bounds(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SETTINGS_PATH", str(tmp_path / "ai-settings.json"))
    get_settings.cache_clear()
    try:
        headers = _admin_headers(client, db_session)
        base = {
            "provider": "not-a-provider",
            "model": "model",
            "base_url": "http://localhost:11434",
            "max_output_tokens": 200,
            "context_max_chars": 500,
        }
        invalid_provider = client.put("/api/v1/ai-settings", json=base, headers=headers)
        base["provider"] = "ollama"
        base["max_output_tokens"] = 0
        invalid_bound = client.put("/api/v1/ai-settings", json=base, headers=headers)
    finally:
        get_settings.cache_clear()

    assert invalid_provider.status_code == 422
    assert invalid_bound.status_code == 422
