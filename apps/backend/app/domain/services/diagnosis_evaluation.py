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
from app.domain.services.diagnosis_engine import DiagnosisContext, diagnose as run_diagnosis_engine
from app.domain.services.knowledge_graph import KnowledgeEdge, KnowledgeGraph, Relation, WordNode
from app.domain.value_objects import ReviewOutcome, ReviewState, SessionMode

# The default seed this repo's baseline numbers are quoted against. Any
# caller may pass a different one; what matters is that the *same* seed
# always produces the *same* dataset (verified in
# tests/test_diagnosis_evaluation.py), so a reported figure is a claim
# someone else can reproduce rather than a one-time measurement.
DEFAULT_SEED = 20260806

_BASE_TIME = datetime(2026, 8, 6, 9, 0)

# A neutral, no-signal review state for cases that don't specifically
# fixture one — FSRS retrievability then never pushes a rule's confidence
# either way, which is the correct default for a case whose label doesn't
# depend on it.
_NEUTRAL_REVIEW_STATE = ReviewState(
    strength=50, ease_factor=2.5, interval_days=5, repetitions=1, due_at=_BASE_TIME,
    last_reviewed_at=None, stability=None,
)


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
    # #183: a real engine needs more than a bare observation stream for
    # some categories (exact confusion and missing prerequisite both read
    # a KnowledgeGraph; none of the rules read review_state for anything
    # but a confidence adjustment). `None` means "no graph-based evidence
    # this case needs" — resolved to an empty graph at evaluation time
    # rather than during construction, so this stays a plain frozen
    # dataclass with no post-init mutation.
    graph: KnowledgeGraph | None = None
    review_state: ReviewState = _NEUTRAL_REVIEW_STATE
    term: str = "palabra"


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
        # near-miss spelling. Just forgetting. The lapse must actually be
        # chronologically last: ForgettingRule reads "latest observation is
        # incorrect", and each `_observation` call otherwise draws an
        # independent random timestamp, so without pinning this the lapse
        # would land before an earlier "correct" by pure chance about as
        # often as after it.
        correct_observations = tuple(
            _observation(word_id, rng, ReviewOutcome.CORRECT) for _ in range(rng.randint(2, 5))
        )
        lapse_time = max(o.observed_at for o in correct_observations) + timedelta(days=rng.randint(1, 30))
        observations = correct_observations + (
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=None, observed_at=lapse_time
            ),
        )
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
        # A synthetic id for the confused-with word, offset well clear of
        # every real word_id this dataset ever allocates, so it can never
        # collide with another case's own word.
        other_id = 1_000_000 + word_id
        term, confused_with = pairs[i % len(pairs)]
        observations = (
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=confused_with, prompt_direction="term_to_translation"
            ),
            _observation(
                word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=confused_with, prompt_direction="term_to_translation"
            ),
        )
        graph = KnowledgeGraph(
            [WordNode(word_id=word_id, term=term), WordNode(word_id=other_id, term=confused_with)],
            [KnowledgeEdge(source_id=word_id, target_id=other_id, relation=Relation.CONFUSED_WITH, evidence="x", occurrences=2)],
        )
        cases.append(
            GoldenCase(
                category="exact_confusion",
                observations=observations,
                expected_outcome="exact_confusion",
                minimum_evidence=2,
                graph=graph,
                term=term,
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
        # Two each way, not one-and-two: SemanticDirectionReversalRule
        # requires >= 2 observations in *both* the consistently-right and
        # consistently-wrong direction before it treats the split as
        # meaningful rather than noise (#183 TODO 2's repeated-evidence bar).
        observations = (
            _observation(word_id, rng, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
            _observation(word_id, rng, ReviewOutcome.CORRECT, prompt_direction="term_to_translation"),
            _observation(word_id, rng, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
            _observation(word_id, rng, ReviewOutcome.INCORRECT, prompt_direction="translation_to_term"),
        )
        cases.append(
            GoldenCase(
                category="direction_reversal",
                observations=observations,
                # Matches DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL's
                # real string value now that #183 closes the taxonomy this
                # fixture was written ahead of.
                expected_outcome="semantic_direction_reversal",
                acceptable_alternatives=("exact_confusion",),
                minimum_evidence=2,
            )
        )
    return cases


def _spelling_near_miss_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    # (correct spelling, a near-miss of it) — the pair a real near-miss
    # check needs; the fixture predates that distinction, so this also
    # fixes a defect where every case compared the wrong answer against
    # the case's own default term instead of its actual correct spelling.
    # "receive"/"recieve" was tried first and dropped: it is a letter
    # transposition, which costs 2 under plain Levenshtein — over this
    # rule's own near-miss threshold for a 7-letter word — so it never
    # actually exercised OrthographicInterferenceRule at all, only
    # PhoneticInterferenceRule (matching consonant skeleton). "occurred"/
    # "occured" is a true single-character deletion, within the threshold,
    # and its skeleton diverges (double vs single 'r') so it does not also
    # trigger the phonetic rule.
    pairs = [("occurred", "occured"), ("separate", "seperate"), ("definitely", "definately")]
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        correct, near_miss = pairs[i % len(pairs)]
        # Two, not one: OrthographicInterferenceRule requires repeated
        # evidence before it fires (#183 TODO 2), matching the same bar a
        # single typo must not clear.
        observations = (
            _observation(word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=near_miss),
            _observation(word_id, rng, ReviewOutcome.INCORRECT, attempted_answer=near_miss),
        )
        cases.append(
            GoldenCase(
                category="spelling_near_miss",
                observations=observations,
                expected_outcome="orthographic_interference",
                minimum_evidence=2,
                term=correct,
            )
        )
    return cases


def _skipped_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        # A single skip with nothing else on record is not evidence of any
        # named cause — genuinely INSUFFICIENT_EVIDENCE, not its own
        # taxonomy member (the closed set in #183 has no "skipped" cause;
        # this fixture predates that taxonomy and originally expected one).
        observations = (_observation(word_id, rng, ReviewOutcome.SKIPPED),)
        cases.append(
            GoldenCase(
                category="skipped",
                observations=observations,
                expected_outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
                minimum_evidence=1,
                must_abstain=True,
            )
        )
    return cases


def _missing_prerequisite_cases(rng: random.Random, start_word_id: int, count: int) -> list[GoldenCase]:
    cases = []
    for i in range(count):
        word_id = start_word_id + i
        prerequisite_id = 2_000_000 + word_id
        # Consistently wrong from the first attempt, no partial-credit near
        # misses — distinguished from ordinary forgetting by never having
        # been answered correctly at all.
        observations = tuple(
            _observation(word_id, rng, ReviewOutcome.INCORRECT) for _ in range(rng.randint(3, 5))
        )
        graph = KnowledgeGraph(
            [
                WordNode(word_id=word_id, term="efectivamente", cefr_level="B2"),
                WordNode(word_id=prerequisite_id, term="efecto", cefr_level="A2"),
            ],
            [
                KnowledgeEdge(
                    source_id=word_id, target_id=prerequisite_id, relation=Relation.TOPIC, evidence="x"
                )
            ],
        )
        cases.append(
            GoldenCase(
                category="missing_prerequisite",
                observations=observations,
                graph=graph,
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


def abstain_baseline(case: GoldenCase) -> Diagnosis:
    """The Phase 0 reference diagnoser: never claims a cause.

    Existed to prove the evaluation harness works end-to-end and to give
    #183 a floor to beat, not as a real diagnosis strategy. Kept as the
    reference point now that #183's real engine (`real_engine` below) is
    the one actually measured against the release gate.
    """
    observations = case.observations
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


def real_engine(case: GoldenCase) -> Diagnosis:
    """#183: the actual rules engine, evaluated against the same fixture
    the Phase 0 baseline was. Builds the `DiagnosisContext` a real account
    would produce from the case's own observations/graph/review_state."""
    if not case.observations:
        context_word_id, context_user_id = 0, 0
    else:
        context_word_id, context_user_id = case.observations[0].word_id, case.observations[0].user_id
    context = DiagnosisContext(
        word_id=context_word_id,
        user_id=context_user_id,
        term=case.term,
        observations=case.observations,
        graph=case.graph or KnowledgeGraph([], []),
        review_state=case.review_state,
    )
    return run_diagnosis_engine(context)


def evaluate(
    cases: Sequence[GoldenCase],
    diagnose: Callable[[GoldenCase], Diagnosis],
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
        diagnosis = diagnose(case)
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


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    """Per-category breakdown (#183 TODO 6). `support` is how many golden
    cases are genuinely labeled this category — not how many the engine
    claimed it for."""

    category: str
    support: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None


def evaluate_per_class(cases: Sequence[GoldenCase], diagnose: Callable[[GoldenCase], Diagnosis]) -> dict[str, ClassMetrics]:
    categories = sorted({c.expected_outcome for c in cases} - {DIAGNOSIS_INSUFFICIENT_EVIDENCE})
    true_positives = {c: 0 for c in categories}
    false_positives = {c: 0 for c in categories}
    false_negatives = {c: 0 for c in categories}
    support = {c: 0 for c in categories}

    for case in cases:
        if case.expected_outcome in support:
            support[case.expected_outcome] += 1

        diagnosis = diagnose(case)
        claimed = None if diagnosis.is_abstention else diagnosis.outcome
        acceptable = {case.expected_outcome, *case.acceptable_alternatives}

        if claimed is not None and claimed in false_positives:
            if claimed in acceptable and not case.must_abstain:
                true_positives[claimed] += 1
            else:
                false_positives[claimed] += 1

        expected_was_matched = claimed is not None and claimed in acceptable and not case.must_abstain
        if case.expected_outcome in false_negatives and not expected_was_matched:
            false_negatives[case.expected_outcome] += 1

    return {
        category: ClassMetrics(
            category=category,
            support=support[category],
            true_positives=true_positives[category],
            false_positives=false_positives[category],
            false_negatives=false_negatives[category],
            precision=(
                true_positives[category] / (true_positives[category] + false_positives[category])
                if (true_positives[category] + false_positives[category])
                else None
            ),
            recall=(
                true_positives[category] / (true_positives[category] + false_negatives[category])
                if (true_positives[category] + false_negatives[category])
                else None
            ),
        )
        for category in categories
    }


# #183 TODO 6's release gate — the one threshold in this whole epic that
# the issue actually states a number for (#181 and #182's equivalents
# named a gate without a number to gate against).
FALSE_CAUSE_RATE_GATE = 0.05


def passes_release_gate(metrics: EvaluationMetrics) -> bool:
    return metrics.false_cause_rate <= FALSE_CAUSE_RATE_GATE
