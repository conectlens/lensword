"""Evidence-grounded companion content contracts (#187).

The provider receives a bounded rendering request and returns editable prose.
Diagnosis, scheduling, mastery, and retention remain application-owned facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from app.domain.services.diagnosis_contracts import Diagnosis, InterventionPlan


class CoachContentRejected(ValueError):
    """Raised when provider content cannot be tied to supplied evidence."""


@dataclass(frozen=True)
class CoachEvidence:
    evidence_id: str
    fact: str
    source: str

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.fact.strip() or not self.source.strip():
            raise ValueError("coach evidence requires an id, fact, and source")
        if len(self.fact) > 1_000:
            raise ValueError("coach evidence facts are limited to 1000 characters")


@dataclass(frozen=True)
class CoachRequest:
    task: str
    target_language: str
    intervention_type: str
    evidence: tuple[CoachEvidence, ...]
    allowed_claims: tuple[str, ...]
    prompt_template_version: str = "coach-v1"

    def __post_init__(self) -> None:
        if not 1 <= len(self.evidence) <= 20:
            raise ValueError("coach requests require 1-20 bounded evidence records")
        if not self.task.strip() or len(self.task) > 500:
            raise ValueError("coach task must contain 1-500 characters")
        if not self.target_language.strip() or not self.intervention_type.strip():
            raise ValueError("coach language and intervention type are required")


@dataclass(frozen=True)
class CoachContent:
    text: str
    evidence_ids: tuple[str, ...]
    content_type: str
    provider: str
    model: str | None
    editable: bool = True


def build_coach_prompt(request: CoachRequest) -> str:
    facts = "\n".join(
        f"[{evidence.evidence_id}] ({evidence.source}) {evidence.fact}"
        for evidence in request.evidence
    )
    claims = ", ".join(request.allowed_claims) or "only the supplied facts"
    return (
        "You are a LensWord content renderer.\n"
        "Never invent observations, diagnoses, mastery, retention, percentages, or prerequisites.\n"
        "Return editable learner-facing content and cite only supplied evidence IDs.\n"
        f"Allowed claims: {claims}\n"
        "<evidence>\n"
        f"{facts}\n"
        "</evidence>\n"
        "<request>\n"
        f"language={request.target_language}; intervention={request.intervention_type}; task={request.task}\n"
        "</request>"
    )


_FORBIDDEN_CLAIMS = re.compile(
    r"(?:\bmaster(?:y|ed|ing)\b|\bretention\s*(?:rate|score|percentage)?\b|\b\d+\s*%|\byou are a\s+(?:visual|auditory|spatial|story)\s+learner\b)",
    re.IGNORECASE,
)


def validate_generated_content(
    payload: Mapping[str, object],
    request: CoachRequest,
    *,
    content_type: str,
    provider: str,
    model: str | None = None,
) -> CoachContent:
    text = payload.get("text")
    raw_ids = payload.get("evidence_ids")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4_000:
        raise CoachContentRejected("coach content must contain 1-4000 characters")
    if not isinstance(raw_ids, list) or not raw_ids or not all(isinstance(item, str) for item in raw_ids):
        raise CoachContentRejected("coach content must cite evidence IDs")
    known_ids = {evidence.evidence_id for evidence in request.evidence}
    evidence_ids = tuple(dict.fromkeys(raw_ids))
    if not set(evidence_ids).issubset(known_ids):
        raise CoachContentRejected("coach content cited evidence outside the request")
    if _FORBIDDEN_CLAIMS.search(text):
        raise CoachContentRejected("coach content contains an unsupported learning claim")
    return CoachContent(text=text.strip(), evidence_ids=evidence_ids, content_type=content_type, provider=provider, model=model)


# The task string is free text built from bounded inputs (a strategy name
# and a content type, both from closed sets), but CoachRequest itself still
# enforces a 500-character ceiling — slicing here keeps that bound visible
# at the call site instead of relying on the dataclass to raise.
_MAX_TASK_CHARS = 500


def build_coach_request(
    plan: InterventionPlan,
    diagnosis: Diagnosis | None,
    *,
    target_language: str,
    content_type: str,
) -> CoachRequest:
    """Turn a persisted `InterventionPlan` (and, when still available, the
    `Diagnosis` that produced it) into a bounded, evidence-only coach
    request (#187 TODO 2).

    Only deterministic, code-generated strings ever become evidence here:
    `DiagnosisEvidence.description` (diagnosis_engine.py) is templated from
    observation counts, ids and category names, and `InterventionPlan.
    rationale` (intervention_planning.py) is one of a fixed set of authored
    sentences — neither ever echoes a learner's raw submitted answer. That
    is what makes #187 TODO 1's "hostile learner text can't ... cause
    invented diagnoses" hold structurally: there is no path from an
    attempted answer into this request at all, not merely a prompt asking
    a model to ignore one.

    Falls back to the plan's own rationale as the sole evidence record when
    no diagnosis matching the plan's exact outcome is found (e.g. it aged
    out of `DiagnosisRepository`'s retention, or a plan was seeded directly
    in a test) — the rationale is itself evidence-derived, so it is safe to
    cite here too.
    """
    if diagnosis is not None and diagnosis.outcome == plan.diagnosis_outcome and diagnosis.evidence:
        evidence = tuple(
            CoachEvidence(
                evidence_id=f"evidence-{index}",
                fact=item.description[:1_000],
                source=item.kind or "diagnosis_evidence",
            )
            for index, item in enumerate(diagnosis.evidence[:20])
        )
    else:
        evidence = (
            CoachEvidence(
                evidence_id="plan-rationale",
                fact=(plan.rationale[:1_000] or "No further detail was recorded for this plan."),
                source="intervention_plan",
            ),
        )
    task = (
        f"Generate {content_type} content for the '{plan.strategy}' intervention "
        "chosen for this diagnosis."
    )
    return CoachRequest(
        task=task[:_MAX_TASK_CHARS],
        target_language=target_language or "the learner's target language",
        intervention_type=content_type,
        evidence=evidence,
        allowed_claims=(f"the diagnosed cause ({plan.diagnosis_outcome}) and the cited evidence",),
    )


def deterministic_fallback(request: CoachRequest, *, content_type: str = "explanation") -> CoachContent:
    """Produce safe content when a provider is disabled, slow, or unavailable."""
    first = request.evidence[0]
    templates = {
        "contrast": f"Compare the two forms using this verified observation: {first.fact}",
        "prerequisite": f"Review the prerequisite connected to this observation: {first.fact}",
        "mnemonic": f"Create your own short memory cue for this observation: {first.fact}",
        "explanation": f"LensWord recorded this learning observation: {first.fact}",
    }
    text = templates.get(request.intervention_type, templates["explanation"])
    return CoachContent(
        text=text,
        evidence_ids=(first.evidence_id,),
        content_type=content_type,
        provider="deterministic",
        model=None,
    )
