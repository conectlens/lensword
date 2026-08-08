"""Tests for app.api.deps.resolve_ai_provider_for_user — the BYOK
resolution policy shared by get_ai_provider_for_user (REST) and
app.api.mcp_auth.get_ai_provider_for_actor (MCP invocation boundary).
"""
from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from app.api.deps import get_settings, resolve_ai_provider_for_user
from app.domain.entities import UserAICredential
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.value_objects import utcnow
from app.infrastructure.ai_providers.google import GeminiProvider
from app.infrastructure.ai_providers.ollama import OllamaProvider
from app.infrastructure.ai_providers.openai_provider import OpenAIProvider
from app.infrastructure.credential_vault import encrypt_credential
from app.infrastructure.models import UserModel
from app.infrastructure.repositories import SqlAlchemyUserAICredentialRepository


@pytest.fixture()
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


@pytest.fixture()
def one_user(db_session):
    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    return user


def _store(db_session, encryption_key, user_id, provider, payload):
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    now = utcnow()
    repo.upsert(
        UserAICredential(
            user_id=user_id,
            provider=provider,
            encrypted_payload=encrypt_credential(payload, encryption_key=encryption_key),
            created_at=now,
            updated_at=now,
        )
    )


def test_a_user_with_no_stored_credential_falls_back_to_the_deployment_default(
    db_session, one_user, monkeypatch
):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    get_settings.cache_clear()

    provider = resolve_ai_provider_for_user(one_user.id, db_session)

    assert isinstance(provider, OllamaProvider)
    get_settings.cache_clear()


def test_ai_switched_off_and_no_credential_returns_none(db_session, one_user, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    get_settings.cache_clear()

    assert resolve_ai_provider_for_user(one_user.id, db_session) is None
    get_settings.cache_clear()


def test_a_users_single_stored_credential_is_used_regardless_of_deployment_provider(
    db_session, one_user, encryption_key, monkeypatch
):
    """The deployment is on ollama (or nothing); the user's own gemini key
    is still used for their own requests — no admin opt-in required."""
    monkeypatch.setenv("AI_PROVIDER", "none")
    get_settings.cache_clear()
    _store(db_session, encryption_key, one_user.id, "gemini", {"api_key": "sk-alex-gemini"})

    provider = resolve_ai_provider_for_user(one_user.id, db_session)

    assert isinstance(provider, GeminiProvider)
    get_settings.cache_clear()


def test_when_a_stored_credential_matches_the_deployment_provider_that_one_wins(
    db_session, one_user, encryption_key, monkeypatch
):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-deployment-key")
    get_settings.cache_clear()
    _store(db_session, encryption_key, one_user.id, "gemini", {"api_key": "sk-alex-gemini"})
    _store(db_session, encryption_key, one_user.id, "openai", {"api_key": "sk-alex-openai"})

    provider = resolve_ai_provider_for_user(one_user.id, db_session)

    assert isinstance(provider, OpenAIProvider)
    get_settings.cache_clear()


def test_multiple_credentials_none_matching_the_deployment_provider_falls_back(
    db_session, one_user, encryption_key, monkeypatch
):
    """Two personal keys, neither on the deployment's own provider — there
    is no principled way to pick one over the other automatically, so this
    falls back to the deployment default rather than guessing."""
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    get_settings.cache_clear()
    _store(db_session, encryption_key, one_user.id, "gemini", {"api_key": "sk-alex-gemini"})
    _store(db_session, encryption_key, one_user.id, "openai", {"api_key": "sk-alex-openai"})

    provider = resolve_ai_provider_for_user(one_user.id, db_session)

    assert isinstance(provider, OllamaProvider)
    get_settings.cache_clear()


def test_a_credential_that_cannot_be_decrypted_raises_rather_than_falling_back(
    db_session, one_user, monkeypatch
):
    """The whole point of BYOK is that the deployment does not pay for a
    user's usage — a broken personal key must not silently spend the
    deployment's own configured provider instead."""
    # Encrypted under one key, then the configured key changes — the
    # classic "master key rotated" failure mode.
    old_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", old_key)
    get_settings.cache_clear()
    _store(db_session, old_key, one_user.id, "gemini", {"api_key": "sk-alex-gemini"})

    new_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("AI_PROVIDER", "none")
    get_settings.cache_clear()

    with pytest.raises(AIProviderUnavailableError):
        resolve_ai_provider_for_user(one_user.id, db_session)
    get_settings.cache_clear()


def test_a_credential_with_unusable_key_material_raises_rather_than_falling_back(
    db_session, one_user, encryption_key, monkeypatch
):
    monkeypatch.setenv("AI_PROVIDER", "none")
    get_settings.cache_clear()
    bad_service_account = json.dumps(
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
    )
    _store(
        db_session, encryption_key, one_user.id, "vertex",
        {"service_account_json": bad_service_account, "project_id": "test-project", "location": "us-central1"},
    )

    with pytest.raises(AIProviderUnavailableError):
        resolve_ai_provider_for_user(one_user.id, db_session)
    get_settings.cache_clear()


def test_one_users_credential_is_never_used_to_resolve_another_users_provider(
    db_session, encryption_key, monkeypatch
):
    monkeypatch.setenv("AI_PROVIDER", "none")
    get_settings.cache_clear()
    alex = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    sam = UserModel(username="sam", email="sam@example.com", hashed_password="x", created_at=utcnow())
    db_session.add_all([alex, sam])
    db_session.flush()
    _store(db_session, encryption_key, alex.id, "gemini", {"api_key": "sk-alex-gemini"})

    assert isinstance(resolve_ai_provider_for_user(alex.id, db_session), GeminiProvider)
    assert resolve_ai_provider_for_user(sam.id, db_session) is None
    get_settings.cache_clear()
