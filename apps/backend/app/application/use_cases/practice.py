from app.domain.entities import DailySessionPreference, PracticeExercise, Word
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import (
    DailySessionPreferenceRepository,
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
