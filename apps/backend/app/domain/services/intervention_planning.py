"""Diagnosis-to-intervention planning (issue #185 TODO 0).

Turns a supported `Diagnosis` into one bounded, closed-catalog strategy —
never a clever explanation with nothing testable attached, and never a
strategy invented outside the closed set below.

Pure and deterministic: no repository, no I/O, zero framework imports
(enforced by `tests/test_diagnosis_architecture_boundary.py`), mirroring
`diagnosis_engine.py`'s own boundary.
"""
from __future__ import annotations

from enum import Enum

from app.domain.services.diagnosis_contracts import Diagnosis, InterventionPlan
from app.domain.services.diagnosis_engine import DiagnosisCategory
from app.domain.value_objects import utcnow

# Bumped when the category -> strategy mapping below changes meaning, so a
# plan can be read later next to the policy version that produced it
# rather than re-interpreted under today's rules.
POLICY_VERSION = 1


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


# One primary strategy per diagnosed category, for this first pass. Two
# categories genuinely warrant more than a single candidate and are
# explicitly left to later TODOs rather than guessed at here:
#   - EXACT_CONFUSION could also warrant ISOLATE first, staged before
#     CONTRAST (TODO 1's "separate now" vs "contrast now" distinction,
#     which needs a "has isolated recall been demonstrated yet" signal
#     this module does not compute). CONTRAST alone is mapped for now.
#   - MISSING_PREREQUISITE could rank multiple prerequisite candidates
#     (TODO 2); this module only asserts the strategy applies, not which
#     specific prerequisite to use first.
# SPATIAL_ANCHOR is deliberately never auto-selected here — it is a
# user-invoked alternative (TODO 3/TODO 4's "let the learner choose an
# alternative"), not something a diagnosis triggers on its own.
# CONTEXT_LOCK maps to CONTEXT_VARIATION even though the rule that
# produces it cannot fire yet (context_source has no write path — #229) —
# the mapping is correct once it can, and untested via the real engine
# until then, the same limitation ContextLockRule's own tests document.
_STRATEGY_FOR_CATEGORY: dict[DiagnosisCategory, tuple[InterventionStrategy, str]] = {
    DiagnosisCategory.EXACT_CONFUSION: (
        InterventionStrategy.CONTRAST,
        "Confused with a specific other word at least twice; contrast asks the learner to articulate the difference between them.",
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
        "The knowledge graph names an easier related word not yet demonstrated; establishing it first is the direct remedy.",
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


def plan_intervention(diagnosis: Diagnosis) -> InterventionPlan | None:
    """One bounded plan for a supported diagnosis, or None.

    TODO 0's own verify clause: "every diagnosis maps to zero or more
    justified strategies; unsupported cases return no intervention." An
    abstention (unknown/insufficient_evidence) or any outcome string this
    module has no mapped strategy for produces no plan at all — not an
    ineligible one — so a persisted plan is always something a learner
    could actually be shown.
    """
    try:
        category = DiagnosisCategory(diagnosis.outcome)
    except ValueError:
        return None

    mapping = _STRATEGY_FOR_CATEGORY.get(category)
    if mapping is None:
        return None

    strategy, rationale = mapping
    return InterventionPlan(
        word_id=diagnosis.word_id,
        user_id=diagnosis.user_id,
        diagnosis_outcome=diagnosis.outcome,
        strategy=strategy.value,
        policy_version=POLICY_VERSION,
        eligible=True,
        rationale=rationale,
        planned_at=utcnow(),
    )
