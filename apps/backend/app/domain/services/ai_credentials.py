"""Bring-Your-Own-Key (BYOK) AI credential schemas.

The cloud deployment of LensWord has no billing/credits system, so it
cannot pay for every user's AI usage — a user who wants real AI features
supplies their own Gemini/OpenAI/Vertex AI credential instead, stored
encrypted and used only for that user's own requests (see
app.infrastructure.credential_vault for the encryption and
app.api.deps.get_ai_provider_for_user for the per-request resolution that
reads it).

This module owns exactly one thing: *is a submitted credential payload
shaped the way its provider needs it to be*. It is a Strategy per provider
(`CredentialSchema` subclasses, one per provider, registered in
`PROVIDER_CREDENTIAL_SCHEMAS`) precisely so a future provider (Mistral,
Anthropic, ...) is one new subclass plus one registry entry — the storage
layer (app/infrastructure/models.py's UserAICredentialModel), the
encryption layer, and the API routes (app/api/routers/ai_credentials.py)
never need to change to support it, since none of them know a schema
exists beyond calling `.validate()` and `.public_view()` through this
registry.

Zero third-party/framework imports here (only `json`, stdlib), matching the
same domain-layer boundary app.domain.services.ai_provider's own docstring
documents. Turning a *validated* payload into the exact constructor kwargs
a real provider adapter class needs — which for Vertex AI means
`google.oauth2.service_account.Credentials.from_service_account_info`, a
third-party import — is deliberately NOT done here; see
app.infrastructure.ai_providers.credential_mapping for that half. This
module answers "is this payload usable at all", not "what SDK object does
it become".
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import ClassVar, Mapping


class CredentialValidationError(ValueError):
    """A submitted BYOK credential payload does not match its provider's
    required shape. Always raised with a message safe to return to the
    submitting user as-is — it must never echo the payload's own values
    (a malformed API key repeated back in an error is still a leaked
    fragment of a secret), only field names and what was wrong with them.
    """


class CredentialSchema(ABC):
    """One provider's credential shape (Strategy pattern) — see module
    docstring. A concrete subclass is stateless; `PROVIDER_CREDENTIAL_SCHEMAS`
    below holds one shared instance per provider.
    """

    # The registry key this schema answers for — "gemini", "openai",
    # "vertex", ... — and the same string stored in
    # UserAICredentialModel.provider / used as the {provider} path segment
    # in the BYOK API.
    provider: ClassVar[str]

    # Which keys of a *valid* payload are safe to return verbatim from
    # GET /api/v1/me/ai-credentials — e.g. Vertex's project_id/location,
    # useful for a user to confirm at a glance which GCP project is
    # configured. Everything else in the payload is assumed secret (an
    # api_key, a service-account private key, ...) and is only ever read
    # back out of the encrypted blob for building a live provider, never
    # for display. Empty by default: most providers here have nothing
    # non-secret worth showing.
    public_fields: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def validate(self, payload: Mapping[str, object]) -> None:
        """Raise CredentialValidationError for a payload that does not
        match this provider's required shape. Returns None (does not
        mutate or normalize the payload) when the payload is acceptable.
        """
        ...

    def public_view(self, payload: Mapping[str, object]) -> dict[str, object]:
        """The subset of an already-validated payload safe to hand back in
        an API response. Callers must only pass a payload that already
        passed `validate()` — this does not re-validate."""
        return {key: payload[key] for key in self.public_fields if key in payload}


def _require_non_empty_str(payload: Mapping[str, object], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CredentialValidationError(f"'{key}' is required and must be a non-empty string")


def _reject_unknown_keys(payload: Mapping[str, object], allowed: set[str]) -> None:
    """Defence in depth against a submitted payload carrying extra fields
    nobody asked for — the encrypted blob stores exactly what was
    submitted, so an unexpected key would otherwise ride along silently
    into storage and, for a field like `model`, potentially influence
    behaviour nobody reviewing this schema signed off on."""
    unknown = set(payload) - allowed
    if unknown:
        raise CredentialValidationError(f"unexpected field(s): {sorted(unknown)}")


class GeminiCredentialSchema(CredentialSchema):
    """`{"api_key": str}` — the Gemini Developer API's own single-secret
    shape, mirroring the deployment-wide GEMINI_API_KEY setting (issue
    #315) one-for-one."""

    provider = "gemini"

    def validate(self, payload: Mapping[str, object]) -> None:
        _require_non_empty_str(payload, "api_key")
        _reject_unknown_keys(payload, {"api_key"})


class OpenAICredentialSchema(CredentialSchema):
    """`{"api_key": str}` — same shape as Gemini's; OpenAI's API is
    likewise a single bearer secret."""

    provider = "openai"

    def validate(self, payload: Mapping[str, object]) -> None:
        _require_non_empty_str(payload, "api_key")
        _reject_unknown_keys(payload, {"api_key"})


# The fields google.oauth2.service_account.Credentials.from_service_account_info
# itself requires to construct at all (confirmed against the installed SDK
# while building this). Checking for them here means a user who pastes a
# malformed or truncated key file gets a clear rejection at submit time
# instead of an opaque failure the first time it is actually used to talk
# to Vertex AI. This is deliberately NOT a full validation of the key's
# cryptographic validity or the account's actual permissions in GCP (a
# private_key that parses but is not a real key still passes this check) —
# see the module docstring's "not a full GCP IAM validator" framing.
_SERVICE_ACCOUNT_REQUIRED_KEYS = ("type", "project_id", "private_key", "client_email", "token_uri")

# google-auth's Credentials.from_service_account_info trusts token_uri
# verbatim as the destination for its own OAuth token-refresh HTTP request —
# made by *this server*, not the submitting user's browser, the first time
# the credential is used. Without this check, a user could submit a
# self-signed service-account JSON (their own key, not a real Google one)
# with token_uri pointed at an internal address — a cloud metadata endpoint
# (169.254.169.254) or any other host this server can reach but a user
# never could directly — and the server would make that request on the
# credential's first real use. A genuine Google-issued service-account key
# always has exactly this token_uri; there is no legitimate reason for a
# real credential to name anything else, so this is a strict allowlist
# rather than a denylist of known-bad addresses (the same "must be known
# to be right" posture app.domain.services.url_safety takes for outbound
# URL fetches, applied here instead of that module's DNS-resolution machinery
# because this field has exactly one correct value, not an open set of
# legitimate ones).
_GOOGLE_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"


class VertexCredentialSchema(CredentialSchema):
    """`{"service_account_json": str, "project_id": str, "location": str}`
    — meaningfully different from the other two: Vertex AI authenticates
    with a GCP service-account key (a JSON document containing a private
    key), not a bearer token, and needs to know which GCP project/region
    to call. `project_id`/`location` are reported back by GET (see
    `public_fields`) since they are not secret and are useful for a user
    to confirm; `service_account_json` never is."""

    provider = "vertex"
    public_fields = ("project_id", "location")

    def validate(self, payload: Mapping[str, object]) -> None:
        _require_non_empty_str(payload, "service_account_json")
        _require_non_empty_str(payload, "project_id")
        _require_non_empty_str(payload, "location")
        _reject_unknown_keys(payload, {"service_account_json", "project_id", "location"})

        raw = payload["service_account_json"]
        assert isinstance(raw, str)  # narrowed by _require_non_empty_str above
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise CredentialValidationError("service_account_json is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise CredentialValidationError("service_account_json must be a JSON object")

        missing = [key for key in _SERVICE_ACCOUNT_REQUIRED_KEYS if key not in parsed]
        if missing:
            raise CredentialValidationError(
                f"service_account_json is missing required field(s): {missing}"
            )
        if parsed.get("type") != "service_account":
            raise CredentialValidationError(
                "service_account_json must be a service-account key (type must be 'service_account')"
            )
        if parsed.get("token_uri") != _GOOGLE_OAUTH_TOKEN_URI:
            # Never echoes the submitted value back — that would just be a
            # more polite way of confirming to an attacker exactly what got
            # rejected and why, with no benefit to a legitimate submitter
            # (whose real key's token_uri always matches).
            raise CredentialValidationError(
                f"service_account_json's token_uri must be '{_GOOGLE_OAUTH_TOKEN_URI}' "
                "(a genuine Google-issued key always has this value)"
            )


# The one place that knows every BYOK-supported provider. Adding a new one
# (Mistral, Anthropic, ...) means writing one CredentialSchema subclass and
# adding it here — storage, encryption, and the API routes all read this
# registry rather than hardcoding a provider list, so none of them need to
# change.
PROVIDER_CREDENTIAL_SCHEMAS: dict[str, CredentialSchema] = {
    schema.provider: schema
    for schema in (GeminiCredentialSchema(), OpenAICredentialSchema(), VertexCredentialSchema())
}
