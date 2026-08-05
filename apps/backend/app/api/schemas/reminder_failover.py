"""Reminder intents and offline-delivery reconciliation (issue #87)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReminderIntentResponse(BaseModel):
    """One reminder, in the form both the backend and a local scheduler
    agree on. The desktop shell registers a local job from this and decides
    whether to fire it itself based on its own view of backend reachability
    — that decision, `FailoverPolicy.executor_for`, is deliberately made on
    the client, which is the only side that actually knows its own
    connectivity."""

    reminder_id: int
    revision: int
    trigger_time: str
    time_zone: str
    enabled: bool


class ReminderIntentsResponse(BaseModel):
    intents: list[ReminderIntentResponse]


class DeliveryReportRequest(BaseModel):
    reminder_id: int = Field(gt=0)
    occurrence_key: str = Field(min_length=1, max_length=64)
    delivered_at: datetime
    revision: int = Field(gt=0)


class SubmitDeliveryReportsRequest(BaseModel):
    reports: list[DeliveryReportRequest] = Field(min_length=1, max_length=200)


class DeliveryReportResultResponse(BaseModel):
    reminder_id: int
    occurrence_key: str
    accepted: bool
    # Why a report was not accepted, or not claimed once accepted. None when
    # it was cleanly claimed.
    reason: str | None = None


class SubmitDeliveryReportsResponse(BaseModel):
    results: list[DeliveryReportResultResponse]
