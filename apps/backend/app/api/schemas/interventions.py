"""Intervention plan responses and actions (issue #185 TODO 4)."""
from datetime import datetime

from pydantic import BaseModel


class InterventionPlanResponse(BaseModel):
    id: int | None
    word_id: int
    diagnosis_outcome: str
    strategy: str
    policy_version: int
    eligible: bool
    rationale: str
    planned_at: datetime
    second_word_id: int | None
    prerequisite_ids: list[int]


class ChooseAlternativeRequest(BaseModel):
    strategy: str
