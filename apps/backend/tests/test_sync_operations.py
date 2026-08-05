"""The offline mutation log itself (issue #90).

Where test_sync_merge.py covers *what may be applied*, this covers the log that
records it: idempotency by operation id, the per-account cursor, and the fact
that a conflicting operation is kept rather than dropped.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.services.sync_merge import SyncStatus
from app.domain.value_objects import UserRole, utcnow
from app.infrastructure.models import UserModel
from app.infrastructure.repositories import SqlAlchemySyncOperationRepository


def _user(db, user_id: int, username: str) -> None:
    db.add(
        UserModel(
            id=user_id, username=username, email=f"{username}@example.com",
            hashed_password="x", role=UserRole.USER.value, created_at=utcnow(),
            is_active=True, streak_days=0, longest_streak_days=0,
            total_words_learned=0, total_study_seconds=0, time_zone="UTC",
        )
    )
    db.flush()


@pytest.fixture()
def repo(db_session):
    _user(db_session, 1, "alex")
    return SqlAlchemySyncOperationRepository(db_session)


def _record(repo, operation_id="op-1", status=SyncStatus.APPLIED, user_id=1, **overrides):
    fields = dict(
        user_id=user_id,
        operation_id=operation_id,
        entity_type="word",
        entity_id=7,
        operation="update",
        payload={"term": "rapido"},
        base_revision=1,
        status=status.value,
        conflict_reason=None,
    )
    fields.update(overrides)
    return repo.record(**fields)


# --- Idempotency -----------------------------------------------------------


def test_the_same_operation_id_cannot_be_recorded_twice(repo, db_session):
    """The constraint is the mechanism, not a safety net: a client retrying
    after a lost response inserts this same row and loses to itself."""
    _record(repo, operation_id="op-1")

    with pytest.raises(IntegrityError):
        _record(repo, operation_id="op-1")
        db_session.flush()


def test_an_already_submitted_operation_is_findable(repo):
    """Which is how a retry is answered with the original outcome instead of
    being applied a second time."""
    _record(repo, operation_id="op-1")

    found = repo.find(1, "op-1")

    assert found is not None
    assert found.status == SyncStatus.APPLIED.value


def test_operation_ids_are_scoped_per_account(repo, db_session):
    """Client-generated ids are only unique to the client that made them. Two
    accounts must be able to use the same id without colliding."""
    _user(db_session, 2, "sam")
    _record(repo, operation_id="op-1", user_id=1)

    _record(repo, operation_id="op-1", user_id=2)

    assert repo.find(1, "op-1").user_id == 1
    assert repo.find(2, "op-1").user_id == 2


def test_another_accounts_operation_is_not_found(repo, db_session):
    _user(db_session, 2, "sam")
    _record(repo, operation_id="op-1", user_id=2)

    assert repo.find(1, "op-1") is None


# --- The cursor ------------------------------------------------------------


def test_the_sequence_advances_per_account(repo):
    first = _record(repo, operation_id="op-1")
    second = _record(repo, operation_id="op-2")

    assert second.server_sequence == first.server_sequence + 1


def test_one_accounts_activity_does_not_advance_anothers_cursor(repo, db_session):
    """Scoped rather than global, so a busy account does not force everyone
    else to re-pull."""
    _user(db_session, 2, "sam")
    _record(repo, operation_id="a1", user_id=1)
    _record(repo, operation_id="a2", user_id=1)

    theirs = _record(repo, operation_id="b1", user_id=2)

    assert theirs.server_sequence == 1


def test_pulling_since_a_cursor_returns_only_newer_operations(repo):
    first = _record(repo, operation_id="op-1")
    _record(repo, operation_id="op-2")
    _record(repo, operation_id="op-3")

    later = repo.list_since(1, first.server_sequence)

    assert [o.operation_id for o in later] == ["op-2", "op-3"]


def test_pulling_from_zero_returns_everything(repo):
    _record(repo, operation_id="op-1")
    _record(repo, operation_id="op-2")

    assert len(repo.list_since(1, 0)) == 2


def test_changes_are_returned_oldest_first(repo):
    """A client applies them in order; newest-first would replay history
    backwards."""
    _record(repo, operation_id="op-1")
    _record(repo, operation_id="op-2")

    pulled = repo.list_since(1, 0)

    assert pulled[0].server_sequence < pulled[1].server_sequence


def test_one_account_cannot_pull_anothers_operations(repo, db_session):
    _user(db_session, 2, "sam")
    _record(repo, operation_id="theirs", user_id=2)

    assert repo.list_since(1, 0) == []


# --- Conflicts are kept, not dropped ---------------------------------------


def test_a_conflicting_operation_is_recorded_with_its_reason(repo):
    """The issue is explicit that neither version may be silently discarded.
    A conflict is a row, not a rejection."""
    stored = _record(
        repo,
        operation_id="op-1",
        status=SyncStatus.CONFLICT,
        conflict_reason="edited revision 3, which is now revision 5",
    )

    assert stored.status == SyncStatus.CONFLICT.value
    assert "revision 3" in stored.conflict_reason
    # The payload survives, so the version the user made offline can still be
    # shown to them when they resolve it.
    assert stored.payload == {"term": "rapido"}


def test_conflicts_are_listed_for_review(repo):
    _record(repo, operation_id="ok", status=SyncStatus.APPLIED)
    _record(repo, operation_id="bad", status=SyncStatus.CONFLICT, conflict_reason="stale")

    conflicts = repo.list_conflicts(1)

    assert [c.operation_id for c in conflicts] == ["bad"]


def test_one_account_cannot_see_anothers_conflicts(repo, db_session):
    _user(db_session, 2, "sam")
    _record(repo, operation_id="theirs", user_id=2, status=SyncStatus.CONFLICT)

    assert repo.list_conflicts(1) == []
