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
    assert resp.json() == {
        "status": "unavailable",
        "detail": "The AI provider is not reachable — try again shortly.",
    }


def test_unavailable_detail_never_leaks_the_provider_address(client, auth_headers, override_provider):
    """The client gets a fixed, operator-agnostic sentence.

    str(httpx.URL) does not mask userinfo — only repr() does — so an operator
    who fronts Ollama with basic auth would otherwise have the password
    returned in a 200 response body. The specifics stay in the server log.
    """
    secret_url = "http://svc:hunter2@ollama.internal:11434"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    override_provider(OllamaProvider(base_url=secret_url, transport=httpx.MockTransport(handler)))
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.json()["status"] == "unavailable"
    assert "hunter2" not in resp.text
    assert "ollama.internal" not in resp.text
    assert "svc" not in resp.text


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


def test_cannot_suggest_for_another_users_word(client, auth_headers, override_provider):
    """A word id belonging to someone else must be refused before the
    provider is consulted. An LLM mnemonic almost always restates the source
    word, so answering here would echo another account's vocabulary straight
    back in the response body."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("the provider must not be called for another user's word")

    override_provider(_mock_ollama(handler))
    headers_a = auth_headers(username="alex", email="alex@example.com")
    headers_b = auth_headers(username="sam", email="sam@example.com")
    word = _setup_word(client, headers_a, term="Perro", translation="Dog")

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers_b)

    assert resp.status_code == 403
    assert "Perro" not in resp.text
    assert "Dog" not in resp.text


def test_cannot_probe_another_users_word_while_ai_is_disabled(client, auth_headers):
    """The ownership check must run even when no provider is configured.

    Otherwise a foreign word id answers 200 {"status": "disabled"} while an
    unused one answers 404, which enumerates other accounts' ids. This closes
    that 200-vs-404 signal. The residual 403-vs-404 distinction is the same
    one every sibling word endpoint already has (see routers/words.py), so
    this follows the existing convention rather than inventing a new one.
    """
    headers_a = auth_headers(username="alex", email="alex@example.com")
    headers_b = auth_headers(username="sam", email="sam@example.com")
    word = _setup_word(client, headers_a)

    existing = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers_b)
    missing = client.post("/api/v1/words/999999/mnemonics/suggest", headers=headers_b)

    assert existing.status_code == 403
    assert existing.json() != {"status": "disabled"}
    assert missing.status_code == 404


def test_owner_can_still_suggest_for_their_own_word(client, auth_headers, override_provider):
    """The ownership check must not lock out the legitimate owner."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "still works", "done": True})

    override_provider(_mock_ollama(handler))
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "text": "still works"}


def test_requires_authentication(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/mnemonics/suggest")

    assert resp.status_code == 401
