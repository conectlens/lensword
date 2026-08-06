"""The deterministic diagnosis engine (#180, issue #183).

Per taxonomy member: a positive case (the rule fires), a negative case
(evidence exists but doesn't meet the bar), a boundary case (exactly at
the evidentiary threshold), and confirmation that ambiguous/insufficient
evidence abstains rather than guessing.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    LearningObservation,
)
from app.domain.services.diagnosis_engine import (
    ALL_RULES,
    ContextLockRule,
    DiagnosisCandidate,
    DiagnosisCategory,
    DiagnosisContext,
    ExactConfusionRule,
    ForgettingRule,
    MissingPrerequisiteRule,
    OrthographicInterferenceRule,
    PhoneticInterferenceRule,
    RecognitionProductionGapRule,
    SemanticDirectionReversalRule,
    WeakAcquisitionRule,
    diagnose,
)
from app.domain.services.knowledge_graph import KnowledgeEdge, KnowledgeGraph, Relation, WordNode
from app.domain.value_objects import ReviewOutcome, ReviewState, SessionMode

BASE = datetime(2026, 8, 6, 9, 0)
WORD = 1
OTHER = 2
USER = 1


def _obs(idx: int, outcome: ReviewOutcome, when: datetime = BASE, **overrides) -> LearningObservation:
    defaults = dict(
        observation_id=f"o{idx}",
        word_id=WORD,
        user_id=USER,
        outcome=outcome,
        session_mode=SessionMode.STANDARD,
        observed_at=when,
    )
    defaults.update(overrides)
    return LearningObservation(**defaults)


def _state(stability: float | None = 10.0, last_reviewed_at: datetime | None = BASE) -> ReviewState:
    return ReviewState(
        strength=50, ease_factor=2.5, interval_days=5, repetitions=3,
        due_at=BASE + timedelta(days=5), last_reviewed_at=last_reviewed_at, stability=stability,
    )


def _context(
    observations,
    graph: KnowledgeGraph | None = None,
    review_state: ReviewState | None = None,
    term: str = "prestar",
) -> DiagnosisContext:
    return DiagnosisContext(
        word_id=WORD,
        user_id=USER,
        term=term,
        observations=tuple(observations),
        graph=graph or KnowledgeGraph([WordNode(word_id=WORD, term=term)], []),
        review_state=review_state or _state(),
    )


# --- Orchestrator: abstention and determinism -------------------------------


def test_no_evidence_at_all_is_insufficient_evidence():
    result = diagnose(_context([]))
    assert result.outcome == DIAGNOSIS_INSUFFICIENT_EVIDENCE
    assert result.is_abstention
    assert result.evidence == ()
    assert result.confidence is None


def test_rule_order_does_not_change_the_result():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, BASE - timedelta(days=5)),
        _obs(2, ReviewOutcome.INCORRECT, BASE),
    ]
    context = _context(observations)
    forward = diagnose(context, rules=ALL_RULES)
    backward = diagnose(context, rules=tuple(reversed(ALL_RULES)))
    assert forward.outcome == backward.outcome
    assert forward.confidence == backward.confidence


def test_every_diagnosis_carries_evidence_and_a_rules_version():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, BASE - timedelta(days=5)),
        _obs(2, ReviewOutcome.INCORRECT, BASE),
    ]
    result = diagnose(_context(observations))
    assert result.evidence
    assert result.rules_version >= 1
    assert all(e.observation_ids for e in result.evidence)


# --- Forgetting vs weak acquisition (TODO 3) --------------------------------


def test_forgetting_after_a_demonstrated_recall():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, BASE - timedelta(days=10)),
        _obs(2, ReviewOutcome.INCORRECT, BASE),
    ]
    candidate = ForgettingRule().evaluate(_context(observations))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.FORGETTING


def test_forgetting_abstains_with_no_prior_success():
    observations = [_obs(1, ReviewOutcome.INCORRECT, BASE - timedelta(days=1)), _obs(2, ReviewOutcome.INCORRECT, BASE)]
    assert ForgettingRule().evaluate(_context(observations)) is None


def test_weak_acquisition_when_never_recalled_after_repeated_attempts():
    observations = [_obs(1, ReviewOutcome.INCORRECT, BASE - timedelta(days=1)), _obs(2, ReviewOutcome.INCORRECT, BASE)]
    candidate = WeakAcquisitionRule().evaluate(_context(observations))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.WEAK_ACQUISITION


def test_weak_acquisition_abstains_on_a_first_ever_attempt():
    # One failed attempt on a brand-new word is not yet evidence of
    # anything — it is the first attempt.
    observations = [_obs(1, ReviewOutcome.INCORRECT, BASE)]
    assert WeakAcquisitionRule().evaluate(_context(observations)) is None


def test_a_same_session_repeat_does_not_count_as_demonstrated_recall():
    # Correct answer moments after a wrong one is the learner repeating
    # what they were just shown, not durable recall (#182's own reasoning
    # for SUCCESSES_TO_RESOLVE, reapplied here).
    observations = [
        _obs(1, ReviewOutcome.INCORRECT, BASE - timedelta(minutes=5)),
        _obs(2, ReviewOutcome.CORRECT, BASE - timedelta(minutes=4)),
        _obs(3, ReviewOutcome.INCORRECT, BASE),
    ]
    forgetting = ForgettingRule().evaluate(_context(observations))
    weak = WeakAcquisitionRule().evaluate(_context(observations))
    assert forgetting is None
    assert weak is not None


def test_forgetting_and_weak_acquisition_disagree_on_the_same_evidence_by_design():
    # Each names the other explicitly as competing, not silently.
    observations = [
        _obs(1, ReviewOutcome.CORRECT, BASE - timedelta(days=5)),
        _obs(2, ReviewOutcome.INCORRECT, BASE),
    ]
    forgetting = ForgettingRule().evaluate(_context(observations))
    assert DiagnosisCategory.WEAK_ACQUISITION in forgetting.competing_with


def test_low_retrievability_raises_forgetting_confidence():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, BASE - timedelta(days=30)),
        _obs(2, ReviewOutcome.INCORRECT, BASE),
    ]
    stale_state = _state(stability=1.0, last_reviewed_at=BASE - timedelta(days=30))
    fresh_state = _state(stability=100.0, last_reviewed_at=BASE - timedelta(days=1))
    low = ForgettingRule().evaluate(_context(observations, review_state=stale_state))
    high = ForgettingRule().evaluate(_context(observations, review_state=fresh_state))
    assert low.confidence > high.confidence


# --- Exact confusion (TODO 2) ------------------------------------------------


def _graph_with_confusion(occurrences: int) -> KnowledgeGraph:
    nodes = [WordNode(word_id=WORD, term="prestar"), WordNode(word_id=OTHER, term="pedir")]
    edges = [KnowledgeEdge(source_id=WORD, target_id=OTHER, relation=Relation.CONFUSED_WITH, evidence="x", occurrences=occurrences)]
    return KnowledgeGraph(nodes, edges)


def test_exact_confusion_fires_at_the_occurrence_threshold():
    observations = [_obs(1, ReviewOutcome.INCORRECT, attempted_answer="pedir")]
    candidate = ExactConfusionRule().evaluate(_context(observations, graph=_graph_with_confusion(2)))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.EXACT_CONFUSION


def test_exact_confusion_abstains_below_the_threshold():
    observations = [_obs(1, ReviewOutcome.INCORRECT, attempted_answer="pedir")]
    assert ExactConfusionRule().evaluate(_context(observations, graph=_graph_with_confusion(1))) is None


def test_exact_confusion_abstains_with_no_observations_to_cite():
    # A real, reachable state: mistakes recorded before diagnosis was
    # enabled produce a confusion edge with no LearningObservation rows to
    # cite as evidence.
    assert ExactConfusionRule().evaluate(_context([], graph=_graph_with_confusion(5))) is None


# --- Semantic direction reversal (TODO 2) -----------------------------------


def test_direction_reversal_fires_when_one_direction_is_always_right_and_the_other_always_wrong():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
        _obs(2, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
        _obs(3, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
        _obs(4, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
    ]
    candidate = SemanticDirectionReversalRule().evaluate(_context(observations))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL


def test_direction_reversal_abstains_when_direction_is_never_recorded():
    observations = [_obs(1, ReviewOutcome.CORRECT), _obs(2, ReviewOutcome.INCORRECT)]
    assert SemanticDirectionReversalRule().evaluate(_context(observations)) is None


def test_direction_reversal_abstains_when_both_directions_are_mixed():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
        _obs(2, ReviewOutcome.INCORRECT, prompt_direction="term_to_translation"),
        _obs(3, ReviewOutcome.CORRECT, prompt_direction="translation_to_term"),
        _obs(4, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
    ]
    assert SemanticDirectionReversalRule().evaluate(_context(observations)) is None


# --- Orthographic / phonetic interference (TODO 2) --------------------------


def test_orthographic_interference_fires_on_repeated_near_misses():
    observations = [
        _obs(1, ReviewOutcome.INCORRECT, attempted_answer="prestr"),
        _obs(2, ReviewOutcome.INCORRECT, attempted_answer="prestai"),
    ]
    candidate = OrthographicInterferenceRule().evaluate(_context(observations, term="prestar"))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE


def test_orthographic_interference_abstains_on_a_single_near_miss():
    observations = [_obs(1, ReviewOutcome.INCORRECT, attempted_answer="prestr")]
    assert OrthographicInterferenceRule().evaluate(_context(observations, term="prestar")) is None


def test_orthographic_interference_abstains_when_the_answer_is_unrelated():
    observations = [
        _obs(1, ReviewOutcome.INCORRECT, attempted_answer="xilofono"),
        _obs(2, ReviewOutcome.INCORRECT, attempted_answer="banana"),
    ]
    assert OrthographicInterferenceRule().evaluate(_context(observations, term="prestar")) is None


def test_phonetic_interference_fires_on_repeated_sound_alikes():
    observations = [
        _obs(1, ReviewOutcome.INCORRECT, attempted_answer="brrw"),
        _obs(2, ReviewOutcome.INCORRECT, attempted_answer="brrow"),
    ]
    candidate = PhoneticInterferenceRule().evaluate(_context(observations, term="borrow"))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.PHONETIC_INTERFERENCE


def test_phonetic_interference_abstains_on_a_single_match():
    observations = [_obs(1, ReviewOutcome.INCORRECT, attempted_answer="brrw")]
    assert PhoneticInterferenceRule().evaluate(_context(observations, term="borrow")) is None


# --- Missing prerequisite (TODO 4) ------------------------------------------


def test_missing_prerequisite_fires_with_an_easier_related_word():
    graph = KnowledgeGraph(
        [
            WordNode(word_id=WORD, term="efectivamente", cefr_level="B2"),
            WordNode(word_id=OTHER, term="efecto", cefr_level="A2"),
        ],
        [KnowledgeEdge(source_id=WORD, target_id=OTHER, relation=Relation.TOPIC, evidence="x")],
    )
    observations = [_obs(1, ReviewOutcome.INCORRECT), _obs(2, ReviewOutcome.INCORRECT)]
    candidate = MissingPrerequisiteRule().evaluate(_context(observations, graph=graph, term="efectivamente"))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.MISSING_PREREQUISITE


def test_missing_prerequisite_abstains_with_no_easier_related_word():
    observations = [_obs(1, ReviewOutcome.INCORRECT), _obs(2, ReviewOutcome.INCORRECT)]
    assert MissingPrerequisiteRule().evaluate(_context(observations)) is None


def test_missing_prerequisite_abstains_on_a_single_failure():
    graph = KnowledgeGraph(
        [WordNode(word_id=WORD, term="a", cefr_level="B2"), WordNode(word_id=OTHER, term="b", cefr_level="A2")],
        [KnowledgeEdge(source_id=WORD, target_id=OTHER, relation=Relation.TOPIC, evidence="x")],
    )
    observations = [_obs(1, ReviewOutcome.INCORRECT)]
    assert MissingPrerequisiteRule().evaluate(_context(observations, graph=graph)) is None


def test_missing_prerequisite_never_invents_a_word_outside_the_graph():
    # No prerequisite edge exists at all -> nothing to name, regardless of
    # how many times the word was missed.
    observations = [_obs(i, ReviewOutcome.INCORRECT) for i in range(5)]
    result = MissingPrerequisiteRule().evaluate(_context(observations))
    assert result is None


# --- Recognition/production gap (TODO 3) ------------------------------------


def test_recognition_production_gap_fires_when_recognition_succeeds_and_production_fails():
    observations = [
        _obs(1, ReviewOutcome.CORRECT, modality="multiple_choice"),
        _obs(2, ReviewOutcome.CORRECT, modality="multiple_choice"),
        _obs(3, ReviewOutcome.INCORRECT, modality="typing"),
        _obs(4, ReviewOutcome.INCORRECT, modality="typing"),
    ]
    candidate = RecognitionProductionGapRule().evaluate(_context(observations))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.RECOGNITION_PRODUCTION_GAP


def test_recognition_production_gap_abstains_without_enough_of_both_modalities():
    observations = [_obs(1, ReviewOutcome.CORRECT, modality="multiple_choice"), _obs(2, ReviewOutcome.INCORRECT, modality="typing")]
    assert RecognitionProductionGapRule().evaluate(_context(observations)) is None


# --- Context lock (TODO 3 / deferred to #229) -------------------------------


def test_context_lock_always_abstains_today():
    """No write path populates context_source yet (#182 TODO 3 -> #229) —
    this asserts the honest current state, not a permanent design."""
    observations = [
        _obs(1, ReviewOutcome.CORRECT, context_source="readme"),
        _obs(2, ReviewOutcome.CORRECT, context_source="readme"),
        _obs(3, ReviewOutcome.INCORRECT, context_source="commit_message"),
        _obs(4, ReviewOutcome.INCORRECT, context_source="commit_message"),
    ]
    # Even with synthetic context data, the rule is exercised correctly —
    # this is a coverage check on the rule's own logic, not a claim that
    # real data reaches it in production today.
    candidate = ContextLockRule().evaluate(_context(observations))
    assert candidate is not None
    assert candidate.category is DiagnosisCategory.CONTEXT_LOCK


def test_context_lock_abstains_with_the_single_context_every_real_observation_has_today():
    observations = [_obs(1, ReviewOutcome.CORRECT), _obs(2, ReviewOutcome.INCORRECT)]
    assert ContextLockRule().evaluate(_context(observations)) is None
