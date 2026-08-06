"""Conservative, contextual intervention-efficacy calculations (#186).

This service reports evidence about an intervention in a context.  It never
turns a technique into a learner identity and never mutates scheduling state.
Immediate repetitions are collapsed before aggregation; delayed outcomes are
the only observations eligible for a recommendation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable


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
    horizon_days: int
    correct: bool
    is_control: bool
    observed_at: datetime
    exposure_count: int = 1

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.exposure_id.strip():
            raise ValueError("efficacy observations need stable evidence and exposure ids")
        if self.horizon_days < 1:
            raise ValueError("efficacy requires a delayed outcome horizon")
        if self.exposure_count < 1:
            raise ValueError("exposure_count must be positive")
        if not self.intervention_type.strip() or not self.item_class.strip() or not self.language.strip():
            raise ValueError("efficacy context fields cannot be empty")


@dataclass(frozen=True)
class EfficacyContext:
    item_class: str
    language: str
    prompt_direction: str
    difficulty: str
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

    @property
    def recommendation(self) -> str | None:
        if self.status is not EfficacyStatus.MEASURED:
            return None
        return (
            f"{self.intervention_type} has a measured delayed-recall effect of "
            f"{self.effect:+.1%} in {self.context.item_class} at "
            f"{self.context.horizon_days}-day horizon"
        )


def _wilson_interval(successes: int, samples: int) -> tuple[float, float]:
    if samples == 0:
        raise ValueError("cannot calculate an interval without samples")
    rate = successes / samples
    z = 1.96
    denominator = 1 + z * z / samples
    centre = (rate + z * z / (2 * samples)) / denominator
    spread = z * math.sqrt((rate * (1 - rate) + z * z / (4 * samples)) / samples) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _deduplicate(observations: Iterable[InterventionObservation]) -> list[InterventionObservation]:
    """Keep one delayed observation per learner/item/exposure/context."""
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


def estimate_efficacy(
    observations: Iterable[InterventionObservation],
    *,
    intervention_type: str,
    context: EfficacyContext,
    minimum_samples: int = 5,
) -> EfficacyEstimate:
    """Estimate one scoped technique/control comparison.

    The result is intentionally abstention-first: a recommendation requires a
    minimum delayed sample in both arms.  This is not a scheduler or learner
    profile and cannot produce a global modality ranking.
    """
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    scoped = [
        observation
        for observation in _deduplicate(observations)
        if observation.intervention_type == intervention_type
        and EfficacyContext(
            observation.item_class,
            observation.language,
            observation.prompt_direction,
            observation.difficulty,
            observation.horizon_days,
        )
        == context
    ]
    intervention = [item for item in scoped if not item.is_control]
    control = [item for item in scoped if item.is_control]
    evidence_ids = tuple(sorted(item.evidence_id for item in scoped))
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
        )

    intervention_successes = sum(item.correct for item in intervention)
    control_successes = sum(item.correct for item in control)
    intervention_rate = intervention_successes / len(intervention)
    control_rate = control_successes / len(control)
    effect = intervention_rate - control_rate
    low, high = _wilson_interval(intervention_successes, len(intervention))
    control_low, control_high = _wilson_interval(control_successes, len(control))
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
    )
