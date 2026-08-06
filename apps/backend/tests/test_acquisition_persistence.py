"""Persisted acquisition-ladder state (#180, issue #184 TODO 2).

Covers the repository directly: upsert is really append-only with "current
state" derived as the latest row, operation_id retries don't duplicate a
transition, and list_due resolves each word's *true* latest state before
filtering — not a stale-but-due row shadowed by a newer, not-yet-due one.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.acquisition import AcquisitionEntryReason, AcquisitionScheduler
from app.domain.value_objects import ReviewOutcome
from app.infrastructure.repositories import SqlAlchemyAcquisitionStateRepository, SqlAlchemyUserRepository

NOW = datetime(2026, 8, 6, 9, 0)


def _setup_word(client, headers, term="palabra"):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    return client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
        headers=headers,
    ).json()


def test_get_for_word_returns_none_before_anything_is_recorded(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    assert repo.get_for_word(owner_id, word["id"]) is None


def test_upsert_is_append_only_and_get_for_word_returns_the_latest(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)

    state = scheduler.start(word["id"], owner_id, NOW, entry_reason=AcquisitionEntryReason.NEW_ITEM)
    repo.upsert(state)
    state = scheduler.advance(state, ReviewOutcome.CORRECT, NOW + timedelta(seconds=30))
    repo.upsert(state)

    current = repo.get_for_word(owner_id, word["id"])
    assert current.rung == 1
    assert current.entry_reason == "new_item"


def test_a_retried_operation_id_does_not_duplicate_the_transition(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = scheduler.start(word["id"], owner_id, NOW, operation_id="op-1")

    first = repo.upsert(state)
    second = repo.upsert(state)  # simulates a retried request with the same operation_id

    assert first.updated_at == second.updated_at
    # Directly count rows via the model to prove no duplicate was inserted.
    from app.infrastructure.models import AcquisitionEventModel

    assert db_session.query(AcquisitionEventModel).filter_by(operation_id="op-1").count() == 1


def test_delete_for_word_removes_every_row(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = scheduler.start(word["id"], owner_id, NOW)
    repo.upsert(state)
    repo.upsert(scheduler.advance(state, ReviewOutcome.CORRECT, NOW + timedelta(seconds=30)))

    repo.delete_for_word(owner_id, word["id"])

    assert repo.get_for_word(owner_id, word["id"]) is None


def test_list_due_only_returns_the_true_current_states_word_not_a_stale_earlier_one(
    client, auth_headers, db_session
):
    """The regression this repository's list_due docstring warns about:
    an old row that happened to be due must not shadow a newer transition
    for the same word that is not due yet."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)

    # Rung 0, due almost immediately (would be "due" at T+2min).
    state = scheduler.start(word["id"], owner_id, NOW)
    repo.upsert(state)
    # Advances to rung 1 shortly after — due much later (T + 5min offset
    # from this transition's own time).
    state = scheduler.advance(state, ReviewOutcome.CORRECT, NOW + timedelta(seconds=30))
    repo.upsert(state)

    due = repo.list_due(now=NOW + timedelta(minutes=2))
    # The rung-0 row (due at NOW+30s) is due by T+2min, but it is no longer
    # this word's current state — the rung-1 row (due at ~T+5min30s) is,
    # and it is not due yet, so this word must not appear as due at all.
    assert [d.word_id for d in due] == []


def test_list_due_returns_a_word_once_its_true_current_state_is_due(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = scheduler.start(word["id"], owner_id, NOW)
    repo.upsert(state)

    due = repo.list_due(now=NOW + timedelta(minutes=1))
    assert [d.word_id for d in due] == [word["id"]]


def test_list_due_excludes_graduated_ladders(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = scheduler.start(word["id"], owner_id, NOW)
    repo.upsert(state)
    t = NOW
    from app.domain.services.acquisition import LADDER_OFFSETS

    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)
        repo.upsert(state)
    assert state.graduated is True

    due = repo.list_due(now=t + timedelta(days=1))
    assert due == []


def test_list_due_scopes_correctly_across_two_users(client, auth_headers, db_session):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("owner@example.com").id
    owner_word = _setup_word(client, owner_headers, term="uno")

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    stranger_id = SqlAlchemyUserRepository(db_session).get_by_email("stranger@example.com").id
    stranger_word = _setup_word(client, stranger_headers, term="dos")

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    repo.upsert(scheduler.start(owner_word["id"], owner_id, NOW))
    repo.upsert(scheduler.start(stranger_word["id"], stranger_id, NOW))

    due = repo.list_due(now=NOW + timedelta(minutes=1))
    assert {(d.user_id, d.word_id) for d in due} == {
        (owner_id, owner_word["id"]),
        (stranger_id, stranger_word["id"]),
    }


def test_list_due_scoped_to_one_user_excludes_another_users_due_ladder(client, auth_headers, db_session):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("owner@example.com").id
    owner_word = _setup_word(client, owner_headers, term="uno")

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    stranger_id = SqlAlchemyUserRepository(db_session).get_by_email("stranger@example.com").id
    stranger_word = _setup_word(client, stranger_headers, term="dos")

    scheduler = AcquisitionScheduler()
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    repo.upsert(scheduler.start(owner_word["id"], owner_id, NOW))
    repo.upsert(scheduler.start(stranger_word["id"], stranger_id, NOW))

    due = repo.list_due(now=NOW + timedelta(minutes=1), user_id=owner_id)
    assert [(d.user_id, d.word_id) for d in due] == [(owner_id, owner_word["id"])]
