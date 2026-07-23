"""Domain value objects.

Value objects are immutable, have no identity of their own, and are defined
entirely by their attributes. They belong to the domain layer and must not
depend on any framework or infrastructure concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.domain.exceptions import ValidationError

# The convention every stored datetime in this domain follows (see utcnow).
# A user who has never chosen a zone keeps exactly that behavior, so the
# column added for issue #44 defaults to this rather than to a guess.
DEFAULT_TIME_ZONE = "UTC"


def normalize_time_zone(value: str | None) -> str:
    """Validate an IANA time-zone identifier, or fall back to the default.

    `None` means the user has no stored preference — a row predating the
    column, or an account that never set one — and takes the default. An
    identifier that is present but unrecognized is a caller error and is
    rejected, so a typo is refused at the boundary rather than stored and
    discovered later at delivery time.
    """
    if value is None:
        return DEFAULT_TIME_ZONE
    candidate = value.strip()
    if candidate not in available_timezones():
        raise ValidationError(f"'{value}' is not a known IANA time zone identifier")
    return candidate


@lru_cache(maxsize=None)
def zone_for(name: str) -> ZoneInfo:
    """Load a zone, degrading to UTC rather than raising.

    Deliberately more forgiving than normalize_time_zone. That guards the
    write path, where a bad value can still be refused; this is the read path,
    reached from a scheduler job. A zone that was valid when it was stored can
    become unknown when the system's tz database is updated beneath it, and
    losing the reminder outright would be worse than delivering it on the
    previous convention — the same reasoning the quiet-hours parser applies to
    a malformed window.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if name == DEFAULT_TIME_ZONE:
            raise
        return zone_for(DEFAULT_TIME_ZONE)


def resolve_local_time(local: datetime, zone: ZoneInfo) -> datetime:
    """The UTC instant a naive local wall-clock time refers to.

    Defined as *the earliest instant whose local clock in `zone` has reached
    `local`*. One rule, which settles all three cases a wall-clock time can
    fall into:

    - An ordinary time maps to the instant that equals it.
    - A time that occurs twice, on an autumn fall-back date, maps to the
      earlier of the two — so a reminder is delivered once, not twice.
    - A time that never occurs, on a spring-forward date, has no instant that
      equals it, so the earliest instant to *reach* it is the transition
      itself: 02:30 in a 02:00 -> 03:00 jump resolves to 03:00. The reminder
      is moved, not lost.

    The two PEP 495 readings of the wall clock — `fold=0` and `fold=1` —
    supply the answer whenever one exists. Both round-trip back to `local` on
    an ordinary day and agree; on a fall-back date both round-trip and differ,
    and the earlier is taken. When neither round-trips, the time fell in a gap
    and the transition instant is found by bisection.

    Bisection is confined to that gap deliberately. It needs the local clock
    to increase with the instant, which holds inside a gap but *not* across a
    fold, where the clock runs 01:59 -> 01:00 -> 01:30 and a search would slide
    into the second occurrence — the duplicate delivery this rule exists to
    prevent.
    """
    if local.tzinfo is not None:
        raise ValueError("resolve_local_time expects a naive local time, not an aware datetime")

    def instant_for(fold: int) -> datetime:
        return local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)

    def clock_at(instant: datetime) -> datetime:
        return instant.astimezone(zone).replace(tzinfo=None)

    existing = [i for i in (instant_for(0), instant_for(1)) if clock_at(i) == local]
    if existing:
        return min(existing)

    # A gap. fold=1 applies the post-transition offset and so lands before the
    # jump, fold=0 the pre-transition offset and so lands after it; the
    # transition is between them, and the clock increases across that span.
    lo, hi = instant_for(1), instant_for(0)
    while hi - lo > timedelta(seconds=1):
        # Floor division keeps the bracket on whole seconds, so the answer
        # comes back with the precision a reminder is actually expressed in.
        mid = lo + (hi - lo) // 2
        if clock_at(mid) < local:
            lo = mid
        else:
            hi = mid
    return hi



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
