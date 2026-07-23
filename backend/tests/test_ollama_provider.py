"""Tests for OllamaProvider, the first concrete AIProvider adapter (ROADMAP.md
Phase 1.0 / issue #15).

Mocked via httpx.MockTransport for the unit tests below — no real network
calls, no dependency on a running Ollama daemon. See
test_suggest_mnemonic_integration_against_real_ollama for the real-daemon
check required by issue #15's Verify line.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai import OllamaProvider


def _provider(handler, **kwargs) -> OllamaProvider:
    return OllamaProvider(transport=httpx.MockTransport(handler), **kwargs)


def _suggest(provider: OllamaProvider, word: str = "word", context: str = "context") -> str:
    """Drive the coroutine from a sync test.

    asyncio.run rather than a plugin: the adapter is awaitable now, but
    the project has no async pytest plugin and adding a dependency for
    this would change the CI install surface.
    """
    return asyncio.run(provider.suggest_mnemonic(word, context))


def test_suggest_mnemonic_returns_generated_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        payload = json.loads(request.read())
        assert payload["model"] == "llama3.2"
        assert payload["stream"] is False
        assert "ubiquitous" in payload["prompt"]
        return httpx.Response(200, json={"response": "Think 'you-BIK-wit-us'", "done": True})

    provider = _provider(handler)

    result = _suggest(provider, "ubiquitous", "common in academic writing")

    assert result == "Think 'you-BIK-wit-us'"


def test_suggest_mnemonic_raises_clear_error_when_daemon_unreachable(caplog):
    """The caller gets the generic domain error; the operator gets the
    diagnosis in the log, which is where target addresses belong."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(AIProviderUnavailableError):
            _suggest(provider, "perro", "dog in Spanish")

    assert "unreachable" in caplog.text


def test_suggest_mnemonic_raises_clear_error_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider, "word", "context")


def test_suggest_mnemonic_raises_clear_error_when_connection_drops_mid_response():
    """Daemon accepts the connection, then dies/OOMs before finishing — a
    distinct failure mode from a refused connection (ConnectError) or a
    timeout (nothing timed out, the socket just closed)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset", request=request)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider, "word", "context")


def test_suggest_mnemonic_raises_clear_error_when_model_not_pulled(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'llama3.2' not found, try pulling it first"})

    provider = _provider(handler, model="llama3.2")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(AIProviderUnavailableError):
            _suggest(provider, "word", "context")

    # The operator still needs to know *which* model to pull.
    assert "llama3.2" in caplog.text


def test_suggest_mnemonic_strips_surrounding_whitespace():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "  padded answer  \n", "done": True})

    provider = _provider(handler)

    assert _suggest(provider, "word", "context") == "padded answer"


def test_suggest_mnemonic_raises_clear_error_on_malformed_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True})  # missing "response" field

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider, "word", "context")


def test_suggest_mnemonic_raises_clear_error_when_response_field_is_wrong_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": None, "done": True})

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider, "word", "context")


def test_suggest_mnemonic_raises_on_unexpected_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal error"})

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError):
        _suggest(provider, "word", "context")


def test_read_timeout_stays_within_what_a_ui_can_wait_on():
    """Every route in this app is a sync `def`, so each in-flight request
    holds an anyio worker thread (default pool 40) and the image runs a
    single uvicorn worker. A long read timeout lets a handful of slow
    generations exhaust the pool and stall unrelated routes, health check
    included."""
    provider = OllamaProvider()

    assert provider._client.timeout.read <= 20.0


def test_unreachable_daemon_log_masks_credentials_in_the_url(caplog):
    """str(httpx.URL) leaves userinfo intact; only repr() masks it. Logs are
    shipped and grepped, so the masked form is the one that belongs there."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler, base_url="http://svc:hunter2@ollama.internal:11434")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(AIProviderUnavailableError):
            _suggest(provider, "word", "context")

    assert caplog.text.strip() != ""
    assert "hunter2" not in caplog.text


def test_transport_failure_message_does_not_echo_the_raw_exception():
    """The catch-all branch used to interpolate the httpx exception text,
    which can carry the target address."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connect to 10.0.0.5:11434 failed", request=request)

    provider = _provider(handler)

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        _suggest(provider, "word", "context")

    assert "10.0.0.5" not in str(excinfo.value)


def _ollama_model_available(model: str, base_url: str = "http://localhost:11434") -> bool:
    """True only if the daemon responds AND the target model is actually pulled.

    A running daemon with a different (or no) model pulled is the common
    case — Ollama ships with none by default — so this checks both rather
    than just daemon reachability, to avoid a confusing failure instead of
    a clear skip.
    """
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=0.5)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    names = {entry.get("name") for entry in response.json().get("models", [])}
    return any(name == model or name.startswith(f"{model}:") for name in names)


@pytest.mark.skipif(
    not _ollama_model_available("llama3.2"),
    reason="Ollama isn't running locally on :11434, or the 'llama3.2' model isn't pulled",
)
def test_suggest_mnemonic_integration_against_real_ollama():
    provider = OllamaProvider()

    result = _suggest(provider, "perro", "dog in Spanish")

    assert isinstance(result, str)
    assert result.strip() != ""
