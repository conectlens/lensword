from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.entities import User
from app.domain.exceptions import EntityNotFoundError
from app.domain.repositories import ReviewSessionRepository, UserRepository, WordRepository


class ListUsersUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, search: str | None, limit: int = 50, offset: int = 0) -> list[User]:
        return self.user_repo.list_all(search, limit, offset)


def _get_or_404(user_repo: UserRepository, user_id: int) -> User:
    user = user_repo.get_by_id(user_id)
    if user is None:
        raise EntityNotFoundError("User", user_id)
    return user


class SuspendUserUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, user_id: int) -> User:
        user = _get_or_404(self.user_repo, user_id)
        user.suspend()
        return self.user_repo.update(user)


class ReactivateUserUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, user_id: int) -> User:
        user = _get_or_404(self.user_repo, user_id)
        user.reactivate()
        return self.user_repo.update(user)


class DeleteUserUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, user_id: int) -> None:
        _get_or_404(self.user_repo, user_id)  # 404s if missing
        self.user_repo.delete(user_id)


@dataclass(frozen=True, slots=True)
class AdminStats:
    total_users: int
    new_users_last_30_days: int
    total_words_learned: int
    active_sessions_last_hour: int


class GetAdminStatsUseCase:
    def __init__(self, user_repo: UserRepository, word_repo: WordRepository, session_repo: ReviewSessionRepository):
        self.user_repo = user_repo
        self.word_repo = word_repo
        self.session_repo = session_repo

    def execute(self) -> AdminStats:
        now = datetime.now(timezone.utc)
        return AdminStats(
            total_users=self.user_repo.count(),
            new_users_last_30_days=self.user_repo.count_registered_since(now - timedelta(days=30)),
            total_words_learned=self.word_repo.count_all(),
            active_sessions_last_hour=0,  # would require a live-session heartbeat; not tracked in this build
        )
