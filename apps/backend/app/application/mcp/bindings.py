"""Concrete MCP handlers that delegate to application use cases only.

Every handler here must build its own response shape rather than reach for
a bigger one and hope nobody notices an extra field. In particular:
`word_to_response` (used by the pre-existing word-returning tools below)
currently serializes `Word.mnemonic` unredacted — issue #192's gap, fixed on
a parallel branch. The five issue #188 tools added below
(`get_language_profile`/`check_known_term`/`explain_for_user`/
`suggest_stretch_vocabulary`/`record_context_occurrence`) deliberately never
call `word_to_response` and never include `mnemonic` or any other private
field in their own response dicts, so they do not share that leak.
"""
import uuid
from typing import Any

from app.api.mappers import word_to_companion_view, word_to_response
from app.application.use_cases.mcp_dev_workflow import (
    CheckKnownTermUseCase,
    ContextOccurrenceInput,
    ExplainWordForUserUseCase,
    GetLanguageProfileUseCase,
    RecordContextOccurrenceUseCase,
    SuggestStretchVocabularyUseCase,
)
from app.application.use_cases.vocabulary import AddWordUseCase, SearchWordsUseCase, WordInput
from app.application.use_cases.review import GetWeeklyProgressUseCase, StartReviewSessionUseCase, SubmitAnswerUseCase
from app.application.use_cases.practice import GenerateExerciseUseCase
from app.application.use_cases.extract import ExtractVocabularyUseCase
from app.application.use_cases.vocabulary import _require_word_owner
from app.application.use_cases.companion_activities import (
    BeginLearningActivityUseCase,
    ExplainActivityEvidenceUseCase,
    RequestActivityHintUseCase,
    SubmitActivityResponseUseCase,
)
from app.application.use_cases.companion_sessions import (
    FinishCompanionSessionUseCase,
    GetCompanionSessionUseCase,
    StartCompanionSessionUseCase,
    TransitionCompanionSessionUseCase,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from app.domain.repositories import (
    CompanionActivityRepository,
    CompanionSessionRepository,
    DiagnosisRepository,
    GroupRepository,
    LearningObservationRepository,
    PracticeExerciseRepository,
    RecallSettingsRepository,
    WordRepository,
)
from app.domain.repositories import ReviewSessionRepository
from app.domain.services.companion_activities import (
    MAX_HINTS_PER_ACTIVITY,
    ActivityStatus,
    ActivityType,
    LearningActivity,
)
from app.domain.services.companion_sessions import CompanionSession, CompanionSessionStatus
from app.domain.value_objects import SupportedLanguage
from app.domain.value_objects import ReviewOutcome, SessionMode, utcnow
from app.domain.services.spaced_repetition import Scheduler
from app.domain.services.ai_provider import AIProvider


def _decode_cursor(cursor: Any) -> int:
    """An offset encoded as an opaque string. Anything absent, empty, or not
    a non-negative integer starts from the first page — a malformed cursor
    fails open to page one rather than erroring, since a client that lost
    its cursor should see the start of the list again, not a hard failure.
    """
    if not isinstance(cursor, str) or not cursor:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return value if value >= 0 else 0


def _encode_cursor(offset: int) -> str:
    return str(offset)


def _paginate(items: list, limit: int, offset: int) -> tuple[list, str | None]:
    """Real cursor-based paging over a page fetched one row oversized:
    `items` must already have been requested with `limit + 1` rows starting
    at `offset`. Slices back down to `limit` and reports a `next_cursor`
    only when that extra row proved there is more — never a cosmetic
    `None` regardless of how much data actually exists.
    """
    has_more = len(items) > limit
    page = items[:limit]
    next_cursor = _encode_cursor(offset + limit) if has_more else None
    return page, next_cursor


def add_word_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word = AddWordUseCase(words, groups).execute(
            user_id,
            int(payload["group_id"]),
            WordInput(
                term=str(payload["term"]), target_language=SupportedLanguage(payload["target_language"]),
                translations=[str(value) for value in payload.get("translations", [])],
            ),
        )
        return word_to_response(word).model_dump(mode="json")
    return handle


def due_reviews_handler(words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        group_id = int(payload["group_id"]) if payload.get("group_id") is not None else None
        offset = _decode_cursor(payload.get("cursor"))
        fetched = words.list_due_for_user(user_id, limit + 1, group_id, offset)
        page, next_cursor = _paginate(fetched, limit, offset)
        # Redacted, not `word_to_response`: this handler backs the
        # `lensword://me/due` MCP resource (and the equivalent tool call),
        # both read by an AI companion rather than the learner's own client
        # — see `CompanionWordView`'s docstring for why mnemonics never
        # reach this surface (issue #192 TODO 0).
        return {"items": [word_to_companion_view(word).model_dump(mode="json") for word in page], "next_cursor": next_cursor}
    return handle


def search_words_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        offset = _decode_cursor(payload.get("cursor"))
        fetched = SearchWordsUseCase(words, groups).execute(user_id, str(payload.get("query", "")), limit + 1, offset)
        page, next_cursor = _paginate(fetched, limit, offset)
        # Redacted for the same reason as `due_reviews_handler` above — this
        # backs `lensword://me/active-words`.
        return {"items": [word_to_companion_view(word).model_dump(mode="json") for word in page], "next_cursor": next_cursor}
    return handle


def learning_progress_handler(sessions: ReviewSessionRepository):
    def handle(user_id: int, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"weekly_counts": GetWeeklyProgressUseCase(sessions).execute(user_id)}
    return handle


def generate_exercises_handler(exercises: PracticeExerciseRepository, words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word = _require_word_owner(words, groups, int(payload["word_id"]), user_id)
        exercise = GenerateExerciseUseCase(exercises, words).execute(user_id, word, str(payload.get("kind", "translation")))
        return {"id": exercise.id, "word_id": exercise.word_id, "kind": exercise.kind, "prompt": exercise.prompt, "options": exercise.options}
    return handle


def create_study_session_handler(sessions, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        session, due_words = StartReviewSessionUseCase(sessions, words).execute(user_id, SessionMode.STANDARD, payload.get("group_id"), min(int(payload.get("limit", 20)), 100))
        return {"session_id": session.id, "words": [word_to_response(word).model_dump(mode="json") for word in due_words]}
    return handle


def record_answer_handler(sessions, words: WordRepository, scheduler: Scheduler):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = SubmitAnswerUseCase(sessions, words, scheduler).execute(user_id, int(payload["session_id"]), int(payload["word_id"]), ReviewOutcome(payload["outcome"]), payload.get("response_time_ms"))
        return {"word": word_to_response(result.word).model_dump(mode="json"), "was_new_word_learned": result.was_new_word}
    return handle


def extract_vocabulary_handler(groups: GroupRepository, provider: AIProvider | None):
    async def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        items, source = await ExtractVocabularyUseCase(groups, provider).execute(user_id, int(payload["group_id"]), str(payload["text"]), payload.get("source_language"), str(payload["target_language"]), min(int(payload.get("max_items", 20)), 50), payload.get("min_level"))
        return {"source": source, "items": [{"term": item.term, "translations": item.translations, "examples": item.examples, "cefr_level": item.cefr_level} for item in items]}
    return handle


def _companion_session_to_dict(session: CompanionSession) -> dict[str, Any]:
    """The MCP tool surface's view of a session (#193 TODO 1) — the same
    fields the REST `CompanionSessionResponse` exposes (see
    app.api.routers.companion._session_response), minus the turn list: a
    tool result stays a bounded summary, and the full transcript is what the
    `lensword://session/{session_id}` resource is for."""
    return {
        "id": session.id,
        "connection_id": session.connection_id,
        "client_id": session.client_id,
        "goal": session.goal,
        "language": session.language,
        "group_id": session.group_id,
        "difficulty": session.difficulty,
        "active_activity": session.active_activity,
        "summary": session.summary,
        "status": session.status.value,
        "revision": session.revision,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _require_companion_enabled(settings: RecallSettingsRepository, user_id: int) -> None:
    """Same gate as app.api.routers.companion._require_enabled: the MCP
    tool surface must not be a back door around the per-account
    `ai_companion_enabled` flag that the REST endpoints enforce."""
    record = settings.get_by_user(user_id)
    if not record or not record.ai_companion_enabled:
        raise PermissionDeniedError("AI Companion is not enabled")


def start_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session = StartCompanionSessionUseCase(sessions).execute(
            user_id,
            connection_id=str(payload["connection_id"]),
            client_id=str(payload["client_id"]),
            goal=payload.get("goal"),
            language=payload.get("language"),
            group_id=int(payload["group_id"]) if payload.get("group_id") is not None else None,
            difficulty=payload.get("difficulty"),
            active_activity=payload.get("active_activity"),
        )
        return _companion_session_to_dict(session)
    return handle


def get_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session = GetCompanionSessionUseCase(sessions).execute(user_id, str(payload["session_id"]))
        return _companion_session_to_dict(session)
    return handle


def _companion_transition_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository, action: str):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        try:
            session = TransitionCompanionSessionUseCase(sessions).execute(
                user_id, str(payload["session_id"]), lambda s: getattr(s, action)()
            )
        except ValueError as exc:
            # An invalid transition (e.g. resuming a revoked session) is a
            # plain ValueError from the domain object, not a DomainError —
            # the REST router catches it itself, but nothing upstream of an
            # MCP handler does, and an uncaught ValueError here would surface
            # as an opaque 500 instead of the clean 400 every other MCP
            # validation failure gets from main.py's DomainError handler.
            raise ValidationError(str(exc)) from exc
        return _companion_session_to_dict(session)
    return handle


def resume_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    return _companion_transition_handler(sessions, settings, "resume")


def pause_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    return _companion_transition_handler(sessions, settings, "pause")


def finish_companion_session_handler(
    sessions: CompanionSessionRepository, settings: RecallSettingsRepository, provider: AIProvider | None
):
    async def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        try:
            session = await FinishCompanionSessionUseCase(sessions, provider).execute(user_id, str(payload["session_id"]))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return _companion_session_to_dict(session)
    return handle


def language_profile_handler(groups: GroupRepository, words: WordRepository):
    def handle(user_id: int, _payload: dict[str, Any]) -> dict[str, Any]:
        profile = GetLanguageProfileUseCase(groups, words).execute(user_id)
        return {
            "target_languages": list(profile.target_languages),
            "known_word_count": profile.known_word_count,
            "active_word_count": profile.active_word_count,
            "total_word_count": profile.total_word_count,
            "group_count": profile.group_count,
        }
    return handle


def check_known_term_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = CheckKnownTermUseCase(words, groups).execute(user_id, str(payload["term"]))
        return {
            "term": result.term,
            "known": result.known,
            "active": result.active,
            "matches": [
                {
                    "word_id": match.word_id, "target_language": match.target_language,
                    "cefr_level": match.cefr_level, "known": match.known, "active": match.active,
                }
                for match in result.matches
            ],
        }
    return handle


def explain_for_user_handler(words: WordRepository, groups: GroupRepository, diagnoses: DiagnosisRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = ExplainWordForUserUseCase(words, groups, diagnoses).execute(user_id, int(payload["word_id"]))
        return {
            "word_id": result.word_id, "term": result.term, "target_language": result.target_language,
            "cefr_level": result.cefr_level, "has_diagnosis": result.has_diagnosis,
            "diagnosis_outcome": result.diagnosis_outcome, "diagnosis_confidence": result.diagnosis_confidence,
            "sample_size": result.sample_size, "explanation": result.explanation,
        }
    return handle


def suggest_stretch_vocabulary_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        group_id = int(payload["group_id"]) if payload.get("group_id") is not None else None
        limit = int(payload["limit"]) if payload.get("limit") is not None else None
        suggestions = SuggestStretchVocabularyUseCase(words, groups).execute(user_id, group_id, limit)
        return {
            "items": [
                {
                    "word_id": item.word_id, "term": item.term, "target_language": item.target_language,
                    "cefr_level": item.cefr_level, "reason": item.reason,
                }
                for item in suggestions
            ]
        }
    return handle


def record_context_occurrence_handler(
    words: WordRepository, groups: GroupRepository, observations: LearningObservationRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        data = ContextOccurrenceInput(
            word_id=int(payload["word_id"]), context_kind=str(payload["context_kind"]),
            outcome=str(payload["outcome"]), confirmed=bool(payload["confirmed"]),
            operation_id=payload.get("request_id"),
        )
        result = RecordContextOccurrenceUseCase(words, groups, observations).execute(user_id, data)
        return {
            "observation_id": result.observation_id, "word_id": result.word_id,
            "context_source": result.context_source, "outcome": result.outcome,
            "recorded_at": result.recorded_at.isoformat(),
        }
    return handle


# --- Measurable companion activities (#194 TODO 1) --------------------------
#
# Follows #193's own five session tools above exactly: each handler resolves
# the owning session first (a 404-shaped EntityNotFoundError, never a bare
# KeyError), gates on `ai_companion_enabled` the same way, and delegates the
# actual work to the same application use cases the REST router
# (app.api.routers.companion_activities) calls — so an activity begun over
# MCP and one begun over REST behave identically, the same cross-client
# guarantee #193's docstring calls out for companion sessions.


def _companion_activity_to_dict(activity: LearningActivity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "session_id": activity.session_id,
        "activity_type": activity.activity_type.value,
        "prompt": activity.prompt,
        "expected_evaluation": activity.expected_evaluation,
        "status": activity.status.value,
        "response": activity.response,
        "result": activity.result,
        "operation_id": activity.operation_id,
        "started_at": activity.started_at.isoformat(),
        "updated_at": activity.updated_at.isoformat(),
        "revision": activity.revision,
        "hints_used": activity.hints_used,
    }


def _require_companion_session(sessions: CompanionSessionRepository, user_id: int, session_id: str) -> CompanionSession:
    session = sessions.get(user_id, session_id)
    if session is None:
        raise EntityNotFoundError("Companion session", session_id)
    return session


def _require_companion_activity(
    activities: CompanionActivityRepository, user_id: int, session_id: str, activity_id: str
) -> LearningActivity:
    activity = activities.get(user_id, session_id, activity_id)
    if activity is None:
        raise EntityNotFoundError("Companion activity", activity_id)
    return activity


def begin_learning_activity_handler(
    activities: CompanionActivityRepository,
    sessions: CompanionSessionRepository,
    settings: RecallSettingsRepository,
    words: WordRepository,
    groups: GroupRepository,
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        session = _require_companion_session(sessions, user_id, session_id)
        if session.status is not CompanionSessionStatus.ACTIVE:
            raise ValidationError("Session is not active")
        try:
            activity_type = ActivityType(str(payload["activity_type"]))
        except ValueError as exc:
            raise ValidationError("Unsupported activity type") from exc
        expected_evaluation = payload.get("expected_evaluation") or {}
        if not isinstance(expected_evaluation, dict):
            raise ValidationError("expected_evaluation must be an object")
        # The evaluation rule is validated and fixed here, once (#194 TODO
        # 5) — nothing downstream, including `submit_activity_response`
        # below, can change it afterward.
        BeginLearningActivityUseCase(words, groups).validate(user_id, activity_type, expected_evaluation)
        request_id = payload.get("request_id")
        now = utcnow()
        activity = activities.add(
            LearningActivity(
                id=uuid.uuid4().hex,
                session_id=session_id,
                user_id=user_id,
                activity_type=activity_type,
                prompt=str(payload["prompt"]),
                expected_evaluation=expected_evaluation,
                status=ActivityStatus.ACTIVE,
                response=None,
                result=None,
                operation_id=str(request_id) if request_id else None,
                started_at=now,
                updated_at=now,
            )
        )
        return _companion_activity_to_dict(activity)
    return handle


def submit_activity_response_handler(
    activities: CompanionActivityRepository,
    sessions: CompanionSessionRepository,
    settings: RecallSettingsRepository,
    observations: LearningObservationRepository,
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        _require_companion_session(sessions, user_id, session_id)
        activity = _require_companion_activity(activities, user_id, session_id, str(payload["activity_id"]))
        try:
            result = SubmitActivityResponseUseCase(activities, observations).execute(
                user_id, activity, str(payload["response"])
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return _companion_activity_to_dict(result.activity)
    return handle


def get_activity_result_handler(
    activities: CompanionActivityRepository, sessions: CompanionSessionRepository, settings: RecallSettingsRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        _require_companion_session(sessions, user_id, session_id)
        activity = _require_companion_activity(activities, user_id, session_id, str(payload["activity_id"]))
        return _companion_activity_to_dict(activity)
    return handle


def finish_learning_activity_handler(
    activities: CompanionActivityRepository, sessions: CompanionSessionRepository, settings: RecallSettingsRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        _require_companion_session(sessions, user_id, session_id)
        activity = _require_companion_activity(activities, user_id, session_id, str(payload["activity_id"]))
        try:
            activity.finish()
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        activity.updated_at = utcnow()
        return _companion_activity_to_dict(activities.update(activity))
    return handle


def request_hint_handler(
    activities: CompanionActivityRepository,
    sessions: CompanionSessionRepository,
    settings: RecallSettingsRepository,
    words: WordRepository,
    groups: GroupRepository,
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        _require_companion_session(sessions, user_id, session_id)
        activity = _require_companion_activity(activities, user_id, session_id, str(payload["activity_id"]))
        try:
            updated, hint = RequestActivityHintUseCase(activities, words, groups).execute(user_id, activity)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return {
            "activity": _companion_activity_to_dict(updated),
            "hint": hint,
            "hints_used": updated.hints_used,
            "hints_remaining": max(0, MAX_HINTS_PER_ACTIVITY - updated.hints_used),
        }
    return handle


def explain_evidence_handler(
    activities: CompanionActivityRepository,
    sessions: CompanionSessionRepository,
    settings: RecallSettingsRepository,
    words: WordRepository,
    groups: GroupRepository,
    diagnoses: DiagnosisRepository,
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session_id = str(payload["session_id"])
        _require_companion_session(sessions, user_id, session_id)
        activity = _require_companion_activity(activities, user_id, session_id, str(payload["activity_id"]))
        return ExplainActivityEvidenceUseCase(words, groups, diagnoses).execute(user_id, activity)
    return handle
