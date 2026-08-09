from dataclasses import dataclass

from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.entities import DailySessionPreference, PracticeExercise, Word
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import (
    DailySessionPreferenceRepository,
    GroupRepository,
    PracticeExerciseRepository,
    WordRepository,
)


class GenerateExerciseUseCase:
    def __init__(self, exercises: PracticeExerciseRepository, words: WordRepository):
        self.exercises = exercises
        self.words = words

    def execute(self, user_id: int, word: Word, kind: str) -> PracticeExercise:
        answer = (word.translations[0] if word.translations else word.term).strip()
        prompt = {
            "translation": f"Translate '{word.term}'.",
            "definition": f"Write a short definition of '{word.term}'.",
            "cloze": f"Use '{word.term}' in a sentence.",
        }.get(kind, f"Translate '{word.term}'.")
        return self.exercises.add(
            PracticeExercise(
                id=None, user_id=user_id, word_id=word.id or 0, kind=kind, prompt=prompt,
                answer=answer, options=[answer, word.term],
            )
        )


@dataclass(frozen=True, slots=True)
class SkippedExercise:
    word_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class GenerateExercisesResult:
    applied: tuple[PracticeExercise, ...]
    skipped: tuple[SkippedExercise, ...]


class GenerateExercisesUseCase:
    """Generate exercises for several words in one call.

    Unlike batched room placement, there is no shared aggregate here — this
    is a pure per-word transform, so the only saving is round trips, and the
    per-word ownership check is kept exactly as the single-item path performs
    it. Batching must change how often ownership is checked, never whether.
    """

    def __init__(
        self,
        exercises: PracticeExerciseRepository,
        words: WordRepository,
        groups: GroupRepository,
    ):
        self.exercises = exercises
        self.words = words
        self.groups = groups

    def execute(self, user_id: int, word_ids: list[int], kind: str) -> GenerateExercisesResult:
        single = GenerateExerciseUseCase(self.exercises, self.words)
        applied: list[PracticeExercise] = []
        skipped: list[SkippedExercise] = []
        for word_id in word_ids:
            try:
                word = _require_word_owner(self.words, self.groups, word_id, user_id)
            except (EntityNotFoundError, PermissionDeniedError):
                # One reason for both, so a batch cannot be used to probe
                # which word ids exist under other accounts.
                skipped.append(SkippedExercise(word_id, "word_not_found"))
                continue
            applied.append(single.execute(user_id, word, kind))
        return GenerateExercisesResult(applied=tuple(applied), skipped=tuple(skipped))


class AnswerExerciseUseCase:
    def __init__(self, exercises: PracticeExerciseRepository):
        self.exercises = exercises

    def execute(self, user_id: int, exercise_id: int, response: str) -> PracticeExercise:
        exercise = self.exercises.get_by_id(exercise_id)
        if exercise is None:
            raise EntityNotFoundError("PracticeExercise", exercise_id)
        if exercise.user_id != user_id:
            raise PermissionDeniedError("This exercise belongs to another account")
        exercise.answered = True
        exercise.correct = response.strip().casefold() == exercise.answer.strip().casefold()
        return self.exercises.update(exercise)


class GetDailySessionUseCase:
    def __init__(self, preferences: DailySessionPreferenceRepository, words: WordRepository):
        self.preferences = preferences
        self.words = words

    def execute(self, user_id: int) -> tuple[DailySessionPreference, int]:
        preference = self.preferences.get_by_user(user_id) or DailySessionPreference(user_id=user_id)
        due_count = len(self.words.list_due_for_user(user_id, limit=preference.review_limit))
        return preference, due_count


class UpdateDailySessionUseCase:
    def __init__(self, preferences: DailySessionPreferenceRepository):
        self.preferences = preferences

    def execute(self, preference: DailySessionPreference) -> DailySessionPreference:
        return self.preferences.upsert(preference)
