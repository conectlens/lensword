"""Tests for GeminiProvider and VertexAIProvider (issue #315).

Mocked via httpx.MockTransport injected through the real google-genai SDK's
own `HttpOptions.httpx_async_client` — verified directly against the
installed SDK version while building this adapter (see the design notes in
app/infrastructure/ai_providers/google.py). This exercises the SDK's actual
request construction and its own error-mapping
(google.genai.errors.APIError), not just this adapter's code around it, for
real coverage without ever making a live network call — the same level of
coverage OllamaProvider's own tests get from httpx.MockTransport directly.

Vertex AI authenticates through google-auth rather than a bearer API key, so
its tests inject a static, non-refreshing `google.oauth2.credentials.
Credentials` — confirmed necessary and sufficient against the installed SDK:
unset/anonymous credentials attempt a real token refresh even against a
mocked transport and fail before the mock is ever reached, while a
pre-set token sidesteps that refresh entirely.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from google.auth import exceptions as google_auth_errors
from google.auth.credentials import Credentials as GoogleCredentialsBase
from google.genai import types as genai_types
from google.oauth2.credentials import Credentials as StaticCredentials

from app.config import Settings
from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai_providers.factory import build_ai_provider
from app.infrastructure.ai_providers.google import GeminiProvider, VertexAIProvider


def _http_options(handler, *, retries: int = 1) -> genai_types.HttpOptions:
    # retries=1 ("no retries", per HttpRetryOptions' own docstring: "If 0 or
    # 1, it means no retries") keeps every failure-path test here fast and
    # deterministic instead of waiting through the SDK's default backoff.
    return genai_types.HttpOptions(
        httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_options=genai_types.HttpRetryOptions(attempts=retries),
    )


def _gemini(handler, **kwargs) -> GeminiProvider:
    return GeminiProvider(api_key="fake-test-key", http_options=_http_options(handler), **kwargs)


def _vertex(handler, **kwargs) -> VertexAIProvider:
    return VertexAIProvider(
        project_id="test-project",
        credentials=StaticCredentials(token="fake-static-token"),
        http_options=_http_options(handler),
        **kwargs,
    )


def _text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP"}]},
    )


def _request_text(request: httpx.Request) -> str:
    body = json.loads(request.content)
    return body["contents"][0]["parts"][0]["text"]


def _suggest(provider, word: str = "ubiquitous", context: str = "common in academic writing") -> str:
    return asyncio.run(provider.suggest_mnemonic(word, context))


def _enrich(provider, term: str = "prestar"):
    return asyncio.run(provider.enrich_word(term, "English", "Spanish"))


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_suggest_mnemonic_returns_generated_text(factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "ubiquitous" in _request_text(request)
        return _text_response("Think 'you-BIK-wit-us'")

    provider = factory(handler)

    assert _suggest(provider) == "Think 'you-BIK-wit-us'"


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_suggest_mnemonic_strips_surrounding_whitespace(factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("  padded answer  \n")

    provider = factory(handler)

    assert _suggest(provider) == "padded answer"


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_enrich_word_sends_json_mode_and_parses_the_response(factory):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _text_response(json.dumps({"tags": ["finance", "favors"], "cefr_level": "B1"}))

    provider = factory(handler)
    enrichment = _enrich(provider)

    assert captured["generationConfig"]["responseMimeType"] == "application/json"
    assert enrichment.tags == ["finance", "favors"]
    assert enrichment.topics == ["finance", "favors"]
    assert enrichment.provider in ("gemini", "vertex")


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_a_truncated_json_response_reports_being_cut_off(factory):
    """The exact truncation signature (issue #211): a response cut off
    mid-string by the output-token budget must not be reported as "the
    provider is not reachable" — the provider was reached and answered."""
    truncated = '{"translations": ["prestar"], "definitions": ["to len'

    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response(truncated)

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        _enrich(provider)
    assert "cut off" in str(excinfo.value)


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_malformed_json_from_the_start_keeps_the_generic_message(factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("not json at all, and plenty more text follows this point")

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        _enrich(provider)
    assert "cut off" not in str(excinfo.value)


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}}),
        (429, {"error": {"code": 429, "message": "Rate limit exceeded", "status": "RESOURCE_EXHAUSTED"}}),
        (500, {"error": {"code": 500, "message": "Internal error", "status": "INTERNAL"}}),
    ],
    ids=["auth", "rate-limit", "server-error"],
)
def test_api_error_status_codes_map_to_unavailable(factory, status, body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_connection_failure_maps_to_unavailable(factory):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_timeout_maps_to_unavailable(factory):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


@pytest.mark.parametrize("factory", [_gemini, _vertex], ids=["gemini", "vertex"])
def test_a_safety_blocked_response_with_no_text_maps_to_unavailable(factory):
    """response.text is None when every candidate was blocked — a real
    shape the SDK can hand back (confirmed against the installed SDK), not
    a hypothetical."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    provider = factory(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


def test_vertex_credential_resolution_failure_maps_to_unavailable():
    """Vertex-specific failure mode: credential resolution itself failing
    (a broken/expired service-account key, no ADC configured) is reached
    before any HTTP request, so it is a google.auth error, not a
    genai_errors.APIError — must still map to AIProviderUnavailableError,
    never leak as a raw google.auth exception."""

    class _BrokenCredentials(GoogleCredentialsBase):
        def refresh(self, request):
            raise google_auth_errors.RefreshError("token endpoint unreachable")

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("the mocked transport must not be reached when credentials fail to refresh")

    provider = VertexAIProvider(
        project_id="test-project", credentials=_BrokenCredentials(), http_options=_http_options(handler),
    )

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


# --- generate_learning_path's tolerance for a dict-wrapped array ----------


def test_generate_learning_path_unwraps_a_dict_wrapped_array():
    """Gemini's JSON mode can return a bare array directly (unlike OpenAI's
    strict json_object mode) — but a model can still choose to wrap one in
    an object, which the shared base class's unwrap logic must still
    handle regardless of which provider produced it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response(json.dumps({"milestones": [{"title": "Step 1"}]}))

    provider = _gemini(handler)

    result = asyncio.run(provider.generate_learning_path("order food", "Spanish", 8, 2))
    assert result == [{"title": "Step 1"}]


# --- build_ai_provider factory --------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_build_ai_provider_returns_gemini_provider_when_configured():
    provider = build_ai_provider(_settings(ai_provider="gemini", gemini_api_key="key-123"))

    assert isinstance(provider, GeminiProvider)
    assert provider._model == "gemini-2.5-flash"


def test_build_ai_provider_passes_configured_gemini_model_and_bounds():
    provider = build_ai_provider(
        _settings(
            ai_provider="gemini",
            gemini_api_key="key-123",
            gemini_model="gemini-2.0-flash",
            ai_max_output_tokens=42,
            ai_context_max_chars=77,
        )
    )

    assert provider is not None
    assert provider._model == "gemini-2.0-flash"
    assert provider._max_output_tokens == 42
    assert provider._context_max_chars == 77


def test_build_ai_provider_rejects_gemini_without_an_api_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_ai_provider(_settings(ai_provider="gemini"))


def test_build_ai_provider_returns_vertex_provider_when_configured():
    provider = build_ai_provider(_settings(ai_provider="vertex", vertex_project_id="proj-1"))

    assert isinstance(provider, VertexAIProvider)
    assert provider._model == "gemini-2.5-flash"


def test_build_ai_provider_passes_configured_vertex_project_location_and_model():
    provider = build_ai_provider(
        _settings(
            ai_provider="vertex",
            vertex_project_id="proj-1",
            vertex_location="europe-west1",
            vertex_model="gemini-2.0-flash",
        )
    )

    assert provider is not None
    assert provider._model == "gemini-2.0-flash"


def test_build_ai_provider_rejects_vertex_without_a_project_id():
    with pytest.raises(ValueError, match="VERTEX_PROJECT_ID"):
        build_ai_provider(_settings(ai_provider="vertex"))


def test_supported_ai_providers_lists_gemini_and_vertex():
    from app.infrastructure.ai_providers.factory import SUPPORTED_AI_PROVIDERS

    assert "gemini" in SUPPORTED_AI_PROVIDERS
    assert "vertex" in SUPPORTED_AI_PROVIDERS
