"""OpenAI adapter (issue #315).

A separate concrete provider from the Google pair in `google.py` — a
different SDK (`pip install openai`, `from openai import AsyncOpenAI`), so it
does not share `_GoogleGenAIProvider`. It shares only `_TextGeneratingProvider`
(base.py) with every other adapter, the same as `OllamaProvider` does.
"""
from __future__ import annotations

import json
import logging

import httpx
import openai
from openai import AsyncOpenAI

from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai_providers.base import (
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TERM_MAX_CHARS,
    _TextGeneratingProvider,
    _unavailable_error,
)

logger = logging.getLogger(__name__)

# gpt-5.6-luna: OpenAI's cost-optimized tier, matching GeminiProvider's own
# default (gemini-2.5-flash) — see the per-field comment on
# Settings.openai_model (app/config.py) for the full reasoning. Model names
# churn faster than most dependencies; re-check the live model list before
# trusting this indefinitely.
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


class OpenAIProvider(_TextGeneratingProvider):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        term_max_chars: int = DEFAULT_TERM_MAX_CHARS,
        context_max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            model=model,
            max_output_tokens=max_output_tokens,
            term_max_chars=term_max_chars,
            context_max_chars=context_max_chars,
        )
        # http_client is the same injectable-transport testability hook as
        # OllamaProvider's own `transport` param:
        # AsyncOpenAI(http_client=httpx.AsyncClient(transport=httpx.
        # MockTransport(handler))) drives the real SDK against a fake
        # transport in tests, verified directly against the installed SDK.
        self._client = AsyncOpenAI(api_key=api_key, http_client=http_client)

    async def _generate_text(self, system: str, prompt: str) -> str:
        message = await self._complete(system, prompt, json_mode=False)
        text = message.content
        if not isinstance(text, str):
            logger.warning("openai response had no text content")
            raise AIProviderUnavailableError()
        return text

    async def _generate_json(self, system: str, prompt: str) -> dict:
        message = await self._complete(system, prompt, json_mode=True)
        raw_text = message.content
        if not isinstance(raw_text, str):
            logger.warning("openai structured response had no text content")
            raise AIProviderUnavailableError()
        try:
            return json.loads(raw_text)
        except (ValueError, TypeError) as exc:
            logger.warning("openai structured response was not valid JSON: %s", exc)
            raise _unavailable_error(raw_text, exc) from exc

    async def _complete(self, system: str, prompt: str, *, json_mode: bool):
        kwargs: dict[str, object] = {}
        if json_mode:
            # response_format={"type": "json_object"} guarantees the model's
            # top-level reply is a JSON object — it cannot return a bare
            # array even if asked to (see generate_learning_path's own
            # dict-unwrap handling in the base class, which exists partly
            # because of this exact constraint).
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                max_tokens=self._max_output_tokens,
                **kwargs,
            )
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            # Transport-level failures: connection refused/dropped, or a
            # request that never got a response in time.
            logger.warning("openai request failed: %s", exc)
            raise AIProviderUnavailableError() from exc
        except openai.APIStatusError as exc:
            # Base class for the whole 4xx/5xx hierarchy (BadRequestError
            # 400, AuthenticationError 401, PermissionDeniedError 403,
            # NotFoundError 404, RateLimitError 429, InternalServerError
            # 5xx, ...). The SDK's own retry logic already retries a
            # transient 429/5xx with backoff before raising, so what
            # reaches here is already a terminal failure.
            logger.warning("openai API error (%s): %s", exc.status_code, exc.message)
            raise AIProviderUnavailableError() from exc

        choices = response.choices
        if not choices:
            logger.warning("openai response had no choices")
            raise AIProviderUnavailableError()
        return choices[0].message
