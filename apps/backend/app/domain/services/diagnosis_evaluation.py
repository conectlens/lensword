"""Labeled evaluation fixture and metrics harness (#180, issue #181 TODO 3).

No diagnosis engine exists yet — #183 builds it. What this module provides
is the thing #183's engine will be measured against on day one: a synthetic,
labeled dataset independent of any model output, and the four numbers the
issue's success metrics name (precision, coverage, abstention rate,
false-cause rate), computed the same way regardless of which `diagnose`
callable is plugged in.

`abstain_baseline` is the Phase 0 reference point, not a real diagnosis
strategy: it always reports `DIAGNOSIS_INSUFFICIENT_EVIDENCE`. Optimizing
for coverage alone is explicitly warned against in the issue, and a
baseline that never guesses is the honest floor — zero coverage, zero
false-cause rate, 100% abstention. #183's real rules engine has to beat
this by actually being right sometimes, not merely by answering more.
"""
from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    Diagnosis,
    LearningObservation,
)
from app.domain.value_objects import ReviewOutcome, SessionMode

# The default seed this repo's baseline numbers are quoted against. Any
# caller may pass a different one; what matters is that the *same* seed
# always produces the *same* dataset (verified in
# tests/test_diagnosis_evaluation.py), so a reported figure is a claim
# someone else can reproduce rather than a one-time measurement.
DEFAULT_SEED = 20260806

_BASE_TIME = datetime(2026, 8, 6, 9, 0)


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One labeled case: the observations a diagnosis engine would see, and
    what a correct diagnosis of them looks like.

    `must_abstain` cases exist specifically so a baseline cannot inflate its
    score by refusing to answer only on the *easy* unclear cases — this
    marks the ones abstention is the *correct* answer for, distinct from
    cases where abstaining is merely safe.
    """

    category: str
    observations: tuple[LearningObservation, ...]
    expected_outcome: str
    acceptable_alternatives: tuple[str, ...] = ()
    minimum_evidence: int = 0
    must_abstain: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    total_cases: int
    claims_made: int
    correct_claims: int
    coverage: float
    # None rather than 0.0 when no claims were made: a 0% precision score
    # and "never claimed anything to be right or wrong about" are different
    # facts, and collapsing them would let a coverage-zero baseline read as
    # having failed on precision rather than not having been evaluated on it.
    precision: float | None
    abstention_rate: float
    false_cause_rate: float

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "total_cases": self.total_cases,
            "claims_made": self.claims_made,
            "correct_claims": self.correct_claims,
            "coverage": self.coverage,
            "precision": self.precision,
            "abstention_rate": self.abstention_rate,
            "false_cause_rate": self.false_cause_rate,
        }


def _observation(word_id: int, rng: random.Random, outcome: ReviewOutcome, **overrides) -> LearningObservation:
    defaults = dict(
        observation_id=f"golden-{word_id}-{rng.getrandbits(32):08x}",
        word_id=word_id,
        user_id=1,
        outcome=outcome,
        session_mode=SessionMode.STANDARD,
        observed_at=_BASE_TIME + timedelta(minutes=rng.randint(0, 100_000)),
    )
    defaults.update(overrides)
    return LearningObservation(**defaults)


def _ordinary_forgetting_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        # Several early correct answers, then a lapse with nothing else
        # distinguishing it — no confusable pair, no direction swap, no
        # near-miss spelling. Just forgetting.
        observations = tuple(
            _observation(word_id, rng, ReviewOutcome.CORRECT) for _ in range(rng.randint(2, 5))
        ) + (_observation(word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=None),)
        cases.append(
            GoldenCase(
                category="ordinary_forgetting",
                observations=observations,
                expected_outcome="forgetting",
                minimum_evidence=1,
            )
        )
    return cases


def _exact_confusion_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    pairs = [("libre", "libro"), ("embarazada", "avergonzada"), ("actual", "actualmente")]
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        confused_with = pairs[i % len(pairs)][1]
        observations = (
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=confused_with, prompt_direction="term_to_translation"
            ),
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=confused_with, prompt_direction="term_to_translation"
            ),
        )
        cases.append(
            GoldenCase(
                category="exact_confusion",
                observations=observations,
                expected_outcome="exact_confusion",
                minimum_evidence=2,
            )
        )
    return cases


def _direction_reversal_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    # "borrow"/"lend" and similar reciprocal-verb pairs: correct in one
    # prompt direction, wrong in the other — the signature this category
    # is named for.
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        observations = (
            _observation(word_id, rng, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
            _observation(word_id, rng, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
            _observation(word_id, rng, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
        )
        cases.append(
            GoldenCase(
                category="direction_reversal",
                observations=observations,
                expected_outcome="direction_reversal",
                acceptable_alternatives=("exact_confusion",),
                minimum_evidence=2,
            )
        )
    return cases


def _spelling_near_miss_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    near_misses = ["recieve", "seperate", "definately"]
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        observations = (
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=near_misses[i % len(near_misses)]
            ),
        )
        cases.append(
            GoldenCase(
                category="spelling_near_miss",
                observations=observations,
                expected_outcome="orthographic_interference",
                minimum_evidence=1,
            )
        )
    return cases


def _skipped_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        observations = (_observation(word_id, rng, ReviewOutcome.SKIPPED),)
        cases.append(
            GoldenCase(
                category="skipped",
                observations=observations,
                expected_outcome="skipped",
                minimum_evidence=1,
            )
        )
    return cases


def _missing_prerequisite_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        # Consistently wrong from the first attempt, no partial-credit near
        # misses — distinguished from ordinary forgetting by never having
        # been answered correctly at all.
        observations = tuple(
            _observation(word_id, rng, ReviewOutcome.INCORRECT) for _ in range(rng.randint(3, 5))
        )
        cases.append(
            GoldenCase(
                category="missing_prerequisite",
                observations=observations,
                expected_outcome="missing_prerequisite",
                acceptable_alternatives=("forgetting",),
                minimum_evidence=3,
            )
        )
    return cases


def _ambiguous_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        # One lonely data point, nothing corroborating it — genuinely not
        # enough evidence for any specific cause, and the correct answer is
        # to say so rather than to pick the most plausible-sounding one.
        observations = (_observation(word_id, rng, ReviewOutcome.INCORRECT),)
        cases.append(
            GoldenCase(
                category="ambiguous",
                observations=observations,
                expected_outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
                minimum_evidence=0,
                must_abstain=True,
            )
        )
    return cases


def golden_dataset(seed: int = DEFAULT_SEED) -> tuple[GoldenCase, ...]:
    """The labeled fixture, deterministic for a given seed.

    Sizes below satisfy the issue's success metrics (at least 100 events —
    counting individual observations, not cases — and at least 20
    deliberate-abstention cases) with margin, not exactly at the floor.
    """
    rng = random.Random(seed)
    cases: list[GoldenCase] = []
    word_id = 1
    for builder, count in (
        (_ordinary_forgetting_cases, 18),
        (_exact_confusion_cases, 15),
        (_direction_reversal_cases, 15),
        (_spelling_near_miss_cases, 15),
        (_skipped_cases, 12),
        (_missing_prerequisite_cases, 12),
        (_ambiguous_cases, 25),
    ):
        batch = builder(rng, word_id, count)
        cases.extend(batch)
        word_id += count
    return tuple(cases)


def abstain_baseline(observations: Sequence[LearningObservation]) -> Diagnosis:
    """The Phase 0 reference diagnoser: never claims a cause.

    Exists to prove the evaluation harness works end-to-end and to give
    #183 a floor to beat, not as a real diagnosis strategy.
    """
    latest = max(observations, key=lambda o: o.observed_at) if observations else None
    return Diagnosis(
        word_id=latest.word_id if latest else 0,
        user_id=latest.user_id if latest else 0,
        outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
        evidence=(),
        confidence=None,
        rules_version=1,
        diagnosed_at=latest.observed_at if latest else _BASE_TIME,
    )


def evaluate(
    cases: Sequence[GoldenCase],
    diagnose: Callable[[Sequence[LearningObservation]], Diagnosis],
) -> EvaluationMetrics:
    """Run `diagnose` over every case and score it against the labels.

    A "claim" is any outcome other than the two abstention sentinels. A
    claim counts as correct when it matches the expected outcome or one of
    the case's acceptable alternatives — a real rules engine reasonably
    disagreeing between two related causes for the same evidence should
    not be scored identically to a wrong guess.
    """
    total = len(cases)
    claims = 0
    correct = 0
    abstentions = 0

    for case in cases:
        diagnosis = diagnose(case.observations)
        if diagnosis.is_abstention:
            abstentions += 1
            continue
        claims += 1
        acceptable = {case.expected_outcome, *case.acceptable_alternatives}
        if diagnosis.outcome in acceptable and not case.must_abstain:
            correct += 1

    wrong_claims = claims - correct
    return EvaluationMetrics(
        total_cases=total,
        claims_made=claims,
        correct_claims=correct,
        coverage=claims / total if total else 0.0,
        precision=(correct / claims) if claims else None,
        abstention_rate=abstentions / total if total else 0.0,
        false_cause_rate=wrong_claims / total if total else 0.0,
    )
