"""Suggesting and accepting a reminder window (issue #89).

The domain service is tested separately in test_reminder_windows.py. This
covers what the application layer adds: ownership, the user's own clock, the
quiet-hours filter, and the deliberate gap between being shown a suggestion
and having one applied.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.application.use_cases.reminder_windows import (
    AcceptReminderWindowUseCase,
    SuggestReminderWindowUseCase,
)
from app.domain.entities import DesktopNotification, Group, RecallSettings, Reminder, User
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.value_objects import (
    NotificationAction,
    Recurrence,
    SupportedLanguage,
    UserRole,
    utcnow,
)
from app.infrastructure.repositories import (
    SqlAlchemyDesktopNotificationRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyReminderRepository,
    SqlAlchemyUserRepository,
)


@pytest.fixture()
def world(db_session):
    """One account with a 09:00 daily reminder, and the repositories for it."""
    users = SqlAlchemyUserRepository(db_session)
    user = users.add(
        User(id=None, username="alex", email="alex@example.com", hashed_password="x", role=UserRole.USER)
    )
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user.id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    reminders = SqlAlchemyReminderRepository(db_session)
    reminder = reminders.add(
        Reminder(
            id=None, user_id=user.id, group_id=group.id,
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )
    db_session.commit()
    return {
        "user": user,
        "reminder": reminder,
        "users": users,
        "reminders": reminders,
        "notifications": SqlAlchemyDesktopNotificationRepository(db_session),
        "settings": SqlAlchemyRecallSettingsRepository(db_session),
        "db": db_session,
    }


def _seed_history(world, hour: int, engaged: int, ignored: int, utc_offset_hours: int = 0):
    """Deliver notifications at a given *local* hour and record the outcome."""
    repo = world["notifications"]
    base = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=40)
    created = 0
    for index in range(engaged + ignored):
        at = base + timedelta(days=index, hours=hour - utc_offset_hours)
        stored = repo.add(
            DesktopNotification(
                id=None,
                user_id=world["user"].id,
                message="due",
                created_at=at,
                delivered_at=at,
                action=NotificationAction.START_SESSION.value if created < engaged else None,
            )
        )
        assert stored.id is not None
        created += 1
    world["db"].commit()


def _suggest(world, **kwargs):
    return SuggestReminderWindowUseCase(
        world["reminders"], world["notifications"], world["settings"], world["users"], **kwargs
    )


# --- Ownership -------------------------------------------------------------


def test_another_accounts_reminder_cannot_be_analysed(world, db_session):
    intruder = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="sam", email="sam@example.com", hashed_password="x", role=UserRole.USER)
    )
    db_session.commit()

    with pytest.raises(PermissionDeniedError):
        _suggest(world).execute(intruder.id, world["reminder"].id)


def test_an_unknown_reminder_is_not_found(world):
    with pytest.raises(EntityNotFoundError):
        _suggest(world).execute(world["user"].id, 999999)


# --- Reading the history ---------------------------------------------------


def test_no_suggestion_without_history(world):
    assert _suggest(world).execute(world["user"].id, world["reminder"].id) is None


def test_a_better_hour_is_suggested_from_real_engagement(world):
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)

    suggestion = _suggest(world).execute(world["user"].id, world["reminder"].id)

    assert suggestion is not None
    assert suggestion.recommendation.hour == 20
    assert suggestion.current_hour == 9


def test_the_explanation_is_carried_through(world):
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)

    suggestion = _suggest(world).execute(world["user"].id, world["reminder"].id)

    assert "20:00" in suggestion.explanation
    assert "90%" in suggestion.explanation


def test_history_older_than_the_window_does_not_vote(world):
    """A habit abandoned months ago should stop influencing the suggestion."""
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)

    suggestion = _suggest(world, history_window=timedelta(days=1)).execute(
        world["user"].id, world["reminder"].id
    )

    assert suggestion is None


def test_bucketing_uses_the_accounts_own_clock(world, db_session):
    """The same UTC history must recommend a different hour for an account in
    a different zone. Bucketing on UTC would be wrong by the offset for
    everyone outside it."""
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)
    in_utc = _suggest(world).execute(world["user"].id, world["reminder"].id)

    moved = world["user"]
    moved.time_zone = "Europe/Istanbul"  # UTC+3
    world["users"].update(moved)
    db_session.commit()
    in_istanbul = _suggest(world).execute(world["user"].id, world["reminder"].id)

    assert in_utc.recommendation.hour == 20
    assert in_istanbul.recommendation.hour == 23


# --- Hard constraints ------------------------------------------------------


def test_an_hour_inside_quiet_hours_is_never_suggested(world, db_session):
    """The issue requires the engine never send outside hard constraints. The
    22:00 slot has a perfect record here and is still not offered."""
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=22, engaged=10, ignored=0)
    world["settings"].upsert(
        RecallSettings(user_id=world["user"].id, quiet_hours_start="21:00", quiet_hours_end="07:00")
    )
    db_session.commit()

    assert _suggest(world).execute(world["user"].id, world["reminder"].id) is None


def test_an_hour_only_partly_inside_quiet_hours_is_excluded(world, db_session):
    """21:00-21:59 overlaps a 21:30 quiet-hours start. Checking only the top of
    the hour would let the window be worked around."""
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=21, engaged=10, ignored=0)
    world["settings"].upsert(
        RecallSettings(user_id=world["user"].id, quiet_hours_start="21:30", quiet_hours_end="07:00")
    )
    db_session.commit()

    assert _suggest(world).execute(world["user"].id, world["reminder"].id) is None


# --- Acceptance is separate and explicit -----------------------------------


def test_suggesting_changes_no_schedule(world):
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)

    _suggest(world).execute(world["user"].id, world["reminder"].id)

    assert world["reminders"].get_by_id(world["reminder"].id).trigger_time == "09:00"


def test_accepting_moves_the_reminder_and_keeps_the_minute(world):
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)
    use_case = AcceptReminderWindowUseCase(world["reminders"], _suggest(world))

    use_case.execute(world["user"].id, world["reminder"].id, 20)

    assert world["reminders"].get_by_id(world["reminder"].id).trigger_time == "20:00"


def test_accepting_an_hour_that_was_not_suggested_is_refused(world):
    """Otherwise this is an endpoint for setting a reminder to any hour at all
    under the cover of accepting a recommendation — including one inside the
    account's own quiet hours."""
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)
    use_case = AcceptReminderWindowUseCase(world["reminders"], _suggest(world))

    with pytest.raises(EntityNotFoundError):
        use_case.execute(world["user"].id, world["reminder"].id, 3)

    assert world["reminders"].get_by_id(world["reminder"].id).trigger_time == "09:00"


def test_accepting_when_there_is_no_longer_a_suggestion_is_refused(world):
    """The recommendation lapsed between being shown and being accepted. The
    explanation the user agreed to no longer describes what would happen."""
    use_case = AcceptReminderWindowUseCase(world["reminders"], _suggest(world))

    with pytest.raises(EntityNotFoundError):
        use_case.execute(world["user"].id, world["reminder"].id, 20)


def test_accepting_re_registers_the_moved_job(world):
    _seed_history(world, hour=9, engaged=1, ignored=9)
    _seed_history(world, hour=20, engaged=9, ignored=1)

    class _RecordingJobs:
        def __init__(self):
            self.scheduled = []

        def schedule(self, reminder, time_zone="UTC"):
            self.scheduled.append(reminder.trigger_time)

    jobs = _RecordingJobs()
    AcceptReminderWindowUseCase(world["reminders"], _suggest(world), jobs).execute(
        world["user"].id, world["reminder"].id, 20
    )

    assert jobs.scheduled == ["20:00"]


# --- The API ---------------------------------------------------------------
#
# Cross-account denial for these routes is covered by the tenant-isolation
# audit. What is checked here is the shape of the answer, and that reading a
# recommendation cannot change a schedule.


def _api_world(client, auth_headers, db_session):
    from datetime import timedelta

    headers = auth_headers()
    me = client.get("/api/v1/auth/me", headers=headers).json()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    reminders = SqlAlchemyReminderRepository(db_session)
    reminder = reminders.add(
        Reminder(
            id=None, user_id=me["id"], group_id=group["id"],
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )
    notifications = SqlAlchemyDesktopNotificationRepository(db_session)
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    for day in range(10):
        for hour, action in ((9, None), (20, NotificationAction.START_SESSION.value)):
            at = midnight + timedelta(days=day, hours=hour)
            notifications.add(
                DesktopNotification(
                    id=None, user_id=me["id"], message="due",
                    created_at=at, delivered_at=at, action=action,
                )
            )
    db_session.commit()
    return headers, reminder, reminders


def test_the_api_returns_the_recommendation_with_its_evidence(client, auth_headers, db_session):
    headers, reminder, _ = _api_world(client, auth_headers, db_session)

    body = client.get(
        f"/api/v1/reminders/{reminder.id}/window-recommendation", headers=headers
    ).json()

    recommendation = body["recommendation"]
    assert recommendation["suggested_hour"] == 20
    assert recommendation["current_hour"] == 9
    # Both rates and both samples, so the reason can be checked rather than
    # taken on trust.
    assert recommendation["suggested_rate"] == 1.0
    assert recommendation["current_rate"] == 0.0
    assert recommendation["suggested_sample"] == 10
    assert "20:00" in recommendation["explanation"]


def test_having_no_recommendation_is_a_200_with_null(client, auth_headers, db_session):
    """Not a 404: having nothing to suggest is the ordinary answer, and a 404
    would make it indistinguishable from a reminder that does not exist."""
    headers = auth_headers()
    me = client.get("/api/v1/auth/me", headers=headers).json()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    reminder = SqlAlchemyReminderRepository(db_session).add(
        Reminder(
            id=None, user_id=me["id"], group_id=group["id"],
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/reminders/{reminder.id}/window-recommendation", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["recommendation"] is None


def test_reading_a_recommendation_does_not_move_the_reminder(client, auth_headers, db_session):
    headers, reminder, reminders = _api_world(client, auth_headers, db_session)

    client.get(f"/api/v1/reminders/{reminder.id}/window-recommendation", headers=headers)

    assert reminders.get_by_id(reminder.id).trigger_time == "09:00"


def test_accepting_through_the_api_moves_the_reminder(client, auth_headers, db_session):
    headers, reminder, reminders = _api_world(client, auth_headers, db_session)

    response = client.post(
        f"/api/v1/reminders/{reminder.id}/window-recommendation/accept",
        json={"hour": 20},
        headers=headers,
    )

    assert response.status_code == 204, response.text
    assert reminders.get_by_id(reminder.id).trigger_time == "20:00"


def test_accepting_an_hour_that_was_not_suggested_is_refused_by_the_api(
    client, auth_headers, db_session
):
    headers, reminder, reminders = _api_world(client, auth_headers, db_session)

    response = client.post(
        f"/api/v1/reminders/{reminder.id}/window-recommendation/accept",
        json={"hour": 3},
        headers=headers,
    )

    assert response.status_code == 404
    assert reminders.get_by_id(reminder.id).trigger_time == "09:00"


def test_an_out_of_range_hour_is_rejected(client, auth_headers, db_session):
    headers, reminder, _ = _api_world(client, auth_headers, db_session)

    response = client.post(
        f"/api/v1/reminders/{reminder.id}/window-recommendation/accept",
        json={"hour": 99},
        headers=headers,
    )

    assert response.status_code == 422


def test_the_recommendation_requires_authentication(client, auth_headers, db_session):
    _, reminder, _ = _api_world(client, auth_headers, db_session)

    assert client.get(f"/api/v1/reminders/{reminder.id}/window-recommendation").status_code == 401
