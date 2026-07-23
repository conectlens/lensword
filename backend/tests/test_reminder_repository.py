from datetime import datetime

import pytest

from app.domain.entities import Reminder
from app.domain.exceptions import ValidationError
from app.domain.value_objects import Recurrence, utcnow
from app.infrastructure.models import GroupModel, ReminderModel, UserModel
from app.infrastructure.repositories import SqlAlchemyReminderRepository


@pytest.fixture()
def owner(db_session):
    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()
    group = GroupModel(owner_id=user.id, name="Spanish Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()
    return user, group


def test_reminder_entity_defaults_to_enabled():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)

    assert reminder.enabled is True
    assert isinstance(reminder.created_at, datetime)


def test_reminder_can_be_disabled_and_re_enabled():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)

    reminder.disable()
    assert reminder.enabled is False

    reminder.enable()
    assert reminder.enabled is True


def test_reminder_parses_hour_and_minute_trigger_times():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:05", recurrence=Recurrence.DAILY)

    assert reminder.time_of_day.hour == 9
    assert reminder.time_of_day.minute == 5
    assert reminder.time_of_day.second == 0


def test_reminder_parses_second_precision_trigger_times():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:05:30", recurrence=Recurrence.DAILY)

    assert reminder.time_of_day.second == 30


def test_reminder_rejects_an_unparseable_trigger_time():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="tea time", recurrence=Recurrence.DAILY)

    with pytest.raises(ValidationError):
        _ = reminder.time_of_day


def test_next_occurrence_is_later_the_same_day_when_the_time_has_not_passed():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)

    assert reminder.next_occurrence(datetime(2026, 3, 1, 8, 30)) == datetime(2026, 3, 1, 9, 0)


def test_next_occurrence_rolls_over_to_tomorrow_once_the_time_has_passed():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)

    assert reminder.next_occurrence(datetime(2026, 3, 1, 9, 30)) == datetime(2026, 3, 2, 9, 0)


def test_next_occurrence_rolls_over_on_an_exact_hit_so_a_job_is_never_scheduled_in_the_past():
    reminder = Reminder(id=None, user_id=1, group_id=2, trigger_time="09:00", recurrence=Recurrence.DAILY)

    assert reminder.next_occurrence(datetime(2026, 3, 1, 9, 0)) == datetime(2026, 3, 2, 9, 0)


def test_repository_round_trips_a_reminder(db_session, owner):
    user, group = owner
    repo = SqlAlchemyReminderRepository(db_session)

    saved = repo.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )

    assert saved.id is not None
    fetched = repo.get_by_id(saved.id)
    assert fetched == saved
    assert fetched.recurrence is Recurrence.DAILY
    assert fetched.trigger_time == "09:00"


def test_repository_updates_an_existing_reminder(db_session, owner):
    user, group = owner
    repo = SqlAlchemyReminderRepository(db_session)
    saved = repo.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )

    saved.trigger_time = "21:30"
    saved.disable()
    updated = repo.update(saved)

    assert updated.trigger_time == "21:30"
    assert updated.enabled is False


def test_repository_lists_only_enabled_reminders(db_session, owner):
    user, group = owner
    repo = SqlAlchemyReminderRepository(db_session)
    repo.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )
    repo.add(
        Reminder(
            id=None,
            user_id=user.id,
            group_id=group.id,
            trigger_time="21:00",
            recurrence=Recurrence.DAILY,
            enabled=False,
        )
    )

    enabled = repo.list_enabled()

    assert [r.trigger_time for r in enabled] == ["09:00"]


def test_repository_lists_reminders_for_one_user_only(db_session, owner):
    user, group = owner
    other = UserModel(username="sam", email="sam@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(other)
    db_session.flush()
    repo = SqlAlchemyReminderRepository(db_session)
    repo.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )
    repo.add(
        Reminder(id=None, user_id=other.id, group_id=group.id, trigger_time="10:00", recurrence=Recurrence.DAILY)
    )

    assert [r.trigger_time for r in repo.list_by_user(user.id)] == ["09:00"]


def _raw_reminder(db_session, user_id, group_id, **overrides) -> ReminderModel:
    """Insert a row straight through the ORM, bypassing the domain entity, so
    values the entity could never produce can be simulated."""
    defaults = dict(
        user_id=user_id, group_id=group_id, trigger_time="09:00", recurrence="daily", created_at=utcnow()
    )
    defaults.update(overrides)
    row = ReminderModel(**defaults)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.mark.parametrize("bad_recurrence", ["weekly", "DAILY", "", "hourly"], ids=repr)
def test_listing_skips_a_row_whose_recurrence_is_unusable(db_session, owner, bad_recurrence):
    """The recurrence column is a bare String with no CHECK constraint, so an
    unmappable value is a data possibility, not a hypothetical."""
    user, group = owner
    _raw_reminder(db_session, user.id, group.id, recurrence=bad_recurrence, trigger_time="07:00")
    good = _raw_reminder(db_session, user.id, group.id, trigger_time="09:00")

    listed = SqlAlchemyReminderRepository(db_session).list_enabled()

    assert [r.id for r in listed] == [good.id]


def test_one_unusable_row_never_hides_the_others(db_session, owner):
    """The load must degrade row by row: a single corrupt reminder cannot cost
    every other user their reminders."""
    user, group = owner
    before = _raw_reminder(db_session, user.id, group.id, trigger_time="06:00")
    _raw_reminder(db_session, user.id, group.id, recurrence="weekly", trigger_time="07:00")
    after = _raw_reminder(db_session, user.id, group.id, trigger_time="08:00")

    listed = SqlAlchemyReminderRepository(db_session).list_enabled()

    assert [r.id for r in listed] == [before.id, after.id]


def test_listing_by_user_also_skips_an_unusable_row(db_session, owner):
    user, group = owner
    _raw_reminder(db_session, user.id, group.id, recurrence="weekly")
    good = _raw_reminder(db_session, user.id, group.id, trigger_time="09:00")

    listed = SqlAlchemyReminderRepository(db_session).list_by_user(user.id)

    assert [r.id for r in listed] == [good.id]


def test_fetching_an_unusable_row_by_id_reports_it_as_absent(db_session, owner):
    """A reminder that cannot be understood is treated the same as one that no
    longer exists, so a firing job simply does nothing."""
    user, group = owner
    row = _raw_reminder(db_session, user.id, group.id, recurrence="weekly")

    assert SqlAlchemyReminderRepository(db_session).get_by_id(row.id) is None


def test_an_unusable_row_is_logged_rather_than_dropped_in_silence(db_session, owner, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    user, group = owner
    _raw_reminder(db_session, user.id, group.id, recurrence="weekly")

    SqlAlchemyReminderRepository(db_session).list_enabled()

    assert "weekly" in caplog.text


def test_repository_deletes_a_reminder(db_session, owner):
    user, group = owner
    repo = SqlAlchemyReminderRepository(db_session)
    saved = repo.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )

    repo.delete(saved.id)

    assert repo.get_by_id(saved.id) is None
