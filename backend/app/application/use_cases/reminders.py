from app.domain.entities import Reminder
from app.domain.repositories import ReminderRepository, UserRepository
from app.domain.services.notification_channel import NotificationChannel
from app.domain.services.reminder_scheduler import ReminderScheduler

REMINDER_MESSAGE = "Time to review your vocabulary."


class ScheduleReminderUseCase:
    """Persist a reminder and register the background job that fires it.

    Persisting first is deliberate: the job identifies its reminder by id when
    it wakes up, so registering an unsaved reminder would schedule work that
    can never find its own subject.
    """

    def __init__(self, reminder_repo: ReminderRepository, reminder_scheduler: ReminderScheduler):
        self.reminder_repo = reminder_repo
        self.reminder_scheduler = reminder_scheduler

    def execute(self, reminder: Reminder) -> Reminder:
        saved = self.reminder_repo.add(reminder)
        if saved.enabled:
            self.reminder_scheduler.schedule(saved)
        return saved


class CancelReminderUseCase:
    """Delete a reminder and drop its job in the same step, so a removed
    reminder can never keep firing for the rest of the process's life."""

    def __init__(self, reminder_repo: ReminderRepository, reminder_scheduler: ReminderScheduler):
        self.reminder_repo = reminder_repo
        self.reminder_scheduler = reminder_scheduler

    def execute(self, reminder_id: int) -> None:
        self.reminder_repo.delete(reminder_id)
        self.reminder_scheduler.unschedule(reminder_id)


class DeliverReminderUseCase:
    """The body of a reminder's scheduled job.

    Reminder state is re-read at fire time rather than captured when the job
    was registered: a reminder disabled or deleted in between must not still
    produce a notification. A missing reminder or user is a no-op, not an
    error — a job outliving its subject is expected, not exceptional.
    """

    def __init__(
        self,
        reminder_repo: ReminderRepository,
        user_repo: UserRepository,
        channel: NotificationChannel,
    ):
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo
        self.channel = channel

    def execute(self, reminder_id: int) -> None:
        reminder = self.reminder_repo.get_by_id(reminder_id)
        if reminder is None or not reminder.enabled:
            return
        user = self.user_repo.get_by_id(reminder.user_id)
        if user is None:
            return
        self.channel.send(user, REMINDER_MESSAGE, "push")
