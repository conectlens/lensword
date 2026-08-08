"""Gemini Developer API and Google Vertex AI adapters (issue #315).

Google's unified `google-genai` SDK (`pip install google-genai`) targets both
the Gemini Developer API and Vertex AI through the identical
`client.aio.models.generate_content(...)` call — they differ only in how the
`genai.Client` itself is constructed (an API key vs. `vertexai=True` plus a
GCP project/location resolved through Application Default Credentials). That
is the whole reason `GeminiProvider` and `VertexAIProvider` below are thin:
each is just its own `Client` construction, handed to the shared
`_GoogleGenAIProvider` base, which does everything else identically for both.

Vertex AI's credentials are the SDK's own concern, not this module's:
`genai.Client(vertexai=True, ...)` resolves Application Default Credentials
(`GOOGLE_APPLICATION_CREDENTIALS` pointing at a service-account key file, or
workload identity on GCP compute) the same way every other google-cloud
library does. `VertexAIProvider` does not load, parse, or validate a
credentials file itself — building a parallel credential-loading mechanism
here would be the "don't reinvent what a vetted library already does" mistake
this codebase's `authlib` dependency comment (requirements.txt) already
warns against for OAuth. A deploy that sets `AI_PROVIDER=vertex` must
configure ADC in its own environment; see `apps/backend/.env.example` and
docs/install/local-ai-ollama.md's cloud-provider neighbours for how.
"""
from __future__ import annotations

import json
import logging

import httpx
from google import genai
from google.auth import exceptions as google_auth_errors
from google.auth.credentials import Credentials as GoogleCredentials
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.domain.exceptions import AIProviderUnavailableError
from app.infrastructure.ai_providers.base import (
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TERM_MAX_CHARS,
    _TextGeneratingProvider,
    _unavailable_error,
)

logger = logging.getLogger(__name__)

# gemini-2.5-flash: Google's current fast/economical Gemini tier, the same
# one a hosted deploy without its own GPU budget would reach for by default —
# not the top-of-line reasoning model, which is a deliberately more expensive
# default for a feature (mnemonic suggestions, vocabulary enrichment) that
# runs on every learner action.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"
# us-central1: one of Vertex AI's original and most widely available
# regions for Gemini models — a reasonable default for an operator who
# has not yet thought about where their GCP project's data should live,
# not a claim that it is the best or only choice for a given deployment.
DEFAULT_VERTEX_LOCATION = "us-central1"


class _GoogleGenAIProvider(_TextGeneratingProvider):
    """Shared base for Gemini and Vertex AI — see module docstring.

    Takes an already-constructed `genai.Client`, never builds one itself:
    that is `GeminiProvider`/`VertexAIProvider`'s own job, since it is the
    one place the two adapters actually differ.
    """

    def __init__(
        self,
        client: genai.Client,
        model: str,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        term_max_chars: int = DEFAULT_TERM_MAX_CHARS,
        context_max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> None:
        super().__init__(
            model=model,
            max_output_tokens=max_output_tokens,
            term_max_chars=term_max_chars,
            context_max_chars=context_max_chars,
        )
        self._client = client

    async def _generate_text(self, system: str, prompt: str) -> str:
        response = await self._call(system, prompt, json_mode=False)
        text = self._extract_text(response)
        if not isinstance(text, str):
            logger.warning("%s response had no usable text", self.provider_name)
            raise AIProviderUnavailableError()
        return text

    async def _generate_json(self, system: str, prompt: str) -> dict:
        response = await self._call(system, prompt, json_mode=True)
        raw_text = self._extract_text(response)
        if raw_text is None:
            logger.warning("%s structured response had no usable text", self.provider_name)
            raise AIProviderUnavailableError()
        try:
            return json.loads(raw_text)
        except (ValueError, TypeError) as exc:
            logger.warning("%s structured response was not valid JSON: %s", self.provider_name, exc)
            raise _unavailable_error(raw_text, exc) from exc

    def _extract_text(self, response: genai_types.GenerateContentResponse) -> str | None:
        """`response.text` itself raises for some blocked/empty shapes and
        returns `None` for others (a safety block with no candidates at
        all) — both are "nothing usable came back", not a caller bug, so
        both fold into the same None-means-unavailable path below rather
        than a second raw exception reaching the adapter boundary."""
        try:
            return response.text
        except ValueError as exc:
            logger.warning("%s response text was not accessible: %s", self.provider_name, exc)
            return None

    async def _call(
        self, system: str, prompt: str, *, json_mode: bool
    ) -> genai_types.GenerateContentResponse:
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json" if json_mode else None,
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self._model, contents=prompt, config=config,
            )
        except genai_errors.APIError as exc:
            # Base class for both ClientError (4xx: bad api key, permission
            # denied, ...) and ServerError (5xx) — the SDK's own retry logic
            # already retries a transient 408/429/5xx with backoff before
            # raising, so what reaches here is already a terminal failure,
            # not one this adapter should retry again itself.
            logger.warning("%s API error (%s): %s", self.provider_name, exc.code, exc.message)
            raise AIProviderUnavailableError() from exc
        except google_auth_errors.GoogleAuthError as exc:
            # Credential resolution itself failing (no ADC configured, an
            # expired/invalid service-account key, ...) — Vertex AI's own
            # failure mode, since it authenticates through google-auth
            # rather than a bearer API key. Reached before any HTTP request
            # is even made, so it is not a genai_errors.APIError.
            logger.warning("%s credentials could not be resolved: %s", self.provider_name, exc)
            raise AIProviderUnavailableError() from exc
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            # Transport-level failures the SDK does not wrap into its own
            # APIError hierarchy (confirmed against the actual SDK: a raw
            # httpx exception from a broken transport propagates as-is).
            logger.warning("%s transport failure: %s", self.provider_name, exc)
            raise AIProviderUnavailableError() from exc
        except httpx.RequestError as exc:
            # Catch-all for the rest of httpx's transport-failure surface,
            # matching OllamaProvider's own defence in depth for the same
            # reason: anything that isn't a clean refusal or a timeout must
            # still not leak past this method as a raw transport exception.
            logger.warning("%s request failed: %s", self.provider_name, exc)
            raise AIProviderUnavailableError() from exc


class GeminiProvider(_GoogleGenAIProvider):
    """The Gemini Developer API — authenticated with a single API key."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        term_max_chars: int = DEFAULT_TERM_MAX_CHARS,
        context_max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
        http_options: genai_types.HttpOptions | None = None,
    ) -> None:
        # http_options is a pass-through testability hook, the same role
        # OllamaProvider's `transport` param plays: `types.HttpOptions(
        # httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(
        # handler)))` lets a test drive the real SDK against a fake
        # transport instead of a live network call — verified directly
        # against the installed SDK version while building this adapter,
        # not assumed from documentation alone.
        client = genai.Client(api_key=api_key, http_options=http_options)
        super().__init__(
            client, model,
            max_output_tokens=max_output_tokens, term_max_chars=term_max_chars, context_max_chars=context_max_chars,
        )


class VertexAIProvider(_GoogleGenAIProvider):
    """Google Vertex AI — authenticated via Application Default Credentials,
    not an API key. See the module docstring for how ADC must be configured
    in the deploy environment; this class does not build its own credential
    loading."""

    provider_name = "vertex"

    def __init__(
        self,
        project_id: str,
        location: str = DEFAULT_VERTEX_LOCATION,
        model: str = DEFAULT_VERTEX_MODEL,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        term_max_chars: int = DEFAULT_TERM_MAX_CHARS,
        context_max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
        http_options: genai_types.HttpOptions | None = None,
        credentials: "google.auth.credentials.Credentials | None" = None,
    ) -> None:
        # `credentials` is a testability hook only — production never passes
        # it, so the SDK falls through to its normal ADC resolution exactly
        # as the module docstring describes. A test supplies a static,
        # non-refreshing `google.oauth2.credentials.Credentials(token=...)`
        # so a MockTransport-backed request can be exercised without either
        # a live network call or a real GCP service account (confirmed
        # directly against the installed SDK: anonymous/unset credentials
        # attempt a real token refresh even against a mocked transport,
        # and fail before the mock is ever reached — a concrete pre-set
        # token sidesteps that refresh entirely).
        client = genai.Client(
            vertexai=True, project=project_id, location=location,
            credentials=credentials, http_options=http_options,
        )
        super().__init__(
            client, model,
            max_output_tokens=max_output_tokens, term_max_chars=term_max_chars, context_max_chars=context_max_chars,
        )
