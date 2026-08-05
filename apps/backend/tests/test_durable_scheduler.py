"""Durable, multi-instance-safe scheduling (ROADMAP 4.2, issue #20).

The issue's verify criterion is one sentence: *two backend instances running
concurrently do not double-fire the same reminder.* Everything here exists to
check that, plus the persistence half that makes running two instances worth
doing in the first place.

Two instances are simulated by two `ReminderDispatcher` objects over the same
database, which is what the instances actually share. Running real processes
would test the operating system rather than the mechanism.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.config import Settings
from app.domain.entities import Reminder, User
from app.domain.value_objects import Recurrence, UserRole, utcnow
from app.infrastructure.job_claims import (
    CLAIM_RETENTION,
    claim,
    occurrence_key,
    purge_expired_claims,
    reminder_job_key,
)
from app.infrastructure.jobs.reminder_dispatch import ReminderDispatcher
from app.infrastructure.models import SchedulerJobClaimModel
from app.infrastructure.repositories import (
    SqlAlchemyGroupRepository,
    SqlAlchemyReminderRepository,
    SqlAlchemyUserRepository,
)
from app.infrastructure.scheduler import create_scheduler
from app.domain.entities import Group
from app.domain.value_objects import SupportedLanguage


class _RecordingChannel:
    def __init__(self):
        self.sent = []

    def send(self, user, message, channel):
        self.sent.append((user.username, channel))


@pytest.fixture()
def daily_reminder(db_session):
    """A user with one enabled daily reminder, due now on their own clock."""
    user = SqlAlchemyUserRepository(db_session).add(
        User(
            id=None,
            username="alex",
            email="alex@example.com",
            hashed_password="x",
            role=UserRole.USER,
        )
    )
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user.id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    reminder = SqlAlchemyReminderRepository(db_session).add(
        Reminder(
            id=None,
            user_id=user.id,
            group_id=group.id,
            trigger_time="09:00",
            recurrence=Recurrence.DAILY,
        )
    )
    db_session.commit()
    return reminder


# --- The criterion ---------------------------------------------------------


# One delivery fans out across every channel the recall policy permits, so
# these count *instances that delivered*, not sends. Counting sends would make
# the assertions depend on how many channels happen to be enabled.


def test_two_instances_deliver_a_reminder_once(db_session, daily_reminder):
    """The verify criterion of #20, stated directly."""
    first, second = _RecordingChannel(), _RecordingChannel()

    ReminderDispatcher(lambda: db_session, first)(daily_reminder.id)
    ReminderDispatcher(lambda: db_session, second)(daily_reminder.id)

    delivered = [bool(first.sent), bool(second.sent)]
    assert delivered.count(True) == 1, (
        f"instance A sent {first.sent}, instance B sent {second.sent}"
    )


def test_a_third_and_fourth_instance_change_nothing(db_session, daily_reminder):
    channels = [_RecordingChannel() for _ in range(4)]
    for channel in channels:
        ReminderDispatcher(lambda: db_session, channel)(daily_reminder.id)

    assert [bool(c.sent) for c in channels].count(True) == 1


def test_a_different_reminder_is_not_suppressed(db_session, daily_reminder):
    """The claim is per job, so one reminder firing must not block another."""
    other = SqlAlchemyReminderRepository(db_session).add(
        Reminder(
            id=None,
            user_id=daily_reminder.user_id,
            group_id=daily_reminder.group_id,
            trigger_time="09:00",
            recurrence=Recurrence.DAILY,
        )
    )
    db_session.commit()
    first, second = _RecordingChannel(), _RecordingChannel()

    ReminderDispatcher(lambda: db_session, first)(daily_reminder.id)
    ReminderDispatcher(lambda: db_session, second)(other.id)

    assert first.sent and second.sent, "a second reminder was wrongly suppressed"


def test_a_vanished_reminder_is_not_claimed(db_session):
    """A job outliving its subject is expected. Claiming for it would only
    leave litter keyed to an id that no longer exists."""
    channel = _RecordingChannel()

    ReminderDispatcher(lambda: db_session, channel)(999999)

    assert channel.sent == []
    assert db_session.query(SchedulerJobClaimModel).count() == 0


# --- The occurrence key ----------------------------------------------------
#
# This is where exactly-once is actually decided. A key computed from "now"
# would differ between two instances reading the clock moments apart, and the
# duplicate would sail through.


def test_instances_reading_the_clock_seconds_apart_agree():
    slot = time(9, 0)
    early = occurrence_key(datetime(2026, 8, 2, 9, 0, 0), slot)
    later = occurrence_key(datetime(2026, 8, 2, 9, 0, 3), slot)

    assert early == later


def test_a_late_misfire_claims_the_firing_it_belongs_to():
    """A catch-up run minutes after the slot is the *same* firing, not a new
    one, so it must produce the key the on-time instance already used."""
    slot = time(9, 0)

    on_time = occurrence_key(datetime(2026, 8, 2, 9, 0, 1), slot)
    late = occurrence_key(datetime(2026, 8, 2, 9, 4, 30), slot)

    assert on_time == late


def test_a_delivery_before_todays_slot_belongs_to_yesterday():
    """Running at 00:10 for an 09:00 reminder is a very late delivery of
    yesterday's firing. Keying it to today would reserve a slot that has not
    happened yet and silently suppress this evening's real one."""
    slot = time(9, 0)

    key = occurrence_key(datetime(2026, 8, 2, 0, 10), slot)

    assert key.startswith(date(2026, 8, 1).isoformat())


def test_consecutive_days_are_distinct_firings():
    slot = time(9, 0)

    assert occurrence_key(datetime(2026, 8, 2, 9, 0), slot) != occurrence_key(
        datetime(2026, 8, 3, 9, 0), slot
    )


def test_a_one_shot_reminder_has_a_single_occurrence():
    assert occurrence_key(datetime(2026, 8, 2, 9, 0), None) == "once"
    assert occurrence_key(datetime(2027, 1, 1, 3, 0), None) == "once"


# --- The claim itself ------------------------------------------------------


def test_the_first_caller_wins_and_the_rest_stand_down(db_session):
    key = "2026-08-02T09:00:00"

    assert claim(db_session, "reminder:1", key) is True
    assert claim(db_session, "reminder:1", key) is False
    assert claim(db_session, "reminder:1", key) is False


def test_a_losing_claim_leaves_the_session_usable(db_session):
    """The integrity error has to be rolled back cleanly: the dispatcher goes
    on to use this same session, and a session left in a failed transaction
    would turn a routine duplicate into a broken delivery."""
    key = "2026-08-02T09:00:00"
    claim(db_session, "reminder:1", key)

    claim(db_session, "reminder:1", key)

    assert db_session.query(SchedulerJobClaimModel).count() == 1


def test_claims_are_namespaced_by_job(db_session):
    assert reminder_job_key(1) != "1"
    assert claim(db_session, reminder_job_key(1), "k") is True
    assert claim(db_session, reminder_job_key(2), "k") is True


def test_expired_claims_are_purged_and_recent_ones_kept(db_session):
    db_session.add(
        SchedulerJobClaimModel(
            job_key="reminder:1",
            occurrence_key="old",
            claimed_at=utcnow() - CLAIM_RETENTION - timedelta(days=1),
        )
    )
    db_session.add(
        SchedulerJobClaimModel(
            job_key="reminder:1", occurrence_key="fresh", claimed_at=utcnow()
        )
    )
    db_session.commit()

    assert purge_expired_claims(db_session) == 1
    remaining = db_session.query(SchedulerJobClaimModel).all()
    assert [c.occurrence_key for c in remaining] == ["fresh"]


# --- Persistence -----------------------------------------------------------


def test_the_default_scheduler_persists_its_jobs():
    scheduler = create_scheduler(Settings(scheduler_job_store="database", _env_file=None))

    assert isinstance(scheduler._jobstores["default"], SQLAlchemyJobStore)


def test_memory_is_available_for_processes_that_should_not_persist():
    scheduler = create_scheduler(Settings(scheduler_job_store="memory", _env_file=None))

    assert not isinstance(scheduler._jobstores.get("default"), SQLAlchemyJobStore)


def test_an_unknown_job_store_is_rejected_at_startup():
    """A typo should stop the process while someone is watching, not quietly
    fall back to in-memory and lose every job on the next restart."""
    with pytest.raises(ValueError):
        Settings(scheduler_job_store="postgres", _env_file=None)
