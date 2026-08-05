"""Golden fixture and evaluation harness (#180, issue #181 TODO 3).

Verify steps from the issue: the baseline report has the four named
metrics, the fixture meets the size floors, and the numbers are
reproducible from a fixed seed rather than measured once and quoted
forever.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    Diagnosis,
    LearningObservation,
)
from app.domain.services.diagnosis_evaluation import (
    DEFAULT_SEED,
    GoldenCase,
    abstain_baseline,
    evaluate,
    golden_dataset,
)
from app.domain.value_objects import ReviewOutcome, SessionMode

NOW = datetime(2026, 8, 6, 9, 0)


def test_the_fixture_meets_the_issues_size_floor():
    dataset = golden_dataset()
    total_observations = sum(len(case.observations) for case in dataset)
    assert total_observations >= 100

    abstention_cases = [c for c in dataset if c.must_abstain]
    assert len(abstention_cases) >= 20


def test_the_fixture_covers_every_named_category():
    dataset = golden_dataset()
    categories = {case.category for case in dataset}
    assert categories == {
        "ordinary_forgetting",
        "exact_confusion",
        "direction_reversal",
        "spelling_near_miss",
        "skipped",
        "missing_prerequisite",
        "ambiguous",
    }


def test_the_same_seed_reproduces_the_identical_dataset():
    first = golden_dataset(seed=DEFAULT_SEED)
    second = golden_dataset(seed=DEFAULT_SEED)
    assert first == second


def test_a_different_seed_still_meets_the_size_floor():
    # Reproducibility does not mean hardcoded to one seed's specific output —
    # any seed must still produce a valid fixture.
    dataset = golden_dataset(seed=999)
    assert sum(len(c.observations) for c in dataset) >= 100


def _obs(word_id: int, outcome: ReviewOutcome) -> LearningObservation:
    return LearningObservation(
        observation_id=f"o-{word_id}",
        word_id=word_id,
        user_id=1,
        outcome=outcome,
        session_mode=SessionMode.STANDARD,
        observed_at=NOW,
    )


def test_the_always_abstain_baseline_scores_zero_coverage_and_full_abstention():
    # The Phase 0 reference point: proves the harness end-to-end without
    # claiming to be a real diagnosis strategy.
    dataset = golden_dataset()
    metrics = evaluate(dataset, abstain_baseline)

    assert metrics.total_cases == len(dataset)
    assert metrics.claims_made == 0
    assert metrics.coverage == 0.0
    assert metrics.precision is None
    assert metrics.abstention_rate == 1.0
    assert metrics.false_cause_rate == 0.0


def test_evaluate_scores_a_perfect_diagnoser_against_a_small_fixture():
    cases = (
        GoldenCase(
            category="ordinary_forgetting",
            observations=(_obs(1, ReviewOutcome.INCORRECT),),
            expected_outcome="forgetting",
        ),
        GoldenCase(
            category="ambiguous",
            observations=(_obs(2, ReviewOutcome.INCORRECT),),
            expected_outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
            must_abstain=True,
        ),
    )

    def perfect(observations):
        word_id = observations[0].word_id
        outcome = "forgetting" if word_id == 1 else DIAGNOSIS_INSUFFICIENT_EVIDENCE
        return Diagnosis(
            word_id=word_id, user_id=1, outcome=outcome, evidence=(),
            confidence=None, rules_version=1, diagnosed_at=NOW,
        )

    metrics = evaluate(cases, perfect)
    assert metrics.total_cases == 2
    assert metrics.claims_made == 1
    assert metrics.correct_claims == 1
    assert metrics.coverage == 0.5
    assert metrics.precision == 1.0
    assert metrics.abstention_rate == 0.5
    assert metrics.false_cause_rate == 0.0


def test_evaluate_does_not_credit_a_claim_on_a_must_abstain_case():
    # A confident wrong guess on a case that should have been abstained is
    # exactly the false-cause failure mode this metric exists to catch —
    # even if the guessed string happens to match `expected_outcome`.
    cases = (
        GoldenCase(
            category="ambiguous",
            observations=(_obs(1, ReviewOutcome.INCORRECT),),
            expected_outcome="forgetting",
            must_abstain=True,
        ),
    )

    def overconfident(observations):
        return Diagnosis(
            word_id=1, user_id=1, outcome="forgetting", evidence=(),
            confidence=0.9, rules_version=1, diagnosed_at=NOW,
        )

    metrics = evaluate(cases, overconfident)
    assert metrics.claims_made == 1
    assert metrics.correct_claims == 0
    assert metrics.false_cause_rate == 1.0
