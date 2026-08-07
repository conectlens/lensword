"""Intervention plan responses and actions (issue #185 TODO 4).

`InterventionPlanResponse` and `ChooseAlternativeRequest` back the per-word
endpoints in `interventions.py`'s `router`. `InterventionPlanListResponse`
is the account-wide counterpart added for issue #192's `/me/interventions`
companion resource — the first place a plan is read back outside of one
word's active-decision list; before this, a plan was only ever referenced
afterward by its `intervention_plan_ref` string on an observation.
"""
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


class InterventionPlanListResponse(BaseModel):
    """Issue #192's `/me/interventions` companion resource — every planned
    intervention across the account's whole vocabulary. Bounded and
    paginated the same way `DiagnosisListResponse` is.
    """

    items: list[InterventionPlanResponse]
    next_cursor: str | None = None
