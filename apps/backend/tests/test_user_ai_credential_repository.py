"""Tests for SqlAlchemyUserAICredentialRepository — storage only, opaque
bytes in and out. Never encrypts/decrypts (that is credential_vault's job,
called from the application/API layer) and never inspects the payload.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.entities import UserAICredential
from app.domain.value_objects import utcnow
from app.infrastructure.models import UserModel
from app.infrastructure.repositories import SqlAlchemyUserAICredentialRepository


@pytest.fixture()
def two_users(db_session):
    """Real UserModel rows — user_ai_credentials.user_id is a genuine
    foreign key, enforced under the Postgres CI leg even though SQLite
    does not enforce it by default, so a bare integer would silently pass
    here and only fail there."""
    alex = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    sam = UserModel(username="sam", email="sam@example.com", hashed_password="x", created_at=utcnow())
    db_session.add_all([alex, sam])
    db_session.flush()
    return alex, sam


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _credential(user_id: int, provider: str, blob: bytes = b"opaque-ciphertext") -> UserAICredential:
    now = _now()
    return UserAICredential(user_id=user_id, provider=provider, encrypted_payload=blob, created_at=now, updated_at=now)


def test_get_returns_none_when_nothing_is_stored(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)

    assert repo.get(user_id=alex.id, provider="gemini") is None


def test_upsert_then_get_round_trips_the_exact_bytes(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    stored = repo.upsert(_credential(alex.id, "gemini", b"\x00\x01\xffsome-ciphertext"))

    fetched = repo.get(user_id=alex.id, provider="gemini")

    assert fetched is not None
    assert fetched.encrypted_payload == b"\x00\x01\xffsome-ciphertext"
    assert fetched.user_id == alex.id
    assert fetched.provider == "gemini"
    assert stored.encrypted_payload == fetched.encrypted_payload


def test_upsert_for_the_same_provider_replaces_rather_than_duplicates(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    repo.upsert(_credential(alex.id, "gemini", b"first-key"))
    repo.upsert(_credential(alex.id, "gemini", b"second-key"))

    assert repo.get(user_id=alex.id, provider="gemini").encrypted_payload == b"second-key"
    assert len(repo.list_for_user(alex.id)) == 1


def test_a_user_may_store_credentials_for_more_than_one_provider_at_once(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    repo.upsert(_credential(alex.id, "gemini", b"gemini-key"))
    repo.upsert(_credential(alex.id, "openai", b"openai-key"))

    stored = {c.provider: c.encrypted_payload for c in repo.list_for_user(alex.id)}
    assert stored == {"gemini": b"gemini-key", "openai": b"openai-key"}


def test_one_users_credentials_are_never_returned_for_another(db_session, two_users):
    alex, sam = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    repo.upsert(_credential(alex.id, "gemini", b"alex-key"))
    repo.upsert(_credential(sam.id, "gemini", b"sam-key"))

    assert repo.get(user_id=alex.id, provider="gemini").encrypted_payload == b"alex-key"
    assert repo.get(user_id=sam.id, provider="gemini").encrypted_payload == b"sam-key"
    assert len(repo.list_for_user(alex.id)) == 1


def test_delete_removes_the_row_and_reports_true(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    repo.upsert(_credential(alex.id, "gemini"))

    assert repo.delete(user_id=alex.id, provider="gemini") is True
    assert repo.get(user_id=alex.id, provider="gemini") is None


def test_deleting_a_credential_that_does_not_exist_reports_false(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)

    assert repo.delete(user_id=alex.id, provider="gemini") is False


def test_deleting_one_providers_credential_leaves_another_providers_alone(db_session, two_users):
    alex, _ = two_users
    repo = SqlAlchemyUserAICredentialRepository(db_session)
    repo.upsert(_credential(alex.id, "gemini"))
    repo.upsert(_credential(alex.id, "openai"))

    repo.delete(user_id=alex.id, provider="gemini")

    assert repo.get(user_id=alex.id, provider="gemini") is None
    assert repo.get(user_id=alex.id, provider="openai") is not None
