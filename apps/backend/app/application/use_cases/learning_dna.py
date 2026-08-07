"""Learning DNA: a learner's efficacy conclusions and stated modality
preference, assembled from real repository data (issue #186 TODO 0/1/2,
the "make it reachable by a client" half of the issue).

`GetEfficacyConclusionsUseCase` is the read path the API (and the frontend,
TODO 4) actually calls. It is real, but the attribution step it depends on
(`intervention_attribution.attribute_efficacy_observations`) is an honest
first cut, not a randomized trial — see that module's own docstring for the
documented limitation. Everything downstream of attribution (confounding
detection, minimum samples, staleness) is the fully general, independently
tested logic in `intervention_efficacy.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.repositories import (
    InterventionRepository,
    LearningObservationRepository,
    ModalityPreferenceRepository,
)
from app.domain.services.diagnosis_contracts import ModalityPreference
from app.domain.services.intervention_attribution import (
    WordEfficacyContext,
    attribute_efficacy_observations,
)
from app.domain.services.intervention_efficacy import (
    EfficacyContext,
    EfficacyEstimate,
    estimate_efficacy,
    refresh_staleness,
)
from app.domain.value_objects import utcnow

# How far back the live endpoint looks for evidence. Bounded rather than a
# full-account scan (matching `LearningObservationRepository`'s own "never
# an unbounded scan" rule) and comfortably wider than
# `intervention_efficacy.DEFAULT_MAX_AGE_DAYS` (45 days), so this window is
# never the reason a still-fresh estimate goes missing.
LOOKBACK_DAYS = 365
OBSERVATION_LIMIT = 2000


class GetEfficacyConclusionsUseCase:
    def __init__(
        self,
        observation_repo: LearningObservationRepository,
        intervention_repo: InterventionRepository,
        word_repo,
    ):
        self.observation_repo = observation_repo
        self.intervention_repo = intervention_repo
        self.word_repo = word_repo

    def execute(self, user_id: int, *, now: datetime | None = None) -> list[EfficacyEstimate]:
        moment = now or utcnow()
        since = moment - timedelta(days=LOOKBACK_DAYS)
        observations = self.observation_repo.list_in_window(user_id, since, moment, limit=OBSERVATION_LIMIT)
        plans = self.intervention_repo.list_all_for_user(user_id)
        if not observations or not plans:
            return []

        words = self.word_repo.list_all_for_user(user_id)
        word_contexts = {
            word.id: WordEfficacyContext(
                item_class=word.part_of_speech or "unclassified",
                language=word.target_language.value,
                difficulty=word.cefr_level or "unspecified",
                created_at=word.created_at,
            )
            for word in words
            if word.id is not None
        }

        attributed = attribute_efficacy_observations(
            learner_id=user_id, observations=observations, plans=plans, word_contexts=word_contexts
        )
        if not attributed:
            return []

        # Every distinct (intervention_type, context) combination actually
        # present in the attributed evidence — computed from the data
        # itself rather than iterated over some closed catalog, so a
        # comparison is only ever attempted where there is something to
        # compare.
        combinations = {
            (
                row.intervention_type,
                EfficacyContext(
                    row.learner_id,
                    row.item_class,
                    row.language,
                    row.prompt_direction,
                    row.difficulty,
                    row.modality,
                    row.horizon_days,
                ),
            )
            for row in attributed
        }

        estimates = [
            estimate_efficacy(attributed, intervention_type=intervention_type, context=context)
            for intervention_type, context in combinations
        ]
        return [refresh_staleness(estimate, now=moment) for estimate in estimates]


class RecordModalityPreferenceUseCase:
    def __init__(self, preference_repo: ModalityPreferenceRepository):
        self.preference_repo = preference_repo

    def execute(self, user_id: int, modality: str, *, now: datetime | None = None) -> ModalityPreference:
        moment = now or utcnow()
        return self.preference_repo.add(
            ModalityPreference(user_id=user_id, modality=modality, stated_at=moment)
        )


class GetModalityPreferenceUseCase:
    def __init__(self, preference_repo: ModalityPreferenceRepository):
        self.preference_repo = preference_repo

    def execute(self, user_id: int) -> ModalityPreference | None:
        return self.preference_repo.latest_for_user(user_id)
