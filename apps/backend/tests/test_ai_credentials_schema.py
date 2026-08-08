"""Tests for the Bring-Your-Own-Key credential schemas (Strategy pattern,
one CredentialSchema subclass per provider) — pure validation, no encryption
or network involved.
"""
from __future__ import annotations

import pytest

from app.domain.services.ai_credentials import (
    PROVIDER_CREDENTIAL_SCHEMAS,
    CredentialValidationError,
    GeminiCredentialSchema,
    OpenAICredentialSchema,
    VertexCredentialSchema,
)


def test_registry_lists_exactly_the_three_current_providers():
    assert set(PROVIDER_CREDENTIAL_SCHEMAS) == {"gemini", "openai", "vertex"}


def test_each_schemas_provider_attribute_matches_its_registry_key():
    for key, schema in PROVIDER_CREDENTIAL_SCHEMAS.items():
        assert schema.provider == key


# --- Gemini / OpenAI (identical single-secret shape) -----------------------


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_a_valid_api_key_payload_passes(schema_cls):
    schema_cls().validate({"api_key": "sk-real-looking-key-123"})


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_a_missing_api_key_is_rejected(schema_cls):
    with pytest.raises(CredentialValidationError, match="api_key"):
        schema_cls().validate({})


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_a_blank_api_key_is_rejected(schema_cls):
    with pytest.raises(CredentialValidationError, match="api_key"):
        schema_cls().validate({"api_key": "   "})


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_a_non_string_api_key_is_rejected(schema_cls):
    with pytest.raises(CredentialValidationError, match="api_key"):
        schema_cls().validate({"api_key": 12345})


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_an_unexpected_extra_field_is_rejected(schema_cls):
    """Defence in depth: nothing beyond the documented shape is ever
    accepted into storage."""
    with pytest.raises(CredentialValidationError, match="unexpected"):
        schema_cls().validate({"api_key": "sk-real", "admin": True})


@pytest.mark.parametrize("schema_cls", [GeminiCredentialSchema, OpenAICredentialSchema])
def test_public_view_reveals_nothing_for_a_single_secret_provider(schema_cls):
    """Gemini/OpenAI credentials are one bare secret — there is nothing
    non-secret in the payload worth reporting back."""
    assert schema_cls().public_view({"api_key": "sk-real"}) == {}


# --- Vertex AI (service-account JSON + project/location) -------------------


def _valid_service_account_json() -> str:
    import json

    return json.dumps(
        {
            "type": "service_account",
            "project_id": "test-project",
            "private_key_id": "abc123",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIFake\n-----END PRIVATE KEY-----\n",
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "client_id": "12345",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def _valid_vertex_payload() -> dict:
    return {
        "service_account_json": _valid_service_account_json(),
        "project_id": "test-project",
        "location": "us-central1",
    }


def test_a_valid_vertex_payload_passes():
    VertexCredentialSchema().validate(_valid_vertex_payload())


@pytest.mark.parametrize("missing_field", ["service_account_json", "project_id", "location"])
def test_a_vertex_payload_missing_a_required_field_is_rejected(missing_field):
    payload = _valid_vertex_payload()
    del payload[missing_field]
    with pytest.raises(CredentialValidationError, match=missing_field):
        VertexCredentialSchema().validate(payload)


def test_vertex_rejects_an_unexpected_extra_field():
    payload = _valid_vertex_payload()
    payload["extra"] = "nope"
    with pytest.raises(CredentialValidationError, match="unexpected"):
        VertexCredentialSchema().validate(payload)


def test_vertex_rejects_service_account_json_that_is_not_valid_json():
    payload = _valid_vertex_payload()
    payload["service_account_json"] = "{not json"
    with pytest.raises(CredentialValidationError, match="not valid JSON"):
        VertexCredentialSchema().validate(payload)


def test_vertex_rejects_service_account_json_that_is_a_json_array_not_object():
    payload = _valid_vertex_payload()
    payload["service_account_json"] = "[1, 2, 3]"
    with pytest.raises(CredentialValidationError, match="JSON object"):
        VertexCredentialSchema().validate(payload)


def test_vertex_rejects_a_service_account_json_missing_required_keys():
    import json

    payload = _valid_vertex_payload()
    incomplete = json.loads(payload["service_account_json"])
    del incomplete["private_key"]
    payload["service_account_json"] = json.dumps(incomplete)
    with pytest.raises(CredentialValidationError, match="private_key"):
        VertexCredentialSchema().validate(payload)


def test_vertex_rejects_a_service_account_json_with_the_wrong_type_field():
    """A user-uploaded OAuth client secret or API key JSON, not a
    service-account key, must be rejected with a clear reason rather than
    silently accepted and failing later."""
    import json

    payload = _valid_vertex_payload()
    wrong_type = json.loads(payload["service_account_json"])
    wrong_type["type"] = "authorized_user"
    payload["service_account_json"] = json.dumps(wrong_type)
    with pytest.raises(CredentialValidationError, match="service_account"):
        VertexCredentialSchema().validate(payload)


@pytest.mark.parametrize(
    "malicious_token_uri",
    [
        "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
        "http://localhost:8000/internal",
        "http://10.0.0.5/admin",
        "https://attacker.example.com/steal",
    ],
)
def test_vertex_rejects_a_service_account_json_with_a_non_google_token_uri(malicious_token_uri):
    """Regression test for an SSRF: google-auth's Credentials.
    from_service_account_info trusts token_uri verbatim as the destination
    for its own server-side OAuth token-refresh request, made on this
    credential's first real use — not by the submitting user's browser, by
    this backend. A self-signed service-account JSON with token_uri pointed
    at an internal address (a cloud metadata endpoint, localhost, an
    internal IP) would otherwise make the server issue that request on the
    submitting user's behalf. A genuine Google-issued key always has
    exactly one token_uri value; anything else is rejected outright."""
    import json

    payload = _valid_vertex_payload()
    tampered = json.loads(payload["service_account_json"])
    tampered["token_uri"] = malicious_token_uri
    payload["service_account_json"] = json.dumps(tampered)
    with pytest.raises(CredentialValidationError, match="token_uri"):
        VertexCredentialSchema().validate(payload)


def test_vertex_public_view_reveals_project_and_location_but_never_the_key():
    payload = _valid_vertex_payload()
    view = VertexCredentialSchema().public_view(payload)
    assert view == {"project_id": "test-project", "location": "us-central1"}
    assert "service_account_json" not in view
    assert "MIIFake" not in str(view)
