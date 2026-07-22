"""Domain entities (aggregates).

Aggregate boundaries chosen for this domain:
  - User: its own aggregate. Owns denormalized stats (streak, totals) that
    are updated when a ReviewSession completes.
  - Group: its own aggregate (a named, owned collection of Words). Does not
    hold Words in memory because Words are queried/updated far more
    frequently than Groups and independently — Word is its own aggregate
    root referencing group_id, which avoids loading potentially thousands
    of words to change a group's name.
  - Word: its own aggregate root. Owns its ReviewState (embedded value
    object) and its own lexical associations (translations/synonyms/
    antonyms/topics), which have no identity or lifecycle apart from the
    word.
  - Room: aggregate root that DOES own its RoomPlacement child entities in
    memory, because the invariant "a placed word must belong to the room's
    group" is a Room-level rule that must be enforced atomically with the
    placement being added — a textbook case for keeping child entities
    inside the aggregate boundary that owns the invariant.
  - ReviewSession: aggregate root owning its ReviewAttempt child entities,
    and is the Information Expert for its own summary statistics (it has
    all the data needed to compute them; no external service should
    recompute this from scratch).
  - MnemonicNote: small, independent aggregate root.
  - RecallSettings: 1:1 with User, independent aggregate root (kept
    separate from User because it changes for different reasons and at a
    different rate than identity/auth data — divergent change avoidance).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.domain.exceptions import InvalidPlacementError, SessionAlreadyCompletedError
from app.domain.value_objects import (
    ReviewOutcome,
    ReviewState,
    SessionMode,
    SupportedLanguage,
    UserRole,
    utcnow,
)


@dataclass(slots=True)
class User:
    id: int | None
    username: str
    email: str
    hashed_password: str
    role: UserRole = UserRole.USER
    created_at: datetime = field(default_factory=utcnow)
    is_active: bool = True
    streak_days: int = 0
    longest_streak_days: int = 0
    last_activity_date: date | None = None
    total_words_learned: int = 0
    total_study_seconds: int = 0

    def record_completed_session(self, session: "ReviewSession") -> None:
        """Update denormalized profile stats after a session completes.

        User is the Information Expert for streak continuity because it is
        the only object that knows the user's last activity date.
        """
        if session.ended_at is None:
            raise SessionAlreadyCompletedError(session.id or 0)

        today = session.ended_at.date()
        if self.last_activity_date is None or self.last_activity_date < today - timedelta(days=1):
            self.streak_days = 1
        elif self.last_activity_date == today - timedelta(days=1):
            self.streak_days += 1
        # if last_activity_date == today, streak already counted today: no-op

        self.last_activity_date = today
        self.longest_streak_days = max(self.longest_streak_days, self.streak_days)
        self.total_study_seconds += session.duration_seconds
        self.total_words_learned += session.new_words_learned_count

    def promote_to_admin(self) -> None:
        self.role = UserRole.ADMIN

    def suspend(self) -> None:
        self.is_active = False

    def reactivate(self) -> None:
        self.is_active = True


@dataclass(slots=True)
class Group:
    """A named, personal collection of vocabulary words (shown as 'Group' /
    'Deck' in the UI). Deliberately does not hold its words in memory —
    see module docstring."""

    id: int | None
    owner_id: int
    name: str
    target_language: SupportedLanguage
    created_at: datetime = field(default_factory=utcnow)

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise InvalidPlacementError("Group name cannot be empty")
        self.name = new_name.strip()


@dataclass(slots=True)
class Word:
    """A single vocabulary word owned by a Group, with its own spaced-
    repetition state and lexical associations."""

    id: int | None
    group_id: int
    term: str
    target_language: SupportedLanguage
    translations: list[str] = field(default_factory=list)
    example_sentence: str | None = None
    mnemonic: str | None = None
    category: str | None = None
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    review_state: ReviewState = field(default_factory=ReviewState.initial)
    created_at: datetime = field(default_factory=utcnow)

    def add_translation(self, text: str) -> None:
        text = text.strip()
        if text and text not in self.translations:
            self.translations.append(text)

    def remove_translation(self, text: str) -> None:
        self.translations = [t for t in self.translations if t != text]

    def set_mnemonic(self, text: str | None) -> None:
        self.mnemonic = text.strip() if text else None

    def add_association(self, kind: str, value: str) -> None:
        bucket = self._association_bucket(kind)
        value = value.strip()
        if value and value not in bucket:
            bucket.append(value)

    def remove_association(self, kind: str, value: str) -> None:
        bucket = self._association_bucket(kind)
        bucket[:] = [v for v in bucket if v != value]

    def _association_bucket(self, kind: str) -> list[str]:
        mapping = {"synonym": self.synonyms, "antonym": self.antonyms, "topic": self.topics}
        if kind not in mapping:
            raise InvalidPlacementError(f"Unknown association kind '{kind}'")
        return mapping[kind]

    def apply_review(self, outcome: ReviewOutcome, scheduler: "SpacedRepetitionScheduler") -> None:
        """Delegate the *algorithm* to the scheduler (protected variation
        point — SM-2 today, could be FSRS tomorrow) while Word retains
        control over *when* and *that* its own state changes."""
        self.review_state = scheduler.schedule_next(self.review_state, outcome)

    @property
    def is_due(self) -> bool:
        return self.review_state.is_due


@dataclass(slots=True)
class RoomPlacement:
    """A word positioned on a Room's 2D canvas (the memory-palace anchor)."""

    word_id: int
    x_percent: float
    y_percent: float
    placed_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Room:
    """A 'memory room' — a spatial canvas used to place a Group's words as
    visual/spatial mnemonic anchors (method-of-loci technique)."""

    id: int | None
    owner_id: int
    group_id: int
    name: str
    icon: str = "meeting_room"
    created_at: datetime = field(default_factory=utcnow)
    placements: list[RoomPlacement] = field(default_factory=list)

    def place_word(self, word: Word, x_percent: float, y_percent: float) -> None:
        if word.group_id != self.group_id:
            raise InvalidPlacementError(
                f"Word '{word.id}' belongs to group '{word.group_id}', not this room's group '{self.group_id}'"
            )
        if not (0 <= x_percent <= 100 and 0 <= y_percent <= 100):
            raise InvalidPlacementError("Placement coordinates must be within 0-100 percent")

        existing = self._find_placement(word.id)
        if existing:
            existing.x_percent = x_percent
            existing.y_percent = y_percent
            existing.placed_at = utcnow()
        else:
            self.placements.append(RoomPlacement(word_id=word.id, x_percent=x_percent, y_percent=y_percent))

    def remove_placement(self, word_id: int) -> None:
        self.placements = [p for p in self.placements if p.word_id != word_id]

    def _find_placement(self, word_id: int | None) -> RoomPlacement | None:
        return next((p for p in self.placements if p.word_id == word_id), None)

    def placement_ratio(self, total_group_words: int) -> float:
        if total_group_words <= 0:
            return 0.0
        return min(1.0, len(self.placements) / total_group_words)


@dataclass(slots=True)
class ReviewAttempt:
    word_id: int
    outcome: ReviewOutcome
    response_time_ms: int | None
    answered_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ReviewSession:
    """A single sitting of reviewing due words. Owns its attempts and is the
    Information Expert for its own summary — nothing outside the session
    should recompute these figures independently."""

    id: int | None
    user_id: int
    mode: SessionMode
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None
    attempts: list[ReviewAttempt] = field(default_factory=list)
    new_words_learned_count: int = 0

    def record_attempt(self, word_id: int, outcome: ReviewOutcome, response_time_ms: int | None = None) -> None:
        if self.ended_at is not None:
            raise SessionAlreadyCompletedError(self.id or 0)
        self.attempts.append(ReviewAttempt(word_id=word_id, outcome=outcome, response_time_ms=response_time_ms))

    def complete(self) -> None:
        if self.ended_at is None:
            self.ended_at = utcnow()

    @property
    def duration_seconds(self) -> int:
        end = self.ended_at or utcnow()
        return max(0, int((end - self.started_at).total_seconds()))

    @property
    def words_reviewed_count(self) -> int:
        return len(self.attempts)

    @property
    def correct_count(self) -> int:
        return sum(1 for a in self.attempts if a.outcome == ReviewOutcome.CORRECT)

    @property
    def incorrect_count(self) -> int:
        return sum(1 for a in self.attempts if a.outcome == ReviewOutcome.INCORRECT)

    @property
    def accuracy_percent(self) -> float:
        if not self.attempts:
            return 0.0
        return round(100 * self.correct_count / len(self.attempts), 1)


@dataclass(slots=True)
class MnemonicNote:
    """A user-authored mnemonic/memory-trick for a word, part of the
    MnemoLab gallery. Voting is intentionally unbounded per user in this
    version — see README for the documented scope simplification around
    cross-user visibility."""

    id: int | None
    word_id: int
    author_id: int
    text: str
    is_ai_generated: bool = False
    upvotes: int = 0
    downvotes: int = 0
    created_at: datetime = field(default_factory=utcnow)

    def upvote(self) -> None:
        self.upvotes += 1

    def downvote(self) -> None:
        self.downvotes += 1

    @property
    def score(self) -> int:
        return self.upvotes - self.downvotes


@dataclass(slots=True)
class RecallSettings:
    """Per-user 'Forced Recall Engine' configuration. Persisting/updating
    these is fully implemented; actually *dispatching* push/email/desktop
    notifications on a schedule is not (see README — no credentialed
    notification provider is configured in this build)."""

    user_id: int
    enabled: bool = True
    intensity: int = 3  # 1 (gentle) - 5 (intense)
    morning_checkin_enabled: bool = True
    idle_time_enabled: bool = True
    walking_mode_enabled: bool = False
    walking_steps_threshold: int = 1000
    study_breaks_enabled: bool = True
    study_blocks_before_break: int = 2
    night_winddown_enabled: bool = False
    night_start_time: str = "22:00"
    night_end_time: str = "23:00"
    push_enabled: bool = True
    email_enabled: bool = False
    desktop_enabled: bool = False
    in_app_enabled: bool = True
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None

    def set_intensity(self, level: int) -> None:
        if not (1 <= level <= 5):
            raise InvalidPlacementError("Intensity must be between 1 and 5")
        self.intensity = level
