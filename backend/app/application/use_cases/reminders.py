from datetime import datetime
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
from app.domain.value_objects import utcnow

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
    ):
        self.reminder_repo = reminder_repo
        self.group_repo = group_repo
        self.reminder_scheduler = reminder_scheduler

    def execute(self, reminder: Reminder) -> Reminder:
        _require_group_owner(self.group_repo, reminder.group_id, reminder.user_id)
        saved = self.reminder_repo.add(reminder)
        if saved.enabled:
            self.reminder_scheduler.schedule(saved)
        return saved


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
        allowed = RecallDeliveryPolicy.decide(settings, self.clock())

        # Sorted so delivery order is deterministic rather than dependent on
        # set iteration order, which makes failures reproducible.
        for target in sorted(allowed, key=lambda c: c.value):
            self.channel.send(user, REMINDER_MESSAGE, target.value)
