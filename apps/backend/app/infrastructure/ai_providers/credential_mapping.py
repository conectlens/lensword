"""Maps a validated BYOK credential payload to a constructed AIProvider
instance for that same provider.

Paired 1:1 with app.domain.services.ai_credentials's schema registry — one
builder function per provider, registered in `_PROVIDER_BUILDERS` the same
way a schema is registered in `PROVIDER_CREDENTIAL_SCHEMAS` — but kept in
this infrastructure module rather than that domain one, because Vertex's
mapping needs `google.oauth2.service_account.Credentials.
from_service_account_info`, a third-party import app/domain/ must never
carry (see app.domain.services.ai_provider's own docstring for the same
rule this respects, and app.domain.services.ai_credentials's module
docstring for why the split lands here specifically). The domain layer
answers "is this payload valid"; this module answers "what does a valid
payload become".

Callers must only pass an already-validated payload (see
`CredentialSchema.validate`) — this module does not re-validate, only
constructs.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from google.oauth2 import service_account

from app.domain.services.ai_provider import AIProvider
from app.infrastructure.ai_providers.google import GeminiProvider, VertexAIProvider
from app.infrastructure.ai_providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

# Vertex AI needs at least this scope for any Cloud API call, including
# generateContent — the same scope Google's own service-account
# documentation names for Vertex AI usage.
_VERTEX_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


class CredentialMappingError(ValueError):
    """A validated credential payload could not be turned into a real
    provider adapter — e.g. a service_account_json whose private_key
    parses as a string but is not an actual usable key. Distinct from
    app.domain.services.ai_credentials.CredentialValidationError:
    that one is a structural shape problem caught before storage, this one
    is "the shape was right but the SDK still rejected the content",
    caught at the point a stored credential is first turned into a live
    provider. Never includes the payload's own values in its message.
    """


def _build_gemini(payload: dict, *, max_output_tokens: int, context_max_chars: int) -> AIProvider:
    return GeminiProvider(
        api_key=payload["api_key"], max_output_tokens=max_output_tokens, context_max_chars=context_max_chars
    )


def _build_openai(payload: dict, *, max_output_tokens: int, context_max_chars: int) -> AIProvider:
    return OpenAIProvider(
        api_key=payload["api_key"], max_output_tokens=max_output_tokens, context_max_chars=context_max_chars
    )


def _build_vertex(payload: dict, *, max_output_tokens: int, context_max_chars: int) -> AIProvider:
    try:
        info = json.loads(payload["service_account_json"])
        credentials = service_account.Credentials.from_service_account_info(info, scopes=list(_VERTEX_SCOPES))
    except (ValueError, TypeError, KeyError) as exc:
        # CredentialSchema.validate already confirmed this parses as JSON
        # with the required keys present and type == "service_account" —
        # what can still fail here is content that has the right shape but
        # is not actually usable key material (e.g. private_key is present
        # but not a real PEM-encoded key). Never echoes the payload itself.
        logger.warning("vertex service_account_json failed to build real credentials: %s", exc)
        raise CredentialMappingError(
            "service_account_json could not be used to build Google credentials — "
            "check that it is a genuine, unmodified service-account key file"
        ) from exc
    return VertexAIProvider(
        project_id=payload["project_id"],
        location=payload["location"],
        credentials=credentials,
        max_output_tokens=max_output_tokens,
        context_max_chars=context_max_chars,
    )


# The one place BYOK resolution knows which provider maps to which real
# adapter class. Adding a new provider means adding a schema (see
# app.domain.services.ai_credentials) and one builder function registered
# here — nothing else in the BYOK stack (storage, encryption, the API
# routes) needs to change.
_PROVIDER_BUILDERS: dict[str, Callable[..., AIProvider]] = {
    "gemini": _build_gemini,
    "openai": _build_openai,
    "vertex": _build_vertex,
}


def build_provider_from_credential(
    provider: str, payload: dict, *, max_output_tokens: int, context_max_chars: int
) -> AIProvider:
    """Construct the real AIProvider adapter for one already-validated BYOK
    credential payload. Raises CredentialMappingError for a provider with
    no registered builder (should never happen if the caller only reaches
    here for a provider found in PROVIDER_CREDENTIAL_SCHEMAS — checked
    anyway, since silently returning nothing would be worse) or whose
    payload fails to become real SDK credentials.
    """
    builder = _PROVIDER_BUILDERS.get(provider)
    if builder is None:
        raise CredentialMappingError(f"no BYOK adapter mapping registered for provider '{provider}'")
    return builder(payload, max_output_tokens=max_output_tokens, context_max_chars=context_max_chars)
