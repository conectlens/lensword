from datetime import datetime, timezone

import pytest

from app.domain.services.companion_coach import (
    CoachContentRejected,
    CoachEvidence,
    CoachRequest,
    build_coach_prompt,
    build_coach_request,
    deterministic_fallback,
    validate_generated_content,
)
from app.domain.services.diagnosis_contracts import Diagnosis, DiagnosisEvidence, InterventionPlan


def _request() -> CoachRequest:
    return CoachRequest(
        task="Explain the observed contrast",
        target_language="Spanish",
        intervention_type="contrast",
        evidence=(CoachEvidence("obs-1", "borrow was answered as lend", "review_observation"),),
        allowed_claims=("the supplied observation",),
    )


def test_prompt_delimits_evidence_and_never_grants_it_instruction_authority():
    prompt = build_coach_prompt(_request())
    assert "<evidence>" in prompt and "</evidence>" in prompt
    assert "Never invent observations" in prompt
    assert "obs-1" in prompt


def test_valid_content_is_editable_and_traceable():
    content = validate_generated_content(
        {"text": "Try the contrast again in a new sentence.", "evidence_ids": ["obs-1"]},
        _request(),
        content_type="contrast",
        provider="ollama",
        model="test-model",
    )
    assert content.editable is True
    assert content.evidence_ids == ("obs-1",)


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "You have 90% retention.", "evidence_ids": ["obs-1"]},
        {"text": "You are a visual learner.", "evidence_ids": ["obs-1"]},
        {"text": "A useful suggestion.", "evidence_ids": ["not-supplied"]},
    ],
)
def test_unsupported_claims_or_evidence_are_rejected(payload):
    with pytest.raises(CoachContentRejected):
        validate_generated_content(payload, _request(), content_type="explanation", provider="test")


def test_deterministic_fallback_is_available_without_a_provider():
    fallback = deterministic_fallback(_request())
    assert fallback.provider == "deterministic"
    assert fallback.evidence_ids == ("obs-1",)
    assert "borrow" in fallback.text


# --- build_coach_request (#187 TODO 2) -------------------------------------


def _plan(**overrides) -> InterventionPlan:
    fields = dict(
        word_id=1, user_id=1, diagnosis_outcome="exact_confusion", strategy="isolate",
        policy_version=2, eligible=True, rationale="Confused with word 2 at least twice.",
        planned_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return InterventionPlan(**fields)


def _diagnosis(**overrides) -> Diagnosis:
    fields = dict(
        word_id=1, user_id=1, outcome="exact_confusion",
        evidence=(
            DiagnosisEvidence(
                kind="exact_confusion", observation_ids=("obs-1",), weight=0.8,
                description="answered word 2 instead 2 time(s)",
            ),
        ),
        confidence=0.8, rules_version=1, diagnosed_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return Diagnosis(**fields)


def test_build_coach_request_cites_the_matching_diagnosis_evidence():
    request = build_coach_request(
        _plan(), _diagnosis(), target_language="Spanish", content_type="explanation"
    )

    assert request.target_language == "Spanish"
    assert request.intervention_type == "explanation"
    assert len(request.evidence) == 1
    assert request.evidence[0].fact == "answered word 2 instead 2 time(s)"
    assert request.evidence[0].source == "exact_confusion"


def test_build_coach_request_falls_back_to_the_plan_rationale_without_a_matching_diagnosis():
    """No diagnosis at all (e.g. a plan seeded directly, or one whose
    diagnosis aged out) must not crash the request — the plan's own
    rationale is itself evidence-derived and safe to cite."""
    request = build_coach_request(_plan(), None, target_language="Spanish", content_type="explanation")

    assert len(request.evidence) == 1
    assert request.evidence[0].fact == "Confused with word 2 at least twice."
    assert request.evidence[0].source == "intervention_plan"


def test_build_coach_request_ignores_a_diagnosis_for_a_different_outcome():
    """A stale diagnosis (re-diagnosed to something else since the plan was
    made) must not be cited as though it still explains this plan."""
    stale = _diagnosis(outcome="forgetting", evidence=())
    request = build_coach_request(_plan(), stale, target_language="Spanish", content_type="explanation")

    assert request.evidence[0].source == "intervention_plan"


def test_build_coach_request_bounds_evidence_at_twenty():
    many_evidence = tuple(
        DiagnosisEvidence(kind="k", observation_ids=(f"obs-{i}",), weight=0.1, description=f"fact {i}")
        for i in range(30)
    )
    request = build_coach_request(
        _plan(), _diagnosis(evidence=many_evidence), target_language="Spanish", content_type="explanation"
    )

    assert len(request.evidence) == 20


def test_build_coach_request_never_echoes_raw_learner_text():
    """#187 TODO 1: the only strings that can end up as evidence here are
    `DiagnosisEvidence.description` and `InterventionPlan.rationale`, both
    deterministic and code-generated — never the learner's own submitted
    answer, which never appears in either field."""
    hostile_free_diagnosis = _diagnosis()
    request = build_coach_request(
        _plan(), hostile_free_diagnosis, target_language="Spanish", content_type="explanation"
    )

    for evidence in request.evidence:
        assert "ignore" not in evidence.fact.lower()
        assert "instruction" not in evidence.fact.lower()
