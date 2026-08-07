"""Learning DNA responses (issue #186 TODO 4): technique efficacy with
context/sample-size/uncertainty, and a learner's stated modality
preference — kept as two separate response shapes so the API itself cannot
blur "I like images" into "images measurably help" (see
`intervention_efficacy.build_modality_insight`'s docstring for the same
rule enforced at the domain layer).
"""
from datetime import datetime

from pydantic import BaseModel


class EfficacyContextResponse(BaseModel):
    item_class: str
    language: str
    prompt_direction: str
    difficulty: str
    modality: str
    horizon_days: int


class EfficacyEstimateResponse(BaseModel):
    intervention_type: str
    context: EfficacyContextResponse
    status: str
    intervention_samples: int
    control_samples: int
    intervention_rate: float | None
    control_rate: float | None
    effect: float | None
    interval_low: float | None
    interval_high: float | None
    reason: str | None
    recommendation: str | None
    period_start: datetime | None
    period_end: datetime | None
    valid_until: datetime | None


class ModalityPreferenceResponse(BaseModel):
    modality: str
    stated_at: datetime


class SetModalityPreferenceRequest(BaseModel):
    modality: str
