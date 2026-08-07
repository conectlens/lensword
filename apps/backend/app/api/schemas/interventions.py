"""Intervention plan responses and actions (issue #185 TODO 4, #187 TODO 2/3)."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


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


# --- AI-generated intervention content (#187 TODO 2/3) --------------------
#
# Discriminated on `status`, the same shape MnemonicSuggestionDisabled/
# Unavailable/Ok (app/api/schemas/review.py) already uses for
# "no AI configured" vs "AI unreachable" vs "AI answered" — always a 200,
# because both are ordinary states of a healthy install, not client errors.
# Unlike the mnemonic suggestion (which has nothing useful to say without a
# real generation), every non-"ok" branch here still carries
# `deterministic_fallback`'s template content (companion_coach.py) so the
# learner always has something to look at (#187 TODO 3's own verify
# clause: the templates must be reachable from this endpoint, not just
# theoretically available). "rejected" is the one status with no mnemonics
# equivalent: it reports a provider that answered but whose content failed
# validation (an unsupported claim, or evidence outside the request) —
# TODO 2's "malformed/unsafe outputs rejected without losing the underlying
# plan." The plan itself is never touched by any branch.


class InterventionExplanationDisabled(BaseModel):
    status: Literal["disabled"] = "disabled"
    text: str
    evidence_ids: list[str]
    content_type: str
    editable: bool = True


class InterventionExplanationUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    detail: str
    text: str
    evidence_ids: list[str]
    content_type: str
    editable: bool = True


class InterventionExplanationRejected(BaseModel):
    status: Literal["rejected"] = "rejected"
    detail: str
    text: str
    evidence_ids: list[str]
    content_type: str
    editable: bool = True


class InterventionExplanationOk(BaseModel):
    status: Literal["ok"] = "ok"
    text: str
    evidence_ids: list[str]
    content_type: str
    provider: str
    model: str | None
    editable: bool = True


InterventionExplanationResponse = Annotated[
    InterventionExplanationDisabled
    | InterventionExplanationUnavailable
    | InterventionExplanationRejected
    | InterventionExplanationOk,
    Field(discriminator="status"),
]
