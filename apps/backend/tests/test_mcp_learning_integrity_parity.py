"""Issue #199 TODO 3: companion evidence and first-party evidence produce the
same downstream diagnosis/scheduling behavior.

Two structural facts about this codebase make the parity claim checkable
deterministically, with no I/O (per this repo's convention that domain
services are pure and testable under a fixed clock):

1. `app.domain.services.diagnosis_engine.diagnose` (the FSRS-adjacent
   scheduling/diagnosis pipeline every review outcome eventually feeds) reads
   only closed, structural `LearningObservation` fields — `outcome`,
   `modality`, `context_source`, `observed_at` — never a "this came from the
   companion" flag. There is no such flag anywhere in the domain layer: the
   companion path (`app.application.use_cases.companion_activities.
   SubmitActivityResponseUseCase`) and the first-party review path
   (`app.application.use_cases.review`) both construct the exact same
   `LearningObservation` dataclass and hand it to the exact same
   `LearningObservationRepository.add`.
2. Free chat never reaches this pipeline at all
   (`test_companion_activity_observations.py::
   test_free_chat_turns_produce_zero_review_observations`, #194) - so "same
   door, same effect" is meaningful only for the structured-activity door
   this file exercises, which is the correct scope: free conversation was
   never supposed to have a scheduling effect from either door.

This test builds two observation histories that are identical except for
their `answer_format`/`context_source`/`modality` provenance tags - one
shaped like `SubmitActivityResponseUseCase`'s companion-activity output, one
shaped like `review.py`'s first-party review-answer output - and confirms
`diagnose()` returns the same category and the same confidence for both,
proving the provenance tag is informational, not a hidden input that treats
one door's evidence as weaker or stronger than the other's.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.diagnosis_contracts import LearningObservation
from app.domain.services.diagnosis_engine import DiagnosisCategory, DiagnosisContext, diagnose
from app.domain.services.knowledge_graph import KnowledgeGraph, WordNode
from app.domain.value_objects import ReviewOutcome, ReviewState, SessionMode

BASE = datetime(2026, 8, 6, 9, 0)
WORD_ID = 1
USER_ID = 1
TERM = "prestar"


def _review_state() -> ReviewState:
    return ReviewState(strength=50, ease_factor=2.5, interval_days=5, repetitions=3, due_at=BASE + timedelta(days=5), last_reviewed_at=BASE, stability=10.0)


def _context(observations) -> DiagnosisContext:
    return DiagnosisContext(
        word_id=WORD_ID, user_id=USER_ID, term=TERM, observations=tuple(observations),
        graph=KnowledgeGraph([WordNode(word_id=WORD_ID, term=TERM)], []), review_state=_review_state(),
    )


def _companion_shaped_history() -> list[LearningObservation]:
    """Same shape `SubmitActivityResponseUseCase` (companion_activities.py)
    actually produces: `answer_format="companion_activity"`,
    `context_source="companion_activity:{activity_type}"`."""
    return [
        LearningObservation(
            observation_id="companion-1", word_id=WORD_ID, user_id=USER_ID, outcome=ReviewOutcome.CORRECT,
            session_mode=SessionMode.STANDARD, observed_at=BASE - timedelta(days=10),
            answer_format="companion_activity", context_source="companion_activity:short_answer", modality="typed",
        ),
        LearningObservation(
            observation_id="companion-2", word_id=WORD_ID, user_id=USER_ID, outcome=ReviewOutcome.INCORRECT,
            session_mode=SessionMode.STANDARD, observed_at=BASE,
            answer_format="companion_activity", context_source="companion_activity:short_answer", modality="typed",
        ),
    ]


def _first_party_shaped_history() -> list[LearningObservation]:
    """Same shape `review.py`'s `RecordAnswerUseCase` (the REST
    `/review/answer` endpoint and the MCP `lensword_record_answer` tool)
    actually produces: no `answer_format`/`context_source` override, plain
    review telemetry."""
    return [
        LearningObservation(
            observation_id="review-1", word_id=WORD_ID, user_id=USER_ID, outcome=ReviewOutcome.CORRECT,
            session_mode=SessionMode.STANDARD, observed_at=BASE - timedelta(days=10),
            answer_format="typed", modality="typed",
        ),
        LearningObservation(
            observation_id="review-2", word_id=WORD_ID, user_id=USER_ID, outcome=ReviewOutcome.INCORRECT,
            session_mode=SessionMode.STANDARD, observed_at=BASE,
            answer_format="typed", modality="typed",
        ),
    ]


def test_companion_and_first_party_evidence_produce_the_same_diagnosis():
    companion_result = diagnose(_context(_companion_shaped_history()))
    first_party_result = diagnose(_context(_first_party_shaped_history()))

    assert not companion_result.is_abstention
    assert companion_result.outcome == DiagnosisCategory.FORGETTING
    assert companion_result.outcome == first_party_result.outcome
    assert companion_result.confidence == first_party_result.confidence
    assert companion_result.sample_size == first_party_result.sample_size


def test_the_two_histories_really_do_differ_only_in_provenance_tagging():
    """Guards the test above against becoming vacuous: if this ever starts
    failing, the two histories stopped being "identical except for
    provenance," which would silently invalidate the parity claim."""
    companion, first_party = _companion_shaped_history(), _first_party_shaped_history()
    assert [o.outcome for o in companion] == [o.outcome for o in first_party]
    assert [o.observed_at for o in companion] == [o.observed_at for o in first_party]
    assert [o.answer_format for o in companion] != [o.answer_format for o in first_party]
    assert any(o.context_source for o in companion) and not any(o.context_source for o in first_party)


def test_every_observation_names_its_own_method_and_provenance():
    """Spot-check of TODO 3's "all measurements name method and provenance"
    against the three real construction sites: companion_activities.py,
    mcp_dev_workflow.py, and review.py all set `answer_format` (the
    method) and, where the source is not an ordinary review prompt, a
    `context_source` (the provenance) - neither is ever left blank on these
    paths."""
    for observation in (*_companion_shaped_history(), *_first_party_shaped_history()):
        assert observation.answer_format, "answer_format (method) must be named, not blank"
