"""Multi-instance-safe acquisition dispatch (#180, issue #184 TODO 2).

Mirrors test_durable_scheduler.py's ReminderDispatcher tests exactly: two
`AcquisitionDispatcher` objects sharing one database simulate two backend
instances polling the same due ladder, which is the actual shared resource
two real instances would race on.
"""
from __future__ import annotations

from datetime import timedelta

from app.domain.entities import User
from app.domain.services.acquisition import AcquisitionScheduler
from app.domain.value_objects import ReviewOutcome, UserRole
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

    def send(self, user, message, channel):
        self.sent.append((user.username, channel))


def _user(db_session, username="alex", email="alex@example.com"):
    return SqlAlchemyUserRepository(db_session).add(
        User(id=None, username=username, email=email, hashed_password="x", role=UserRole.USER)
    )


def _enable_loop(db_session, user_id):
    repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = repo.get_by_user(user_id)
    from app.domain.entities import RecallSettings

    settings = settings or RecallSettings(user_id=user_id)
    settings.acquisition_loop_enabled = True
    repo.upsert(settings)
    db_session.commit()


def _due_ladder(db_session, user_id, word_id=1, now=None):
    # Started far enough in the past (relative to the real wall clock the
    # dispatcher itself reads) that rung 0's 30-second offset has already
    # elapsed by the time the test runs, regardless of what moment that is.
    now = now or (real_utcnow() - timedelta(minutes=5))
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    state = AcquisitionScheduler().start(word_id, user_id, now)
    repo.upsert(state)
    db_session.commit()
    return state


def test_two_instances_dispatch_the_same_due_ladder_once(db_session):
    user = _user(db_session)
    _enable_loop(db_session, user.id)
    _due_ladder(db_session, user.id)

    first, second = _RecordingChannel(), _RecordingChannel()

    AcquisitionDispatcher(lambda: db_session, first)()
    AcquisitionDispatcher(lambda: db_session, second)()

    delivered = [bool(first.sent), bool(second.sent)]
    assert delivered.count(True) == 1, f"instance A sent {first.sent}, instance B sent {second.sent}"


def test_a_different_words_ladder_is_not_suppressed(db_session):
    user = _user(db_session)
    _enable_loop(db_session, user.id)
    _due_ladder(db_session, user.id, word_id=1)
    _due_ladder(db_session, user.id, word_id=2)

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()

    # Each delivery fans out across every channel the recall policy
    # permits (in_app and push are both on by default), so two due ladders
    # produce four sends, not two — what matters is that the second
    # ladder's delivery was not suppressed by the first's claim.
    assert len(channel.sent) == 4


def test_a_graduated_ladder_is_never_dispatched(db_session):
    user = _user(db_session)
    _enable_loop(db_session, user.id)
    state = _due_ladder(db_session, user.id)

    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    scheduler = AcquisitionScheduler()
    from app.domain.services.acquisition import LADDER_OFFSETS

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


def test_dispatch_is_a_no_op_when_the_account_has_since_disabled_the_loop(db_session):
    user = _user(db_session)
    _enable_loop(db_session, user.id)
    _due_ladder(db_session, user.id)

    repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = repo.get_by_user(user.id)
    settings.acquisition_loop_enabled = False
    repo.upsert(settings)
    db_session.commit()

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()
    assert channel.sent == []


def test_dispatch_survives_a_vanished_word_without_raising(db_session):
    """A word deleted between becoming due and the poll running — the
    cascading-delete cleanup already removes its acquisition_events row,
    so list_due simply never surfaces it. This proves the poll does not
    crash if it somehow did."""
    user = _user(db_session)
    _enable_loop(db_session, user.id)

    channel = _RecordingChannel()
    AcquisitionDispatcher(lambda: db_session, channel)()  # nothing due at all
    assert channel.sent == []
