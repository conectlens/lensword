"""Tests for app.infrastructure.ai_providers.credential_mapping — turning a
validated BYOK payload into a real, constructed AIProvider adapter.

These test *construction only* (no generate_content/suggest_mnemonic call):
GeminiProvider/OpenAIProvider/VertexAIProvider's own generation behavior —
request shape, JSON-mode handling, error mapping — is already covered by
tests/test_google_ai_providers.py and tests/test_openai_provider.py (issue
#315). Re-driving a full mocked generation here would duplicate that
coverage for zero additional confidence about what this module actually
does differently: map a payload to the right constructor arguments. No
network call is made or needed for that.
"""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.ai_providers.credential_mapping import (
    CredentialMappingError,
    build_provider_from_credential,
)
from app.infrastructure.ai_providers.google import GeminiProvider, VertexAIProvider
from app.infrastructure.ai_providers.openai_provider import OpenAIProvider


def test_gemini_payload_builds_a_gemini_provider():
    provider = build_provider_from_credential(
        "gemini", {"api_key": "sk-real-key"}, max_output_tokens=42, context_max_chars=77
    )

    assert isinstance(provider, GeminiProvider)
    assert provider._max_output_tokens == 42
    assert provider._context_max_chars == 77


def test_openai_payload_builds_an_openai_provider():
    provider = build_provider_from_credential(
        "openai", {"api_key": "sk-real-key"}, max_output_tokens=42, context_max_chars=77
    )

    assert isinstance(provider, OpenAIProvider)
    assert provider._max_output_tokens == 42
    assert provider._context_max_chars == 77


def _real_looking_service_account_json(project_id: str = "test-project") -> str:
    """A syntactically genuine RSA key, so
    google.oauth2.service_account.Credentials.from_service_account_info
    (which parses the PEM at construction time) succeeds — confirmed
    necessary while building this: a placeholder string in place of
    private_key fails construction immediately, before any network call
    would even be attempted."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project_id,
            "private_key_id": "abc123",
            "private_key": pem,
            "client_email": f"test@{project_id}.iam.gserviceaccount.com",
            "client_id": "12345",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_vertex_payload_builds_a_vertex_provider_with_the_given_project_and_location():
    payload = {
        "service_account_json": _real_looking_service_account_json("my-gcp-project"),
        "project_id": "my-gcp-project",
        "location": "europe-west1",
    }

    provider = build_provider_from_credential("vertex", payload, max_output_tokens=42, context_max_chars=77)

    assert isinstance(provider, VertexAIProvider)
    assert provider._max_output_tokens == 42
    assert provider._context_max_chars == 77


def test_vertex_payload_with_unusable_key_material_raises_a_clean_mapping_error():
    """A private_key that is present and a string (passes the domain
    schema's structural check) but is not real PEM key data must not let a
    raw cryptography/SDK exception — which can carry fragments of the
    submitted content — escape this module."""
    payload = {
        "service_account_json": json.dumps(
            {
                "type": "service_account",
                "project_id": "test-project",
                "private_key_id": "abc123",
                "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
                "client_email": "test@test-project.iam.gserviceaccount.com",
                "client_id": "12345",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        "project_id": "test-project",
        "location": "us-central1",
    }

    with pytest.raises(CredentialMappingError) as excinfo:
        build_provider_from_credential("vertex", payload, max_output_tokens=42, context_max_chars=77)
    assert "not-a-real-key" not in str(excinfo.value)


def test_an_unregistered_provider_raises_a_clean_mapping_error():
    with pytest.raises(CredentialMappingError, match="mistral"):
        build_provider_from_credential("mistral", {"api_key": "x"}, max_output_tokens=42, context_max_chars=77)
