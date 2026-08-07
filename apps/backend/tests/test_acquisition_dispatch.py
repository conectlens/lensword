"""Multi-instance-safe acquisition dispatch (#180, issue #184 TODO 2).

Mirrors test_durable_scheduler.py's ReminderDispatcher tests exactly: two
`AcquisitionDispatcher` objects sharing one database simulate two backend
instances polling the same due ladder, which is the actual shared resource
two real instances would race on.

Words are created through the real API rather than referenced by a
fabricated id: word_id is a genuine foreign key, and SQLite (which never
enforces PRAGMA foreign_keys) would not catch a dangling reference the way
Postgres correctly does — the same class of bug already caught once in
#182 and worth not repeating here.
"""
from __future__ import annotations

from datetime import timedelta

from app.domain.entities import RecallSettings
from app.domain.services.acquisition import LADDER_OFFSETS, AcquisitionScheduler
from app.domain.value_objects import ReviewOutcome
from app.domain.value_objects import utcnow as real_utcnow
from app.infrastructure.jobs.acquisition_dispatch import AcquisitionDispatcher
from app.infrastructure.repositories import (
    SqlAlchemyAcquisitionStateRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyUserRepository,
)


class _RecordingChannel:
    def __init__(self):
        self.sent = []

    def send(self, user, message, channel, companion_deep_link=None):
        self.sent.append((user.username, channel))


def _setup_word(client, headers, term="palabra"):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    return client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
        headers=headers,
    ).json()


def _enable_loop(db_session, user_id):
    repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = repo.get_by_user(user_id) or RecallSettings(user_id=user_id)
    settings.acquisition_loop_enabled = True
    repo.upsert(settings)
    db_session.commit()


def _due_ladder(db_session, user_id, word_id, now=None):
    # Started far enough in the past (relative to the real wall clock the
    # dispatcher itself reads) that rung 0's 30-second offset has already
    # elapsed by the time the test runs, regardless of what moment that is.
    now = now or (real_utcnow() - timedelta(minutes=5))
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = AcquisitionScheduler().start(word_id, user_id, now)
    repo.upsert(state)
    db_session.commit()
    return state


def test_two_instances_dispatch_the_same_due_ladder_once(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)
    _enable_loop(db_session, owner_id)
    _due_ladder(db_session, owner_id, word["id"])

    first, second = _RecordingChannel(), _RecordingChannel()

    AcquisitionDispatcher(lambda: db_session, first)()
    AcquisitionDispatcher(lambda: db_session, second)()

    delivered = [bool(first.sent), bool(second.sent)]
    assert delivered.count(True) == 1, f"instance A sent {first.sent}, instance B sent {second.sent}"


def test_a_different_words_ladder_is_not_suppressed(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word_a = _setup_word(client, headers, term="uno")
    word_b = _setup_word(client, headers, term="dos")
    _enable_loop(db_session, owner_id)
    _due_ladder(db_session, owner_id, word_a["id"])
    _due_ladder(db_session, owner_id, word_b["id"])

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()

    # Each delivery fans out across every channel the recall policy
    # permits (in_app and push are both on by default), so two due ladders
    # produce four sends, not two — what matters is that the second
    # ladder's delivery was not suppressed by the first's claim.
    assert len(channel.sent) == 4


def test_a_graduated_ladder_is_never_dispatched(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)
    _enable_loop(db_session, owner_id)
    state = _due_ladder(db_session, owner_id, word["id"])

    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    scheduler = AcquisitionScheduler()

    t = state.started_at
    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)
        repo.upsert(state)
    db_session.commit()
    assert state.graduated is True

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()
    assert channel.sent == []


def test_dispatch_is_a_no_op_when_the_account_has_since_disabled_the_loop(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word = _setup_word(client, headers)
    _enable_loop(db_session, owner_id)
    _due_ladder(db_session, owner_id, word["id"])

    repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = repo.get_by_user(owner_id)
    settings.acquisition_loop_enabled = False
    repo.upsert(settings)
    db_session.commit()

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()
    assert channel.sent == []


def test_dispatch_survives_an_empty_due_list_without_raising(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _enable_loop(db_session, owner_id)

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()  # nothing due at all
    assert channel.sent == []
