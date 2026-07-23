"""Domain value objects.

Value objects are immutable, have no identity of their own, and are defined
entirely by their attributes. They belong to the domain layer and must not
depend on any framework or infrastructure concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SupportedLanguage(str, Enum):
    """Closed set of languages LensWord can schedule vocabulary for.

    Kept as a value object (not a database table) because languages have no
    behavior or lifecycle of their own here — they are labels. If per-language
    behavior (e.g. locale-aware pluralization) is ever needed, promote this to
    an entity; YAGNI until then.
    """

    ENGLISH = "English"
    SPANISH = "Spanish"
    FRENCH = "French"
    GERMAN = "German"
    ITALIAN = "Italian"
    PORTUGUESE = "Portuguese"
    JAPANESE = "Japanese"
    KOREAN = "Korean"
    TURKISH = "Turkish"
    OTHER = "Other"


class ReviewOutcome(str, Enum):
    """The result of a single recall attempt on a word."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    SKIPPED = "skipped"


class SessionMode(str, Enum):
    """Presentation context a review session is being taken in.

    All modes share the same scheduling and scoring domain logic
    (see SpacedRepetitionScheduler). The mode only changes how the frontend
    presents the question (typed answer vs multiple choice) and pacing —
    it never changes SRS math, which lives in one place regardless of mode.
    """

    STANDARD = "standard"
    FOCUS = "focus"
    WALKING = "walking"
    NIGHT = "night"
    BREAK = "break"


class WordStatus(str, Enum):
    """Derived learning status of a word, computed from its ReviewState."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    MASTERED = "mastered"
    NEEDS_REVIEW = "needs_review"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class Recurrence(str, Enum):
    """How often a reminder repeats.

    Deliberately a small, closed set: every member has to be expressible as a
    real scheduler trigger, so adding one is a decision about behavior rather
    than a free-text label. Anything richer (weekdays only, every N hours)
    belongs behind a real product need.
    """

    ONCE = "once"
    DAILY = "daily"


class Channel(str, Enum):
    """A delivery route a notification can take.

    The values match the `channel` argument of the NotificationChannel port
    and the `*_enabled` flags on RecallSettings, so no translation table is
    needed between settings, policy and adapter.
    """

    PUSH = "push"
    EMAIL = "email"
    DESKTOP = "desktop"
    IN_APP = "in_app"


def utcnow() -> datetime:
    """Single source of truth for 'now', as a naive UTC datetime.

    Deliberately naive (not aware) because SQLite has no real datetime type —
    it stores text and always returns naive datetimes on read. Comparing an
    aware 'now' against a naive value read back from the database raises
    TypeError, so every datetime in this domain is naive-but-UTC by
    convention, consistently, end to end.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class ReviewState:
    """SM-2 style spaced-repetition state for one word.

    This is an embedded value object: it is persisted on the same database
    row as its owning Word (no separate table), because it has no identity
    or lifecycle independent of the word it describes. It is still modeled
    as its own immutable type so SpacedRepetitionScheduler can operate on it
    as a pure function: ReviewState -> ReviewState, independent of the ORM.
    """

    strength: int  # 0-100, "Learning Strength" / mastery score shown in the UI
    ease_factor: float  # SM-2 ease factor, bounded to >= 1.3
    interval_days: float
    repetitions: int
    due_at: datetime
    last_reviewed_at: datetime | None

    @staticmethod
    def initial() -> "ReviewState":
        return ReviewState(
            strength=0,
            ease_factor=2.5,
            interval_days=0,
            repetitions=0,
            due_at=utcnow(),
            last_reviewed_at=None,
        )

    @property
    def status(self) -> WordStatus:
        if self.repetitions == 0:
            return WordStatus.NEW
        if self.due_at <= utcnow():
            return WordStatus.NEEDS_REVIEW
        if self.strength >= 80:
            return WordStatus.MASTERED
        if self.strength >= 40:
            return WordStatus.REVIEW
        return WordStatus.LEARNING

    @property
    def is_due(self) -> bool:
        return self.due_at <= utcnow()
