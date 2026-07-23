import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest
from zoneinfo import ZoneInfo
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.orm import Session

from app.application.use_cases.reminders import (
    CancelReminderUseCase,
    DeliverReminderUseCase,
    ScheduleReminderUseCase,
)
from app.config import Settings
from app.domain.entities import Group, RecallSettings, Reminder, User
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.value_objects import Recurrence, SupportedLanguage, UserRole, utcnow
from app.infrastructure.reminders import ApSchedulerReminderScheduler, reminder_job_id
from app.infrastructure.scheduler import create_scheduler, register_jobs


def _reminder(**overrides) -> Reminder:
    defaults = dict(
        id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY
    )
    defaults.update(overrides)
    return Reminder(**defaults)


def _user(**overrides) -> User:
    defaults = dict(id=1, username="alex", email="alex@example.com", hashed_password="x", role=UserRole.USER)
    defaults.update(overrides)
    return User(**defaults)


class _InMemoryReminderRepository:
    def __init__(self, reminders: list[Reminder] | None = None):
        self.rows: dict[int, Reminder] = {r.id: r for r in (reminders or [])}
        self._next_id = max(self.rows, default=0) + 1

    def get_by_id(self, reminder_id):
        return self.rows.get(reminder_id)

    def list_by_user(self, user_id):
        return [r for r in self.rows.values() if r.user_id == user_id]

    def list_enabled(self):
        return [r for r in self.rows.values() if r.enabled]

    def add(self, reminder):
        reminder.id = self._next_id
        self._next_id += 1
        self.rows[reminder.id] = reminder
        return reminder

    def update(self, reminder):
        self.rows[reminder.id] = reminder
        return reminder

    def delete(self, reminder_id):
        self.rows.pop(reminder_id, None)


class _InMemoryUserRepository:
    def __init__(self, users: list[User]):
        self.rows = {u.id: u for u in users}

    def get_by_id(self, user_id):
        return self.rows.get(user_id)


class _InMemoryGroupRepository:
    def __init__(self, groups: list[Group]):
        self.rows = {g.id: g for g in groups}

    def get_by_id(self, group_id):
        return self.rows.get(group_id)


def _independent_sessions(db_session) -> Callable[[], Session]:
    """Hand production code a session of its own, bound to the same engine.

    `restore_reminder_jobs` closes whatever its factory returns. Passing the
    test's own fixture session would have the code under test close the
    fixture out from under the test, which is harmless only for as long as
    nobody adds an assertion after the call.

    Seeded rows are committed first so the independent session can see them.
    """
    engine = db_session.get_bind()
    db_session.commit()
    return lambda: Session(bind=engine)


def _groups(group_id: int = 2, owner_id: int = 1) -> _InMemoryGroupRepository:
    return _InMemoryGroupRepository(
        [Group(id=group_id, owner_id=owner_id, name="Verbs", target_language=SupportedLanguage.SPANISH)]
    )


class _SingleUserSettingsRepository:
    def __init__(self, settings: RecallSettings):
        self.settings = settings

    def get_by_user(self, user_id):
        return self.settings


class _RecordingReminderScheduler:
    def __init__(self):
        self.scheduled: list[Reminder] = []
        self.scheduled_zones: list[str] = []
        self.unscheduled: list[int] = []

    def schedule(self, reminder: Reminder, time_zone: str = "UTC") -> None:
        self.scheduled.append(reminder)
        self.scheduled_zones.append(time_zone)

    def unschedule(self, reminder_id: int) -> None:
        self.unscheduled.append(reminder_id)


class _RecordingChannel:
    def __init__(self):
        self.calls: list[tuple[User, str, str]] = []

    def send(self, user, message, channel):
        self.calls.append((user, message, channel))


# ---------------------------------------------------------------------------
# ScheduleReminderUseCase
# ---------------------------------------------------------------------------


def test_scheduling_a_reminder_persists_it_and_registers_exactly_one_job():
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()

    saved = ScheduleReminderUseCase(repo, _groups(), jobs).execute(_reminder())

    assert saved.id is not None
    assert repo.get_by_id(saved.id) is saved
    assert [r.id for r in jobs.scheduled] == [saved.id]


def test_a_reminder_is_persisted_before_its_job_is_registered():
    """A job registered against an unsaved reminder would have no id to look
    itself up by when it fires."""
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()

    ScheduleReminderUseCase(repo, _groups(), jobs).execute(_reminder())

    assert jobs.scheduled[0].id is not None


def test_a_disabled_reminder_is_persisted_but_registers_no_job():
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()

    saved = ScheduleReminderUseCase(repo, _groups(), jobs).execute(_reminder(enabled=False))

    assert repo.get_by_id(saved.id) is not None
    assert jobs.scheduled == []


def test_cancelling_a_reminder_deletes_it_and_unregisters_its_job():
    repo = _InMemoryReminderRepository([_reminder(id=7)])
    jobs = _RecordingReminderScheduler()

    CancelReminderUseCase(repo, jobs).execute(user_id=1, reminder_id=7)

    assert repo.get_by_id(7) is None
    assert jobs.unscheduled == [7]


# ---------------------------------------------------------------------------
# Ownership. The repositories' get_by_id are deliberately unscoped, so every
# use case has to establish that the actor owns what it is about to touch.
# ---------------------------------------------------------------------------


def test_a_reminder_cannot_be_scheduled_against_someone_elses_group():
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()
    groups = _groups(owner_id=99)

    with pytest.raises(PermissionDeniedError):
        ScheduleReminderUseCase(repo, groups, jobs).execute(_reminder(user_id=1, group_id=2))

    assert repo.rows == {}
    assert jobs.scheduled == []


def test_a_reminder_cannot_be_scheduled_against_a_group_that_does_not_exist():
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()

    with pytest.raises(EntityNotFoundError):
        ScheduleReminderUseCase(repo, _InMemoryGroupRepository([]), jobs).execute(_reminder())

    assert repo.rows == {}
    assert jobs.scheduled == []


def test_another_users_reminder_cannot_be_cancelled():
    repo = _InMemoryReminderRepository([_reminder(id=7, user_id=1)])
    jobs = _RecordingReminderScheduler()

    with pytest.raises(PermissionDeniedError):
        CancelReminderUseCase(repo, jobs).execute(user_id=99, reminder_id=7)

    assert repo.get_by_id(7) is not None
    assert jobs.unscheduled == []


def test_cancelling_a_reminder_that_does_not_exist_reports_it_as_missing():
    repo = _InMemoryReminderRepository()
    jobs = _RecordingReminderScheduler()

    with pytest.raises(EntityNotFoundError):
        CancelReminderUseCase(repo, jobs).execute(user_id=1, reminder_id=404)

    assert jobs.unscheduled == []


# ---------------------------------------------------------------------------
# APScheduler adapter
# ---------------------------------------------------------------------------


def test_adapter_registers_a_recurring_cron_job_for_a_daily_reminder():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(id=3, trigger_time="09:05", recurrence=Recurrence.DAILY))

    job = scheduler.get_job(reminder_job_id(3))
    assert isinstance(job.trigger, CronTrigger)
    assert job.args == (3,)
    assert {f.name: str(f) for f in job.trigger.fields}["hour"] == "9"
    assert {f.name: str(f) for f in job.trigger.fields}["minute"] == "5"


def test_a_recurring_reminder_is_registered_in_utc_not_the_hosts_local_time():
    """A reminder is registered against its owner's zone, which defaults to
    UTC. Dropping that leaves APScheduler to fall back on the *host's* local
    zone, which fires every reminder at the wrong wall-clock hour on any
    deployment outside UTC while a UTC continuous-integration host sees
    nothing wrong.

    Compared by equality against ZoneInfo("UTC") rather than by identity
    against `timezone.utc`: since issue #44 the trigger legitimately carries a
    ZoneInfo, so identity would no longer distinguish the owner's zone from
    the host fallback. Equality still does — a host-local fallback on a
    machine outside UTC yields a different zone.
    """
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(id=30, trigger_time="09:05", recurrence=Recurrence.DAILY))

    assert scheduler.get_job(reminder_job_id(30)).trigger.timezone == ZoneInfo("UTC")


def test_adapter_registers_a_one_shot_job_at_the_next_occurrence():
    scheduler = create_scheduler()
    clock = lambda: datetime(2026, 3, 1, 8, 30)  # noqa: E731
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None, clock=clock)

    adapter.schedule(_reminder(id=4, trigger_time="09:00", recurrence=Recurrence.ONCE))

    job = scheduler.get_job(reminder_job_id(4))
    assert isinstance(job.trigger, DateTrigger)
    assert job.trigger.run_date.replace(tzinfo=None) == datetime(2026, 3, 1, 9, 0)


def test_a_one_shot_reminder_is_registered_in_utc_not_the_hosts_local_time():
    """The same UTC guarantee as above, for the other trigger type."""
    scheduler = create_scheduler()
    clock = lambda: datetime(2026, 3, 1, 8, 30)  # noqa: E731
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None, clock=clock)

    adapter.schedule(_reminder(id=40, trigger_time="09:00", recurrence=Recurrence.ONCE))

    run_date = scheduler.get_job(reminder_job_id(40)).trigger.run_date
    assert run_date.tzinfo is timezone.utc
    assert run_date == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("recurrence", [Recurrence.DAILY, Recurrence.ONCE])
def test_a_reminders_job_is_configured_so_a_backlog_cannot_become_a_burst(recurrence):
    """The duplicate-delivery guarantee, pinned.

    Every one of these settings is load-bearing: `coalesce` collapses runs the
    scheduler missed into a single notification instead of replaying each one,
    `max_instances` stops a slow delivery from overlapping with the next, and
    the misfire grace period is what makes a late reminder still arrive rather
    than being dropped. Without assertions they are three defaults nothing
    protects.
    """
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(id=50, recurrence=recurrence))

    job = scheduler.get_job(reminder_job_id(50))
    assert job.coalesce is True
    assert job.max_instances == 1
    assert job.misfire_grace_time == 300


def test_registering_the_same_reminder_twice_leaves_exactly_one_job():
    """The guard against duplicate delivery: a reminder's job id is derived
    from its identity, so a re-registration replaces rather than doubles."""
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)
    reminder = _reminder(id=5)

    adapter.schedule(reminder)
    adapter.schedule(reminder)

    assert [job.id for job in scheduler.get_jobs()] == [reminder_job_id(5)]


def test_unscheduling_removes_the_job():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)
    adapter.schedule(_reminder(id=6))

    adapter.unschedule(6)

    assert scheduler.get_jobs() == []


def test_unscheduling_an_unregistered_reminder_leaves_other_jobs_alone():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)
    adapter.schedule(_reminder(id=8))

    adapter.unschedule(999)  # must not raise

    assert [job.id for job in scheduler.get_jobs()] == [reminder_job_id(8)]


def test_scheduling_an_unsaved_reminder_is_rejected():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    with pytest.raises(ValueError):
        adapter.schedule(_reminder(id=None))


# ---------------------------------------------------------------------------
# End-to-end timing (the one test that uses the scheduler's real clock).
# The job body's own rules are covered in test_reminder_delivery.py.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_a_reminder_five_seconds_out_fires_and_notifies_exactly_once():
    """Issue #25's stated verification. Settings permit exactly one channel,
    so the notification port's call count measures nothing but how many times
    the reminder fired — two deliveries would show up as two calls."""
    channel = _RecordingChannel()
    repo = _InMemoryReminderRepository()
    settings = RecallSettings(
        user_id=1, push_enabled=True, email_enabled=False, desktop_enabled=False, in_app_enabled=False
    )
    deliver = DeliverReminderUseCase(
        repo, _InMemoryUserRepository([_user()]), _SingleUserSettingsRepository(settings), channel
    )

    async def _run() -> None:
        scheduler = create_scheduler()
        scheduler.start()
        adapter = ApSchedulerReminderScheduler(scheduler, dispatch=deliver.execute)

        fires_at = utcnow() + timedelta(seconds=5)
        reminder = ScheduleReminderUseCase(repo, _groups(), adapter).execute(
            _reminder(trigger_time=fires_at.strftime("%H:%M:%S"), recurrence=Recurrence.ONCE)
        )
        assert scheduler.get_job(reminder_job_id(reminder.id)) is not None

        await asyncio.sleep(8)  # 5s until it fires, then 3s of watching for a repeat
        scheduler.shutdown(wait=False)

    asyncio.run(_run())

    assert len(channel.calls) == 1
    assert channel.calls[0][2] == "push"


# ---------------------------------------------------------------------------
# Startup registration
# ---------------------------------------------------------------------------


def test_register_jobs_restores_a_job_for_every_enabled_reminder(db_session):
    from app.domain.entities import Reminder as DomainReminder
    from app.infrastructure.models import GroupModel, UserModel
    from app.infrastructure.repositories import SqlAlchemyReminderRepository

    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()
    repo = SqlAlchemyReminderRepository(db_session)
    enabled = repo.add(
        DomainReminder(
            id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY
        )
    )
    repo.add(
        DomainReminder(
            id=None,
            user_id=user.id,
            group_id=group.id,
            trigger_time="21:00",
            recurrence=Recurrence.DAILY,
            enabled=False,
        )
    )

    scheduler = create_scheduler()
    register_jobs(
        scheduler,
        Settings(environment="production"),
        session_factory=_independent_sessions(db_session),
        channel=_RecordingChannel(),
    )

    assert [job.id for job in scheduler.get_jobs()] == [reminder_job_id(enabled.id)]


def test_register_jobs_without_a_session_factory_registers_only_the_heartbeat():
    scheduler = create_scheduler()

    register_jobs(scheduler, Settings(environment="development"))

    assert {job.id for job in scheduler.get_jobs()} == {"dev_heartbeat"}


def test_app_startup_restores_reminder_jobs(db_session, monkeypatch):
    """Registering jobs is only useful if the running app actually does it."""
    from fastapi.testclient import TestClient

    from app.domain.entities import Reminder as DomainReminder
    from app.infrastructure.models import GroupModel, UserModel
    from app.infrastructure.repositories import SqlAlchemyReminderRepository

    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()
    saved = SqlAlchemyReminderRepository(db_session).add(
        DomainReminder(
            id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY
        )
    )

    import app.main as main_module

    monkeypatch.setattr(main_module, "SessionLocal", _independent_sessions(db_session))

    with TestClient(main_module.app):
        job_ids = {job.id for job in main_module.app.state.scheduler.get_jobs()}

    assert reminder_job_id(saved.id) in job_ids


def test_register_jobs_skips_an_unusable_recurrence_and_restores_the_rest(db_session):
    """A corrupt reminder must cost only itself. The surviving-rows assertion
    is the point: one bad row previously took the whole restore down with it."""
    from app.infrastructure.models import GroupModel, ReminderModel, UserModel

    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()

    def _row(**overrides):
        defaults = dict(
            user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence="daily", created_at=utcnow()
        )
        defaults.update(overrides)
        row = ReminderModel(**defaults)
        db_session.add(row)
        db_session.flush()
        return row

    before = _row(trigger_time="06:00")
    _row(recurrence="weekly", trigger_time="07:00")
    _row(recurrence="", trigger_time="07:30")
    after = _row(trigger_time="08:00")

    scheduler = create_scheduler()
    register_jobs(
        scheduler, Settings(environment="production"), session_factory=_independent_sessions(db_session)
    )

    assert [job.id for job in scheduler.get_jobs()] == [
        reminder_job_id(before.id),
        reminder_job_id(after.id),
    ]


def test_register_jobs_survives_a_reminder_restore_that_fails_outright():
    """Reminders are a nudge, not the product. Nothing about restoring them
    may stop the application from starting."""

    def _exploding_session_factory():
        raise RuntimeError("the reminders table is unreadable")

    scheduler = create_scheduler()

    register_jobs(
        scheduler, Settings(environment="development"), session_factory=_exploding_session_factory
    )

    assert {job.id for job in scheduler.get_jobs()} == {"dev_heartbeat"}


def test_app_startup_survives_a_corrupt_reminders_table(db_session, monkeypatch):
    """End to end: the application boots, and the readable reminders in the
    same table are still scheduled."""
    from fastapi.testclient import TestClient

    from app.infrastructure.models import GroupModel, ReminderModel, UserModel

    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()
    corrupt = ReminderModel(
        user_id=user.id, group_id=group.id, trigger_time="07:00", recurrence="weekly", created_at=utcnow()
    )
    healthy = ReminderModel(
        user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence="daily", created_at=utcnow()
    )
    db_session.add_all([corrupt, healthy])
    db_session.flush()

    import app.main as main_module

    monkeypatch.setattr(main_module, "SessionLocal", _independent_sessions(db_session))

    with TestClient(main_module.app) as test_client:
        assert test_client.get("/api/v1/health").status_code == 200
        job_ids = {job.id for job in main_module.app.state.scheduler.get_jobs()}

    assert reminder_job_id(healthy.id) in job_ids
    assert reminder_job_id(corrupt.id) not in job_ids


def test_register_jobs_skips_a_reminder_whose_trigger_time_is_unusable(db_session):
    """One malformed row must not stop the remaining reminders from being
    restored at startup."""
    from app.infrastructure.models import GroupModel, ReminderModel, UserModel

    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()
    db_session.add(
        ReminderModel(
            user_id=user.id, group_id=group.id, trigger_time="nope", recurrence="daily", created_at=utcnow()
        )
    )
    db_session.flush()
    good = ReminderModel(
        user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence="daily", created_at=utcnow()
    )
    db_session.add(good)
    db_session.flush()

    scheduler = create_scheduler()
    register_jobs(
        scheduler, Settings(environment="production"), session_factory=_independent_sessions(db_session)
    )

    assert [job.id for job in scheduler.get_jobs()] == [reminder_job_id(good.id)]
