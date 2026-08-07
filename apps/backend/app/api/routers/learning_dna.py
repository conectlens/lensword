"""Learning DNA endpoints (issue #186 TODO 0/4): a learner's contextual
efficacy conclusions and their stated modality preference. No brain-type
bars, no "you are a visual learner" — every estimate carries its own
context, sample size, and uncertainty (`EfficacyEstimateResponse`), and the
stated preference is a separate resource entirely, matching the
`/api/v1/me/weaknesses` pattern's own "not enough evidence yet" honesty.

No flag check here, mirroring `diagnosis.py`/`interventions.py`: reads are
never gated by `learning_diagnosis_enabled`, only the writes that produce
the underlying `LearningObservation`/`InterventionPlan` rows are — an
account with the flag off or never-populated history simply has nothing to
show, the same as a fresh account.
"""
from fastapi import APIRouter

from app.api.deps import CurrentUser, InterventionRepo, LearningObservationRepo, ModalityPreferenceRepo, WordRepo
from app.api.schemas.learning_dna import (
    EfficacyContextResponse,
    EfficacyEstimateResponse,
    ModalityPreferenceResponse,
    SetModalityPreferenceRequest,
)
from app.application.use_cases.learning_dna import (
    GetEfficacyConclusionsUseCase,
    GetModalityPreferenceUseCase,
    RecordModalityPreferenceUseCase,
)
from app.domain.services.diagnosis_contracts import ModalityPreference
from app.domain.services.intervention_efficacy import EfficacyEstimate

router = APIRouter(prefix="/api/v1/me/learning-dna", tags=["learning-dna"])


def _estimate_response(e: EfficacyEstimate) -> EfficacyEstimateResponse:
    return EfficacyEstimateResponse(
        intervention_type=e.intervention_type,
        context=EfficacyContextResponse(
            item_class=e.context.item_class,
            language=e.context.language,
            prompt_direction=e.context.prompt_direction,
            difficulty=e.context.difficulty,
            modality=e.context.modality,
            horizon_days=e.context.horizon_days,
        ),
        status=e.status.value,
        intervention_samples=e.intervention_samples,
        control_samples=e.control_samples,
        intervention_rate=e.intervention_rate,
        control_rate=e.control_rate,
        effect=e.effect,
        interval_low=e.interval_low,
        interval_high=e.interval_high,
        reason=e.reason,
        recommendation=e.recommendation,
        period_start=e.period_start,
        period_end=e.period_end,
        valid_until=e.valid_until,
    )


def _preference_response(p: ModalityPreference) -> ModalityPreferenceResponse:
    return ModalityPreferenceResponse(modality=p.modality, stated_at=p.stated_at)


@router.get("/efficacy", response_model=list[EfficacyEstimateResponse])
def list_efficacy_conclusions(
    current_user: CurrentUser,
    observation_repo: LearningObservationRepo,
    intervention_repo: InterventionRepo,
    word_repo: WordRepo,
):
    """Every scoped technique/context comparison this account has enough
    delayed evidence to even attempt — not a ranking, not a learner-style
    label. A client renders `status` (MEASURED / INCONCLUSIVE /
    INSUFFICIENT_EVIDENCE) as the three-way split TODO 4 asks for."""
    use_case = GetEfficacyConclusionsUseCase(observation_repo, intervention_repo, word_repo)
    return [_estimate_response(e) for e in use_case.execute(current_user.id)]


@router.get("/modality-preference", response_model=ModalityPreferenceResponse | None)
def get_modality_preference(current_user: CurrentUser, preference_repo: ModalityPreferenceRepo):
    preference = GetModalityPreferenceUseCase(preference_repo).execute(current_user.id)
    return _preference_response(preference) if preference is not None else None


@router.post("/modality-preference", response_model=ModalityPreferenceResponse)
def set_modality_preference(
    payload: SetModalityPreferenceRequest, current_user: CurrentUser, preference_repo: ModalityPreferenceRepo
):
    """Records a *stated* preference only — never derived from, and never
    fed back into, any `EfficacyEstimate` computation (#186 TODO 0)."""
    preference = RecordModalityPreferenceUseCase(preference_repo).execute(current_user.id, payload.modality)
    return _preference_response(preference)
