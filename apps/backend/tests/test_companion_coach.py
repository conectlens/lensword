import pytest

from app.domain.services.companion_coach import (
    CoachContentRejected,
    CoachEvidence,
    CoachRequest,
    build_coach_prompt,
    deterministic_fallback,
    validate_generated_content,
)


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
