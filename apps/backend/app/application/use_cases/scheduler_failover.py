"""Reminder intents and offline-delivery reconciliation (issue #87).

`FailoverPolicy` (domain) already decides who owns a firing and which
delivery reports survive reconciliation; this is the caller that builds
`ReminderIntent`s from the account's actual reminders and runs reported
deliveries through that policy. Claiming an accepted report — the step that
actually stops the backend firing it again — is left to the router, which
already has the raw session `app.infrastructure.job_claims.claim` needs;
this use case stays a pure decision, like the policy it wraps.
"""
from __future__ import annotations

from app.domain.repositories import ReminderRepository, UserRepository
from app.domain.services.scheduler_failover import (
    DeliveryReport,
    FailoverPolicy,
    ReminderIntent,
)


class ListReminderIntentsUseCase:
    def __init__(self, reminder_repo: ReminderRepository, user_repo: UserRepository):
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo

    def execute(self, user_id: int) -> list[ReminderIntent]:
        user = self.user_repo.get_by_id(user_id)
        time_zone = user.time_zone if user else "UTC"
        return [
            ReminderIntent(
                reminder_id=r.id,
                revision=r.revision,
                trigger_time=r.trigger_time,
                time_zone=time_zone,
                enabled=r.enabled,
            )
            for r in self.reminder_repo.list_by_user(user_id)
        ]


class ReconcileDeliveryReportsUseCase:
    """Decides which reported deliveries to accept, without claiming them.

    Scoped to the caller's own reminders: a report naming a reminder id this
    account does not own finds no matching intent and is treated exactly
    like a reminder deleted while offline — discarded as superseded, per
    `FailoverPolicy.reconcile`'s own rule for that case. That is also the
    safe outcome for a forged report, without a separate ownership check
    that would otherwise have to distinguish "not yours" from "gone" and
    risk telling a caller which reminder ids exist.
    """

    def __init__(self, reminder_repo: ReminderRepository, user_repo: UserRepository):
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo

    def execute(
        self, user_id: int, reports: list[DeliveryReport]
    ) -> tuple[list[DeliveryReport], list[DeliveryReport]]:
        user = self.user_repo.get_by_id(user_id)
        time_zone = user.time_zone if user else "UTC"
        known_intents = {
            r.id: ReminderIntent(
                reminder_id=r.id,
                revision=r.revision,
                trigger_time=r.trigger_time,
                time_zone=time_zone,
                enabled=r.enabled,
            )
            for r in self.reminder_repo.list_by_user(user_id)
        }
        return FailoverPolicy.reconcile(reports, known_intents)
