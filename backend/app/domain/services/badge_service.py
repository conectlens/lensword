"""Badge/achievement computation.

Badges are computed on the fly from real stats rather than stored as
unlocked rows — there is no meaningful "unlock event" business rule yet
(no notifications, no badge-specific rewards), so persisting achievement
rows would be speculative generality. If unlock timestamps or badge-specific
side effects are ever needed, this is the seam to introduce an Achievement
entity and repository.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities import User


@dataclass(frozen=True, slots=True)
class Badge:
    code: str
    name: str
    icon: str
    description: str


_CATALOG: list[tuple[Badge, callable]] = []


def _register(code: str, name: str, icon: str, description: str, predicate):
    _CATALOG.append((Badge(code=code, name=name, icon=icon, description=description), predicate))


_register(
    "novice_linguist", "Novice Linguist", "workspace_premium",
    "Learn your first 10 words",
    lambda u, langs: u.total_words_learned >= 10,
)
_register(
    "word_explorer", "Word Explorer", "explore",
    "Learn 100 words",
    lambda u, langs: u.total_words_learned >= 100,
)
_register(
    "polyglot_prodigy", "Polyglot Prodigy", "translate",
    "Study words in 3 or more languages",
    lambda u, langs: langs >= 3,
)
_register(
    "language_master", "Language Master", "school",
    "Learn 1,000 words",
    lambda u, langs: u.total_words_learned >= 1000,
)
_register(
    "streak_keeper", "Streak Keeper", "local_fire_department",
    "Reach a 7-day review streak",
    lambda u, langs: u.longest_streak_days >= 7,
)


class BadgeService:
    """Stateless domain service: given a user's stats, which badges have
    they earned? Information Expert would suggest this lives on User
    itself, but badge *catalog* membership is a cross-cutting policy that
    is expected to grow independently of the User entity, so it is kept as
    a separate service (Pure Fabrication) to avoid User accumulating an
    ever-growing list of unrelated badge predicates."""

    @staticmethod
    def earned_badges(user: User, distinct_languages_studied: int) -> list[Badge]:
        return [badge for badge, predicate in _CATALOG if predicate(user, distinct_languages_studied)]

    @staticmethod
    def all_badges() -> list[Badge]:
        return [badge for badge, _ in _CATALOG]
