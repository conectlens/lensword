"""API tests for POST /api/v1/words/{word_id}/mnemonics/suggest
(ROADMAP.md Phase 1.1 / issue #22).

The endpoint always answers 200 with a discriminated `status`, because "no
AI provider is configured" is a deployment setting rather than a failure and
must not reach the client as a 4xx/5xx. The two provider-backed branches use
an injected httpx.MockTransport, so nothing here depends on a running Ollama
daemon.
"""
from __future__ import annotations

import httpx
import pytest

from app.api.deps import get_ai_provider
from app.infrastructure.ai import OllamaProvider
from app.main import app


def _setup_word(client, headers, term="Perro", translation="Dog"):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    return client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": "Spanish", "translations": [translation]},
        headers=headers,
    ).json()


@pytest.fixture()
def override_provider():
    """Swap the app's AI provider for the duration of one test."""
    installed = []

    def _install(provider):
        app.dependency_overrides[get_ai_provider] = lambda: provider
        installed.append(True)

    yield _install
    app.dependency_overrides.pop(get_ai_provider, None)


def _mock_ollama(handler) -> OllamaProvider:
    return OllamaProvider(transport=httpx.MockTransport(handler))


def test_returns_disabled_when_no_provider_is_configured(client, auth_headers):
    """The default deployment: nothing configured, so a calm 200 rather than
    an error the UI would have to string-match."""
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "disabled"}


def test_returns_ok_with_the_generated_text(client, auth_headers, override_provider):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "A 'perro' guards the 'pero' tree.", "done": True})

    override_provider(_mock_ollama(handler))
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "text": "A 'perro' guards the 'pero' tree."}


def test_sends_the_word_term_to_the_provider(client, auth_headers, override_provider):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.read().decode())
        return httpx.Response(200, json={"response": "ok", "done": True})

    override_provider(_mock_ollama(handler))
    headers = auth_headers()
    word = _setup_word(client, headers, term="Ephemeral", translation="Fleeting")

    client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert len(seen) == 1
    assert "Ephemeral" in seen[0]


def test_returns_unavailable_when_the_provider_cannot_be_reached(client, auth_headers, override_provider):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    override_provider(_mock_ollama(handler))
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["detail"].strip() != ""


def test_returns_unavailable_when_the_model_is_not_pulled(client, auth_headers, override_provider):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    override_provider(_mock_ollama(handler))
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "unavailable"


def test_unknown_word_is_a_404(client, auth_headers, override_provider):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("the provider must not be called for an unknown word")

    override_provider(_mock_ollama(handler))
    headers = auth_headers()

    resp = client.post("/api/v1/words/999999/mnemonics/suggest", headers=headers)

    assert resp.status_code == 404


def test_unknown_word_is_a_404_even_when_ai_is_disabled(client, auth_headers):
    headers = auth_headers()

    resp = client.post("/api/v1/words/999999/mnemonics/suggest", headers=headers)

    assert resp.status_code == 404


def test_requires_authentication(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest")

    assert resp.status_code == 401
