"""SQLAlchemy ORM models.

These are transport/persistence models only. They are deliberately kept
separate from app.domain.entities so the domain layer has zero dependency
on SQLAlchemy; mapping between the two happens in
app.infrastructure.repositories.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_words_learned: Mapped[int] = mapped_column(Integer, default=0)
    total_study_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # server_default matters as much as default here: the column is added
    # to existing databases by an ALTER, and every row already present
    # must land on UTC rather than NULL (issue #44).
    time_zone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )

    groups: Mapped[list["GroupModel"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    rooms: Mapped[list["RoomModel"]] = relationship(cascade="all, delete-orphan")
    review_sessions: Mapped[list["ReviewSessionModel"]] = relationship(cascade="all, delete-orphan")


class GroupModel(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    target_language: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    owner: Mapped[UserModel] = relationship(back_populates="groups")
    words: Mapped[list["WordModel"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    rooms: Mapped[list["RoomModel"]] = relationship(cascade="all, delete-orphan")


class WordModel(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    term: Mapped[str] = mapped_column(String(255))
    target_language: Mapped[str] = mapped_column(String(32))
    translations: Mapped[list] = mapped_column(JSON, default=list)
    example_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    mnemonic: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_of_speech: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cefr_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pronunciation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collocations: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    antonyms: Mapped[list] = mapped_column(JSON, default=list)
    topics: Mapped[list] = mapped_column(JSON, default=list)

    # Embedded ReviewState value object
    strength: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    # Bumped on every write. A client that edited revision 3 while offline is
    # editing a word that is now revision 5, and that difference is what makes
    # a stale edit detectable rather than silently last-write-wins.
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    group: Mapped[GroupModel] = relationship(back_populates="words")
    mnemonic_notes: Mapped[list["MnemonicNoteModel"]] = relationship(cascade="all, delete-orphan")


class RoomModel(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    name: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(64), default="meeting_room")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    placements: Mapped[list["RoomPlacementModel"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class RoomPlacementModel(Base):
    __tablename__ = "room_placements"
    __table_args__ = (UniqueConstraint("room_id", "word_id", name="uq_room_word"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    x_percent: Mapped[float] = mapped_column(Float)
    y_percent: Mapped[float] = mapped_column(Float)
    placed_at: Mapped[datetime] = mapped_column(DateTime)

    room: Mapped[RoomModel] = relationship(back_populates="placements")


class ReviewSessionModel(Base):
    __tablename__ = "review_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    new_words_learned_count: Mapped[int] = mapped_column(Integer, default=0)

    attempts: Mapped[list["ReviewAttemptModel"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ReviewAttemptModel(Base):
    __tablename__ = "review_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("review_sessions.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    outcome: Mapped[str] = mapped_column(String(16))
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime)

    session: Mapped[ReviewSessionModel] = relationship(back_populates="attempts")


class MnemonicNoteModel(Base):
    __tablename__ = "mnemonic_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    downvotes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ReminderModel(Base):
    """Per-user cron-like schedule: when to fire, how often, and which
    review group it targets. Wiring this to the Phase 0.0 scheduler is a
    Phase 2 concern (reminder scheduling use case) — this is only the
    persisted shape."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    trigger_time: Mapped[str] = mapped_column(String(8))
    recurrence: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Authority for failover (issue #87). Two devices holding different
    # revisions hold the same reminder; the higher one is the real schedule,
    # and a firing computed from a lower one is discarded on reconnect.
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RecallSettingsModel(Base):
    __tablename__ = "recall_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    intensity: Mapped[int] = mapped_column(Integer, default=3)
    morning_checkin_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    idle_time_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    walking_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    walking_steps_threshold: Mapped[int] = mapped_column(Integer, default=1000)
    study_breaks_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    study_blocks_before_break: Mapped[int] = mapped_column(Integer, default=2)
    night_winddown_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    night_start_time: Mapped[str] = mapped_column(String(8), default="22:00")
    night_end_time: Mapped[str] = mapped_column(String(8), default="23:00")
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    desktop_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    hide_notification_details: Mapped[bool] = mapped_column(Boolean, default=False)
    notifications_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduler: Mapped[str] = mapped_column(String(16), default="sm2")


class PracticeExerciseModel(Base):
    __tablename__ = "practice_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DailySessionPreferenceModel(Base):
    __tablename__ = "daily_session_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    goal_minutes: Mapped[int] = mapped_column(Integer, default=10)
    review_limit: Mapped[int] = mapped_column(Integer, default=20)


class WeeklyLearningReportModel(Base):
    __tablename__ = "weekly_learning_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[datetime] = mapped_column(DateTime)
    week_end: Mapped[datetime] = mapped_column(DateTime)
    time_zone: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class MCPGrantModel(Base):
    __tablename__ = "mcp_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester: Mapped[str] = mapped_column(String(255), index=True)
    server: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(255))
    access: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(1024))
    mode: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MCPAuditEventModel(Base):
    __tablename__ = "mcp_audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester: Mapped[str] = mapped_column(String(255), index=True)
    tool: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(64))
    event: Mapped[dict] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class MCPIdempotencyKeyModel(Base):
    __tablename__ = "mcp_idempotency_keys"
    __table_args__ = (UniqueConstraint("requester", "request_id", name="uq_mcp_requester_request_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester: Mapped[str] = mapped_column(String(255), index=True)
    request_id: Mapped[str] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(255))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DesktopNotificationModel(Base):
    """Outbox row for one desktop notification (ROADMAP 2.2, issue #27).

    ADR 0002 made the desktop app remote-only, so the process that decides a
    notification is owed and the process that owns the notification tray are
    not the same one. This table is the handoff between them.

    Indexed on (user_id, delivered_at) rather than user_id alone, because the
    only hot query is "pending rows for this user" — an index on user_id would
    still walk every row this account has ever been sent.
    """

    __tablename__ = "desktop_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Which reminder produced this, so an action can reach back to the schedule
    # it belongs to. Nullable: a notification need not come from a reminder.
    reminder_id: Mapped[int | None] = mapped_column(ForeignKey("reminders.id"), nullable=True)
    # After this instant the actions are refused. An OS notification can sit in
    # a tray for days, and "start a five-minute session" answered on Thursday
    # for Tuesday's prompt is not the thing the user was asked.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The action taken, and when. First one wins — see PerformNotificationAction.
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_desktop_notifications_user_undelivered", "user_id", "delivered_at"),
    )


class SchedulerJobClaimModel(Base):
    """One row per (job, logical occurrence) that some instance has taken.

    APScheduler 3's SQLAlchemy job store makes jobs survive a restart, but it
    does not stop two schedulers polling the same store from both picking up
    the same due job — nothing in it locks a job for the instance that fetched
    it. Persistence and exclusivity are separate problems, and this table is
    the second one.

    The unique constraint is the whole mechanism: every instance tries to
    insert the same row, exactly one succeeds, and the rest see an integrity
    error and stand down. That works identically on Postgres and SQLite and
    needs no advisory locks or leader election.
    """

    __tablename__ = "scheduler_job_claims"
    __table_args__ = (
        UniqueConstraint("job_key", "occurrence_key", name="uq_scheduler_job_occurrence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_key: Mapped[str] = mapped_column(String(128), index=True)
    # Identifies *which firing* this is — see occurrence_key() in
    # app.infrastructure.job_claims. Not a timestamp: two instances firing the
    # same reminder a few seconds apart must produce the same value, and two
    # wall-clock readings never would.
    occurrence_key: Mapped[str] = mapped_column(String(64))
    claimed_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SyncOperationModel(Base):
    """One offline mutation, submitted for reconciliation (issue #90).

    Append-only. A row is never rewritten to a different operation — an
    operation that conflicts is recorded as conflicting and kept, because the
    whole point is that neither version is silently discarded.

    The unique constraint on (user_id, operation_id) is what makes submission
    idempotent: a client that retries after a lost response inserts the same
    row and loses the race with itself rather than applying twice.
    """

    __tablename__ = "sync_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_id", name="uq_sync_user_operation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Client-generated and stable across retries. Not a server id: the client
    # has to be able to name an operation it made while it had no network and
    # therefore no server id to refer to.
    operation_id: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    # Null for a create, whose server id does not exist until it is applied.
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
    # The revision the client believed it was editing. A scalar edit against a
    # stale revision is a conflict; an append (a review) never is.
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    conflict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Monotonic per account. A client pulls everything above its cursor.
    server_sequence: Mapped[int] = mapped_column(Integer, index=True)
    # Retry bookkeeping (issue #91). Kept on the operation rather than in a
    # side table so a quarantined row carries its own history.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class MistakeEventModel(Base):
    """One recorded error (issue #134).

    Append-only history rather than state. A mistake that happened cannot
    un-happen, and rewriting a row when the learner later gets the word right
    would destroy the very signal the weakness profile is built from.

    `occurrence_count` exists because the same mistake repeated in one session
    is one pattern, not several. Rows are not merged across sessions — the
    aggregation in `WeaknessProfileService` does that, and it needs the
    timestamps to do it.
    """

    __tablename__ = "mistake_events"
    __table_args__ = (
        # The profile query is always "this learner's mistakes, recent first".
        Index("ix_mistake_events_user_occurred", "user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    # What the learner actually typed. Kept so a profile can show the mistake
    # rather than only its category — "you wrote 'gata'" is evidence, "wrong
    # word" is a verdict, and the learner deserves to check our work.
    attempted_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable rather than absent when the confused word is deleted: the
    # mistake still happened, and it degrades to a plain wrong-word error
    # rather than vanishing or leaving a dangling reference.
    confused_with_word_id: Mapped[int | None] = mapped_column(
        ForeignKey("words.id"), nullable=True, index=True
    )
    # Free text describing where it happened ("review", "writing correction").
    context: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
