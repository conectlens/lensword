import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_effective_ai_settings, get_settings
from app.domain.entities import User
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.ai_provider import AIProvider
from app.domain.services.rate_limiter import InProcessRateLimiter, RateLimitRule
from app.domain.value_objects import UserRole
from app.infrastructure.ai import build_ai_provider
from app.infrastructure.ai_providers.credential_mapping import CredentialMappingError, build_provider_from_credential
from app.infrastructure.credential_vault import (
    CredentialDecryptionError,
    CredentialEncryptionNotConfiguredError,
    decrypt_credential,
)
from app.infrastructure.db import get_db
from app.infrastructure.repositories import (
    SqlAlchemyDesktopNotificationRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyConversationRepository,
    SqlAlchemyConversationCorrectionFeedbackRepository,
    SqlAlchemyScenarioAttemptRepository,
    SqlAlchemyLearningPathRepository,
    SqlAlchemyMistakeEventRepository,
    SqlAlchemyWordRevisionRepository,
    SqlAlchemyLearningObservationRepository,
    SqlAlchemyKnowledgeEdgeRepository,
    SqlAlchemyDiagnosisRepository,
    SqlAlchemyInterventionRepository,
    SqlAlchemyModalityPreferenceRepository,
    SqlAlchemyCompanionSessionRepository,
    SqlAlchemyCompanionActivityRepository,
    SqlAlchemyCompanionTaskRepository,
    SqlAlchemyCompanionLoopStateRepository,
    SqlAlchemyCompanionSamplingEventRepository,
    SqlAlchemyAcquisitionStateRepository,
    SqlAlchemyMnemonicRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyDailySessionPreferenceRepository,
    SqlAlchemyPracticeExerciseRepository,
    SqlAlchemyWeeklyLearningReportRepository,
    SqlAlchemyReminderRepository,
    SqlAlchemySyncOperationRepository,
    SqlAlchemyReviewSessionRepository,
    SqlAlchemyRoomRepository,
    SqlAlchemyUserAICredentialRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)
from app.infrastructure.security import decode_access_token

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_user_repository(db: DbSession) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(db)


def get_group_repository(db: DbSession) -> SqlAlchemyGroupRepository:
    return SqlAlchemyGroupRepository(db)


def get_word_repository(db: DbSession) -> SqlAlchemyWordRepository:
    return SqlAlchemyWordRepository(db)


def get_room_repository(db: DbSession) -> SqlAlchemyRoomRepository:
    return SqlAlchemyRoomRepository(db)


def get_review_session_repository(db: DbSession) -> SqlAlchemyReviewSessionRepository:
    return SqlAlchemyReviewSessionRepository(db)


def get_mnemonic_repository(db: DbSession) -> SqlAlchemyMnemonicRepository:
    return SqlAlchemyMnemonicRepository(db)


def get_recall_settings_repository(db: DbSession) -> SqlAlchemyRecallSettingsRepository:
    return SqlAlchemyRecallSettingsRepository(db)


def get_daily_session_preference_repository(db: DbSession) -> SqlAlchemyDailySessionPreferenceRepository:
    return SqlAlchemyDailySessionPreferenceRepository(db)


def get_practice_exercise_repository(db: DbSession) -> SqlAlchemyPracticeExerciseRepository:
    return SqlAlchemyPracticeExerciseRepository(db)


def get_weekly_learning_report_repository(db: DbSession) -> SqlAlchemyWeeklyLearningReportRepository:
    return SqlAlchemyWeeklyLearningReportRepository(db)


def get_reminder_repository(db: DbSession) -> SqlAlchemyReminderRepository:
    return SqlAlchemyReminderRepository(db)


def get_desktop_notification_repository(db: DbSession) -> SqlAlchemyDesktopNotificationRepository:
    return SqlAlchemyDesktopNotificationRepository(db)


def get_sync_operation_repository(db: DbSession) -> SqlAlchemySyncOperationRepository:
    return SqlAlchemySyncOperationRepository(db)


def get_mistake_event_repository(db: DbSession) -> SqlAlchemyMistakeEventRepository:
    return SqlAlchemyMistakeEventRepository(db)


def get_word_revision_repository(db: DbSession) -> SqlAlchemyWordRevisionRepository:
    return SqlAlchemyWordRevisionRepository(db)


def get_learning_observation_repository(db: DbSession) -> SqlAlchemyLearningObservationRepository:
    return SqlAlchemyLearningObservationRepository(db)


def get_knowledge_edge_repository(db: DbSession) -> SqlAlchemyKnowledgeEdgeRepository:
    return SqlAlchemyKnowledgeEdgeRepository(db)


def get_diagnosis_repository(db: DbSession) -> SqlAlchemyDiagnosisRepository:
    return SqlAlchemyDiagnosisRepository(db)


def get_intervention_repository(db: DbSession) -> SqlAlchemyInterventionRepository:
    return SqlAlchemyInterventionRepository(db)


def get_modality_preference_repository(db: DbSession) -> SqlAlchemyModalityPreferenceRepository:
    return SqlAlchemyModalityPreferenceRepository(db)


def get_companion_session_repository(db: DbSession) -> SqlAlchemyCompanionSessionRepository:
    return SqlAlchemyCompanionSessionRepository(db)


def get_companion_activity_repository(db: DbSession) -> SqlAlchemyCompanionActivityRepository:
    return SqlAlchemyCompanionActivityRepository(db)


def get_companion_task_repository(db: DbSession) -> SqlAlchemyCompanionTaskRepository:
    return SqlAlchemyCompanionTaskRepository(db)


def get_companion_loop_state_repository(db: DbSession) -> SqlAlchemyCompanionLoopStateRepository:
    return SqlAlchemyCompanionLoopStateRepository(db)


def get_companion_sampling_event_repository(db: DbSession) -> SqlAlchemyCompanionSamplingEventRepository:
    return SqlAlchemyCompanionSamplingEventRepository(db)


def get_acquisition_state_repository(db: DbSession) -> SqlAlchemyAcquisitionStateRepository:
    return SqlAlchemyAcquisitionStateRepository(db)


def get_learning_path_repository(db: DbSession) -> SqlAlchemyLearningPathRepository:
    return SqlAlchemyLearningPathRepository(db)


def get_conversation_repository(db: DbSession) -> SqlAlchemyConversationRepository:
    return SqlAlchemyConversationRepository(db)


def get_scenario_attempt_repository(db: DbSession) -> SqlAlchemyScenarioAttemptRepository:
    return SqlAlchemyScenarioAttemptRepository(db)


def get_conversation_correction_feedback_repository(
    db: DbSession,
) -> SqlAlchemyConversationCorrectionFeedbackRepository:
    return SqlAlchemyConversationCorrectionFeedbackRepository(db)


def get_user_ai_credential_repository(db: DbSession) -> SqlAlchemyUserAICredentialRepository:
    return SqlAlchemyUserAICredentialRepository(db)


@lru_cache
def _ai_provider() -> AIProvider | None:
    """Built once per process, not per request — the Ollama adapter owns a
    pooled HTTP client that would otherwise be recreated on every call."""
    return build_ai_provider(get_effective_ai_settings())


def get_ai_provider() -> AIProvider | None:
    return _ai_provider()


def resolve_ai_provider_for_user(user_id: int, db: Session) -> AIProvider | None:
    """Resolve the AI provider for one user's own request: their own
    stored Bring-Your-Own-Key credential when they have a usable one, the
    deployment's AI_PROVIDER (get_ai_provider() above, unchanged) when
    they don't. Shared by get_ai_provider_for_user below (the REST/
    CurrentUser-authenticated call sites) and
    app.api.mcp_auth.get_ai_provider_for_actor (the MCP invocation
    boundary, which resolves caller identity differently — see that
    module's docstring) so the one resolution policy lives in one place.

    Deliberately NOT cached the way _ai_provider() above is: that one is a
    process-wide singleton because it is the same for every request: this
    one depends on which user is asking, so caching it per-process would
    serve one user's provider (or worse, one user's decrypted credential)
    to another. Constructing any of these adapters is cheap — none of them
    open a network connection at construction time (confirmed in
    app.infrastructure.ai_providers.factory.build_ai_provider's own
    docstring) — so building fresh per request costs nothing worth caching
    away.

    Precedence when a user has stored more than one provider's credential
    (a judgment call, documented here since nothing forces a single
    answer): prefer whichever matches the deployment's own AI_PROVIDER,
    since that keeps a user's expectations aligned with what the
    deployment normally offers; otherwise, if exactly one credential is
    stored, use it unambiguously; otherwise (two or more credentials, none
    matching the deployment's own provider) there is no principled way to
    pick one over the other automatically, so this falls back to the
    deployment default rather than guessing which of a user's own keys to
    spend. A future UI could add an explicit "active provider" choice for
    someone who configures more than one; nothing here prevents adding
    that later.

    A credential that exists but is currently unusable (wrong
    AI_CREDENTIAL_ENCRYPTION_KEY, a corrupted row, key material the
    provider SDK rejects) deliberately does NOT fall back to the
    deployment's own key: the entire point of BYOK is that a deployment
    with no billing/credits system does not pay for a user's usage, so
    silently spending the deployment's budget because a user's own key
    broke would undermine that. It raises AIProviderUnavailableError
    instead — the same "something about your current AI setup is not
    working" signal every other provider failure in this codebase already
    uses, not a new error shape every caller has to learn to special-case.
    """
    credentials = SqlAlchemyUserAICredentialRepository(db).list_for_user(user_id)
    if not credentials:
        return get_ai_provider()

    settings_ = get_effective_ai_settings()
    chosen = next((c for c in credentials if c.provider == settings_.ai_provider), None)
    if chosen is None and len(credentials) == 1:
        chosen = credentials[0]
    if chosen is None:
        return get_ai_provider()

    try:
        payload = decrypt_credential(
            chosen.encrypted_payload, encryption_key=settings_.ai_credential_encryption_key
        )
        return build_provider_from_credential(
            chosen.provider,
            payload,
            max_output_tokens=settings_.ai_max_output_tokens,
            context_max_chars=settings_.ai_context_max_chars,
        )
    except (CredentialDecryptionError, CredentialEncryptionNotConfiguredError, CredentialMappingError) as exc:
        logger.warning(
            "stored AI credential for user %s provider %s is unusable: %s", user_id, chosen.provider, exc
        )
        raise AIProviderUnavailableError() from exc


# get_ai_provider_for_user/PerUserAIProvider are defined further down,
# right after CurrentUser — they depend on it and this file has no
# `from __future__ import annotations` to defer that reference.


# One limiter for the whole process, same shape as _ai_provider above: built
# once, shared by every request, reset between tests by the
# isolate_rate_limits fixture in conftest.py.
_rate_limiter = InProcessRateLimiter()


def get_rate_limiter() -> InProcessRateLimiter:
    return _rate_limiter


RateLimiter = Annotated[InProcessRateLimiter, Depends(get_rate_limiter)]


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(limiter: InProcessRateLimiter, rule_name: str, key: str, rule: RateLimitRule) -> None:
    result = limiter.check(rule_name, key, rule, now=datetime.now(timezone.utc))
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def rate_limit_login(request: Request, limiter: RateLimiter) -> None:
    """Keyed by IP: there is no account yet at login time."""
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_auth_attempts,
        window=timedelta(seconds=settings_.rate_limit_auth_window_seconds),
    )
    _enforce_rate_limit(limiter, "auth_login", f"ip:{_client_host(request)}", rule)


def rate_limit_mcp_oauth(request: Request, limiter: RateLimiter) -> None:
    """Independent budget for the remote MCP OAuth endpoints (issue #196
    TODO 4: registration, the authorization-code/refresh token exchange,
    and revocation). Keyed by IP like rate_limit_login, for the same
    reason: a code/refresh-token exchange attempt has no account bound to
    it until it either succeeds or is rejected.

    This is a single-process limiter — see rate_limiter.py's module
    docstring for the documented "more than one instance" gap that applies
    identically here. TODO 4 asks for shared rate limiting across
    instances; this repo has no distributed limiter infrastructure (no
    Redis or equivalent) to build that on, so this scopes down to the same
    honest single-instance posture the rest of the app already has rather
    than fabricating a fake distributed one.
    """
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_mcp_oauth_attempts,
        window=timedelta(seconds=settings_.rate_limit_mcp_oauth_window_seconds),
    )
    _enforce_rate_limit(limiter, "mcp_oauth", f"ip:{_client_host(request)}", rule)


UserRepo = Annotated[SqlAlchemyUserRepository, Depends(get_user_repository)]
GroupRepo = Annotated[SqlAlchemyGroupRepository, Depends(get_group_repository)]
WordRepo = Annotated[SqlAlchemyWordRepository, Depends(get_word_repository)]
RoomRepo = Annotated[SqlAlchemyRoomRepository, Depends(get_room_repository)]
ReviewSessionRepo = Annotated[SqlAlchemyReviewSessionRepository, Depends(get_review_session_repository)]
MnemonicRepo = Annotated[SqlAlchemyMnemonicRepository, Depends(get_mnemonic_repository)]
RecallSettingsRepo = Annotated[SqlAlchemyRecallSettingsRepository, Depends(get_recall_settings_repository)]
DailySessionPreferenceRepo = Annotated[SqlAlchemyDailySessionPreferenceRepository, Depends(get_daily_session_preference_repository)]
PracticeExerciseRepo = Annotated[SqlAlchemyPracticeExerciseRepository, Depends(get_practice_exercise_repository)]
WeeklyLearningReportRepo = Annotated[SqlAlchemyWeeklyLearningReportRepository, Depends(get_weekly_learning_report_repository)]
ReminderRepo = Annotated[SqlAlchemyReminderRepository, Depends(get_reminder_repository)]
DesktopNotificationRepo = Annotated[SqlAlchemyDesktopNotificationRepository, Depends(get_desktop_notification_repository)]
SyncOperationRepo = Annotated[SqlAlchemySyncOperationRepository, Depends(get_sync_operation_repository)]
MistakeEventRepo = Annotated[SqlAlchemyMistakeEventRepository, Depends(get_mistake_event_repository)]
WordRevisionRepo = Annotated[SqlAlchemyWordRevisionRepository, Depends(get_word_revision_repository)]
LearningObservationRepo = Annotated[
    SqlAlchemyLearningObservationRepository, Depends(get_learning_observation_repository)
]
KnowledgeEdgeRepo = Annotated[SqlAlchemyKnowledgeEdgeRepository, Depends(get_knowledge_edge_repository)]
DiagnosisRepo = Annotated[SqlAlchemyDiagnosisRepository, Depends(get_diagnosis_repository)]
InterventionRepo = Annotated[SqlAlchemyInterventionRepository, Depends(get_intervention_repository)]
ModalityPreferenceRepo = Annotated[
    SqlAlchemyModalityPreferenceRepository, Depends(get_modality_preference_repository)
]
CompanionSessionRepo = Annotated[
    SqlAlchemyCompanionSessionRepository, Depends(get_companion_session_repository)
]
CompanionActivityRepo = Annotated[
    SqlAlchemyCompanionActivityRepository, Depends(get_companion_activity_repository)
]
CompanionTaskRepo = Annotated[
    SqlAlchemyCompanionTaskRepository, Depends(get_companion_task_repository)
]
CompanionLoopStateRepo = Annotated[
    SqlAlchemyCompanionLoopStateRepository, Depends(get_companion_loop_state_repository)
]
CompanionSamplingEventRepo = Annotated[
    SqlAlchemyCompanionSamplingEventRepository, Depends(get_companion_sampling_event_repository)
]
AcquisitionStateRepo = Annotated[
    SqlAlchemyAcquisitionStateRepository, Depends(get_acquisition_state_repository)
]
LearningPathRepo = Annotated[SqlAlchemyLearningPathRepository, Depends(get_learning_path_repository)]
ConversationRepo = Annotated[SqlAlchemyConversationRepository, Depends(get_conversation_repository)]
ScenarioAttemptRepo = Annotated[SqlAlchemyScenarioAttemptRepository, Depends(get_scenario_attempt_repository)]
UserAICredentialRepo = Annotated[
    SqlAlchemyUserAICredentialRepository, Depends(get_user_ai_credential_repository)
]
ConversationCorrectionFeedbackRepo = Annotated[
    SqlAlchemyConversationCorrectionFeedbackRepository, Depends(get_conversation_correction_feedback_repository)
]
# The deployment-wide provider with no per-user BYOK resolution — every
# route that serves an AI feature to a signed-in user now depends on
# PerUserAIProvider/PerActorAIProvider instead (see resolve_ai_provider_for_
# user's docstring below), which fall back to this exact dependency when a
# user has no usable credential of their own. Kept as its own name for a
# genuinely deployment-scoped caller (e.g. a future background job with no
# single user to resolve a credential for) rather than removed as unused.
OptionalAIProvider = Annotated[AIProvider | None, Depends(get_ai_provider)]


def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)], user_repo: UserRepo) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error
    subject = decode_access_token(token)
    if subject is None:
        raise credentials_error
    user = user_repo.get_by_id(int(subject))
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_ai_provider_for_user(current_user: CurrentUser, db: DbSession) -> AIProvider | None:
    return resolve_ai_provider_for_user(current_user.id, db)


PerUserAIProvider = Annotated[AIProvider | None, Depends(get_ai_provider_for_user)]


def rate_limit_ai(current_user: CurrentUser, limiter: RateLimiter) -> None:
    """Shared by enrich, converse, evaluate-scenario and generate-path — all
    occupy a local model for seconds per call, so they share one budget
    rather than each getting a separate one a caller could add together."""
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_ai_requests,
        window=timedelta(seconds=settings_.rate_limit_ai_window_seconds),
    )
    _enforce_rate_limit(limiter, "ai_generation", f"user:{current_user.id}", rule)


def rate_limit_ai_credential_write(current_user: CurrentUser, limiter: RateLimiter) -> None:
    """PUT/DELETE on a user's own BYOK AI credential — a separate budget
    from rate_limit_ai above (see Settings.rate_limit_ai_credential_writes'
    own comment): that one governs generation calls, this one governs
    writes to the encrypted-credential path, which is a different abuse
    surface (repeatedly probing accepted payload shapes, hammering
    encrypt/decrypt) with no reason to share a budget with ordinary AI
    usage or be starved by it."""
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_ai_credential_writes,
        window=timedelta(seconds=settings_.rate_limit_ai_credential_write_window_seconds),
    )
    _enforce_rate_limit(limiter, "ai_credential_write", f"user:{current_user.id}", rule)


def rate_limit_import_url(current_user: CurrentUser, limiter: RateLimiter) -> None:
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_fetch_requests,
        window=timedelta(seconds=settings_.rate_limit_fetch_window_seconds),
    )
    _enforce_rate_limit(limiter, "import_url", f"user:{current_user.id}", rule)


def rate_limit_import_upload(current_user: CurrentUser, limiter: RateLimiter) -> None:
    settings_ = get_settings()
    rule = RateLimitRule(
        limit=settings_.rate_limit_upload_requests,
        window=timedelta(seconds=settings_.rate_limit_upload_window_seconds),
    )
    _enforce_rate_limit(limiter, "import_upload", f"user:{current_user.id}", rule)


def get_current_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
