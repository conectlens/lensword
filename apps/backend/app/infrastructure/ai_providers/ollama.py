"""OllamaProvider — the first concrete adapter for the AIProvider port
(ROADMAP.md Phase 1.0 / issue #15), talking to a local Ollama daemon over
HTTP. It deliberately takes explicit constructor arguments with Ollama's own
defaults and never reaches into app.config — that keeps it injectable and
testable in isolation. build_ai_provider (Phase 1.1 / issue #22) is the one
place that reads Settings and passes them in.

Refactored onto `_TextGeneratingProvider` (issue #315): the request
construction, response parsing, and companion-coach enforcement that used to
live directly on this class now live in the shared base — this file is only
the httpx transport and Ollama's own failure-mode mapping.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai_providers.base import (
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TERM_MAX_CHARS,
    _TextGeneratingProvider,
    _unavailable_error,
)

logger = logging.getLogger(__name__)


class OllamaProvider(_TextGeneratingProvider):
    provider_name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        *,
        connect_timeout: float = 2.0,
        read_timeout: float = 20.0,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        term_max_chars: int = DEFAULT_TERM_MAX_CHARS,
        context_max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            model=model,
            max_output_tokens=max_output_tokens,
            term_max_chars=term_max_chars,
            context_max_chars=context_max_chars,
        )
        # A generation occupies this client for seconds. Awaiting it keeps
        # the wait on the event loop instead of an OS thread, so slow or hung
        # generations cannot exhaust the server's bounded worker pool and
        # stall unrelated endpoints. The ceiling becomes the HTTP connection
        # pool rather than anyio's CapacityLimiter(40).
        #
        # read_timeout stays short regardless: it is longer than anyone will
        # watch a suggestion spinner, and it bounds how long a wedged daemon
        # can tie up a connection.
        timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=connect_timeout, pool=connect_timeout
        )
        # Constructed here rather than at import: httpx.AsyncClient does not
        # bind to an event loop until it is first used, so the one instance
        # built per process (see api.deps._ai_provider) attaches to the
        # running server loop and lives as long as the process.
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def _generate_text(self, system: str, prompt: str) -> str:
        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": self._max_output_tokens},
                },
            )
        except httpx.ConnectError as exc:
            logger.warning("Ollama unreachable at %r: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError() from exc
        except httpx.TimeoutException as exc:
            logger.warning("Ollama at %r timed out: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError() from exc
        except httpx.RequestError as exc:
            # Catch-all for the rest of httpx's transport-failure surface (a
            # connection accepted then dropped mid-response, a protocol
            # error, an unsupported proxy, ...) — anything that isn't a
            # clean refusal or a timeout still must not leak past this
            # method as a raw transport exception.
            logger.warning("Ollama request to %r failed: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError() from exc

        if response.status_code == 404:
            logger.warning("Ollama model '%s' isn't pulled", self._model)
            raise AIProviderUnavailableError()
        if response.is_error:
            logger.warning("Ollama returned HTTP %s", response.status_code)
            raise AIProviderUnavailableError()

        try:
            text = response.json()["response"]
        except (ValueError, KeyError) as exc:
            logger.warning("Ollama response missing 'response' field: %s", exc)
            raise AIProviderUnavailableError() from exc
        if not isinstance(text, str):
            logger.warning("Ollama response 'response' field was not a string: %r", text)
            raise AIProviderUnavailableError()

        # Stripping is the base class's job (suggest_mnemonic) — every
        # provider hands back raw text here.
        return text

    async def _generate_json(self, system: str, prompt: str) -> dict:
        """Shared request/parse path for every JSON-returning call.

        Collapses what used to be two near-identical private methods on
        `OllamaProvider` (`_json_generate` for the learning path, which
        tolerated a bare list, and `_json_generation` for everything else,
        which required a dict and used a slightly different error-handling
        shape) into the one hook every provider now implements. The
        dict-vs-list tolerance moved to the base class's callers
        (`_generate_structured` vs. `generate_learning_path`/
        `extract_vocabulary` calling this directly) — see
        `_TextGeneratingProvider`'s docstring.
        """
        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"num_predict": self._max_output_tokens},
                },
            )
        except httpx.RequestError as exc:
            logger.warning("Ollama request to %r failed: %s", self._client.base_url, exc)
            raise AIProviderUnavailableError() from exc

        if response.status_code == 404:
            logger.warning("Ollama model '%s' isn't pulled", self._model)
            raise AIProviderUnavailableError()
        if response.is_error:
            logger.warning("Ollama structured generation returned HTTP %s", response.status_code)
            raise AIProviderUnavailableError()

        raw_text = None
        try:
            raw_text = response.json()["response"]
            return json.loads(raw_text)
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Ollama structured generation response was not valid JSON: %s", exc)
            raise _unavailable_error(raw_text, exc) from exc
