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
from app.domain.repositories import (
    DiagnosisRepository,
    GroupRepository,
    LearningObservationRepository,
    PracticeExerciseRepository,
    WordRepository,
)
from app.domain.repositories import ReviewSessionRepository
from app.domain.value_objects import SupportedLanguage
from app.domain.value_objects import ReviewOutcome, SessionMode
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
