from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_effective_ai_settings, get_settings
from app.domain.entities import User
from app.domain.services.ai_provider import AIProvider
from app.domain.services.rate_limiter import InProcessRateLimiter, RateLimitRule
from app.domain.value_objects import UserRole
from app.infrastructure.ai import build_ai_provider
from app.infrastructure.db import get_db
from app.infrastructure.repositories import (
    SqlAlchemyDesktopNotificationRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyConversationRepository,
    SqlAlchemyScenarioAttemptRepository,
    SqlAlchemyLearningPathRepository,
    SqlAlchemyMistakeEventRepository,
    SqlAlchemyWordRevisionRepository,
    SqlAlchemyLearningObservationRepository,
    SqlAlchemyKnowledgeEdgeRepository,
    SqlAlchemyDiagnosisRepository,
    SqlAlchemyInterventionRepository,
    SqlAlchemyCompanionSessionRepository,
    SqlAlchemyCompanionActivityRepository,
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
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)
from app.infrastructure.security import decode_access_token

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


def get_companion_session_repository(db: DbSession) -> SqlAlchemyCompanionSessionRepository:
    return SqlAlchemyCompanionSessionRepository(db)


def get_companion_activity_repository(db: DbSession) -> SqlAlchemyCompanionActivityRepository:
    return SqlAlchemyCompanionActivityRepository(db)


def get_acquisition_state_repository(db: DbSession) -> SqlAlchemyAcquisitionStateRepository:
    return SqlAlchemyAcquisitionStateRepository(db)


def get_learning_path_repository(db: DbSession) -> SqlAlchemyLearningPathRepository:
    return SqlAlchemyLearningPathRepository(db)


def get_conversation_repository(db: DbSession) -> SqlAlchemyConversationRepository:
    return SqlAlchemyConversationRepository(db)


def get_scenario_attempt_repository(db: DbSession) -> SqlAlchemyScenarioAttemptRepository:
    return SqlAlchemyScenarioAttemptRepository(db)


@lru_cache
def _ai_provider() -> AIProvider | None:
    """Built once per process, not per request — the Ollama adapter owns a
    pooled HTTP client that would otherwise be recreated on every call."""
    return build_ai_provider(get_effective_ai_settings())


def get_ai_provider() -> AIProvider | None:
    return _ai_provider()


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
CompanionSessionRepo = Annotated[
    SqlAlchemyCompanionSessionRepository, Depends(get_companion_session_repository)
]
CompanionActivityRepo = Annotated[
    SqlAlchemyCompanionActivityRepository, Depends(get_companion_activity_repository)
]
AcquisitionStateRepo = Annotated[
    SqlAlchemyAcquisitionStateRepository, Depends(get_acquisition_state_repository)
]
LearningPathRepo = Annotated[SqlAlchemyLearningPathRepository, Depends(get_learning_path_repository)]
ConversationRepo = Annotated[SqlAlchemyConversationRepository, Depends(get_conversation_repository)]
ScenarioAttemptRepo = Annotated[SqlAlchemyScenarioAttemptRepository, Depends(get_scenario_attempt_repository)]
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
