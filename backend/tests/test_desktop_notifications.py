"""Desktop notification outbox: adapter, repository, use cases, API (issue #27).

ADR 0002 made the desktop app remote-only, so "deliver a desktop notification"
means recording one for a shell to collect. These tests pin the three
properties that decision makes load-bearing: the other three channels keep
working, one account can never see or acknowledge another's notifications, and
repeated acknowledgement is harmless.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.application.use_cases.notifications import (
    AcknowledgeDesktopNotificationsUseCase,
    CollectDesktopNotificationsUseCase,
)
from app.domain.entities import DesktopNotification, User
from app.domain.value_objects import Channel, UserRole, utcnow
from app.infrastructure.models import DesktopNotificationModel, UserModel
from app.infrastructure.notifications import DesktopNotificationChannel, LogNotificationChannel
from app.infrastructure.repositories import SqlAlchemyDesktopNotificationRepository


def _user(user_id: int = 1, **overrides) -> User:
    defaults = dict(
        id=user_id,
        username="alex",
        email="alex@example.com",
        hashed_password="x",
        role=UserRole.USER,
    )
    defaults.update(overrides)
    return User(**defaults)


def _persist_user(db, user_id: int, username: str) -> None:
    """The outbox has a foreign key to users, so a row needs a real account."""
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


class _RecordingChannel:
    def __init__(self):
        self.calls = []

    def send(self, user, message, channel):
        self.calls.append((user.username, message, channel))


# --- The adapter -----------------------------------------------------------


def test_desktop_channel_records_an_outbox_row(db_session):
    _persist_user(db_session, 1, "alex")
    channel = DesktopNotificationChannel(lambda: db_session)

    channel.send(_user(), "5 words are due", Channel.DESKTOP.value)

    pending = SqlAlchemyDesktopNotificationRepository(db_session).list_pending(
        1, utcnow() - timedelta(hours=1), 10
    )
    assert [n.message for n in pending] == ["5 words are due"]
    assert pending[0].pending is True


@pytest.mark.parametrize("channel_name", ["push", "email", "in_app"])
def test_non_desktop_channels_are_delegated_untouched(db_session, channel_name):
    """The regression this guards is silent: wiring the desktop adapter in must
    not stop the other three routes, and a swallowed channel logs nothing to
    notice."""
    _persist_user(db_session, 1, "alex")
    fallback = _RecordingChannel()
    channel = DesktopNotificationChannel(lambda: db_session, fallback=fallback)

    channel.send(_user(), "5 words are due", channel_name)

    assert fallback.calls == [("alex", "5 words are due", channel_name)]
    assert (
        SqlAlchemyDesktopNotificationRepository(db_session).list_pending(
            1, utcnow() - timedelta(hours=1), 10
        )
        == []
    )


def test_desktop_channel_defaults_to_the_log_adapter_for_other_channels(db_session, caplog):
    _persist_user(db_session, 1, "alex")
    channel = DesktopNotificationChannel(lambda: db_session)

    with caplog.at_level("INFO"):
        channel.send(_user(), "5 words are due", "push")

    assert "5 words are due" in caplog.text


def test_a_user_without_an_id_is_reported_not_raised(db_session, caplog):
    channel = DesktopNotificationChannel(lambda: db_session)

    with caplog.at_level("ERROR"):
        channel.send(_user(user_id=None), "5 words are due", Channel.DESKTOP.value)

    assert "no id" in caplog.text


def test_a_failing_write_does_not_propagate_to_the_scheduler(caplog):
    """ReminderDispatcher swallows exceptions, but a notification adapter that
    raises past its own session would still abort the remaining channels of the
    same delivery."""

    class _Exploding:
        def __call__(self):
            return self

        def add(self, *_):
            raise RuntimeError("database is gone")

        def commit(self):
            raise RuntimeError("database is gone")

        def rollback(self):
            pass

        def close(self):
            pass

    channel = DesktopNotificationChannel(_Exploding())

    with caplog.at_level("ERROR"):
        channel.send(_user(), "5 words are due", Channel.DESKTOP.value)

    assert "could not be queued" in caplog.text


# --- The repository --------------------------------------------------------


def test_pending_is_scoped_to_one_account(db_session):
    _persist_user(db_session, 1, "alex")
    _persist_user(db_session, 2, "sam")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    repo.add(DesktopNotification(id=None, user_id=1, message="alex's"))
    repo.add(DesktopNotification(id=None, user_id=2, message="sam's"))

    assert [n.message for n in repo.list_pending(1, utcnow() - timedelta(hours=1), 10)] == ["alex's"]


def test_pending_returns_oldest_first_and_respects_the_limit(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    base = utcnow() - timedelta(minutes=30)
    for offset, text in enumerate(["first", "second", "third"]):
        repo.add(
            DesktopNotification(
                id=None, user_id=1, message=text, created_at=base + timedelta(minutes=offset)
            )
        )

    collected = repo.list_pending(1, utcnow() - timedelta(hours=1), 2)

    assert [n.message for n in collected] == ["first", "second"]


def test_notifications_older_than_the_cutoff_are_not_collected(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    repo.add(
        DesktopNotification(
            id=None, user_id=1, message="stale", created_at=utcnow() - timedelta(days=3)
        )
    )
    repo.add(DesktopNotification(id=None, user_id=1, message="fresh"))

    collected = repo.list_pending(1, utcnow() - timedelta(hours=12), 10)

    assert [n.message for n in collected] == ["fresh"]


def test_acknowledgement_is_idempotent(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    stored = repo.add(DesktopNotification(id=None, user_id=1, message="5 words are due"))

    assert repo.mark_delivered(1, [stored.id]) == 1
    assert repo.mark_delivered(1, [stored.id]) == 0
    assert repo.list_pending(1, utcnow() - timedelta(hours=1), 10) == []


def test_one_account_cannot_acknowledge_anothers_notifications(db_session):
    _persist_user(db_session, 1, "alex")
    _persist_user(db_session, 2, "sam")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    sams = repo.add(DesktopNotification(id=None, user_id=2, message="sam's"))

    assert repo.mark_delivered(1, [sams.id]) == 0
    assert len(repo.list_pending(2, utcnow() - timedelta(hours=1), 10)) == 1


def test_acknowledging_nothing_is_a_no_op(db_session):
    assert SqlAlchemyDesktopNotificationRepository(db_session).mark_delivered(1, []) == 0


def test_purge_removes_only_old_delivered_rows(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    old_pending = repo.add(
        DesktopNotification(
            id=None, user_id=1, message="never collected", created_at=utcnow() - timedelta(days=30)
        )
    )
    collected = repo.add(DesktopNotification(id=None, user_id=1, message="collected"))
    repo.mark_delivered(1, [collected.id])

    # A cutoff in the future, so the just-delivered row is unambiguously older.
    assert repo.purge_delivered_before(utcnow() + timedelta(minutes=1)) == 1
    remaining = db_session.query(DesktopNotificationModel).all()
    assert [m.id for m in remaining] == [old_pending.id]


# --- The use cases ---------------------------------------------------------


def test_collection_reports_more_without_returning_the_lookahead_row(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    for i in range(3):
        repo.add(DesktopNotification(id=None, user_id=1, message=f"n{i}"))

    result = CollectDesktopNotificationsUseCase(repo).execute(1, limit=2)

    assert [n.message for n in result.notifications] == ["n0", "n1"]
    assert result.has_more is True


def test_an_exactly_full_page_is_not_reported_as_having_more(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    for i in range(2):
        repo.add(DesktopNotification(id=None, user_id=1, message=f"n{i}"))

    result = CollectDesktopNotificationsUseCase(repo).execute(1, limit=2)

    assert len(result.notifications) == 2
    assert result.has_more is False


def test_the_staleness_window_is_measured_from_the_injected_clock(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    repo.add(DesktopNotification(id=None, user_id=1, message="now-ish"))
    much_later = lambda: utcnow() + timedelta(days=2)  # noqa: E731

    result = CollectDesktopNotificationsUseCase(repo, clock=much_later).execute(1)

    assert result.notifications == []


def test_acknowledge_use_case_returns_rows_actually_moved(db_session):
    _persist_user(db_session, 1, "alex")
    repo = SqlAlchemyDesktopNotificationRepository(db_session)
    stored = repo.add(DesktopNotification(id=None, user_id=1, message="5 words are due"))
    use_case = AcknowledgeDesktopNotificationsUseCase(repo)

    assert use_case.execute(1, [stored.id]) == 1
    assert use_case.execute(1, [stored.id]) == 0


# --- The entity ------------------------------------------------------------


def test_mark_delivered_keeps_the_first_timestamp():
    notification = DesktopNotification(id=1, user_id=1, message="m")
    first = datetime(2026, 8, 2, 9, 0, 0)

    notification.mark_delivered(first)
    notification.mark_delivered(datetime(2026, 8, 2, 10, 0, 0))

    assert notification.delivered_at == first
    assert notification.pending is False


# --- The migration ---------------------------------------------------------


def test_the_migration_creates_the_table_the_model_expects(tmp_path):
    """The table is reached through Alembic in every deployment, but through
    `Base.metadata.create_all` in the test fixtures. Nothing else notices if
    the two drift, so this compares them directly."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import create_engine, inspect

    backend_dir = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=backend_dir,
        env=os.environ | {"DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )

    migrated = inspect(create_engine(database_url))
    assert "desktop_notifications" in migrated.get_table_names()
    assert {c["name"] for c in migrated.get_columns("desktop_notifications")} == {
        column.name for column in DesktopNotificationModel.__table__.columns
    }
    # The pending query filters on (user_id, delivered_at); without the
    # composite index it degrades to a scan of everything the account was
    # ever sent.
    assert "ix_desktop_notifications_user_undelivered" in {
        index["name"] for index in migrated.get_indexes("desktop_notifications")
    }


# --- The API ---------------------------------------------------------------


def test_collection_requires_authentication(client):
    assert client.get("/api/v1/desktop-notifications").status_code == 401


def test_acknowledgement_requires_authentication(client):
    response = client.post("/api/v1/desktop-notifications/ack", json={"notification_ids": [1]})
    assert response.status_code == 401


def test_the_shell_collects_then_acknowledges(client, auth_headers, db_session):
    headers = auth_headers()
    me = client.get("/api/v1/auth/me", headers=headers).json()
    SqlAlchemyDesktopNotificationRepository(db_session).add(
        DesktopNotification(id=None, user_id=me["id"], message="5 words are due")
    )
    db_session.commit()

    listed = client.get("/api/v1/desktop-notifications", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [n["message"] for n in body["notifications"]] == ["5 words are due"]
    assert body["has_more"] is False

    ids = [n["id"] for n in body["notifications"]]
    acked = client.post(
        "/api/v1/desktop-notifications/ack", json={"notification_ids": ids}, headers=headers
    )
    assert acked.status_code == 200
    assert acked.json()["acknowledged"] == 1

    # Collected notifications are not served again.
    assert client.get("/api/v1/desktop-notifications", headers=headers).json()["notifications"] == []


def test_a_repeated_acknowledgement_succeeds_and_reports_zero(client, auth_headers, db_session):
    """The OS callbacks issue #88 will add are allowed to fire twice, so a
    duplicate must be success-with-0 rather than a 404 or a 409."""
    headers = auth_headers()
    me = client.get("/api/v1/auth/me", headers=headers).json()
    stored = SqlAlchemyDesktopNotificationRepository(db_session).add(
        DesktopNotification(id=None, user_id=me["id"], message="5 words are due")
    )
    db_session.commit()

    payload = {"notification_ids": [stored.id]}
    assert client.post("/api/v1/desktop-notifications/ack", json=payload, headers=headers).json()[
        "acknowledged"
    ] == 1
    second = client.post("/api/v1/desktop-notifications/ack", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["acknowledged"] == 0


def test_one_account_cannot_collect_anothers_notifications(client, auth_headers, db_session):
    alex = auth_headers()
    sam = auth_headers(username="sam", email="sam@example.com")
    sam_id = client.get("/api/v1/auth/me", headers=sam).json()["id"]
    SqlAlchemyDesktopNotificationRepository(db_session).add(
        DesktopNotification(id=None, user_id=sam_id, message="sam's reminder")
    )
    db_session.commit()

    assert client.get("/api/v1/desktop-notifications", headers=alex).json()["notifications"] == []


def test_an_empty_acknowledgement_is_rejected(client, auth_headers):
    response = client.post(
        "/api/v1/desktop-notifications/ack", json={"notification_ids": []}, headers=auth_headers()
    )
    assert response.status_code == 422


def test_the_collection_limit_is_bounded(client, auth_headers):
    response = client.get("/api/v1/desktop-notifications?limit=500", headers=auth_headers())
    assert response.status_code == 422
