"""Reminder intents and offline-delivery reconciliation (issue #87).

Two endpoints, one for each side of the handoff: the shell reads the
account's current reminder intents to know what it might have to run
locally, and reports back what it actually delivered while the backend was
unreachable so the backend can suppress a duplicate firing.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, ReminderRepo, UserRepo
from app.api.schemas.reminder_failover import (
    DeliveryReportResultResponse,
    ReminderIntentResponse,
    ReminderIntentsResponse,
    SubmitDeliveryReportsRequest,
    SubmitDeliveryReportsResponse,
)
from app.application.use_cases.scheduler_failover import (
    ListReminderIntentsUseCase,
    ReconcileDeliveryReportsUseCase,
)
from app.domain.services.scheduler_failover import DeliveryReport
from app.infrastructure.job_claims import claim, reminder_job_key

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])


@router.get("/failover-intents", response_model=ReminderIntentsResponse)
def list_failover_intents(
    current_user: CurrentUser, reminder_repo: ReminderRepo, user_repo: UserRepo
) -> ReminderIntentsResponse:
    intents = ListReminderIntentsUseCase(reminder_repo, user_repo).execute(current_user.id)
    return ReminderIntentsResponse(
        intents=[
            ReminderIntentResponse(
                reminder_id=i.reminder_id,
                revision=i.revision,
                trigger_time=i.trigger_time,
                time_zone=i.time_zone,
                enabled=i.enabled,
            )
            for i in intents
        ]
    )


@router.post("/delivery-reports", response_model=SubmitDeliveryReportsResponse)
def submit_delivery_reports(
    payload: SubmitDeliveryReportsRequest,
    current_user: CurrentUser,
    reminder_repo: ReminderRepo,
    user_repo: UserRepo,
    db: DbSession,
) -> SubmitDeliveryReportsResponse:
    """Reconcile what the shell delivered while offline (issue #87).

    Always 200: a report failing to reconcile is an expected outcome of an
    edit racing an offline delivery, not a fault. Accepted reports are
    claimed against the same key the backend scheduler claims with (#20),
    so reconnecting cannot replay an acknowledged firing.
    """
    reports = [
        DeliveryReport(
            reminder_id=r.reminder_id,
            occurrence_key=r.occurrence_key,
            delivered_at=r.delivered_at,
            revision=r.revision,
        )
        for r in payload.reports
    ]
    accepted, superseded = ReconcileDeliveryReportsUseCase(reminder_repo, user_repo).execute(
        current_user.id, reports
    )

    results: list[DeliveryReportResultResponse] = []
    for report in accepted:
        won = claim(db, reminder_job_key(report.reminder_id), report.occurrence_key)
        results.append(
            DeliveryReportResultResponse(
                reminder_id=report.reminder_id,
                occurrence_key=report.occurrence_key,
                accepted=True,
                reason=None if won else "already claimed — the backend fired this occurrence too",
            )
        )
    for report in superseded:
        results.append(
            DeliveryReportResultResponse(
                reminder_id=report.reminder_id,
                occurrence_key=report.occurrence_key,
                accepted=False,
                reason="revision superseded — the reminder changed or was deleted after this fired",
            )
        )
    return SubmitDeliveryReportsResponse(results=results)
