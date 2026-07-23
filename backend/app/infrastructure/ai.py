"""Concrete AIProvider adapters and the settings-driven factory that picks one.

OllamaProvider is the first concrete adapter for the AIProvider port
(ROADMAP.md Phase 1.0 / issue #15), talking to a local Ollama daemon over
HTTP. It deliberately takes explicit constructor arguments with Ollama's own
defaults and never reaches into app.config — that keeps it injectable and
testable in isolation. build_ai_provider (Phase 1.1 / issue #22) is the one
place that reads Settings and passes them in.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.ai_provider import AIProvider

logger = logging.getLogger(__name__)

SUPPORTED_AI_PROVIDERS = ("none", "ollama")


class OllamaProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        *,
        connect_timeout: float = 2.0,
        read_timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=connect_timeout, pool=connect_timeout
        )
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def suggest_mnemonic(self, word: str, context: str) -> str:
        prompt = f"Give a short, memorable mnemonic for the word '{word}' ({context})."
        try:
            response = self._client.post(
                "/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
            )
        except httpx.ConnectError as exc:
            logger.warning("Ollama unreachable at %s: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError(
                f"Ollama is not reachable at {self._client.base_url} — is it running?"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.warning("Ollama at %s timed out: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError(f"Ollama at {self._client.base_url} timed out") from exc
        except httpx.RequestError as exc:
            # Catch-all for the rest of httpx's transport-failure surface (a
            # connection accepted then dropped mid-response, a protocol
            # error, an unsupported proxy, ...) — anything that isn't a
            # clean refusal or a timeout still must not leak past this
            # method as a raw transport exception.
            logger.warning("Ollama request to %s failed: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError(f"Ollama request failed: {exc}") from exc

        if response.status_code == 404:
            logger.warning("Ollama model '%s' isn't pulled", self._model)
            raise AIProviderUnavailableError(
                f"Ollama model '{self._model}' isn't pulled — run `ollama pull {self._model}`."
            )
        if response.is_error:
            logger.warning("Ollama returned HTTP %s", response.status_code)
            raise AIProviderUnavailableError(
                f"Ollama returned an unexpected error (HTTP {response.status_code})"
            )

        try:
            text = response.json()["response"]
        except (ValueError, KeyError) as exc:
            logger.warning("Ollama response missing 'response' field: %s", exc)
            raise AIProviderUnavailableError("Ollama's response was missing the generated text") from exc
        if not isinstance(text, str):
            logger.warning("Ollama response 'response' field was not a string: %r", text)
            raise AIProviderUnavailableError("Ollama's response was missing the generated text")

        return text.strip()


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """Build the configured AIProvider, or None when AI is switched off.

    Returning None rather than a null-object provider keeps "no AI
    configured" a state the caller can see and report honestly, instead of
    something indistinguishable from a provider that always fails.
    """
    provider = settings.ai_provider.strip().lower()
    if provider == "none":
        return None
    if provider == "ollama":
        return OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
    raise ValueError(
        f"Unknown AI_PROVIDER '{settings.ai_provider}' — supported values are: "
        f"{', '.join(SUPPORTED_AI_PROVIDERS)}"
    )
