"""Reminder failover intents and delivery reconciliation via the real API
(issue #87)."""
from __future__ import annotations

from app.domain.entities import Group, Reminder
from app.domain.value_objects import Recurrence, SupportedLanguage
from app.infrastructure.repositories import SqlAlchemyGroupRepository, SqlAlchemyReminderRepository


def _seed_reminder(db_session, user_id: int, trigger_time: str = "09:00") -> Reminder:
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user_id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    reminder = SqlAlchemyReminderRepository(db_session).add(
        Reminder(id=None, user_id=user_id, group_id=group.id, trigger_time=trigger_time, recurrence=Recurrence.DAILY)
    )
    db_session.commit()
    return reminder


def test_failover_intents_lists_the_accounts_reminders(client, auth_headers, db_session):
    headers = auth_headers()
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    reminder = _seed_reminder(db_session, user_id)

    resp = client.get("/api/v1/reminders/failover-intents", headers=headers)

    assert resp.status_code == 200
    intents = resp.json()["intents"]
    assert len(intents) == 1
    assert intents[0]["reminder_id"] == reminder.id
    assert intents[0]["revision"] == reminder.revision
    assert intents[0]["trigger_time"] == "09:00"


def test_another_accounts_intents_are_not_visible(client, auth_headers, db_session):
    owner = auth_headers()
    owner_id = client.get("/api/v1/auth/me", headers=owner).json()["id"]
    _seed_reminder(db_session, owner_id)

    intruder = auth_headers(username="sam", email="sam@example.com")
    resp = client.get("/api/v1/reminders/failover-intents", headers=intruder)

    assert resp.json()["intents"] == []


def test_a_delivery_report_is_accepted_and_claimed_so_the_backend_will_not_refire_it(client, auth_headers, db_session):
    headers = auth_headers()
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    reminder = _seed_reminder(db_session, user_id)

    resp = client.post(
        "/api/v1/reminders/delivery-reports",
        json={
            "reports": [
                {
                    "reminder_id": reminder.id,
                    "occurrence_key": "2026-08-06T09:00:00",
                    "delivered_at": "2026-08-06T09:00:05Z",
                    "revision": reminder.revision,
                }
            ]
        },
        headers=headers,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["accepted"] is True
    assert result["reason"] is None

    # The backend scheduler must now see this occurrence as already claimed.
    from app.infrastructure.job_claims import claim, reminder_job_key

    won = claim(db_session, reminder_job_key(reminder.id), "2026-08-06T09:00:00")
    assert won is False


def test_a_report_for_a_stale_revision_is_not_accepted_and_not_claimed(client, auth_headers, db_session):
    headers = auth_headers()
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    reminder = _seed_reminder(db_session, user_id)
    stale_revision = reminder.revision

    # Edit the reminder (via the domain object directly — there is no PUT
    # endpoint for reminders; they are system-managed) so its revision moves.
    updated = SqlAlchemyReminderRepository(db_session).update(
        Reminder(id=reminder.id, user_id=user_id, group_id=reminder.group_id, trigger_time="18:00", recurrence=Recurrence.DAILY)
    )
    db_session.commit()
    assert updated.revision > stale_revision

    resp = client.post(
        "/api/v1/reminders/delivery-reports",
        json={
            "reports": [
                {
                    "reminder_id": reminder.id,
                    "occurrence_key": "2026-08-06T09:00:00",
                    "delivered_at": "2026-08-06T09:00:05Z",
                    "revision": stale_revision,
                }
            ]
        },
        headers=headers,
    )

    result = resp.json()["results"][0]
    assert result["accepted"] is False
    assert "superseded" in result["reason"]

    from app.infrastructure.job_claims import claim, reminder_job_key

    # Not claimed: the backend must still be free to deliver the *new*
    # 18:00 occurrence rather than finding it pre-claimed by a stale report.
    won = claim(db_session, reminder_job_key(reminder.id), "2026-08-06T09:00:00")
    assert won is True
