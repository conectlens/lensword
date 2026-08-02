"""Actionable notifications (ROADMAP 3.2, issue #88).

The issue's verify criteria: each action changes state once, stale and
duplicate callbacks are harmless, and notification bodies can hide vocabulary
content on lock screens. Idempotence carries the most weight here, because the
caller is an operating system that is *allowed* to deliver the same activation
twice and there is no way to stop it doing so.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.use_cases.notifications import PerformNotificationActionUseCase
from app.domain.entities import DesktopNotification, RecallSettings
from app.domain.exceptions import EntityNotFoundError, NotificationExpiredError
from app.domain.value_objects import (
    NOTIFICATION_ACTION_TTL,
    NOTIFICATION_PAYLOAD_VERSION,
    Channel,
    NotificationAction,
    UserRole,
    utcnow,
)
from app.domain.entities import User
from app.infrastructure.models import UserModel
from app.infrastructure.notifications import DesktopNotificationChannel
from app.infrastructure.repositories import (
    SqlAlchemyDesktopNotificationRepository,
    SqlAlchemyRecallSettingsRepository,
)


def _persist_user(db, user_id: int = 1, username: str = "alex") -> None:
    db.add(
        UserModel(
            id=user_id,
            username=username,
            email=f"{username}@example.com",
            hashed_password="x",
            role=UserRole.USER.value,
            created_at=utcnow(),
            is_active=True,
            streak_days=0,
            longest_streak_days=0,
            total_words_learned=0,
            total_study_seconds=0,
            time_zone="UTC",
        )
    )
    db.flush()


@pytest.fixture()
def repo(db_session):
    _persist_user(db_session)
    return SqlAlchemyDesktopNotificationRepository(db_session)


def _notification(repo, **overrides) -> DesktopNotification:
    defaults = dict(
        id=None,
        user_id=1,
        message="5 words are due",
        expires_at=utcnow() + NOTIFICATION_ACTION_TTL,
    )
    defaults.update(overrides)
    return repo.add(DesktopNotification(**defaults))


# --- Idempotence -----------------------------------------------------------


@pytest.mark.parametrize("action", list(NotificationAction))
def test_a_repeated_callback_changes_nothing(repo, action):
    """The OS may deliver the same activation twice. The second call reports
    the action that stands and does not repeat its effect."""
    stored = _notification(repo)
    use_case = PerformNotificationActionUseCase(repo)

    first = use_case.execute(1, stored.id, action)
    second = use_case.execute(1, stored.id, action)

    assert first.applied is True
    assert second.applied is False
    assert second.action is action


def test_a_second_different_action_loses_to_the_first(repo):
    """Two buttons pressed in quick succession, or a click racing a restart.
    Whichever was recorded first is the one that happened."""
    stored = _notification(repo)
    use_case = PerformNotificationActionUseCase(repo)

    use_case.execute(1, stored.id, NotificationAction.SKIP_TODAY)
    second = use_case.execute(1, stored.id, NotificationAction.START_SESSION)

    assert second.applied is False
    # Not START_SESSION: the caller is told what actually stands, not what it
    # asked for.
    assert second.action is NotificationAction.SKIP_TODAY
    assert second.open_review is False


def test_remind_later_queues_exactly_one_repeat_however_often_it_is_called(repo):
    stored = _notification(repo)
    use_case = PerformNotificationActionUseCase(repo)

    use_case.execute(1, stored.id, NotificationAction.REMIND_LATER)
    use_case.execute(1, stored.id, NotificationAction.REMIND_LATER)
    use_case.execute(1, stored.id, NotificationAction.REMIND_LATER)

    later = repo.list_pending(1, utcnow() - timedelta(days=1), 50)
    # The original plus one repeat. Three presses must not queue three.
    assert len(later) == 2


# --- What each action does -------------------------------------------------


def test_start_session_asks_the_shell_to_open_the_review(repo):
    stored = _notification(repo)

    outcome = PerformNotificationActionUseCase(repo).execute(
        1, stored.id, NotificationAction.START_SESSION
    )

    assert outcome.open_review is True


def test_start_session_creates_no_review_session_server_side(repo, db_session):
    """Creating one here would leave an empty session behind every time
    somebody clicked and then walked away."""
    from app.infrastructure.models import ReviewSessionModel

    stored = _notification(repo)

    PerformNotificationActionUseCase(repo).execute(1, stored.id, NotificationAction.START_SESSION)

    assert db_session.query(ReviewSessionModel).count() == 0


def test_remind_later_queues_the_repeat_in_the_future(repo):
    stored = _notification(repo)

    PerformNotificationActionUseCase(repo).execute(1, stored.id, NotificationAction.REMIND_LATER)

    queued = [n for n in repo.list_pending(1, utcnow() - timedelta(days=1), 50) if n.id != stored.id]
    assert len(queued) == 1
    assert queued[0].created_at > utcnow()


def test_a_snoozed_repeat_carries_its_own_expiry(repo):
    """Otherwise snoozing repeatedly would extend one notification's life
    indefinitely."""
    stored = _notification(repo)

    PerformNotificationActionUseCase(repo).execute(1, stored.id, NotificationAction.REMIND_LATER)

    queued = [n for n in repo.list_pending(1, utcnow() - timedelta(days=1), 50) if n.id != stored.id]
    assert queued[0].expires_at is not None
    assert queued[0].expires_at > stored.expires_at


def test_skip_today_retires_the_reminders_other_pending_prompts(repo, db_session):
    from app.infrastructure.models import GroupModel, ReminderModel

    db_session.add(GroupModel(id=1, owner_id=1, name="G", target_language="Spanish", created_at=utcnow()))
    db_session.add(
        ReminderModel(
            id=1, user_id=1, group_id=1, trigger_time="09:00", recurrence="daily",
            enabled=True, created_at=utcnow(),
        )
    )
    db_session.flush()
    first = _notification(repo, reminder_id=1)
    _notification(repo, reminder_id=1, message="snoozed repeat")
    unrelated = _notification(repo, reminder_id=None, message="not from a reminder")

    PerformNotificationActionUseCase(repo).execute(1, first.id, NotificationAction.SKIP_TODAY)

    still_pending = [n.id for n in repo.list_pending(1, utcnow() - timedelta(days=1), 50)]
    assert still_pending == [unrelated.id]


def test_skip_today_on_a_notification_with_no_reminder_is_harmless(repo):
    stored = _notification(repo, reminder_id=None)

    outcome = PerformNotificationActionUseCase(repo).execute(
        1, stored.id, NotificationAction.SKIP_TODAY
    )

    assert outcome.applied is True


# --- Stale and unauthorised callbacks --------------------------------------


def test_an_expired_notification_refuses_every_action(repo):
    """A toast can sit in a tray for days. 'Start a five-minute session'
    answered on Thursday for Tuesday's prompt is not what was asked."""
    stored = _notification(repo, expires_at=utcnow() - timedelta(minutes=1))

    with pytest.raises(NotificationExpiredError):
        PerformNotificationActionUseCase(repo).execute(
            1, stored.id, NotificationAction.START_SESSION
        )


def test_an_expired_action_records_nothing(repo):
    stored = _notification(repo, expires_at=utcnow() - timedelta(minutes=1))

    with pytest.raises(NotificationExpiredError):
        PerformNotificationActionUseCase(repo).execute(1, stored.id, NotificationAction.SKIP_TODAY)

    assert repo.get_owned(1, stored.id).action is None


def test_a_notification_without_an_expiry_never_lapses(repo):
    """The shape a non-reminder notification takes. It should not stop working
    because a field was added for reminders."""
    stored = _notification(repo, expires_at=None)

    outcome = PerformNotificationActionUseCase(repo).execute(
        1, stored.id, NotificationAction.START_SESSION
    )

    assert outcome.applied is True


def test_an_unknown_notification_is_not_found(repo):
    with pytest.raises(EntityNotFoundError):
        PerformNotificationActionUseCase(repo).execute(1, 999999, NotificationAction.SKIP_TODAY)


def test_another_accounts_notification_is_not_found(repo, db_session):
    """Reported as absent rather than forbidden — acting on someone else's
    reminder would suppress their prompts, so the id should not even confirm
    it exists."""
    _persist_user(db_session, user_id=2, username="sam")
    theirs = _notification(repo, user_id=2)

    with pytest.raises(EntityNotFoundError):
        PerformNotificationActionUseCase(repo).execute(1, theirs.id, NotificationAction.SKIP_TODAY)


# --- Delivery carries what actions need ------------------------------------


def test_a_delivered_notification_records_its_reminder_and_expiry(db_session):
    from app.infrastructure.models import GroupModel, ReminderModel

    _persist_user(db_session)
    # A real reminder row, not an invented id: the column is a foreign key, and
    # Postgres enforces it even where SQLite would let the test pass.
    db_session.add(
        GroupModel(id=1, owner_id=1, name="G", target_language="Spanish", created_at=utcnow())
    )
    db_session.add(
        ReminderModel(
            id=7, user_id=1, group_id=1, trigger_time="09:00", recurrence="daily",
            enabled=True, created_at=utcnow(),
        )
    )
    db_session.flush()
    channel = DesktopNotificationChannel(lambda: db_session).for_reminder(7)

    channel.send(
        User(id=1, username="alex", email="a@b.c", hashed_password="x", role=UserRole.USER),
        "5 words are due",
        Channel.DESKTOP.value,
    )

    stored = SqlAlchemyDesktopNotificationRepository(db_session).list_pending(
        1, utcnow() - timedelta(hours=1), 10
    )[0]
    assert stored.reminder_id == 7
    assert stored.expires_at is not None


def test_binding_a_reminder_does_not_mutate_the_shared_channel(db_session):
    """Reminders dispatch concurrently; a channel that mutated in place would
    attribute one reminder's notification to another."""
    shared = DesktopNotificationChannel(lambda: db_session)

    bound = shared.for_reminder(7)

    assert shared.reminder_id is None
    assert bound.reminder_id == 7


# --- The API ---------------------------------------------------------------


def _seed(client, db_session, headers, **overrides):
    me = client.get("/api/v1/auth/me", headers=headers).json()
    fields = dict(
        id=None,
        user_id=me["id"],
        message="5 words are due",
        expires_at=utcnow() + NOTIFICATION_ACTION_TTL,
    )
    fields.update(overrides)
    stored = SqlAlchemyDesktopNotificationRepository(db_session).add(
        DesktopNotification(**fields)
    )
    db_session.commit()
    return stored


def test_the_payload_is_versioned_and_carries_actions(client, auth_headers, db_session):
    headers = auth_headers()
    _seed(client, db_session, headers)

    body = client.get("/api/v1/desktop-notifications", headers=headers).json()

    assert body["payload_version"] == NOTIFICATION_PAYLOAD_VERSION
    notification = body["notifications"][0]
    assert notification["title"] == "LensWord"
    assert notification["body"] == "5 words are due"
    assert set(notification["actions"]) == {a.value for a in NotificationAction}


def test_hiding_details_redacts_the_body_but_not_the_stored_message(
    client, auth_headers, db_session
):
    """A toast is drawn on lock screens and shared displays. The stored record
    keeps the real text — this is about what is rendered, not what is kept."""
    headers = auth_headers()
    _seed(client, db_session, headers)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    SqlAlchemyRecallSettingsRepository(db_session).upsert(
        RecallSettings(user_id=me["id"], hide_notification_details=True)
    )
    db_session.commit()

    notification = client.get("/api/v1/desktop-notifications", headers=headers).json()[
        "notifications"
    ][0]

    assert notification["body"] == "A review is waiting."
    assert notification["message"] == "5 words are due"


def test_pausing_delivers_nothing_but_keeps_the_notifications(client, auth_headers, db_session):
    """Paused is not cancelled: unpausing must not have lost them."""
    headers = auth_headers()
    _seed(client, db_session, headers)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    settings_repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings_repo.upsert(RecallSettings(user_id=me["id"], notifications_paused=True))
    db_session.commit()

    assert client.get("/api/v1/desktop-notifications", headers=headers).json()["notifications"] == []

    settings_repo.upsert(RecallSettings(user_id=me["id"], notifications_paused=False))
    db_session.commit()
    assert len(client.get("/api/v1/desktop-notifications", headers=headers).json()["notifications"]) == 1


def test_an_expired_notification_offers_no_actions(client, auth_headers, db_session):
    """Rendering three buttons that all return an error would be worse than
    rendering none."""
    headers = auth_headers()
    _seed(client, db_session, headers, expires_at=utcnow() - timedelta(minutes=1))

    notification = client.get("/api/v1/desktop-notifications", headers=headers).json()[
        "notifications"
    ][0]

    assert notification["actions"] == []


def test_acting_through_the_api_is_idempotent(client, auth_headers, db_session):
    headers = auth_headers()
    stored = _seed(client, db_session, headers)
    path = f"/api/v1/desktop-notifications/{stored.id}/action"

    first = client.post(path, json={"action": "start_session"}, headers=headers)
    second = client.post(path, json={"action": "start_session"}, headers=headers)

    assert first.status_code == 200, first.text
    assert first.json() == {"action": "start_session", "applied": True, "open_review": True}
    assert second.status_code == 200
    assert second.json()["applied"] is False
    assert second.json()["open_review"] is False


def test_acting_on_an_expired_notification_is_a_conflict(client, auth_headers, db_session):
    """409 rather than 404 or 422: it is real and it is the caller's, just too
    old — which a shell needs to tell apart from a bad id."""
    headers = auth_headers()
    stored = _seed(client, db_session, headers, expires_at=utcnow() - timedelta(minutes=1))

    response = client.post(
        f"/api/v1/desktop-notifications/{stored.id}/action",
        json={"action": "skip_today"},
        headers=headers,
    )

    assert response.status_code == 409


def test_an_unknown_action_id_is_rejected(client, auth_headers, db_session):
    """422 rather than a recorded action nothing knows how to carry out."""
    headers = auth_headers()
    stored = _seed(client, db_session, headers)

    response = client.post(
        f"/api/v1/desktop-notifications/{stored.id}/action",
        json={"action": "delete_everything"},
        headers=headers,
    )

    assert response.status_code == 422


def test_acting_requires_authentication(client, auth_headers, db_session):
    stored = _seed(client, db_session, auth_headers())

    response = client.post(
        f"/api/v1/desktop-notifications/{stored.id}/action", json={"action": "skip_today"}
    )

    assert response.status_code == 401
