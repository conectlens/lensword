"""Concrete AIProvider adapters.

OllamaProvider is the first concrete adapter for the AIProvider port
(ROADMAP.md Phase 1.0 / issue #15), talking to a local Ollama daemon over
HTTP. Settings wiring (AI_PROVIDER / OLLAMA_MODEL / OLLAMA_BASE_URL) is
Phase 1.1 — this class takes explicit constructor args with Ollama's own
defaults and does not reach into app.config.
"""
from __future__ import annotations

import logging

import httpx

from app.domain.exceptions import AIProviderUnavailableError

logger = logging.getLogger(__name__)


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
