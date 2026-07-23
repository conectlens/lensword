from datetime import datetime, timezone
from typing import Callable

# Reused rather than restated: an authorization rule copied into a second
# module is one that will eventually be tightened in only one of them.
from app.application.use_cases.vocabulary import _require_group_owner
from app.domain.entities import RecallSettings, Reminder
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import (
    GroupRepository,
    RecallSettingsRepository,
    ReminderRepository,
    UserRepository,
)
from app.domain.services.notification_channel import NotificationChannel
from app.domain.services.recall_delivery import RecallDeliveryPolicy
from app.domain.services.reminder_scheduler import ReminderScheduler
from app.domain.value_objects import DEFAULT_TIME_ZONE, normalize_time_zone, utcnow, zone_for

REMINDER_MESSAGE = "Time to review your vocabulary."


def _require_reminder_owner(reminder_repo: ReminderRepository, reminder_id: int, owner_id: int) -> Reminder:
    """Reminder repositories look up by id alone, deliberately, so ownership
    has to be established here — exactly as the vocabulary use cases do for
    groups, words and rooms."""
    reminder = reminder_repo.get_by_id(reminder_id)
    if reminder is None:
        raise EntityNotFoundError("Reminder", reminder_id)
    if reminder.user_id != owner_id:
        raise PermissionDeniedError("This reminder belongs to another account")
    return reminder


class ScheduleReminderUseCase:
    """Persist a reminder and register the background job that fires it.

    Persisting first is deliberate: the job identifies its reminder by id when
    it wakes up, so registering an unsaved reminder would schedule work that
    can never find its own subject.

    Ownership of the target group is checked before anything is written, so a
    reminder pointed at another account's group is refused outright rather than
    stored and left to nudge someone about words they cannot see.
    """

    def __init__(
        self,
        reminder_repo: ReminderRepository,
        group_repo: GroupRepository,
        reminder_scheduler: ReminderScheduler,
        user_repo: UserRepository | None = None,
    ):
        self.reminder_repo = reminder_repo
        self.group_repo = group_repo
        self.reminder_scheduler = reminder_scheduler
        self.user_repo = user_repo

    def _time_zone_of(self, user_id: int) -> str:
        """The owner's zone, or the default when it cannot be established.

        The repository is optional so a caller that has no need for zones
        still gets the previous UTC convention rather than an error.
        """
        if self.user_repo is None:
            return DEFAULT_TIME_ZONE
        user = self.user_repo.get_by_id(user_id)
        return user.time_zone if user else DEFAULT_TIME_ZONE

    def execute(self, reminder: Reminder) -> Reminder:
        _require_group_owner(self.group_repo, reminder.group_id, reminder.user_id)
        saved = self.reminder_repo.add(reminder)
        if saved.enabled:
            self.reminder_scheduler.schedule(saved, self._time_zone_of(saved.user_id))
        return saved


class SetUserTimeZoneUseCase:
    """Store a user's time zone and re-register their reminders against it.

    Rescheduling is the whole point of the use case rather than an extra.
    A registered job carries its zone inside its trigger, so a user who moves
    from UTC to UTC+3 would otherwise keep being notified on the old offset
    until the process restarted and jobs were rebuilt from the database.

    An unrecognized identifier is refused here, at the write boundary, rather
    than stored and discovered later by a scheduler job (issue #44).
    """

    def __init__(
        self,
        user_repo: UserRepository,
        reminder_repo: ReminderRepository,
        reminder_scheduler: ReminderScheduler | None,
    ):
        self.user_repo = user_repo
        self.reminder_repo = reminder_repo
        self.reminder_scheduler = reminder_scheduler

    def execute(self, user_id: int, time_zone: str | None) -> str:
        requested = normalize_time_zone(time_zone)
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User", user_id)
        if user.time_zone == requested:
            return user.time_zone

        user.time_zone = requested
        self.user_repo.update(user)
        # No scheduler means nothing is registered to move — the stored zone
        # still takes effect the next time jobs are built from the database.
        if self.reminder_scheduler is not None:
            for reminder in self.reminder_repo.list_by_user(user_id):
                if reminder.enabled:
                    self.reminder_scheduler.schedule(reminder, requested)
        return requested


class CancelReminderUseCase:
    """Delete a reminder and drop its job in the same step, so a removed
    reminder can never keep firing for the rest of the process's life.

    Takes the acting user, not just the reminder id: deleting by id alone
    would let anyone able to guess a number cancel another account's reminders.
    """

    def __init__(self, reminder_repo: ReminderRepository, reminder_scheduler: ReminderScheduler):
        self.reminder_repo = reminder_repo
        self.reminder_scheduler = reminder_scheduler

    def execute(self, user_id: int, reminder_id: int) -> None:
        _require_reminder_owner(self.reminder_repo, reminder_id, user_id)
        self.reminder_repo.delete(reminder_id)
        self.reminder_scheduler.unschedule(reminder_id)


class DeliverReminderUseCase:
    """The body of a reminder's scheduled job.

    Reminder state, the account and its recall settings are all re-read at fire
    time rather than captured when the job was registered: a reminder disabled
    in between, an account since deactivated, or quiet hours switched on since,
    must all be honoured. A missing reminder or user is a no-op, not an error —
    a job outliving its subject is expected, not exceptional.

    Which channels are permissible is decided by RecallDeliveryPolicy, not
    here; this use case only carries out the decision, exactly once per
    channel it is given.
    """

    def __init__(
        self,
        reminder_repo: ReminderRepository,
        user_repo: UserRepository,
        settings_repo: RecallSettingsRepository,
        channel: NotificationChannel,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo
        self.settings_repo = settings_repo
        self.channel = channel
        self.clock = clock

    def execute(self, reminder_id: int) -> None:
        reminder = self.reminder_repo.get_by_id(reminder_id)
        if reminder is None or not reminder.enabled:
            return
        user = self.user_repo.get_by_id(reminder.user_id)
        if user is None or not user.is_active:
            return

        # An account that never saved settings gets RecallSettings' own
        # defaults, deliberately unmodified: GetRecallSettingsUseCase shows the
        # user those same defaults, and delivery must not quietly use a
        # different set from the one the settings screen displays.
        settings = self.settings_repo.get_by_user(reminder.user_id) or RecallSettings(user_id=reminder.user_id)

        # Quiet hours are a statement about the user's night, so the policy is
        # asked about the user's clock rather than UTC. A 22:00-07:00 window
        # otherwise covers UTC night, which for a user at UTC+3 is 01:00-10:00
        # of their own day (issue #44). The policy itself stays pure and
        # zone-unaware; only the instant it is handed changes.
        now_local = (
            self.clock()
            .replace(tzinfo=timezone.utc)
            .astimezone(zone_for(user.time_zone))
            .replace(tzinfo=None)
        )
        allowed = RecallDeliveryPolicy.decide(settings, now_local)

        # Sorted so delivery order is deterministic rather than dependent on
        # set iteration order, which makes failures reproducible.
        for target in sorted(allowed, key=lambda c: c.value):
            self.channel.send(user, REMINDER_MESSAGE, target.value)
