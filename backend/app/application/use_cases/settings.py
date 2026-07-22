from dataclasses import dataclass

from app.domain.entities import RecallSettings, User
from app.domain.exceptions import EntityNotFoundError
from app.domain.repositories import RecallSettingsRepository, UserRepository, WordRepository
from app.domain.services.badge_service import Badge, BadgeService


class GetRecallSettingsUseCase:
    def __init__(self, settings_repo: RecallSettingsRepository):
        self.settings_repo = settings_repo

    def execute(self, user_id: int) -> RecallSettings:
        settings = self.settings_repo.get_by_user(user_id)
        return settings or RecallSettings(user_id=user_id)


class UpdateRecallSettingsUseCase:
    def __init__(self, settings_repo: RecallSettingsRepository):
        self.settings_repo = settings_repo

    def execute(self, user_id: int, updated: RecallSettings) -> RecallSettings:
        updated.user_id = user_id
        return self.settings_repo.upsert(updated)


@dataclass(frozen=True, slots=True)
class ProfileOverview:
    user: User
    earned_badges: list[Badge]
    all_badges: list[Badge]


class GetProfileOverviewUseCase:
    def __init__(self, user_repo: UserRepository, word_repo: WordRepository):
        self.user_repo = user_repo
        self.word_repo = word_repo

    def execute(self, user_id: int) -> ProfileOverview:
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User", user_id)
        languages = self.word_repo.distinct_languages_for_user(user_id)
        earned = BadgeService.earned_badges(user, languages)
        return ProfileOverview(user=user, earned_badges=earned, all_badges=BadgeService.all_badges())
