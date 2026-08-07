"""Diagnosis-to-intervention planning (issue #185).

Turns a supported `Diagnosis` into one bounded, closed-catalog strategy —
never a clever explanation with nothing testable attached, and never a
strategy invented outside the closed set below.

Pure and deterministic: no repository, no I/O, zero framework imports
(enforced by `tests/test_diagnosis_architecture_boundary.py`), mirroring
`diagnosis_engine.py`'s own boundary. Everything this module needs about
prior plans/outcomes and the knowledge graph is passed in by the use case
that calls it (`RunDiagnosisForWordUseCase`), the same seam
`diagnosis_engine.py`'s own `DiagnosisContext` already uses.
"""
from __future__ import annotations

from enum import Enum

from app.domain.services.diagnosis_contracts import Diagnosis, InterventionOutcome, InterventionPlan
from app.domain.services.diagnosis_engine import DiagnosisCategory
from app.domain.services.knowledge_graph import KnowledgeGraph
from app.domain.value_objects import utcnow

# Bumped when the category -> strategy mapping below changes meaning, so a
# plan can be read later next to the policy version that produced it
# rather than re-interpreted under today's rules.
POLICY_VERSION = 2

# TODO 2: rank at most this many prerequisite candidates.
MAX_PREREQUISITES = 3

# TODO 5: a checkpoint needs at least this many observations on each side of
# the comparison before it counts as evidence rather than noise.
MIN_HORIZON_SAMPLES = 2


class InterventionStrategy(str, Enum):
    """The closed catalog TODO 0 asks for. A rule (or, later, a model
    asked only to phrase a plan the rule already reached — ADR 0007's own
    boundary) may never invent a tenth value."""

    ISOLATE = "isolate"
    CONTRAST = "contrast"
    PREREQUISITE_PATH = "prerequisite_path"
    MORPHOLOGY_DECOMPOSITION = "morphology_decomposition"
    CONTEXT_VARIATION = "context_variation"
    PRODUCTION_PRACTICE = "production_practice"
    SPATIAL_ANCHOR = "spatial_anchor"
    MNEMONIC_REPLACEMENT = "mnemonic_replacement"
    ACQUISITION_RESTART = "acquisition_restart"


# One primary strategy per diagnosed category. EXACT_CONFUSION's entry below
# is the *default first stage* only — `_stage_confusion` may escalate it to
# CONTRAST once isolated recall has been demonstrated (TODO 1).
# MISSING_PREREQUISITE's ranked candidates are computed by
# `_rank_prerequisites`, not stored here (TODO 2).
# SPATIAL_ANCHOR is deliberately never auto-selected here — it is a
# user-invoked alternative (TODO 4's "let the learner choose an
# alternative"), not something a diagnosis triggers on its own.
_STRATEGY_FOR_CATEGORY: dict[DiagnosisCategory, tuple[InterventionStrategy, str]] = {
    DiagnosisCategory.EXACT_CONFUSION: (
        InterventionStrategy.ISOLATE,
        "Confused with a specific other word at least twice; separating the pair first establishes isolated recall before contrasting them.",
    ),
    DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL: (
        InterventionStrategy.PRODUCTION_PRACTICE,
        "Reliably correct in one prompt direction and reliably wrong in the other; direction-focused production practice targets the failing direction specifically.",
    ),
    DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE: (
        InterventionStrategy.MORPHOLOGY_DECOMPOSITION,
        "Repeated near-miss spellings suggest the word's structure isn't distinct yet; decomposition makes the parts explicit.",
    ),
    DiagnosisCategory.PHONETIC_INTERFERENCE: (
        InterventionStrategy.MNEMONIC_REPLACEMENT,
        "Repeated answers sharing this word's sound suggest it needs a distinguishing memory device, not more repetition of the same cue.",
    ),
    DiagnosisCategory.MISSING_PREREQUISITE: (
        InterventionStrategy.PREREQUISITE_PATH,
        "The knowledge graph names easier related word(s) not yet demonstrated; establishing them first is the direct remedy.",
    ),
    DiagnosisCategory.RECOGNITION_PRODUCTION_GAP: (
        InterventionStrategy.PRODUCTION_PRACTICE,
        "Reliably correct at recognition and reliably wrong at production; the gap is specifically about producing the word, not recognizing it.",
    ),
    DiagnosisCategory.CONTEXT_LOCK: (
        InterventionStrategy.CONTEXT_VARIATION,
        "Correct only in the context it was learned in; varying the context is the direct remedy.",
    ),
    DiagnosisCategory.FORGETTING: (
        InterventionStrategy.ACQUISITION_RESTART,
        "Demonstrated recall previously and lost it; restarting the acquisition ladder re-establishes it.",
    ),
    DiagnosisCategory.WEAK_ACQUISITION: (
        InterventionStrategy.ACQUISITION_RESTART,
        "Never demonstrated recall in the first place; the acquisition ladder is the remedy this diagnosis exists to route to.",
    ),
}


def _pair(word_id: int, other_id: int | None) -> frozenset[int] | None:
    if other_id is None:
        return None
    return frozenset((word_id, other_id))


def _stage_confusion(
    diagnosis: Diagnosis,
    prior_plans: tuple[InterventionPlan, ...],
    prior_outcomes: tuple[InterventionOutcome, ...],
) -> tuple[InterventionStrategy, str]:
    """TODO 1: isolate first; contrast only after isolated recall is
    demonstrated. "Demonstrated" means a prior ISOLATE plan for this exact
    pair has a recorded "effective" outcome — never merely that time has
    passed, and never inferred from this rule's own guess."""
    pair = _pair(diagnosis.word_id, diagnosis.related_word_id)
    if pair is None:
        # No structured pair to stage against (should not happen for a real
        # ExactConfusionRule hit, but a hand-built fixture might omit it) —
        # fall back to the conservative first stage.
        return _STRATEGY_FOR_CATEGORY[DiagnosisCategory.EXACT_CONFUSION]

    has_prior_isolate = any(
        plan.strategy == InterventionStrategy.ISOLATE.value
        and _pair(plan.word_id, plan.second_word_id) == pair
        for plan in prior_plans
    )
    isolate_effective = any(
        outcome.strategy == InterventionStrategy.ISOLATE.value
        and outcome.horizon != "immediate"
        and outcome.result == "effective"
        for outcome in prior_outcomes
    )
    if has_prior_isolate and isolate_effective:
        return (
            InterventionStrategy.CONTRAST,
            "Isolated recall was demonstrated for this pair; contrast now asks the learner to articulate the difference between them.",
        )
    return _STRATEGY_FOR_CATEGORY[DiagnosisCategory.EXACT_CONFUSION]


def _rank_prerequisites(graph: KnowledgeGraph, word_id: int, candidate_ids: list[int]) -> tuple[int, ...]:
    """TODO 2: dedupe, then rank by the strongest edge directly joining the
    candidate to the target word, capped at `MAX_PREREQUISITES`."""
    deduped = sorted(set(candidate_ids))

    def strength_for(candidate_id: int) -> float:
        best = 0.0
        for edge in graph.edges:
            if {edge.source_id, edge.target_id} == {word_id, candidate_id}:
                best = max(best, edge.strength)
        return best

    ranked = sorted(deduped, key=lambda c: (-strength_for(c), c))
    return tuple(ranked[:MAX_PREREQUISITES])


def plan_intervention(
    diagnosis: Diagnosis,
    *,
    graph: KnowledgeGraph | None = None,
    prior_plans: tuple[InterventionPlan, ...] = (),
    prior_outcomes: tuple[InterventionOutcome, ...] = (),
) -> InterventionPlan | None:
    """One bounded plan for a supported diagnosis, or None.

    TODO 0's own verify clause: "every diagnosis maps to zero or more
    justified strategies; unsupported cases return no intervention." An
    abstention (unknown/insufficient_evidence) or any outcome string this
    module has no mapped strategy for produces no plan at all — not an
    ineligible one — so a persisted plan is always something a learner
    could actually be shown.

    `graph`/`prior_plans`/`prior_outcomes` are optional so existing pure
    unit tests that only care about the category->strategy mapping keep
    working unchanged; the real use case always supplies them.
    """
    try:
        category = DiagnosisCategory(diagnosis.outcome)
    except ValueError:
        return None

    mapping = _STRATEGY_FOR_CATEGORY.get(category)
    if mapping is None:
        return None

    strategy, rationale = mapping
    second_word_id: int | None = None
    prerequisite_ids: tuple[int, ...] = ()

    if category is DiagnosisCategory.EXACT_CONFUSION:
        strategy, rationale = _stage_confusion(diagnosis, prior_plans, prior_outcomes)
        second_word_id = diagnosis.related_word_id
    elif category is DiagnosisCategory.MISSING_PREREQUISITE and graph is not None:
        prerequisite_ids = _rank_prerequisites(graph, diagnosis.word_id, graph.prerequisites(diagnosis.word_id))

    return InterventionPlan(
        word_id=diagnosis.word_id,
        user_id=diagnosis.user_id,
        diagnosis_outcome=diagnosis.outcome,
        strategy=strategy.value,
        policy_version=POLICY_VERSION,
        eligible=True,
        rationale=rationale,
        planned_at=utcnow(),
        second_word_id=second_word_id,
        prerequisite_ids=prerequisite_ids,
    )


def is_duplicate_of_active_plan(
    candidate: InterventionPlan,
    prior_plans: tuple[InterventionPlan, ...],
    prior_outcomes: tuple[InterventionOutcome, ...],
) -> bool:
    """TODO 4's idempotency verify clause: re-diagnosing the same standing
    confusion must not pile up a fresh plan every time the learner answers
    again. A prior plan for the same (diagnosis_outcome, strategy) is still
    active — and the candidate is a duplicate of it — until a terminal
    outcome (anything other than "postponed") has been recorded against it.
    """
    _TERMINAL = frozenset({"resolved", "abandoned", "rejected", "effective", "ineffective"})
    for plan in prior_plans:
        if plan.diagnosis_outcome != candidate.diagnosis_outcome or plan.strategy != candidate.strategy:
            continue
        has_terminal_outcome = any(
            outcome.strategy == plan.strategy and outcome.result in _TERMINAL for outcome in prior_outcomes
        )
        if not has_terminal_outcome:
            return True
    return False


def evaluate_intervention_outcome(
    *, pre_correct: int, pre_total: int, post_correct: int, post_total: int
) -> str:
    """TODO 5: mark a checkpoint effective/ineffective/inconclusive from
    delayed evidence — comparing accuracy before the plan against accuracy
    after it, never counting a single side alone. Too few observations on
    either side is inconclusive rather than a guess in either direction."""
    if pre_total < MIN_HORIZON_SAMPLES or post_total < MIN_HORIZON_SAMPLES:
        return "inconclusive"
    pre_accuracy = pre_correct / pre_total
    post_accuracy = post_correct / post_total
    if post_accuracy > pre_accuracy:
        return "effective"
    if post_accuracy < pre_accuracy:
        return "ineffective"
    return "inconclusive"
