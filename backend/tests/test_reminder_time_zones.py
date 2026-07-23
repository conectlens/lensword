"""End-to-end checks for per-user time zones (issue #44).

These cover the issue's own verification lines: a 09:00 reminder for a user at
UTC+3 fires at 06:00 UTC, and a 22:00-07:00 quiet-hours window suppresses
intrusive channels across that user's local night rather than UTC night.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.application.use_cases.reminders import DeliverReminderUseCase, ScheduleReminderUseCase
from app.domain.entities import RecallSettings, Reminder, User
from app.domain.value_objects import Recurrence, UserRole
from app.infrastructure.reminders import (
    ApSchedulerReminderScheduler,
    LocalWallClockCronTrigger,
    reminder_job_id,
)
from app.infrastructure.scheduler import create_scheduler

ISTANBUL = "Europe/Istanbul"  # UTC+3, no DST since 2016
NEW_YORK = "America/New_York"  # DST transitions


def _user(user_id: int = 1, time_zone: str = "UTC") -> User:
    return User(
        id=user_id,
        username=f"u{user_id}",
        email=f"u{user_id}@example.com",
        hashed_password="x",
        role=UserRole.USER,
        time_zone=time_zone,
    )


def _reminder(**kwargs) -> Reminder:
    defaults = dict(
        id=1, user_id=1, group_id=1, trigger_time="09:00", recurrence=Recurrence.DAILY
    )
    return Reminder(**{**defaults, **kwargs})


# --- Scheduling -----------------------------------------------------------


def test_a_reminder_for_a_utc_plus_3_user_fires_at_06_00_utc():
    """The issue's stated acceptance criterion."""
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(trigger_time="09:00", recurrence=Recurrence.ONCE), ISTANBUL)

    run_date = scheduler.get_job(reminder_job_id(1)).trigger.run_date
    assert run_date.astimezone(timezone.utc).strftime("%H:%M") == "06:00"


def test_a_recurring_reminder_carries_the_owners_zone():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(recurrence=Recurrence.DAILY), ISTANBUL)

    trigger = scheduler.get_job(reminder_job_id(1)).trigger
    assert isinstance(trigger, LocalWallClockCronTrigger)
    assert trigger.timezone == ZoneInfo(ISTANBUL)


def test_a_user_without_a_zone_keeps_the_previous_utc_behaviour():
    scheduler = create_scheduler()
    adapter = ApSchedulerReminderScheduler(scheduler, dispatch=lambda reminder_id: None)

    adapter.schedule(_reminder(recurrence=Recurrence.DAILY), "UTC")

    assert scheduler.get_job(reminder_job_id(1)).trigger.timezone == ZoneInfo("UTC")


# --- DST, through the real trigger ---------------------------------------


def test_recurring_reminder_in_a_spring_forward_gap_fires_once_at_the_gap_end():
    """02:30 does not occur on 2026-03-08 in New York. It resolves to 03:00
    local, matching what a one-shot reminder would do — not to 03:30, which is
    what the underlying CronTrigger returns unaided."""
    zone = ZoneInfo(NEW_YORK)
    trigger = LocalWallClockCronTrigger(hour=2, minute=30, second=0, timezone=zone)

    fire = trigger.get_next_fire_time(None, datetime(2026, 3, 8, 0, 0, tzinfo=zone))

    assert fire.astimezone(timezone.utc) == datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
    assert fire.astimezone(zone).strftime("%H:%M") == "03:00"


def test_recurring_reminder_in_a_fall_back_fold_fires_on_the_first_occurrence():
    """01:30 occurs twice on 2026-11-01 in New York. Only the earlier instant
    is used, so the reminder is delivered once rather than twice."""
    zone = ZoneInfo(NEW_YORK)
    trigger = LocalWallClockCronTrigger(hour=1, minute=30, second=0, timezone=zone)

    fire = trigger.get_next_fire_time(None, datetime(2026, 11, 1, 0, 0, tzinfo=zone))

    assert fire.astimezone(timezone.utc) == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)


def test_a_dst_day_produces_exactly_one_fire_time():
    """The invariant behind the whole policy: one delivery, never zero, never
    two — checked by walking the trigger across each transition day."""
    zone = ZoneInfo(NEW_YORK)
    for hour, minute, day in ((2, 30, 8), (1, 30, 1)):
        month = 3 if day == 8 else 11
        trigger = LocalWallClockCronTrigger(hour=hour, minute=minute, second=0, timezone=zone)
        start = datetime(2026, month, day, 0, 0, tzinfo=zone)
        end = datetime(2026, month, day, 23, 59, tzinfo=zone)

        fires = []
        cursor = trigger.get_next_fire_time(None, start)
        while cursor is not None and cursor <= end:
            fires.append(cursor)
            cursor = trigger.get_next_fire_time(cursor, cursor)

        assert len(fires) == 1, f"expected one fire on {month}/{day}, got {fires}"


# --- Quiet hours ----------------------------------------------------------


class _RecordingChannel:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send(self, user: User, message: str, channel: str) -> None:
        self.sent.append((user.id, channel))


class _Repo:
    def __init__(self, item):
        self.item = item

    def get_by_id(self, _id):
        return self.item

    def get_by_user(self, _user_id):
        return self.item


def _deliver(user_zone: str, utc_now: datetime, quiet=("22:00", "07:00")) -> list[str]:
    channel = _RecordingChannel()
    settings = RecallSettings(
        user_id=1,
        push_enabled=True,
        email_enabled=True,
        desktop_enabled=True,
        in_app_enabled=True,
        quiet_hours_start=quiet[0],
        quiet_hours_end=quiet[1],
    )
    DeliverReminderUseCase(
        _Repo(_reminder()),
        _Repo(_user(time_zone=user_zone)),
        _Repo(settings),
        channel,
        clock=lambda: utc_now,
    ).execute(1)
    return [c for _, c in channel.sent]


def test_quiet_hours_follow_the_users_night_not_utc_night():
    """01:00 UTC is 04:00 in Istanbul — inside a 22:00-07:00 window on the
    user's clock, so the intrusive channels are suppressed."""
    delivered = _deliver(ISTANBUL, datetime(2026, 7, 15, 1, 0))

    assert delivered == ["in_app"]


def test_utc_daytime_that_is_local_night_is_still_quiet():
    """23:00 UTC is 02:00 in Istanbul: quiet locally even though the UTC clock
    reads a different hour."""
    delivered = _deliver(ISTANBUL, datetime(2026, 7, 15, 23, 0))

    assert delivered == ["in_app"]


def test_utc_night_that_is_local_daytime_is_not_quiet():
    """The converse, and the actual bug: 04:00 UTC is 07:00 in Istanbul, which
    is outside the window. Before this change the UTC reading suppressed it."""
    delivered = _deliver(ISTANBUL, datetime(2026, 7, 15, 4, 0))

    assert sorted(delivered) == ["desktop", "email", "in_app", "push"]


def test_a_utc_user_is_unaffected():
    quiet = _deliver("UTC", datetime(2026, 7, 15, 23, 0))
    loud = _deliver("UTC", datetime(2026, 7, 15, 12, 0))

    assert quiet == ["in_app"]
    assert sorted(loud) == ["desktop", "email", "in_app", "push"]


def test_an_unknown_stored_zone_degrades_to_utc_rather_than_losing_delivery():
    delivered = _deliver("Mars/Olympus_Mons", datetime(2026, 7, 15, 12, 0))

    assert sorted(delivered) == ["desktop", "email", "in_app", "push"]


# --- Use-case wiring ------------------------------------------------------


class _RecordingScheduler:
    def __init__(self):
        self.calls: list[tuple[int, str]] = []

    def schedule(self, reminder: Reminder, time_zone: str = "UTC") -> None:
        self.calls.append((reminder.id, time_zone))

    def unschedule(self, reminder_id: int) -> None:
        pass


class _AddRepo:
    def add(self, reminder):
        return reminder


class _Groups:
    def get_by_id(self, _id):
        from app.domain.entities import Group
        from app.domain.value_objects import SupportedLanguage

        return Group(id=1, owner_id=1, name="g", target_language=SupportedLanguage.SPANISH)


@pytest.mark.parametrize("zone", ["UTC", ISTANBUL, NEW_YORK])
def test_scheduling_passes_the_owners_zone_to_the_scheduler(zone):
    jobs = _RecordingScheduler()

    ScheduleReminderUseCase(_AddRepo(), _Groups(), jobs, _Repo(_user(time_zone=zone))).execute(
        _reminder()
    )

    assert jobs.calls == [(1, zone)]


def test_scheduling_without_a_user_repository_falls_back_to_utc():
    """Callers that predate the zone feature keep the previous behavior."""
    jobs = _RecordingScheduler()

    ScheduleReminderUseCase(_AddRepo(), _Groups(), jobs).execute(_reminder())

    assert jobs.calls == [(1, "UTC")]
