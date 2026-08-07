"""Deterministic failure diagnosis engine (#180, issue #183).

Converts a word's own observation history into a conservative, explainable
`Diagnosis` — never by asking a model, always by evaluating a closed set of
rules against evidence the account itself produced. Preferring abstention
over a plausible-sounding guess is the whole point: `UNKNOWN` and
`INSUFFICIENT_EVIDENCE` are first-class outcomes (#181), not failure modes
of this engine, and every rule below is written to return `None` rather
than stretch its own evidence to cover a case it cannot actually support.

Nothing here calls an AI provider. Confidence, sample size, and evidence
counts are computed from `LearningObservation` and `KnowledgeGraph` data
only (ADR 0007).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Protocol, Sequence

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    DIAGNOSIS_UNKNOWN,
    Diagnosis,
    DiagnosisEvidence,
    LearningObservation,
)
from app.domain.services.knowledge_graph import KnowledgeGraph
from app.domain.services.spaced_repetition import FSRSScheduler
from app.domain.value_objects import ReviewOutcome, ReviewState, utcnow


class DiagnosisCategory(str, Enum):
    """The closed taxonomy issue #183 TODO 0 asks for. Closed on purpose: a
    free-form string here would let a rule invent a cause nothing else in
    the system knows how to act on."""

    FORGETTING = "forgetting"
    EXACT_CONFUSION = "exact_confusion"
    SEMANTIC_DIRECTION_REVERSAL = "semantic_direction_reversal"
    ORTHOGRAPHIC_INTERFERENCE = "orthographic_interference"
    PHONETIC_INTERFERENCE = "phonetic_interference"
    MISSING_PREREQUISITE = "missing_prerequisite"
    RECOGNITION_PRODUCTION_GAP = "recognition_production_gap"
    CONTEXT_LOCK = "context_lock"
    WEAK_ACQUISITION = "weak_acquisition"
    # Same string values as the #181 sentinels, so Diagnosis.outcome and
    # Diagnosis.is_abstention keep working unmodified now that this phase
    # closes the taxonomy around them.
    UNKNOWN = DIAGNOSIS_UNKNOWN
    INSUFFICIENT_EVIDENCE = DIAGNOSIS_INSUFFICIENT_EVIDENCE


# The rules engine version. Bumped whenever a rule's *logic* changes in a
# way that could change its output for the same evidence — not for
# comments, refactors, or new rules that do not touch existing ones.
RULES_VERSION = 1

# Two observations of the same word are "the same session" (a same-session
# repeat proves nothing about durable recall) below this gap, and separate
# attempts at or above it. Chosen as an hour: shorter than that is someone
# re-testing themselves moments after seeing the answer; a spaced-repetition
# app's own review cadence is measured in days, not minutes.
_MEANINGFUL_GAP = timedelta(hours=1)

# A confusion pair needs to have actually recurred, not happened once, to
# outrank a plain wrong-answer explanation — the same "repeated behavioral
# evidence" bar TODO 2 sets for orthographic/phonetic candidates.
_MIN_CONFUSION_OCCURRENCES = 2
_MIN_NEAR_MISS_OCCURRENCES = 2


@dataclass(frozen=True, slots=True)
class DiagnosisCandidate:
    """One rule's output before conflict resolution picks a winner.

    Distinct from the persisted `Diagnosis` (#181): a candidate is one
    rule's opinion, not yet the engine's final answer, and carries the
    extra bookkeeping (`sample_size`, `competing_with`) TODO 1 asks a rule
    to report but that only matters during resolution, not after.
    """

    category: DiagnosisCategory
    confidence: float
    evidence: tuple[DiagnosisEvidence, ...]
    sample_size: int
    # Other categories this same evidence could also plausibly support,
    # named explicitly by the rule that noticed the overlap — TODO 1's
    # "prevent multiple rules from silently claiming the same evidence as
    # independent proof."
    competing_with: tuple[DiagnosisCategory, ...] = ()
    # The other word of a confusion pair, named only by ExactConfusionRule
    # (#185 TODO 1).
    related_word_id: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"DiagnosisCandidate.confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True, slots=True)
class DiagnosisContext:
    """Everything a rule may consult, gathered once by the orchestrator so
    no rule reaches into a repository itself (keeping every rule a pure
    function, testable under a fixed clock with no I/O)."""

    word_id: int
    user_id: int
    term: str
    # This word's own observations, any order — rules sort what they need.
    observations: tuple[LearningObservation, ...]
    graph: KnowledgeGraph
    review_state: ReviewState


class DiagnosisRule(Protocol):
    category: DiagnosisCategory

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        """Return a candidate if this rule's own conditions are met, or
        `None` to abstain. Abstaining is a normal outcome, not an error —
        most rules will not fire for most words."""
        ...


def _recent_first(observations: Sequence[LearningObservation]) -> list[LearningObservation]:
    return sorted(observations, key=lambda o: o.observed_at, reverse=True)


def _had_prior_demonstrated_recall(observations: Sequence[LearningObservation], before) -> bool:
    """A CORRECT answer that was not merely a same-session repeat of a
    prior attempt — the bar TODO 3 sets for "stable delayed recall has
    ever been demonstrated." """
    correct = [o for o in observations if o.outcome is ReviewOutcome.CORRECT and o.observed_at < before]
    if not correct:
        return False
    others = [o for o in observations if o.observed_at < before]
    for c in correct:
        preceding = [o for o in others if o.observed_at < c.observed_at]
        if not preceding:
            # The very first attempt on this word was correct: a cold,
            # unprimed recall, which counts on its own.
            return True
        if c.observed_at - max(o.observed_at for o in preceding) >= _MEANINGFUL_GAP:
            return True
    return False


class ForgettingRule:
    """TODO 3: loss after prior demonstrated recall, not merely an
    incorrect answer. FSRS retrievability corroborates rather than gates
    the diagnosis: a low predicted retrievability at the moment of failure
    is consistent with genuine forgetting, so it raises confidence, but a
    demonstrated-recall lapse is still forgetting even when retrievability
    looked fine — FSRS's own estimate can be wrong in either direction,
    which is exactly why this rule is not asked to trust it alone."""

    category = DiagnosisCategory.FORGETTING

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        observations = _recent_first(context.observations)
        if not observations or observations[0].outcome is ReviewOutcome.CORRECT:
            return None
        latest = observations[0]
        if not _had_prior_demonstrated_recall(context.observations, latest.observed_at):
            return None

        retrievability = FSRSScheduler.retrievability(context.review_state)
        confidence = 0.7 + (0.15 if retrievability < 0.5 else 0.0)
        evidence = [
            DiagnosisEvidence(
                kind="lapse_after_demonstrated_recall",
                observation_ids=(latest.observation_id,),
                weight=0.7,
                description="incorrect after at least one prior recall separated by a meaningful gap",
            ),
        ]
        if retrievability < 0.5:
            evidence.append(
                DiagnosisEvidence(
                    kind="low_predicted_retrievability",
                    observation_ids=(latest.observation_id,),
                    weight=0.15,
                    description=f"FSRS estimated retrievability {retrievability:.2f} at the time of this answer",
                )
            )

        return DiagnosisCandidate(
            category=self.category,
            confidence=min(confidence, 0.95),
            evidence=tuple(evidence),
            sample_size=len(observations),
            competing_with=(DiagnosisCategory.WEAK_ACQUISITION,),
        )


class WeakAcquisitionRule:
    """TODO 3: failure before stable delayed recall has ever been
    demonstrated — the complement of ForgettingRule, not a separate
    guess."""

    category = DiagnosisCategory.WEAK_ACQUISITION

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        observations = _recent_first(context.observations)
        if not observations or observations[0].outcome is ReviewOutcome.CORRECT:
            return None
        latest = observations[0]
        if _had_prior_demonstrated_recall(context.observations, latest.observed_at):
            return None
        # A single failed attempt on a brand-new word is not yet evidence
        # of weak acquisition — it is just the first attempt. Require at
        # least one prior attempt (of any outcome) to distinguish "still
        # learning it" from "has failed repeatedly without ever landing it."
        prior = [o for o in observations if o.observed_at < latest.observed_at]
        if not prior:
            return None

        return DiagnosisCandidate(
            category=self.category,
            confidence=0.65,
            evidence=(
                DiagnosisEvidence(
                    kind="no_demonstrated_recall",
                    observation_ids=tuple(o.observation_id for o in observations[: len(prior) + 1]),
                    weight=0.65,
                    description="repeated failure with no prior correct answer separated by a meaningful gap",
                ),
            ),
            sample_size=len(observations),
            competing_with=(DiagnosisCategory.FORGETTING,),
        )


class ExactConfusionRule:
    """TODO 2: reuse CONFUSED_WITH edges from the knowledge graph (#134,
    #138) rather than re-deriving confusion from raw observations —
    KnowledgeGraph already applies the "exact lookup, not similarity
    guessing" rule this diagnosis needs."""

    category = DiagnosisCategory.EXACT_CONFUSION

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        confused = [e for e in context.graph.confused_with(context.word_id) if e.occurrences >= _MIN_CONFUSION_OCCURRENCES]
        if not confused:
            return None
        # The confusion edge is derived from MistakeEvent rows, a separate
        # data source from LearningObservation (mistakes are recorded
        # unconditionally; observations only when diagnosis is enabled) —
        # an account with confusion history but no observation history yet
        # is a real, reachable state, not a bug. DiagnosisEvidence requires
        # at least one observation id to cite, so this rule abstains rather
        # than fabricate one, matching "prefer abstention" over faking the
        # evidence trail.
        if not context.observations:
            return None
        strongest = max(confused, key=lambda e: e.strength)
        other_id = strongest.target_id if strongest.source_id == context.word_id else strongest.source_id
        recent_ids = tuple(o.observation_id for o in _recent_first(context.observations)[: strongest.occurrences])

        return DiagnosisCandidate(
            category=self.category,
            confidence=min(0.6 + 0.1 * (strongest.occurrences - _MIN_CONFUSION_OCCURRENCES), 0.95),
            evidence=(
                DiagnosisEvidence(
                    kind="confused_with_edge",
                    observation_ids=recent_ids or (context.observations[0].observation_id,),
                    # KnowledgeEdge.strength is a *ranking* weight, capped
                    # at 2x its base rather than at 1.0 — CONFUSED_WITH's
                    # base is already the taxonomy's maximum (1.0), so a
                    # repeated confusion's strength can exceed 1.0.
                    # DiagnosisEvidence.weight is a different, bounded
                    # scale; clamped here rather than left to violate it.
                    weight=min(strongest.strength, 1.0),
                    description=f"answered word {other_id} instead {strongest.occurrences} time(s)",
                ),
            ),
            sample_size=strongest.occurrences,
            related_word_id=other_id,
        )


def _direction_split(observations: Sequence[LearningObservation]) -> dict[str, list[LearningObservation]]:
    by_direction: dict[str, list[LearningObservation]] = {}
    for o in observations:
        if o.prompt_direction:
            by_direction.setdefault(o.prompt_direction, []).append(o)
    return by_direction


class SemanticDirectionReversalRule:
    """TODO 2: only when both directions and prompt semantics are known —
    reads `LearningObservation.prompt_direction` (#182) directly, since a
    KnowledgeGraph edge alone does not carry which direction a card was
    asked in."""

    category = DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        by_direction = _direction_split(context.observations)
        if len(by_direction) < 2:
            return None

        summaries = {
            direction: (
                sum(1 for o in obs if o.outcome is ReviewOutcome.CORRECT),
                len(obs),
            )
            for direction, obs in by_direction.items()
        }
        # One direction consistently right, the other consistently wrong —
        # not just noisier in one direction.
        strong_directions = [d for d, (correct, total) in summaries.items() if total >= 2 and correct == total]
        weak_directions = [d for d, (correct, total) in summaries.items() if total >= 2 and correct == 0]
        if not strong_directions or not weak_directions:
            return None

        weak_obs = by_direction[weak_directions[0]]
        strong_obs = by_direction[strong_directions[0]]
        return DiagnosisCandidate(
            category=self.category,
            confidence=0.6,
            evidence=(
                DiagnosisEvidence(
                    kind="direction_asymmetry",
                    observation_ids=tuple(o.observation_id for o in weak_obs + strong_obs),
                    weight=0.6,
                    description=(
                        f"correct every time asked '{strong_directions[0]}', "
                        f"wrong every time asked '{weak_directions[0]}'"
                    ),
                ),
            ),
            sample_size=len(weak_obs) + len(strong_obs),
            competing_with=(DiagnosisCategory.EXACT_CONFUSION,),
        )


def _levenshtein(a: str, b: str) -> int:
    """Small, dependency-free edit distance — this codebase has no fuzzy-
    matching library, and a near-miss check does not need one."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
        previous = current
    return previous[-1]


def _near_misses(context: DiagnosisContext) -> list[LearningObservation]:
    term = context.term.strip().casefold()
    out = []
    for o in context.observations:
        if o.outcome is ReviewOutcome.CORRECT or not o.attempted_answer:
            continue
        attempt = o.attempted_answer.strip().casefold()
        if attempt == term:
            continue
        # Bounded by length so a near-miss check on "a" does not match
        # half the alphabet, and scaled so longer words tolerate more
        # single-character slips proportionally.
        if _levenshtein(attempt, term) <= max(1, len(term) // 4):
            out.append(o)
    return out


class OrthographicInterferenceRule:
    """TODO 2: near-miss spelling, generated only as a hypothesis and
    surfaced only once it has recurred — a single typo is a typo, not a
    diagnosis."""

    category = DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        misses = _near_misses(context)
        if len(misses) < _MIN_NEAR_MISS_OCCURRENCES:
            return None
        return DiagnosisCandidate(
            category=self.category,
            confidence=min(0.5 + 0.1 * (len(misses) - _MIN_NEAR_MISS_OCCURRENCES), 0.85),
            evidence=(
                DiagnosisEvidence(
                    kind="repeated_near_miss_spelling",
                    observation_ids=tuple(o.observation_id for o in misses),
                    weight=0.5,
                    description=f"{len(misses)} answer(s) within edit distance of the correct spelling",
                ),
            ),
            sample_size=len(misses),
            competing_with=(DiagnosisCategory.PHONETIC_INTERFERENCE,),
        )


_VOWELS = set("aeiou")


def _consonant_skeleton(term: str) -> str:
    """A deliberately crude phonetic simplification — vowels dropped,
    nothing more. Real phonetic algorithms (Soundex, Metaphone) are not a
    dependency this codebase has, and this diagnosis already requires
    repeated evidence before it can fire (TODO 2), which is where its
    conservatism actually comes from, not from the skeleton's precision.
    """
    return "".join(ch for ch in term.strip().casefold() if ch not in _VOWELS)


class PhoneticInterferenceRule:
    """TODO 2: sound-alike answers, generated only as a hypothesis and
    surfaced only once it has recurred — same evidentiary bar as
    orthographic interference, over a cruder, explicitly approximate
    similarity measure (see `_consonant_skeleton`)."""

    category = DiagnosisCategory.PHONETIC_INTERFERENCE

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        term_skeleton = _consonant_skeleton(context.term)
        if not term_skeleton:
            return None
        matches = []
        for o in context.observations:
            if o.outcome is ReviewOutcome.CORRECT or not o.attempted_answer:
                continue
            attempt = o.attempted_answer.strip().casefold()
            if attempt == context.term.strip().casefold():
                continue
            skeleton = _consonant_skeleton(attempt)
            if skeleton and skeleton == term_skeleton and attempt[:1] == context.term.strip().casefold()[:1]:
                matches.append(o)
        if len(matches) < _MIN_NEAR_MISS_OCCURRENCES:
            return None
        return DiagnosisCandidate(
            category=self.category,
            confidence=0.5,
            evidence=(
                DiagnosisEvidence(
                    kind="repeated_sound_alike_answer",
                    observation_ids=tuple(o.observation_id for o in matches),
                    weight=0.5,
                    description=f"{len(matches)} answer(s) sharing a first letter and consonant pattern",
                ),
            ),
            sample_size=len(matches),
            competing_with=(DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE,),
        )


class MissingPrerequisiteRule:
    """TODO 4: explicit prerequisite graph edges first (#203); a CEFR-only
    "easier related word" is a suggestion this rule does not treat as
    proof on its own, and repeated failure is required before naming the
    cause — a prerequisite word that happens to also be weak is not
    itself evidence unless this word keeps failing too."""

    category = DiagnosisCategory.MISSING_PREREQUISITE

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        incorrect = [o for o in context.observations if o.outcome is not ReviewOutcome.CORRECT]
        if len(incorrect) < 2:
            return None
        prerequisite_ids = context.graph.prerequisites(context.word_id)
        if not prerequisite_ids:
            return None

        return DiagnosisCandidate(
            category=self.category,
            confidence=0.45,
            evidence=(
                DiagnosisEvidence(
                    kind="repeated_failure_with_easier_prerequisite",
                    observation_ids=tuple(o.observation_id for o in incorrect),
                    weight=0.45,
                    description=f"related word(s) {prerequisite_ids} sit at an easier level and are not yet mastered",
                ),
            ),
            sample_size=len(incorrect),
        )


class RecognitionProductionGapRule:
    """TODO 3/#182: consistently correct in a recognition-style modality
    (multiple choice) and consistently wrong in a production-style one
    (typing/speaking) — reads `LearningObservation.modality` (#182)."""

    category = DiagnosisCategory.RECOGNITION_PRODUCTION_GAP

    _RECOGNITION = frozenset({"multiple_choice"})
    _PRODUCTION = frozenset({"typing", "speaking"})

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        recognition = [o for o in context.observations if o.modality in self._RECOGNITION]
        production = [o for o in context.observations if o.modality in self._PRODUCTION]
        if len(recognition) < 2 or len(production) < 2:
            return None
        recognition_correct = sum(1 for o in recognition if o.outcome is ReviewOutcome.CORRECT)
        production_correct = sum(1 for o in production if o.outcome is ReviewOutcome.CORRECT)
        if recognition_correct != len(recognition) or production_correct != 0:
            return None

        return DiagnosisCandidate(
            category=self.category,
            confidence=0.55,
            evidence=(
                DiagnosisEvidence(
                    kind="modality_asymmetry",
                    observation_ids=tuple(o.observation_id for o in recognition + production),
                    weight=0.55,
                    description="correct every time in multiple choice, wrong every time typing or speaking",
                ),
            ),
            sample_size=len(recognition) + len(production),
        )


class ContextLockRule:
    """TODO 3/#182: known in one context, not another. Structurally always
    abstains today — `LearningObservation.context_source` has no real
    write path yet (#182 TODO 3 was split into the #229 follow-up: a
    bounded-fingerprint context model needs a privacy/product decision
    this diagnosis engine should not make on its own). Kept as its own
    rule, not deleted, so #229 only has to populate the field — this
    rule's condition already matches what real context data would need.
    """

    category = DiagnosisCategory.CONTEXT_LOCK

    def evaluate(self, context: DiagnosisContext) -> DiagnosisCandidate | None:
        sources = {o.context_source for o in context.observations if o.context_source}
        if len(sources) < 2:
            return None
        by_source: dict[str, list[LearningObservation]] = {}
        for o in context.observations:
            if o.context_source:
                by_source.setdefault(o.context_source, []).append(o)
        strong = [s for s, obs in by_source.items() if len(obs) >= 2 and all(o.outcome is ReviewOutcome.CORRECT for o in obs)]
        weak = [s for s, obs in by_source.items() if len(obs) >= 2 and all(o.outcome is not ReviewOutcome.CORRECT for o in obs)]
        if not strong or not weak:
            return None
        return DiagnosisCandidate(
            category=self.category,
            confidence=0.5,
            evidence=(
                DiagnosisEvidence(
                    kind="context_asymmetry",
                    observation_ids=tuple(o.observation_id for src in (strong[0], weak[0]) for o in by_source[src]),
                    weight=0.5,
                    description=f"correct sourced from '{strong[0]}', wrong sourced from '{weak[0]}'",
                ),
            ),
            sample_size=sum(len(by_source[s]) for s in (strong[0], weak[0])),
        )


ALL_RULES: tuple[DiagnosisRule, ...] = (
    ExactConfusionRule(),
    SemanticDirectionReversalRule(),
    OrthographicInterferenceRule(),
    PhoneticInterferenceRule(),
    MissingPrerequisiteRule(),
    RecognitionProductionGapRule(),
    ContextLockRule(),
    ForgettingRule(),
    WeakAcquisitionRule(),
)


# FORGETTING and WEAK_ACQUISITION describe a *pattern* in outcomes over
# time and fire on almost any repeated failure with no other explanation —
# by design, they are the fallback when nothing more specific applies, not
# a diagnosis that should outrank one. Without this tier, their moderate,
# broadly-applicable confidence regularly beat a narrower, more specific
# rule's evidence purely because it fired on more of the golden fixture,
# which is exactly the "most narratively attractive cause" failure mode
# the issue's own success metrics warn against.
_SPECIFIC_MECHANISMS = frozenset(
    {
        DiagnosisCategory.EXACT_CONFUSION,
        DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL,
        DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE,
        DiagnosisCategory.PHONETIC_INTERFERENCE,
        DiagnosisCategory.MISSING_PREREQUISITE,
        DiagnosisCategory.RECOGNITION_PRODUCTION_GAP,
        DiagnosisCategory.CONTEXT_LOCK,
    }
)


def _resolve(candidates: list[DiagnosisCandidate]) -> DiagnosisCandidate:
    """TODO 1's conflict-resolution policy: a specific mechanism (a named
    confusion, a spelling/sound near-miss, a missing prerequisite, a
    modality or context asymmetry) wins over the generic forgetting/weak-
    acquisition pattern rules whenever one fired, regardless of confidence
    — falling back to the pattern rules only when nothing more specific
    explains the failure. Within a tier, highest confidence wins; ties are
    broken by category name for determinism (never by which rule happened
    to run first — `ALL_RULES`'s own order must not be able to change the
    result, which `test_rule_order_does_not_change_the_result` checks
    directly by shuffling it).
    """
    specific = [c for c in candidates if c.category in _SPECIFIC_MECHANISMS]
    pool = specific or candidates
    return sorted(pool, key=lambda c: (-c.confidence, c.category.value))[0]


def diagnose(context: DiagnosisContext, rules: Sequence[DiagnosisRule] = ALL_RULES) -> Diagnosis:
    """Run every rule, resolve conflicts, and return the engine's one
    answer — `INSUFFICIENT_EVIDENCE` when nothing fired, never a guess."""
    candidates = [c for rule in rules if (c := rule.evaluate(context)) is not None]

    if not candidates:
        return Diagnosis(
            word_id=context.word_id,
            user_id=context.user_id,
            outcome=DiagnosisCategory.INSUFFICIENT_EVIDENCE.value,
            evidence=(),
            confidence=None,
            rules_version=RULES_VERSION,
            diagnosed_at=utcnow(),
        )

    winner = _resolve(candidates)
    competitors = tuple(
        c.category.value for c in candidates if c is not winner and c.category in winner.competing_with
    )
    return Diagnosis(
        word_id=context.word_id,
        user_id=context.user_id,
        outcome=winner.category.value,
        evidence=winner.evidence,
        confidence=winner.confidence,
        rules_version=RULES_VERSION,
        diagnosed_at=utcnow(),
        sample_size=winner.sample_size,
        competing_hypotheses=competitors,
        related_word_id=winner.related_word_id,
    )
