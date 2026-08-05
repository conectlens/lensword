"""The Ollama probe endpoint and response caching over HTTP (issue #139).

The cache tests matter more than they look: a cache that serves one account's
response to another, or one model's to another, produces a wrong answer only
when a stale entry happens to exist — the bug nobody can reproduce.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure.ollama_probe import OllamaStatus


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


@pytest.fixture()
def admin_headers(client, db_session):
    """Registered then promoted directly, since there is no public signup path
    for admins — the same approach as test_admin_api.py."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "root", "email": "root@example.com", "password": "supersecret1"},
    )
    user_id = resp.json()["user"]["id"]
    token = resp.json()["token"]["access_token"]

    from app.infrastructure.models import UserModel

    db_session.get(UserModel, user_id).role = "admin"
    db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clean_cache():
    from app.api.routers.ai import clear_ai_response_cache

    clear_ai_response_cache()
    yield
    clear_ai_response_cache()


# --- The probe is admin-only ------------------------------------------------


def test_an_ordinary_user_cannot_probe(client, headers):
    """The response names the deployment's base URL and every model installed
    on that host — infrastructure detail, not something a learner needs."""
    assert client.get("/api/v1/ai-settings/probe", headers=headers).status_code == 403


def test_the_probe_requires_authentication(client):
    assert client.get("/api/v1/ai-settings/probe").status_code == 401


def test_an_admin_gets_the_probe_result(client, admin_headers):
    ready = OllamaStatus(
        reachable=True,
        models=["llama3.2:latest"],
        configured_model="llama3.2",
        configured_model_installed=True,
        detail="Ollama is running with 1 model(s) installed.",
    )

    with patch("app.api.routers.ai_settings.probe_ollama", return_value=ready):
        body = client.get("/api/v1/ai-settings/probe", headers=admin_headers).json()

    assert body["ready"] is True
    assert body["models"] == ["llama3.2:latest"]


def test_a_running_daemon_with_no_model_says_what_to_pull(client, admin_headers):
    """"AI unavailable" would leave someone with Ollama running and no model
    pulled with no idea what to do next."""
    empty = OllamaStatus(
        reachable=True,
        models=[],
        configured_model="llama3.2",
        configured_model_installed=False,
        detail="Ollama is running, but no models are installed. Run `ollama pull llama3.2`.",
    )

    with patch("app.api.routers.ai_settings.probe_ollama", return_value=empty):
        body = client.get("/api/v1/ai-settings/probe", headers=admin_headers).json()

    assert body["reachable"] is True
    assert body["ready"] is False
    assert "ollama pull" in body["detail"]


def test_an_unreachable_daemon_is_reported_rather_than_erroring(client, admin_headers):
    """A detection step that fails the request it runs in would make onboarding
    worse than not having one."""
    down = OllamaStatus(reachable=False, detail="Nothing is answering at http://localhost:11434.")

    with patch("app.api.routers.ai_settings.probe_ollama", return_value=down):
        resp = client.get("/api/v1/ai-settings/probe", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["reachable"] is False


# --- Response caching -------------------------------------------------------


def _enrichment(term: str = "gato"):
    from app.domain.services.ai_provider import WordEnrichment

    return WordEnrichment(
        term=term,
        target_language="English",
        translations=["cat"],
        definitions=["a small feline"],
        examples=["El gato duerme."],
        part_of_speech="noun",
        cefr_level="A1",
        provider="ollama",
        model="llama3.2",
    )


class _CountingProvider:
    """Counts generations so a cache hit is observable."""

    def __init__(self):
        self.calls = 0

    async def enrich_word(self, term, source_language, target_language):
        self.calls += 1
        return _enrichment(term)


class _use_provider:
    """Override just the AI provider, for the duration of a block.

    Only this key is removed afterwards. `dependency_overrides.clear()` would
    also drop the test database override the client fixture installs, and every
    request after it would fail authentication for reasons that look nothing
    like the cause.
    """

    def __init__(self, provider):
        self.provider = provider

    def __enter__(self):
        from app.api import deps
        from app.main import app

        self.app = app
        self.key = deps.get_ai_provider
        app.dependency_overrides[self.key] = lambda: self.provider
        return self

    def __exit__(self, *exc):
        self.app.dependency_overrides.pop(self.key, None)
        return False


def test_asking_the_same_thing_twice_calls_the_model_once(client, headers):
    """A local model takes seconds per generation. Asking it the same question
    twice in a minute is the difference between instant and unusable."""
    provider = _CountingProvider()
    with _use_provider(provider):
        body = {"term": "gato", "source_language": "Spanish", "target_language": "English"}
        first = client.post("/api/v1/ai/enrich", json=body, headers=headers)
        second = client.post("/api/v1/ai/enrich", json=body, headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    assert provider.calls == 1


def test_a_different_term_is_generated_afresh(client, headers):
    provider = _CountingProvider()
    with _use_provider(provider):
        for term in ("gato", "perro"):
            client.post(
                "/api/v1/ai/enrich",
                json={"term": term, "source_language": "Spanish", "target_language": "English"},
                headers=headers,
            )

    assert provider.calls == 2


def test_one_accounts_cached_response_is_never_served_to_another(client, auth_headers):
    """Prompts carry the learner's own vocabulary and context."""
    alex = auth_headers()
    sam = auth_headers(username="sam", email="sam@example.com")

    provider = _CountingProvider()
    with _use_provider(provider):
        body = {"term": "gato", "source_language": "Spanish", "target_language": "English"}
        client.post("/api/v1/ai/enrich", json=body, headers=alex)
        client.post("/api/v1/ai/enrich", json=body, headers=sam)

    assert provider.calls == 2


def test_a_failure_is_not_cached(client, headers):
    """A model that was unreachable a minute ago may be running now, and
    caching the failure would keep a working system broken for the TTL."""
    from app.domain.exceptions import AIProviderUnavailableError

    class _Flaky:
        def __init__(self):
            self.calls = 0

        async def enrich_word(self, term, source_language, target_language):
            self.calls += 1
            if self.calls == 1:
                raise AIProviderUnavailableError("model is starting")
            return _enrichment(term)

    provider = _Flaky()
    with _use_provider(provider):
        body = {"term": "gato", "source_language": "Spanish", "target_language": "English"}
        first = client.post("/api/v1/ai/enrich", json=body, headers=headers)
        second = client.post("/api/v1/ai/enrich", json=body, headers=headers)

    assert first.status_code == 503
    assert second.status_code == 200
    assert provider.calls == 2
