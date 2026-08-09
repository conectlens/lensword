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
    RecordContextOccurrencesUseCase,
    SuggestStretchVocabularyUseCase,
)
from app.application.use_cases.vocabulary import AddWordUseCase, SearchWordsUseCase, WordInput
from app.application.use_cases.vocabulary import (
    AddWordsUseCase,
    BulkEditWordsUseCase,
    BulkFieldEdit,
    CreateGroupUseCase,
    CreateRoomUseCase,
    DeleteWordUseCase,
    GetGroupDetailUseCase,
    GetRoomDetailUseCase,
    ListGroupsUseCase,
    ListRoomsUseCase,
    PlacementInput,
    PlaceWordsUseCase,
    PlaceWordUseCase,
    UpdateWordUseCase,
    _require_group_owner,
)
from app.application.use_cases.knowledge_graph import graph_for_user
from app.application.use_cases.review import (
    AddMnemonicUseCase,
    GetWeeklyProgressUseCase,
    ListMnemonicsUseCase,
    StartReviewSessionUseCase,
    SubmitAnswerUseCase,
    SuggestMnemonicUseCase,
)
from app.application.use_cases.practice import GenerateExerciseUseCase, GenerateExercisesUseCase
from app.application.use_cases.extract import ExtractVocabularyUseCase
from app.application.use_cases.companion_tasks import (
    CancelCompanionTaskUseCase,
    CreateExtractionTaskUseCase,
    GetCompanionTaskUseCase,
)
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
from app.domain.exceptions import EntityNotFoundError, NoWordsDueError, PermissionDeniedError, ValidationError
from app.domain.repositories import (
    CompanionActivityRepository,
    CompanionSessionRepository,
    CompanionTaskRepository,
    DiagnosisRepository,
    GroupRepository,
    KnowledgeEdgeRepository,
    LearningObservationRepository,
    MnemonicRepository,
    PracticeExerciseRepository,
    RecallSettingsRepository,
    RoomRepository,
    WordRepository,
)
from app.domain.repositories import ReviewSessionRepository
from app.domain.services.companion_tasks import CompanionTask
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


def _language(value: Any) -> SupportedLanguage:
    """Coerce a caller-supplied language code, failing as a *domain* error.

    `SupportedLanguage(value)` raises a bare `ValueError` for an unrecognised
    code, and `ValueError` is not a `DomainError` — so it slipped straight
    past main.py's `handle_domain_error` and became an unhandled 500, whose
    body Starlette renders as **plain text**, not JSON. The MCP client
    parses error bodies for a `detail` field, found none, and fell back to
    the literal "LensWord request failed" — identical for every cause, which
    is exactly the opaque failure an audit of this surface flagged as its
    worst error experience. Raising `ValidationError` here routes the same
    condition through the 400 handler with a message naming the accepted
    values, so the caller can fix the call instead of guessing.
    """
    try:
        return SupportedLanguage(value)
    except ValueError as exc:
        supported = ", ".join(sorted(item.value for item in SupportedLanguage))
        raise ValidationError(
            f"target_language {value!r} is not supported (expected one of: {supported})"
        ) from exc


def add_word_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word = AddWordUseCase(words, groups).execute(
            user_id,
            int(payload["group_id"]),
            WordInput(
                term=str(payload["term"]), target_language=_language(payload["target_language"]),
                translations=[str(value) for value in payload.get("translations", [])],
            ),
        )
        return word_to_response(word).model_dump(mode="json")
    return handle


def add_words_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        language = _language(payload["target_language"])
        result = AddWordsUseCase(words, groups).execute(
            user_id,
            int(payload["group_id"]),
            [
                WordInput(
                    term=str(item["term"]), target_language=language,
                    translations=[str(value) for value in item.get("translations", [])],
                )
                for item in payload["items"]
            ],
        )
        return {
            "added": [word_to_response(word).model_dump(mode="json") for word in result.added],
            "skipped": [{"index": item.index, "reason": item.reason} for item in result.skipped],
        }
    return handle


def update_words_handler(words: WordRepository, groups: GroupRepository, revisions):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = BulkEditWordsUseCase(words, groups, revisions).execute(
            user_id,
            [int(word_id) for word_id in payload["word_ids"]],
            BulkFieldEdit(
                cefr_level=payload.get("cefr_level"),
                part_of_speech=payload.get("part_of_speech"),
                category=payload.get("category"),
                tags=[str(tag) for tag in payload["tags"]] if payload.get("tags") is not None else None,
            ),
        )
        return {"updated": result.updated, "skipped": list(result.skipped)}
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


def generate_exercises_for_words_handler(exercises: PracticeExerciseRepository, words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = GenerateExercisesUseCase(exercises, words, groups).execute(
            user_id,
            [int(word_id) for word_id in payload["word_ids"]],
            str(payload.get("kind", "translation")),
        )
        return {
            "applied": [
                {"id": item.id, "word_id": item.word_id, "kind": item.kind, "prompt": item.prompt, "options": item.options}
                for item in result.applied
            ],
            "skipped": [{"word_id": item.word_id, "reason": item.reason} for item in result.skipped],
        }
    return handle


def create_study_session_handler(sessions, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            session, due_words = StartReviewSessionUseCase(sessions, words).execute(user_id, SessionMode.STANDARD, payload.get("group_id"), min(int(payload.get("limit", 20)), 100))
        except NoWordsDueError:
            # "Nothing is due" is a normal, expected state of a healthy
            # schedule, not a failure of the call. Raising here made the
            # caller parse an error string to distinguish "you are caught
            # up" from "something went wrong"; returning the same shape with
            # an empty list lets it branch on `words` being empty and read
            # `reason` if it wants to say why. The REST route keeps raising,
            # since its client renders that message directly.
            return {"session_id": None, "words": [], "reason": "no_words_due"}
        return {"session_id": session.id, "words": [word_to_response(word).model_dump(mode="json") for word in due_words], "reason": None}
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


def _companion_task_response(task: CompanionTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "task_type": task.task_type.value,
        "status": task.status.value,
        "total_units": task.total_units,
        "completed_units": task.completed_units,
        "progress": task.progress,
        "result": task.result,
        "error": task.error,
        "expires_at": task.expires_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "revision": task.revision,
    }


def start_extraction_task_handler(
    task_repo: CompanionTaskRepository, sessions: CompanionSessionRepository, settings: RecallSettingsRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        task = CreateExtractionTaskUseCase(task_repo, sessions, settings).execute(
            user_id,
            str(payload["companion_session_id"]),
            str(payload["text"]),
            str(payload["target_language"]),
            int(payload.get("max_terms", 20)),
            payload.get("request_id"),
        )
        return _companion_task_response(task)
    return handle


def get_companion_task_handler(
    task_repo: CompanionTaskRepository, sessions: CompanionSessionRepository, settings: RecallSettingsRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        task = GetCompanionTaskUseCase(task_repo, sessions, settings).execute(
            user_id, str(payload["companion_session_id"]), str(payload["task_id"])
        )
        return _companion_task_response(task)
    return handle


def cancel_companion_task_handler(
    task_repo: CompanionTaskRepository, sessions: CompanionSessionRepository, settings: RecallSettingsRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        task = CancelCompanionTaskUseCase(task_repo, sessions, settings).execute(
            user_id, str(payload["companion_session_id"]), str(payload["task_id"])
        )
        return _companion_task_response(task)
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
        target_language = payload.get("target_language")
        result = CheckKnownTermUseCase(words, groups).execute(
            user_id, str(payload["term"]), str(target_language) if target_language else None
        )
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


def record_context_occurrences_handler(
    words: WordRepository, groups: GroupRepository, observations: LearningObservationRepository
):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = RecordContextOccurrencesUseCase(words, groups, observations).execute(
            user_id,
            word_ids=[int(word_id) for word_id in payload["word_ids"]],
            context_kind=str(payload["context_kind"]),
            outcome=str(payload["outcome"]),
            confirmed=bool(payload["confirmed"]),
            # One request_id per call, but observations dedupe individually —
            # the use case derives a per-item operation id from this so a
            # retried partial batch converges instead of duplicating or
            # silently skipping the items after the first.
            operation_id=payload.get("request_id"),
        )
        return {
            "applied": [
                {
                    "observation_id": item.observation_id, "word_id": item.word_id,
                    "context_source": item.context_source, "outcome": item.outcome,
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in result.applied
            ],
            "skipped": [{"word_id": item.word_id, "reason": item.reason} for item in result.skipped],
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


# --- Group management (Creator responsibility) ---------------------------
# `add_word` and `extract_vocabulary` both demand a `group_id` that nothing
# on this surface could produce or enumerate, so an agent had to guess an
# integer or send the learner to the web app. These two close that loop.


def create_group_handler(groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        group = CreateGroupUseCase(groups).execute(
            user_id, str(payload["name"]), _language(payload["target_language"])
        )
        return {
            "group_id": group.id,
            "name": group.name,
            "target_language": group.target_language.value,
            "created_at": group.created_at.isoformat(),
        }
    return handle


def list_groups_handler(groups: GroupRepository, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        offset = _decode_cursor(payload.get("cursor"))
        # ListGroupsUseCase returns every summary in one pass (it aggregates
        # per-group counts), so paging is applied here rather than pushed
        # into the repository. Slice one row oversized to keep `_paginate`'s
        # "is there more" contract honest.
        summaries = ListGroupsUseCase(groups, words).execute(user_id)
        page, next_cursor = _paginate(summaries[offset : offset + limit + 1], limit, offset)
        return {
            "items": [
                {
                    "group_id": item.group.id,
                    "name": item.group.name,
                    "target_language": item.group.target_language.value,
                    "word_count": item.word_count,
                    "mastered_count": item.mastered_count,
                    "due_count": item.due_count,
                    "last_reviewed_at": item.last_reviewed_at.isoformat() if item.last_reviewed_at else None,
                }
                for item in page
            ],
            "next_cursor": next_cursor,
        }
    return handle


def list_group_words_handler(groups: GroupRepository, words: WordRepository):
    _SORTS = {
        "term": lambda word: word.term.lower(),
        "added_at": lambda word: word.created_at,
        "next_review_at": lambda word: word.review_state.due_at,
    }

    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        offset = _decode_cursor(payload.get("cursor"))
        # GetGroupDetailUseCase authorizes the group and returns its words;
        # going through it rather than `words.list_by_group` is what keeps a
        # caller from reading another account's deck by id.
        _group, group_words = GetGroupDetailUseCase(groups, words).execute(user_id, int(payload["group_id"]))
        group_words = sorted(group_words, key=_SORTS[str(payload.get("sort_by", "added_at"))])
        page, next_cursor = _paginate(group_words[offset : offset + limit + 1], limit, offset)
        # Redacted for the same reason as `due_reviews_handler`: this is an
        # AI-facing enumeration of the learner's vocabulary.
        return {
            "items": [word_to_companion_view(word).model_dump(mode="json") for word in page],
            "next_cursor": next_cursor,
        }
    return handle


# --- Word lifecycle -------------------------------------------------------


def update_word_handler(words: WordRepository, groups: GroupRepository, revisions=None):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word_id = int(payload["word_id"])
        existing = _require_word_owner(words, groups, word_id, user_id)
        # UpdateWordUseCase *replaces* term/translations/example_sentence/
        # mnemonic/category outright, so every field the caller omitted has
        # to be re-sent with its current value. Sending only what changed
        # would clear the rest — the opposite of this tool's promise that an
        # edit preserves the word.
        updated = UpdateWordUseCase(words, groups, revisions).execute(
            user_id,
            word_id,
            WordInput(
                term=existing.term,
                target_language=existing.target_language,
                translations=[str(value) for value in payload["translations"]]
                if "translations" in payload
                else list(existing.translations),
                example_sentence=payload.get("example_sentence", existing.example_sentence),
                mnemonic=payload.get("mnemonic", existing.mnemonic),
                category=payload.get("category", existing.category),
            ),
        )
        # Moving between groups is a separate concern from editing fields:
        # UpdateWordUseCase has no notion of it, so the target group is
        # authorized explicitly here before the word is re-parented. Doing
        # it after the field update means a rejected move cannot leave the
        # edit half-applied to a group the caller does not own.
        target_group_id = payload.get("group_id")
        if target_group_id is not None and int(target_group_id) != updated.group_id:
            _require_group_owner(groups, int(target_group_id), user_id)
            updated.group_id = int(target_group_id)
            updated = words.update(updated)
        return word_to_companion_view(updated).model_dump(mode="json")
    return handle


def delete_word_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        # The schema already makes `confirmed` a required boolean, so this
        # re-check is about its *value*, not its presence: a caller that
        # sends `false` is explicitly declining, and the deletion must not
        # proceed. Checked before ownership resolution so a refusal reveals
        # nothing about whether the id exists.
        if not bool(payload["confirmed"]):
            raise ValidationError(
                "Refusing to delete: confirmed must be true. Deletion is permanent and "
                "removes the word's review history; use lensword_update_word to correct a word instead."
            )
        word_id = int(payload["word_id"])
        word = _require_word_owner(words, groups, word_id, user_id)
        term = word.term
        DeleteWordUseCase(words, groups).execute(user_id, word_id)
        return {"word_id": word_id, "term": term, "deleted": True}
    return handle


# --- Memory palace (method of loci) --------------------------------------


def list_rooms_handler(rooms: RoomRepository, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        offset = _decode_cursor(payload.get("cursor"))
        summaries = ListRoomsUseCase(rooms, words).execute(user_id)
        page, next_cursor = _paginate(summaries[offset : offset + limit + 1], limit, offset)
        return {
            "items": [
                {
                    "room_id": item.room.id,
                    "name": item.room.name,
                    "group_id": item.room.group_id,
                    "icon": item.room.icon,
                    "placed_count": len(item.room.placements),
                    "group_word_count": item.group_word_count,
                }
                for item in page
            ],
            "next_cursor": next_cursor,
        }
    return handle


def create_room_handler(rooms: RoomRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        room = CreateRoomUseCase(rooms, groups).execute(
            user_id,
            int(payload["group_id"]),
            str(payload["name"]),
            str(payload.get("icon", "meeting_room")),
        )
        return {"room_id": room.id, "name": room.name, "group_id": room.group_id, "icon": room.icon}
    return handle


def place_word_in_room_handler(rooms: RoomRepository, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        # PlaceWordUseCase enforces the invariants that matter here — the
        # word must belong to the room's own group, and coordinates are
        # percentages in 0..100 — inside the Room aggregate, raising
        # InvalidPlacementError rather than storing a nonsensical placement.
        room = PlaceWordUseCase(rooms, words).execute(
            user_id,
            int(payload["room_id"]),
            int(payload["word_id"]),
            float(payload["x_percent"]),
            float(payload["y_percent"]),
        )
        placement = next((item for item in room.placements if item.word_id == int(payload["word_id"])), None)
        return {
            "room_id": room.id,
            "word_id": int(payload["word_id"]),
            "x_percent": placement.x_percent if placement else None,
            "y_percent": placement.y_percent if placement else None,
            "placed_count": len(room.placements),
        }
    return handle


def place_words_in_room_handler(rooms: RoomRepository, words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        # PlaceWordsUseCase holds the same invariants the single-item path
        # does — the word must belong to the room's own group, coordinates
        # are percentages in 0..100 — but applies them all to one loaded
        # Room and saves it once, and reports rather than drops the
        # placements it could not make.
        result = PlaceWordsUseCase(rooms, words, groups).execute(
            user_id,
            int(payload["room_id"]),
            [
                PlacementInput(
                    word_id=int(item["word_id"]),
                    x_percent=float(item["x_percent"]),
                    y_percent=float(item["y_percent"]),
                )
                for item in payload["placements"]
            ],
        )
        placed = {item.word_id: item for item in result.room.placements}
        return {
            "room_id": result.room.id,
            "applied": [
                {
                    "word_id": word_id,
                    "x_percent": placed[word_id].x_percent if word_id in placed else None,
                    "y_percent": placed[word_id].y_percent if word_id in placed else None,
                }
                for word_id in result.applied
            ],
            "skipped": [{"word_id": item.word_id, "reason": item.reason} for item in result.skipped],
            "placed_count": len(result.room.placements),
        }
    return handle


# --- MnemoLab -------------------------------------------------------------
# The one surface where a mnemonic string is the point of the call rather
# than an incidental leak, so these two deliberately do not use
# `word_to_companion_view`'s redaction — see this module's docstring.


def get_mnemonics_handler(mnemonics: MnemonicRepository, words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 10)), 20)
        notes = ListMnemonicsUseCase(mnemonics, words, groups).execute(user_id, int(payload["word_id"]))
        # `MnemonicRepository.list_by_word` promises no ordering, so the
        # "strongest first" the tool description advertises is established
        # here rather than assumed from the repository.
        notes = sorted(notes, key=lambda note: (note.score, note.created_at), reverse=True)
        return {
            "items": [
                {
                    "mnemonic_id": note.id,
                    "text": note.text,
                    "score": note.score,
                    "upvotes": note.upvotes,
                    "downvotes": note.downvotes,
                    "is_ai_generated": note.is_ai_generated,
                }
                for note in notes[:limit]
            ]
        }
    return handle


def generate_mnemonic_handler(
    mnemonics: MnemonicRepository, words: WordRepository, groups: GroupRepository, provider: AIProvider | None
):
    async def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        use_case = SuggestMnemonicUseCase(words, groups, provider)
        word = use_case.resolve_word(user_id, int(payload["word_id"]))
        text = await use_case.generate(word, payload.get("style"))
        persisted = bool(payload.get("persist", False))
        mnemonic_id = None
        if persisted:
            # Flagged as AI-authored so the gallery does not attribute a
            # generated hook to the learner.
            note = AddMnemonicUseCase(mnemonics, words, groups).execute(
                user_id, int(payload["word_id"]), text, is_ai_generated=True
            )
            mnemonic_id = note.id
        return {
            "word_id": word.id,
            "term": word.term,
            "style": payload.get("style"),
            "text": text,
            "persisted": persisted,
            "mnemonic_id": mnemonic_id,
        }
    return handle


# --- Knowledge graph ------------------------------------------------------


def get_word_map_handler(words: WordRepository, groups: GroupRepository, edges: KnowledgeEdgeRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        origin = _require_word_owner(words, groups, int(payload["word_id"]), user_id)
        depth = min(int(payload.get("depth", 1)), 3)
        limit = min(int(payload.get("limit", 20)), 50)
        # `list_all_for_user` is on the concrete repository but missing from
        # the WordRepository Protocol; graph.py's own read path calls it the
        # same way. Scoping to the caller's words is what keeps the walk
        # from ever crossing into another account's graph.
        owned = words.list_all_for_user(user_id)
        graph = graph_for_user(owned, edges, user_id)
        terms = {word.id: word.term for word in owned}

        seen = {origin.id}
        frontier = [origin.id]
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        for hop in range(1, depth + 1):
            next_frontier: list[int] = []
            for source_id in frontier:
                for edge in graph.related(source_id, limit=limit):
                    other_id = edge.target_id if edge.source_id == source_id else edge.source_id
                    links.append({
                        "from_word_id": source_id,
                        "to_word_id": other_id,
                        "relation": edge.relation.value,
                        "strength": round(edge.strength, 3),
                        "evidence": edge.evidence,
                    })
                    if other_id in seen:
                        continue
                    seen.add(other_id)
                    next_frontier.append(other_id)
                    nodes.append({"word_id": other_id, "term": terms.get(other_id), "hop": hop})
            if len(nodes) >= limit:
                break
            frontier = next_frontier
            if not frontier:
                break
        return {
            "word_id": origin.id,
            "term": origin.term,
            "depth": depth,
            "nodes": nodes[:limit],
            "links": links[: limit * 2],
        }
    return handle
