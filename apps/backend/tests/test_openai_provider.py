"""Tests for OpenAIProvider (issue #315).

Mocked via httpx.MockTransport injected through the real openai SDK's own
`http_client` constructor argument — verified directly against the installed
SDK version (AsyncOpenAI(http_client=httpx.AsyncClient(transport=httpx.
MockTransport(handler)))), the same test-injection pattern OllamaProvider's
own `transport` param and GeminiProvider/VertexAIProvider's `http_options`
use. This exercises the SDK's actual request construction and its own
status-code error hierarchy (openai.APIStatusError and subclasses), not just
this adapter's code around it, for real coverage without a live network
call.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai_providers.factory import build_ai_provider
from app.infrastructure.ai_providers.openai_provider import OpenAIProvider


def _provider(handler, **kwargs) -> OpenAIProvider:
    # max_retries defaults to the SDK's own 2 in production; tests pin it to
    # 0 so a failure-path test does not sit through retry backoff.
    return OpenAIProvider(
        api_key="fake-test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-5.6-luna",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
        },
    )


def _request_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _suggest(provider, word: str = "ubiquitous", context: str = "common in academic writing") -> str:
    return asyncio.run(provider.suggest_mnemonic(word, context))


def _enrich(provider, term: str = "prestar"):
    return asyncio.run(provider.enrich_word(term, "English", "Spanish"))


def test_suggest_mnemonic_returns_generated_text():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _request_body(request)
        assert body["model"] == "gpt-5.6-luna"
        assert "ubiquitous" in body["messages"][1]["content"]
        assert "response_format" not in body
        return _chat_response("Think 'you-BIK-wit-us'")

    provider = _provider(handler)

    assert _suggest(provider) == "Think 'you-BIK-wit-us'"


def test_suggest_mnemonic_strips_surrounding_whitespace():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("  padded answer  \n")

    provider = _provider(handler)

    assert _suggest(provider) == "padded answer"


def test_enrich_word_sends_json_object_mode_and_parses_the_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(_request_body(request))
        return _chat_response(json.dumps({"tags": ["finance", "favors"], "cefr_level": "B1"}))

    provider = _provider(handler)
    enrichment = _enrich(provider)

    assert captured["response_format"] == {"type": "json_object"}
    assert enrichment.tags == ["finance", "favors"]
    assert enrichment.topics == ["finance", "favors"]
    assert enrichment.provider == "openai"


def test_a_truncated_json_response_reports_being_cut_off():
    truncated = '{"translations": ["prestar"], "definitions": ["to len'

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(truncated)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        _enrich(provider)
    assert "cut off" in str(excinfo.value)


def test_malformed_json_from_the_start_keeps_the_generic_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("not json at all, and plenty more text follows this point")

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        _enrich(provider)
    assert "cut off" not in str(excinfo.value)


@pytest.mark.parametrize(
    "status,body",
    [
        (400, {"error": {"message": "bad request", "type": "invalid_request_error"}}),
        (401, {"error": {"message": "invalid api key", "type": "invalid_request_error"}}),
        (403, {"error": {"message": "forbidden", "type": "permission_error"}}),
        (404, {"error": {"message": "model not found", "type": "invalid_request_error"}}),
        (429, {"error": {"message": "rate limited", "type": "rate_limit_error"}}),
        (500, {"error": {"message": "server error", "type": "server_error"}}),
    ],
    ids=["bad-request", "auth", "permission", "not-found", "rate-limit", "server-error"],
)
def test_api_status_errors_map_to_unavailable(status, body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, request=request)

    provider = _provider(handler, max_output_tokens=10)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


def test_connection_failure_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


def test_timeout_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


def test_a_response_with_no_choices_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "chatcmpl-empty", "object": "chat.completion", "created": 1, "model": "gpt-5.6-luna", "choices": []},
        )

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider)


def test_generate_learning_path_unwraps_a_dict_wrapped_array():
    """response_format={"type": "json_object"} means OpenAI's JSON mode can
    never return a bare top-level array — a model asked for "a JSON array"
    under this mode has to wrap it in an object, and the shared base
    class's unwrap logic must handle that regardless of which provider
    produced it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(json.dumps({"milestones": [{"title": "Step 1"}]}))

    provider = _provider(handler)

    result = asyncio.run(provider.generate_learning_path("order food", "Spanish", 8, 2))
    assert result == [{"title": "Step 1"}]


def test_coach_methods_send_the_delimited_evidence_block():
    from app.domain.services.companion_coach import CoachEvidence, CoachRequest

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(_request_body(request))
        return _chat_response(json.dumps({"text": "Some helpful content.", "evidence_ids": ["obs-1"]}))

    provider = _provider(handler)
    request = CoachRequest(
        task="Explain the isolate intervention",
        target_language="Spanish",
        intervention_type="explanation",
        evidence=(CoachEvidence("obs-1", "answered word 42 instead 2 time(s)", "exact_confusion"),),
        allowed_claims=("the diagnosed cause and the cited evidence",),
    )

    content = asyncio.run(provider.explain_diagnosis(request))

    prompt = captured["messages"][1]["content"]
    assert "<evidence>" in prompt and "</evidence>" in prompt
    assert content.text == "Some helpful content."
    assert content.evidence_ids == ("obs-1",)
    assert content.provider == "openai"


# --- build_ai_provider factory --------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_build_ai_provider_returns_openai_provider_when_configured():
    provider = build_ai_provider(_settings(ai_provider="openai", openai_api_key="key-123"))

    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-5.6-luna"


def test_build_ai_provider_passes_configured_openai_model_and_bounds():
    provider = build_ai_provider(
        _settings(
            ai_provider="openai",
            openai_api_key="key-123",
            openai_model="gpt-5.6-mini",
            ai_max_output_tokens=42,
            ai_context_max_chars=77,
        )
    )

    assert provider is not None
    assert provider._model == "gpt-5.6-mini"
    assert provider._max_output_tokens == 42
    assert provider._context_max_chars == 77


def test_build_ai_provider_rejects_openai_without_an_api_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_ai_provider(_settings(ai_provider="openai"))


def test_supported_ai_providers_lists_openai():
    from app.infrastructure.ai_providers.factory import SUPPORTED_AI_PROVIDERS

    assert "openai" in SUPPORTED_AI_PROVIDERS
