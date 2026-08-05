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
from app.domain.services.conversation import Difficulty, Speaker, Turn, build_context
from app.domain.services.scenarios import CATALOG
from app.infrastructure.ai import DATA_BLOCK_BEGIN, DATA_BLOCK_END, OllamaProvider


def _provider(handler, **kwargs) -> OllamaProvider:
    return OllamaProvider(transport=httpx.MockTransport(handler), **kwargs)


def _suggest(provider: OllamaProvider, word: str = "word", context: str = "context") -> str:
    """Drive the coroutine from a sync test.

    asyncio.run rather than a plugin: the adapter is awaitable now, but
    the project has no async pytest plugin and adding a dependency for
    this would change the CI install surface.
    """
    return asyncio.run(provider.suggest_mnemonic(word, context))


def _extract(provider: OllamaProvider):
    return asyncio.run(provider.extract_vocabulary("A useful passage.", "English", "Spanish", 2))


def _converse(provider: OllamaProvider, learner_text: str = "Como estas?"):
    context = build_context(
        target_language="Spanish",
        difficulty=Difficulty.STEADY,
        vocabulary=["perro", "gato"],
        recent_mistakes=["ser vs estar"],
        history=[Turn(speaker=Speaker.LEARNER, text="Hola")],
    )
    return asyncio.run(provider.converse(context, learner_text))


def _evaluate(provider: OllamaProvider):
    scenario = CATALOG[0]
    transcript = [
        Turn(speaker=Speaker.LEARNER, text="Hello, I am here for the interview."),
        Turn(speaker=Speaker.TUTOR, text="Great, tell me about yourself."),
    ]
    return asyncio.run(provider.evaluate_scenario(scenario, transcript))


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


def test_extract_normalizes_a_single_nested_candidate_and_keeps_target_examples():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["format"] == "json"
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "term": "diligent",
                        "translations": [{"language": "Spanish", "translation": "diligente"}],
                        "examples": [
                            {"language": "English", "example": "A diligent student."},
                            {"language": "Spanish", "example": "Un estudiante diligente."},
                        ],
                    }
                )
            },
        )

    candidates = _extract(_provider(handler))

    assert [(candidate.term, candidate.translations, candidate.examples) for candidate in candidates] == [
        ("diligent", ["diligente"], ["Un estudiante diligente."])
    ]


def test_extract_normalizes_translation_maps_and_discards_unlabelled_examples():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "term": "diligent",
                        "translations": {"Spanish": "diligente"},
                        "examples": ["An unlabelled example is not trusted as target language output."],
                    }
                )
            },
        )

    candidate = _extract(_provider(handler))[0]

    assert candidate.translations == ["diligente"]
    assert candidate.examples == []


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


def test_converse_returns_reply_and_corrections():
    """Issue #169: this call raised AttributeError against a real provider —
    `converse` did not exist. Guards the actual implementation, not just the
    Protocol/interface checks in test_ai_provider.py."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["format"] == "json"
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "reply": "Estoy bien, gracias!",
                        "corrections": [
                            {
                                "original": "Como estas",
                                "corrected": "¿Cómo estás?",
                                "explanation": "Missing question marks and accents.",
                            }
                        ],
                    }
                )
            },
        )

    result = _converse(_provider(handler))

    assert result["reply"] == "Estoy bien, gracias!"
    assert result["corrections"][0]["corrected"] == "¿Cómo estás?"


def test_converse_places_the_learner_message_and_history_inside_the_data_block():
    """Same data-separation rule as the mnemonic prompt (issue #45): the
    learner's message and prior turns are the untrusted part of this request
    and must not appear outside the delimited block."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["prompt"] = json.loads(request.read())["prompt"]
        return httpx.Response(200, json={"response": json.dumps({"reply": "ok"})})

    _converse(_provider(handler), learner_text="Como estas?")

    prompt = captured["prompt"]
    body = prompt[prompt.index(DATA_BLOCK_BEGIN) + len(DATA_BLOCK_BEGIN) : prompt.index(DATA_BLOCK_END)]
    assert "Como estas?" in body
    assert "Hola" in body
    assert "Como estas?" not in prompt[: prompt.index(DATA_BLOCK_BEGIN)]


def test_converse_raises_clear_error_when_daemon_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AIProviderUnavailableError):
        _converse(_provider(handler))


def test_evaluate_scenario_returns_scores_and_goals_met():
    """Issue #169: this call raised AttributeError against a real provider —
    `evaluate_scenario` did not exist."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["format"] == "json"
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "scores": {
                            "vocabulary": {"score": 80, "comment": "Good range."},
                            "task_completion": {"score": 90, "comment": "Covered the goals."},
                        },
                        "goals_met": ["Introduce yourself"],
                        "summary": "Confident opening, could expand on experience.",
                    }
                )
            },
        )

    result = _evaluate(_provider(handler))

    assert result["scores"]["vocabulary"]["score"] == 80
    assert result["goals_met"] == ["Introduce yourself"]


def test_evaluate_scenario_places_the_transcript_inside_the_data_block():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["prompt"] = json.loads(request.read())["prompt"]
        return httpx.Response(200, json={"response": json.dumps({"scores": {}})})

    _evaluate(_provider(handler))

    prompt = captured["prompt"]
    body = prompt[prompt.index(DATA_BLOCK_BEGIN) + len(DATA_BLOCK_BEGIN) : prompt.index(DATA_BLOCK_END)]
    assert "Hello, I am here for the interview." in body


def test_evaluate_scenario_raises_clear_error_when_daemon_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AIProviderUnavailableError):
        _evaluate(_provider(handler))


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


@pytest.mark.skipif(
    not _ollama_model_available("llama3.2"),
    reason="Ollama isn't running locally on :11434, or the 'llama3.2' model isn't pulled",
)
def test_converse_integration_against_real_ollama():
    """Issue #169's actual verify step: this endpoint 500'd against a real
    provider before converse() existed. No mocked transport here."""
    provider = OllamaProvider()

    result = _converse(provider, learner_text="Hello, how are you today?")

    assert isinstance(result, dict)
    assert isinstance(result.get("reply"), str)
    assert result["reply"].strip() != ""


@pytest.mark.skipif(
    not _ollama_model_available("llama3.2"),
    reason="Ollama isn't running locally on :11434, or the 'llama3.2' model isn't pulled",
)
def test_evaluate_scenario_integration_against_real_ollama():
    provider = OllamaProvider()

    result = _evaluate(provider)

    assert isinstance(result, dict)
    assert isinstance(result.get("scores"), dict)
