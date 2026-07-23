from datetime import datetime

from app.application.use_cases.reminders import DeliverReminderUseCase
from app.domain.entities import RecallSettings, Reminder, User
from app.domain.value_objects import Channel, Recurrence, UserRole

QUIET_HOURS = dict(quiet_hours_start="22:00", quiet_hours_end="07:00")
INTERRUPTIVE = {Channel.PUSH.value, Channel.EMAIL.value, Channel.DESKTOP.value}


def _reminder(**overrides) -> Reminder:
    defaults = dict(id=1, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)
    defaults.update(overrides)
    return Reminder(**defaults)


def _user(**overrides) -> User:
    defaults = dict(id=1, username="alex", email="alex@example.com", hashed_password="x", role=UserRole.USER)
    defaults.update(overrides)
    return User(**defaults)


def _settings(**overrides) -> RecallSettings:
    defaults = dict(user_id=1, push_enabled=True, email_enabled=True, desktop_enabled=True, in_app_enabled=True)
    defaults.update(overrides)
    return RecallSettings(**defaults)


class _InMemoryReminderRepository:
    def __init__(self, reminders: list[Reminder] | None = None):
        self.rows = {r.id: r for r in (reminders or [])}

    def get_by_id(self, reminder_id):
        return self.rows.get(reminder_id)


class _InMemoryUserRepository:
    def __init__(self, users: list[User] | None = None):
        self.rows = {u.id: u for u in (users or [])}

    def get_by_id(self, user_id):
        return self.rows.get(user_id)


class _InMemorySettingsRepository:
    def __init__(self, settings: RecallSettings | None = None):
        self.settings = settings

    def get_by_user(self, user_id):
        return self.settings


class _RecordingChannel:
    def __init__(self):
        self.calls: list[tuple[User, str, str]] = []

    def send(self, user, message, channel):
        self.calls.append((user, message, channel))

    @property
    def channels_used(self) -> list[str]:
        return [channel for _, _, channel in self.calls]


def _deliver(settings: RecallSettings | None, now: datetime, reminder: Reminder | None = None):
    channel = _RecordingChannel()
    reminders = [reminder if reminder is not None else _reminder()]
    use_case = DeliverReminderUseCase(
        _InMemoryReminderRepository(reminders),
        _InMemoryUserRepository([_user()]),
        _InMemorySettingsRepository(settings),
        channel,
        clock=lambda: now,
    )
    use_case.execute(1)
    return channel


NOON = datetime(2026, 3, 1, 12, 0)
LATE_EVENING = datetime(2026, 3, 1, 23, 30)
SMALL_HOURS = datetime(2026, 3, 1, 3, 0)


def test_delivery_uses_every_channel_the_policy_allows():
    channel = _deliver(_settings(**QUIET_HOURS), NOON)

    assert set(channel.channels_used) == {"push", "email", "desktop", "in_app"}


def test_delivery_sends_each_allowed_channel_exactly_once():
    channel = _deliver(_settings(**QUIET_HOURS), NOON)

    assert len(channel.calls) == 4
    assert sorted(channel.channels_used) == sorted(set(channel.channels_used))


def test_delivery_honours_channels_the_user_turned_off():
    channel = _deliver(_settings(email_enabled=False, desktop_enabled=False), NOON)

    assert set(channel.channels_used) == {"push", "in_app"}


def test_a_reminder_inside_quiet_hours_is_not_delivered_by_push_email_or_desktop():
    """Issue #26's stated verification."""
    channel = _deliver(_settings(**QUIET_HOURS), LATE_EVENING)

    assert INTERRUPTIVE.isdisjoint(channel.channels_used)


def test_a_reminder_inside_quiet_hours_is_still_delivered_in_app():
    """Companion to the test above: 'not delivered' must not be satisfied by
    dropping the review altogether."""
    channel = _deliver(_settings(**QUIET_HOURS), LATE_EVENING)

    assert channel.channels_used == ["in_app"]


def test_quiet_hours_still_apply_after_midnight():
    channel = _deliver(_settings(**QUIET_HOURS), SMALL_HOURS)

    assert channel.channels_used == ["in_app"]


def test_quiet_hours_with_in_app_also_disabled_deliver_nothing():
    channel = _deliver(_settings(in_app_enabled=False, **QUIET_HOURS), LATE_EVENING)

    assert channel.calls == []


def test_nothing_is_delivered_when_the_master_switch_is_off():
    channel = _deliver(_settings(enabled=False), NOON)

    assert channel.calls == []


def test_a_user_who_never_saved_settings_gets_the_defaults():
    channel = _deliver(None, NOON)

    assert set(channel.channels_used) == {"push", "in_app"}


def test_every_send_carries_the_same_reminder_message():
    channel = _deliver(_settings(), NOON)

    messages = {message for _, message, _ in channel.calls}
    assert len(messages) == 1
    assert messages.pop().strip()


def test_delivery_skips_a_reminder_disabled_after_its_job_was_registered():
    channel = _deliver(_settings(), NOON, reminder=_reminder(enabled=False))

    assert channel.calls == []


def test_delivery_of_a_deleted_reminder_is_silently_skipped():
    channel = _RecordingChannel()
    DeliverReminderUseCase(
        _InMemoryReminderRepository(),
        _InMemoryUserRepository([_user()]),
        _InMemorySettingsRepository(_settings()),
        channel,
        clock=lambda: NOON,
    ).execute(404)

    assert channel.calls == []


def test_delivery_for_a_vanished_user_is_silently_skipped():
    channel = _RecordingChannel()
    DeliverReminderUseCase(
        _InMemoryReminderRepository([_reminder()]),
        _InMemoryUserRepository(),
        _InMemorySettingsRepository(_settings()),
        channel,
        clock=lambda: NOON,
    ).execute(1)

    assert channel.calls == []
