from __future__ import annotations

from app.api.deps import get_ai_provider
from app.config import get_settings
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.ai_provider import ExtractedVocabulary
from app.main import app


def _group(client, headers):
    response = client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    )
    assert response.status_code == 201
    return response.json()


class _Provider:
    async def extract_vocabulary(self, text, source_language, target_language, max_items):
        return [ExtractedVocabulary(term="perro", translations=["dog"], examples=["El perro corre."])]


class _UnavailableProvider:
    async def extract_vocabulary(self, text, source_language, target_language, max_items):
        raise AIProviderUnavailableError()


def test_extract_returns_disabled_when_ai_is_off(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)

    response = client.post(
        "/api/v1/extract",
        json={"group_id": group["id"], "text": "A short passage", "target_language": "Spanish"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}


def test_extract_uses_the_configured_provider(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = _Provider
    try:
        headers = auth_headers()
        group = _group(client, headers)
        response = client.post(
            "/api/v1/extract",
            json={"group_id": group["id"], "text": "A short passage", "target_language": "Spanish"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "source": "ai",
        "items": [{"term": "perro", "translations": ["dog"], "examples": ["El perro corre."], "cefr_level": None}],
    }


def test_extract_reports_unavailable_without_leaking_transport_details(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = _UnavailableProvider
    try:
        headers = auth_headers()
        group = _group(client, headers)
        response = client.post(
            "/api/v1/extract",
            json={"group_id": group["id"], "text": "A short passage", "target_language": "Spanish"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_extract_feature_flag_enables_the_explicit_fallback(client, auth_headers, monkeypatch):
    monkeypatch.setenv("AI_EXTRACT_FALLBACK_ENABLED", "true")
    get_settings.cache_clear()
    try:
        headers = auth_headers()
        group = _group(client, headers)
        response = client.post(
            "/api/v1/extract",
            json={"group_id": group["id"], "text": "Swift foxes wander swiftly", "target_language": "Spanish"},
            headers=headers,
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["source"] == "fallback"


def test_extract_refuses_another_users_group_before_calling_the_provider(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = _Provider
    try:
        owner_headers = auth_headers(username="owner", email="owner@example.com")
        other_headers = auth_headers(username="other", email="other@example.com")
        group = _group(client, owner_headers)
        response = client.post(
            "/api/v1/extract",
            json={"group_id": group["id"], "text": "private vocabulary", "target_language": "Spanish"},
            headers=other_headers,
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 403
