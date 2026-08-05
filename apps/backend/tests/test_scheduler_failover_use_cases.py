"""Reminder intents and offline-delivery reconciliation, the application
layer (issue #87). The policy itself is tested without a database in
test_scheduler_failover.py; this covers what wiring it to real repositories
adds: ownership, and the user's actual time zone and revision."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.application.use_cases.scheduler_failover import (
    ListReminderIntentsUseCase,
    ReconcileDeliveryReportsUseCase,
)
from app.domain.entities import Group, Reminder, User
from app.domain.services.scheduler_failover import DeliveryReport
from app.domain.value_objects import Recurrence, SupportedLanguage, UserRole
from app.infrastructure.repositories import (
    SqlAlchemyGroupRepository,
    SqlAlchemyReminderRepository,
    SqlAlchemyUserRepository,
)


@pytest.fixture()
def world(db_session):
    users = SqlAlchemyUserRepository(db_session)
    user = users.add(
        User(
            id=None, username="alex", email="alex@example.com", hashed_password="x",
            role=UserRole.USER, time_zone="America/New_York",
        )
    )
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user.id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    reminders = SqlAlchemyReminderRepository(db_session)
    reminder = reminders.add(
        Reminder(id=None, user_id=user.id, group_id=group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )
    db_session.commit()
    return {"user": user, "reminder": reminder, "users": users, "reminders": reminders}


def _report(reminder_id: int, revision: int, occurrence_key: str = "2026-08-06T09:00:00") -> DeliveryReport:
    return DeliveryReport(
        reminder_id=reminder_id, occurrence_key=occurrence_key,
        delivered_at=datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc), revision=revision,
    )


def test_intents_carry_the_owners_time_zone_and_current_revision(world):
    intents = ListReminderIntentsUseCase(world["reminders"], world["users"]).execute(world["user"].id)

    assert len(intents) == 1
    assert intents[0].reminder_id == world["reminder"].id
    assert intents[0].revision == world["reminder"].revision
    assert intents[0].time_zone == "America/New_York"
    assert intents[0].enabled is True


def test_a_report_naming_the_current_revision_is_accepted(world):
    accepted, superseded = ReconcileDeliveryReportsUseCase(world["reminders"], world["users"]).execute(
        world["user"].id, [_report(world["reminder"].id, world["reminder"].revision)]
    )

    assert len(accepted) == 1
    assert superseded == []


def test_a_report_naming_a_stale_revision_is_superseded(world):
    stale_revision = world["reminder"].revision
    world["reminders"].update(
        Reminder(
            id=world["reminder"].id, user_id=world["user"].id, group_id=world["reminder"].group_id,
            trigger_time="18:00", recurrence=Recurrence.DAILY,
        )
    )

    accepted, superseded = ReconcileDeliveryReportsUseCase(world["reminders"], world["users"]).execute(
        world["user"].id, [_report(world["reminder"].id, stale_revision)]
    )

    assert accepted == []
    assert len(superseded) == 1


def test_a_report_for_a_reminder_you_do_not_own_is_superseded_not_leaked(world, db_session):
    """Same outcome as a deleted reminder — a forged report gets no signal
    telling it whether the id exists at all."""
    intruder = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="sam", email="sam@example.com", hashed_password="x", role=UserRole.USER)
    )
    intruder_group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=intruder.id, name="G2", target_language=SupportedLanguage.SPANISH)
    )
    intruder_reminder = SqlAlchemyReminderRepository(db_session).add(
        Reminder(id=None, user_id=intruder.id, group_id=intruder_group.id, trigger_time="09:00", recurrence=Recurrence.DAILY)
    )
    db_session.commit()

    accepted, superseded = ReconcileDeliveryReportsUseCase(world["reminders"], world["users"]).execute(
        world["user"].id, [_report(intruder_reminder.id, intruder_reminder.revision)]
    )

    assert accepted == []
    assert len(superseded) == 1
