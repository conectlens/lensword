"""Public domain contracts for the AI Learning Diagnosis epic (#180, ADR 0007).

This is Phase 0's deliverable (#181 TODO 2): the shapes every later phase
builds on, not the logic that fills them in. `LearningObservation` is
recorded starting in #182; the rules that turn observations into a
`Diagnosis` are #183's; `InterventionPlan`/`InterventionOutcome` are #184's
and #185's; `AcquisitionState` is #184's same-day scheduler. None of that
exists yet — what exists here is the contract those phases must not
silently diverge from, each with a version field so a later phase can
change its own shape without invalidating history recorded under an
earlier one.

Every dataclass here is immutable (`frozen=True`): these are records of
what was observed or decided, not mutable state a service edits in place.
A correction is a new record, not an edit to an old one — the same
append-only reasoning `mistake_memory.py` already uses for mistake history.

Zero framework or infrastructure imports (enforced by
`tests/test_diagnosis_architecture_boundary.py`). Repository ports for
these types live in `app.domain.repositories`, implemented in
`app.infrastructure` once a phase actually persists them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.value_objects import ReviewOutcome, SessionMode

# First-class outcomes every diagnosis engine must be able to report,
# regardless of which real diagnosis categories it eventually supports.
# The closed taxonomy of actual causes (FORGETTING, EXACT_CONFUSION, ...)
# is #183's TODO 0, not this phase's — these two are the ones that must
# exist before that taxonomy does, because "we don't know" and "there
# isn't enough evidence" are answers a rules engine can give from day one,
# and conflating either with a guessed cause is the exact failure mode
# ADR 0007 exists to prevent.
DIAGNOSIS_UNKNOWN = "unknown"
DIAGNOSIS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

_ABSTENTION_OUTCOMES = frozenset({DIAGNOSIS_UNKNOWN, DIAGNOSIS_INSUFFICIENT_EVIDENCE})


@dataclass(frozen=True, slots=True)
class LearningObservation:
    """One recall attempt, recorded with enough context to diagnose *why*
    it went the way it did — not just whether it did.

    Optional fields are nullable by design (#182 TODO 0): a client that only
    ever submits correct/incorrect must remain valid, and the diagnosis
    engine (#183) must treat a missing field as "not observed", never as a
    false negative for whatever it would otherwise indicate.
    """

    observation_id: str
    word_id: int
    user_id: int
    outcome: ReviewOutcome
    session_mode: SessionMode
    observed_at: datetime
    # Client-generated and stable across retries (#182 TODO 1) — the same
    # idempotency pattern #90's sync_operations uses. `None` only for
    # observations a legacy client's answer produced without ever knowing
    # this field exists; the repository that persists observations always
    # fills one in rather than storing a row with no stable identity.
    operation_id: str | None = None
    attempted_answer: str | None = None
    response_time_ms: int | None = None
    # e.g. "term_to_translation" / "translation_to_term". A direction
    # reversal (#183's SEMANTIC_DIRECTION_REVERSAL) is only detectable if
    # the direction the question was asked in is recorded alongside the
    # answer.
    prompt_direction: str | None = None
    hint_used: bool = False
    answer_format: str | None = None
    # text/audio/image/spatial/story/contrast/cloze/typing/speaking/
    # multiple_choice (#182 TODO 2) — an open string rather than an enum
    # here, since the closed set of supported modalities is a UI/feature
    # concern, not a fact this contract should have to be revised to keep
    # up with.
    modality: str | None = None
    # Links this observation to the InterventionPlan that caused it, once
    # #184/#185 ship real intervention plans to link to. An opaque
    # reference rather than a foreign key at this layer — the domain
    # contract does not know how interventions are persisted.
    intervention_plan_ref: str | None = None
    # Only ever set when the *learner* explicitly supplied a confidence
    # rating (e.g. a "how sure were you" prompt). Never populated by an AI
    # guess — see ADR 0007's rule about what confidence values are allowed
    # to come from.
    self_reported_confidence: float | None = None
    context_source: str | None = None
    schema_version: int = 1


class ObservationCorrectionReason(str, Enum):
    """Why a learner flagged an observation (issue #229 TODO 5). A closed,
    small vocabulary — unlike `modality`'s deliberately open string above —
    because these two are the only actions the review-history UI offers,
    not an evolving taxonomy a future phase adds to independently of the UI."""

    MISGRADED = "misgraded"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True, slots=True)
class ObservationCorrection:
    """A learner's flag on a previously recorded observation (issue #229
    TODO 5) — a new record naming the observation it corrects by id, never
    an edit to that observation. See the module docstring's append-only
    rule: the diagnosis engine must still be able to see the original
    alongside the correction for audit, even once it stops using the
    flagged observation as evidence.
    """

    correction_id: str
    observation_id: str
    user_id: int
    reason: ObservationCorrectionReason
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisEvidence:
    """One observed fact a diagnosis cites, kept separate from the
    diagnosis's inferred cause (#183 TODO 0's "separate observed facts from
    inferred causes").
    """

    kind: str
    observation_ids: tuple[str, ...]
    weight: float
    description: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"DiagnosisEvidence.weight must be in [0, 1], got {self.weight}")
        if not self.observation_ids:
            raise ValueError("DiagnosisEvidence must cite at least one observation")


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """A conclusion reached by deterministic rules (#183) from observed
    evidence — never by asking a model what it thinks is wrong.

    `outcome` is one of #183's closed `DiagnosisCategory` values (or the
    `DIAGNOSIS_UNKNOWN`/`DIAGNOSIS_INSUFFICIENT_EVIDENCE` sentinels this
    contract already defined ahead of that taxonomy); this contract does
    not itself constrain which strings are valid, since that closed set is
    owned in `diagnosis_engine.py`, not here. `confidence` is
    deterministic, derived from the evidence's own weights — not a number
    an LLM was asked to produce.

    `sample_size` and `competing_hypotheses` are #183 TODO 1's own
    requirements ("sample size... and competing hypotheses"), added here
    rather than kept only on the engine's intermediate candidate type —
    added after the contract's first version (schema_version-style
    additive change, matching how #182 extended this same dataclass).
    """

    word_id: int
    user_id: int
    outcome: str
    evidence: tuple[DiagnosisEvidence, ...]
    confidence: float | None
    rules_version: int
    diagnosed_at: datetime
    sample_size: int = 0
    # Other outcomes the winning rule's own evidence could also have
    # supported, named by the rule rather than inferred after the fact —
    # #183 TODO 1's "prevent multiple rules from silently claiming the
    # same evidence as independent proof."
    competing_hypotheses: tuple[str, ...] = ()
    # The other word of a confusion pair, when the winning rule names one
    # (currently only EXACT_CONFUSION). #185 TODO 1 needs this to decide
    # isolate-vs-contrast staging without re-parsing evidence description
    # text; #206 TODO 5 needs it to source a real contrast pair.
    related_word_id: int | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Diagnosis.confidence must be in [0, 1] or None, got {self.confidence}")

    @property
    def is_abstention(self) -> bool:
        """True for UNKNOWN/INSUFFICIENT_EVIDENCE — the cases a baseline
        must be measured on separately from a wrong-but-confident guess
        (#181 TODO 3's abstention rate)."""
        return self.outcome in _ABSTENTION_OUTCOMES


@dataclass(frozen=True, slots=True)
class InterventionPlan:
    """A bounded, testable response to a `Diagnosis` — #184's Objective,
    stated as a contract before either exists.

    `strategy` names a member of #185's closed catalog once that catalog
    ships; this contract does not itself close the set, matching how
    `outcome` above does not close #183's taxonomy.
    """

    word_id: int
    user_id: int
    diagnosis_outcome: str
    strategy: str
    policy_version: int
    eligible: bool
    rationale: str
    planned_at: datetime
    scheduled_for: datetime | None = None
    # None until the repository assigns one; a caller referencing an
    # existing plan (reject/postpone/choose-alternative, #185 TODO 4) always
    # has a persisted plan, so this is only ever None on a not-yet-saved one.
    id: int | None = None
    # The pair's other word, set only for isolate/contrast strategies
    # (#185 TODO 1).
    second_word_id: int | None = None
    # Up to 3 prerequisite word ids, strongest evidence first (#185 TODO 2).
    prerequisite_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class InterventionOutcome:
    """Whether a planned intervention actually ran, and what came of it —
    kept separate from `InterventionPlan` so a plan that was never carried
    out (the learner closed the app) is a distinct, honest fact rather than
    an assumed completion.
    """

    word_id: int
    user_id: int
    strategy: str
    completed: bool
    # A bounded status, not free text — safe to include in a structured log
    # event (diagnosis_events.py) unlike InterventionPlan.rationale, which
    # is. TODO 4's completion outcomes: "resolved"/"abandoned"/"rejected"/
    # "postponed". TODO 5's measured-effectiveness outcomes, always paired
    # with a non-"immediate" `horizon` below: "effective"/"ineffective"/
    # "inconclusive".
    result: str
    recorded_at: datetime
    completed_at: datetime | None = None
    # Which delayed checkpoint this measures (#185 TODO 5): "immediate"
    # (TODO 4's completion outcomes, and the default for anything not yet
    # measuring delayed effectiveness), "24h", "7d", or "next_review".
    horizon: str = "immediate"


@dataclass(frozen=True, slots=True)
class ModalityPreference:
    """A learner's stated modality preference ("I like images") — issue
    #186 TODO 0's required separation between what a learner *says* they
    prefer and what `LearningObservation`/`InterventionOutcome` data shows
    is actually effective for them.

    Deliberately its own record, not a field on any effectiveness type:
    `intervention_efficacy.EfficacyEstimate` is built exclusively from
    observed outcomes and must never read from this table, and nothing here
    is ever derived from measured performance. See
    `intervention_efficacy.build_modality_insight`, the one function allowed
    to look at both — and it keeps them in two separate fields rather than
    merging them into one verdict.
    """

    user_id: int
    modality: str
    stated_at: datetime
    id: int | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionState:
    """Position in the same-day graduated-recall ladder (#184), distinct
    from `ReviewState`: this is ephemeral, sub-day scheduling state, not a
    long-term FSRS input. Handoff to FSRS is a single bounded event
    (`graduated`), not a per-rung mutation of long-term stability — the
    same non-negotiable ADR 0007 states for the FSRS boundary.
    """

    word_id: int
    user_id: int
    rung: int
    ladder_version: int
    started_at: datetime
    updated_at: datetime
    graduated: bool = False
    # Why this ladder started (#184 TODO 4) — recorded once at `start()`
    # and carried on every later transition's row so "why did this enter
    # acquisition mode" (TODO 3) never needs a second lookup.
    entry_reason: str | None = None
    # Client-generated and stable across retries (#184 TODO 2's "retries do
    # not duplicate observations"), the same idempotency pattern
    # `LearningObservation.operation_id` already uses. `None` only for a
    # transition recorded with no retry protection requested.
    operation_id: str | None = None
