"""Conservative, contextual intervention-efficacy calculations (#186).

This service reports evidence about an intervention in a context.  It never
turns a technique into a learner identity and never mutates scheduling state.
Immediate repetitions are collapsed before aggregation; delayed outcomes are
the only observations eligible for a recommendation.

TODO 0's context axes are all here: learner, item class, language, prompt
direction, difficulty, modality, intervention type, and retention horizon —
`EfficacyContext` is the closed key every comparison is scoped by, and
`learner_id` in particular exists so this module can never quietly pool two
different learners' evidence into one number, which is exactly the kind of
"you are a visual learner" claim ADR 0007 forbids. `modality` (text/audio/
image/spatial/...) is a first-class axis rather than folded into
`item_class`, because "contrast cards work for reversible verbs" and
"images work for reversible verbs" are different, independently falsifiable
claims.

TODO 1's confounding check lives here too: `_is_confounded` refuses to turn
two arms with materially different prior-mastery or exposure-count
distributions into a Wilson interval, because a naive comparison there would
silently attribute a prior-mastery gap to the intervention.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable

from app.domain.services.diagnosis_contracts import ModalityPreference


class EfficacyStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INCONCLUSIVE = "INCONCLUSIVE"
    MEASURED = "MEASURED"


@dataclass(frozen=True)
class InterventionObservation:
    """One comparable delayed outcome, not a raw answer repetition."""

    evidence_id: str
    learner_id: int
    item_id: int
    exposure_id: str
    intervention_type: str
    item_class: str
    language: str
    prompt_direction: str
    difficulty: str
    # e.g. "text"/"audio"/"image"/"spatial"/"story" — mirrors
    # `LearningObservation.modality` (#186 TODO 0's added axis: the prior
    # version of this dataclass had no modality field at all, which made a
    # per-modality efficacy claim impossible to compute honestly).
    modality: str
    horizon_days: int
    correct: bool
    is_control: bool
    observed_at: datetime
    # Bucketed relative to how much prior exposure this learner had to this
    # item ("new"/"weak"/"strong" — see intervention_attribution.py's
    # `_mastery_bucket`). Open string, not an enum, matching
    # `LearningObservation.modality`'s own reasoning: the bucket boundaries
    # are a computation concern, not a fact this contract should be revised
    # to keep up with. TODO 1's confounding check is the reason this field
    # exists: pooling a "new" learner's first exposure with a "strong" prior
    # learner's tenth is exactly the comparison this dataclass must be able
    # to refuse.
    prior_mastery: str = "unknown"
    # How many times this learner had already been exposed to this item
    # before this observation (>=1, this exposure included). Validated since
    # #258 but never read by any comparison until `_is_confounded` below —
    # TODO 1's other named gap.
    exposure_count: int = 1

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.exposure_id.strip():
            raise ValueError("efficacy observations need stable evidence and exposure ids")
        if self.horizon_days < 1:
            raise ValueError("efficacy requires a delayed outcome horizon")
        if self.exposure_count < 1:
            raise ValueError("exposure_count must be positive")
        if (
            not self.intervention_type.strip()
            or not self.item_class.strip()
            or not self.language.strip()
            or not self.modality.strip()
        ):
            raise ValueError("efficacy context fields cannot be empty")


@dataclass(frozen=True)
class EfficacyContext:
    """The closed key one comparison is scoped by (#186 TODO 0). Equality
    on this dataclass is the entire scoping rule `estimate_efficacy` uses —
    two observations are "the same comparison" iff their derived contexts
    are `==`, so adding a field here is how a new axis gets enforced, not a
    comment asking callers to remember it."""

    learner_id: int
    item_class: str
    language: str
    prompt_direction: str
    difficulty: str
    modality: str
    horizon_days: int


@dataclass(frozen=True)
class EfficacyEstimate:
    intervention_type: str
    context: EfficacyContext
    status: EfficacyStatus
    intervention_samples: int
    control_samples: int
    intervention_rate: float | None
    control_rate: float | None
    effect: float | None
    interval_low: float | None
    interval_high: float | None
    evidence_ids: tuple[str, ...]
    method: str
    reason: str | None = None
    # The evidence window this estimate was computed over (#186 TODO 2's
    # "period" requirement) — None only when there was no scoped evidence at
    # all (pure INSUFFICIENT_EVIDENCE with zero samples on both arms).
    period_start: datetime | None = None
    period_end: datetime | None = None
    # TODO 2's expiry: a MEASURED estimate is only trustworthy until this
    # point without reinforcement (see `refresh_staleness` below). Never set
    # on a non-MEASURED estimate — there is nothing to expire.
    valid_until: datetime | None = None

    @property
    def recommendation(self) -> str | None:
        """A scoped statement with sample size, period, effect, and
        confidence interval (#186 TODO 2) — never a bare "you are a visual
        learner" claim. Returns None for anything but MEASURED: an
        INSUFFICIENT_EVIDENCE or INCONCLUSIVE estimate has nothing honest to
        recommend."""
        if self.status is not EfficacyStatus.MEASURED:
            return None
        period = ""
        if self.period_start is not None and self.period_end is not None:
            period = f" between {self.period_start:%Y-%m-%d} and {self.period_end:%Y-%m-%d}"
        return (
            f"{self.intervention_type} has a measured delayed-recall effect of "
            f"{self.effect:+.1%} (95% CI {self.interval_low:+.1%} to {self.interval_high:+.1%}) "
            f"in {self.context.item_class} ({self.context.modality}) at "
            f"{self.context.horizon_days}-day horizon{period}, from "
            f"{self.intervention_samples} intervention and {self.control_samples} control samples."
        )


# TODO 2: how long a MEASURED estimate stays current without reinforcement.
# Chosen conservatively wide rather than derived from a formal decay model:
# FSRS review intervals for a stabilizing item routinely run 2-4 weeks, so a
# window shorter than that would flag perfectly healthy, still-accruing
# evidence as stale between a learner's own reviews. 45 days is long enough
# to survive a normal review gap but short enough that a claim nobody has
# reinforced in a month and a half stops being shown as current.
DEFAULT_MAX_AGE_DAYS = 45

# TODO 1's confounding thresholds. Both are judgement calls documented here
# rather than derived: a formal covariate-balance test (e.g. standardized
# mean difference) would be more principled but needs a variance estimate
# this module has no reason to trust yet for exposure_count/prior_mastery
# specifically. These are deliberately coarse so a comparison is *more*
# likely to abstain via INCONCLUSIVE than to launder a real confound through
# a false-precision statistical test.
_CONFOUND_EXPOSURE_DELTA = 1.5
_CONFOUND_MASTERY_SHARE_DELTA = 0.34


def wilson_interval(successes: int, samples: int) -> tuple[float, float]:
    """Public (not `_wilson_interval`) so `longitudinal_evaluation.py` (#186
    TODO 5) can build the same kind of confidence interval for a cohort-level
    comparison without a second, possibly-drifting implementation."""
    if samples == 0:
        raise ValueError("cannot calculate an interval without samples")
    rate = successes / samples
    z = 1.96
    denominator = 1 + z * z / samples
    centre = (rate + z * z / (2 * samples)) / denominator
    spread = z * math.sqrt((rate * (1 - rate) + z * z / (4 * samples)) / samples) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


# Back-compat alias: existing call sites inside this module use the
# underscored name.
_wilson_interval = wilson_interval


def deduplicate_observations(
    observations: Iterable[InterventionObservation],
) -> list[InterventionObservation]:
    """Keep one delayed observation per learner/item/exposure/context.

    Public (not `_deduplicate`) because `longitudinal_evaluation.py` (#186
    TODO 5) needs the exact same "several immediate repetitions are not
    independent successes" collapsing this module already established,
    rather than a second, possibly-drifting copy of the rule.
    """
    unique: dict[tuple[object, ...], InterventionObservation] = {}
    for observation in observations:
        key = (
            observation.learner_id,
            observation.item_id,
            observation.exposure_id,
            observation.intervention_type,
            observation.is_control,
            observation.horizon_days,
        )
        previous = unique.get(key)
        if previous is None or observation.observed_at > previous.observed_at:
            unique[key] = observation
    return list(unique.values())


def _category_shares(values: Iterable[str]) -> dict[str, float]:
    values = list(values)
    if not values:
        return {}
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    total = len(values)
    return {value: count / total for value, count in counts.items()}


def _is_confounded(
    intervention: list[InterventionObservation], control: list[InterventionObservation]
) -> bool:
    """#186 TODO 1: "if the same learner/item-class pair has meaningfully
    different prior-mastery or exposure-count distributions between the
    strategies being compared, mark INCONCLUSIVE rather than computing a
    naive Wilson interval." A real effect and a prior-mastery gap look
    identical in a bare accuracy-rate comparison; this is the check that
    keeps this module from reporting the second as the first.
    """
    intervention_exposure = sum(o.exposure_count for o in intervention) / len(intervention)
    control_exposure = sum(o.exposure_count for o in control) / len(control)
    if abs(intervention_exposure - control_exposure) > _CONFOUND_EXPOSURE_DELTA:
        return True

    intervention_mastery = _category_shares(o.prior_mastery for o in intervention)
    control_mastery = _category_shares(o.prior_mastery for o in control)
    for category in set(intervention_mastery) | set(control_mastery):
        delta = abs(intervention_mastery.get(category, 0.0) - control_mastery.get(category, 0.0))
        if delta > _CONFOUND_MASTERY_SHARE_DELTA:
            return True
    return False


def estimate_efficacy(
    observations: Iterable[InterventionObservation],
    *,
    intervention_type: str,
    context: EfficacyContext,
    minimum_samples: int = 5,
) -> EfficacyEstimate:
    """Estimate one scoped technique/control comparison.

    The result is intentionally abstention-first: a recommendation requires a
    minimum delayed sample in both arms, and a comparison whose two arms are
    not comparable (TODO 1's confounding check) is marked INCONCLUSIVE
    instead of measured, however large the samples are. This is not a
    scheduler or learner profile and cannot produce a global modality
    ranking.
    """
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    scoped = [
        observation
        for observation in deduplicate_observations(observations)
        if observation.intervention_type == intervention_type
        and EfficacyContext(
            observation.learner_id,
            observation.item_class,
            observation.language,
            observation.prompt_direction,
            observation.difficulty,
            observation.modality,
            observation.horizon_days,
        )
        == context
    ]
    intervention = [item for item in scoped if not item.is_control]
    control = [item for item in scoped if item.is_control]
    evidence_ids = tuple(sorted(item.evidence_id for item in scoped))
    period_start = min((item.observed_at for item in scoped), default=None)
    period_end = max((item.observed_at for item in scoped), default=None)

    if len(intervention) < minimum_samples or len(control) < minimum_samples:
        return EfficacyEstimate(
            intervention_type=intervention_type,
            context=context,
            status=EfficacyStatus.INSUFFICIENT_EVIDENCE,
            intervention_samples=len(intervention),
            control_samples=len(control),
            intervention_rate=None,
            control_rate=None,
            effect=None,
            interval_low=None,
            interval_high=None,
            evidence_ids=evidence_ids,
            method="delayed_recall_control_comparison_v1",
            reason="minimum delayed samples are required in both intervention and control arms",
            period_start=period_start,
            period_end=period_end,
        )

    if _is_confounded(intervention, control):
        return EfficacyEstimate(
            intervention_type=intervention_type,
            context=context,
            status=EfficacyStatus.INCONCLUSIVE,
            intervention_samples=len(intervention),
            control_samples=len(control),
            intervention_rate=None,
            control_rate=None,
            effect=None,
            interval_low=None,
            interval_high=None,
            evidence_ids=evidence_ids,
            method="delayed_recall_control_comparison_v1",
            reason=(
                "intervention and control arms differ materially in prior mastery or "
                "exposure count; a rate comparison would attribute that gap to the "
                "intervention"
            ),
            period_start=period_start,
            period_end=period_end,
        )

    intervention_successes = sum(item.correct for item in intervention)
    control_successes = sum(item.correct for item in control)
    intervention_rate = intervention_successes / len(intervention)
    control_rate = control_successes / len(control)
    effect = intervention_rate - control_rate
    low, high = _wilson_interval(intervention_successes, len(intervention))
    control_low, control_high = _wilson_interval(control_successes, len(control))
    valid_until = period_end + timedelta(days=DEFAULT_MAX_AGE_DAYS) if period_end is not None else None
    return EfficacyEstimate(
        intervention_type=intervention_type,
        context=context,
        status=EfficacyStatus.MEASURED,
        intervention_samples=len(intervention),
        control_samples=len(control),
        intervention_rate=intervention_rate,
        control_rate=control_rate,
        effect=effect,
        interval_low=low - control_high,
        interval_high=high - control_low,
        evidence_ids=evidence_ids,
        method="delayed_recall_control_comparison_v1",
        period_start=period_start,
        period_end=period_end,
        valid_until=valid_until,
    )


def refresh_staleness(estimate: EfficacyEstimate, *, now: datetime) -> EfficacyEstimate:
    """#186 TODO 2: "expire/downgrade stale conclusions as new evidence
    arrives." Takes `now` explicitly rather than reading the wall clock —
    this module stays pure and deterministic-under-test like every other
    domain service here; the caller (application layer) supplies the real
    time.

    Only a MEASURED estimate can go stale; INSUFFICIENT_EVIDENCE and
    INCONCLUSIVE are already the most conservative state there is, so
    "downgrading" them further is a no-op.
    """
    if estimate.status is not EfficacyStatus.MEASURED or estimate.valid_until is None:
        return estimate
    if now <= estimate.valid_until:
        return estimate
    return replace(
        estimate,
        status=EfficacyStatus.INSUFFICIENT_EVIDENCE,
        intervention_rate=None,
        control_rate=None,
        effect=None,
        interval_low=None,
        interval_high=None,
        valid_until=None,
        reason=(
            f"evidence is stale: no reinforcing observation since "
            f"{estimate.period_end:%Y-%m-%d}" if estimate.period_end else "evidence is stale"
        ),
    )


@dataclass(frozen=True)
class ModalityInsight:
    """The one place stated preference and measured effectiveness are allowed
    to sit next to each other (#186 TODO 0) — as two separate fields a caller
    must read independently, never merged into a single verdict. A learner
    can prefer images (`stated_preference`) while every measured estimate for
    images is INSUFFICIENT_EVIDENCE or shows a flat/negative effect
    (`measured_estimates`), and this type makes both facts visible at once
    rather than picking one to report."""

    modality: str
    stated_preference: bool
    measured_estimates: tuple[EfficacyEstimate, ...]


def build_modality_insight(
    modality: str,
    preference: ModalityPreference | None,
    estimates: Iterable[EfficacyEstimate],
) -> ModalityInsight:
    """Combine a learner's stated preference (or lack of one) with whatever
    measured estimates exist for `modality`. `preference` comes from a
    `ModalityPreferenceRepository` read; `estimates` come from
    `estimate_efficacy` calls — two independent data sources, never one
    inferred from the other."""
    return ModalityInsight(
        modality=modality,
        stated_preference=preference is not None and preference.modality == modality,
        measured_estimates=tuple(e for e in estimates if e.context.modality == modality),
    )
