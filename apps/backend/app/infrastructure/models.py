"""SQLAlchemy ORM models.

These are transport/persistence models only. They are deliberately kept
separate from app.domain.entities so the domain layer has zero dependency
on SQLAlchemy; mapping between the two happens in
app.infrastructure.repositories.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
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
    # When a human last confirmed the model-written fields on this card
    # (#140). A timestamp rather than a boolean: "verified" without "when"
    # cannot be reasoned about once the card changes again. Cleared when a
    # model rewrites a field, because the badge would otherwise vouch for
    # text nobody read.
    ai_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    # FSRS memory stability in days (issue #173). Null for words never reviewed
    # under FSRS, including every SM-2 word — SM-2 does not use this field.
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    # server_default matters as much as default here, the same way it does for
    # time_zone above: a fresh database bootstraps this table from these
    # models directly (20260730_01), so this column already exists with no
    # value supplied by the time migration 20260730_14's raw backfill INSERT
    # runs — that migration's column list predates this field and cannot
    # name it. Only a real server-side default lets that INSERT succeed.
    semantic_relatedness_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    # Same server_default requirement as semantic_relatedness_enabled above,
    # for the same reason: 20260730_14's backfill INSERT predates these
    # fields and cannot name them.
    learning_diagnosis_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    acquisition_loop_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    ai_coach_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


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


class WordFieldRevisionModel(Base):
    """One AI-authored field changing value (issue #140).

    Append-only. The point of a history is to answer "what did this say
    before?", and a row that can be rewritten cannot answer it.

    Values are stored as text even for list fields, joined on newline. A JSON
    column would preserve structure the history does not need — nobody diffs a
    synonym list programmatically, they read it — and it would make the table
    harder to inspect by hand when someone is trying to work out what happened.
    """

    __tablename__ = "word_field_revisions"
    __table_args__ = (
        # Every read is "this word's history, newest first".
        Index("ix_word_field_revisions_word_changed", "word_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    field: Mapped[str] = mapped_column(String(32), index=True)
    # Null means the field had no value before, which is different from having
    # been an empty string — the first is "the model added this", the second
    # would be a change that changed nothing.
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "ai", "human" or "bulk". Recorded at the time rather than inferred later,
    # because after the fact there is no way to tell them apart.
    source: Mapped[str] = mapped_column(String(8), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class LearningPathModel(Base):
    """A stated goal, broken into milestones (issue #137).

    The goal text is stored because it is what the learner asked for, and a
    path that cannot show its own goal is a list of steps with no reason
    attached.

    No progress column. Progress is counted from the learner's vocabulary at
    read time — a stored percentage is a number that was true once, and it
    drifts the moment a word is added or deleted.
    """

    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Optional: a path can be about a language the learner studies in several
    # groups, and forcing it into one would make the goal narrower than it is.
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    goal: Mapped[str] = mapped_column(String(500))
    target_language: Mapped[str] = mapped_column(String(32))
    # Which model produced the plan, kept for the same reason word cards keep
    # it: a suggestion whose origin is unrecorded cannot be judged later.
    ai_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    milestones: Mapped[list["PathMilestoneModel"]] = relationship(
        back_populates="path", cascade="all, delete-orphan", order_by="PathMilestoneModel.position"
    )


class PathMilestoneModel(Base):
    """One step of a path.

    `position` is stored rather than inferred from id: a path's order is part
    of its meaning, and reordering must not depend on insertion order.
    """

    __tablename__ = "path_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # Matched against the learner's own word topics to measure progress, which
    # is why it is one tag rather than prose.
    topic: Mapped[str] = mapped_column(String(64), index=True)
    target_word_count: Mapped[int] = mapped_column(Integer)
    cefr_level: Mapped[str | None] = mapped_column(String(8), nullable=True)

    path: Mapped[LearningPathModel] = relationship(back_populates="milestones")
class ConversationSessionModel(Base):
    """One tutoring conversation (issue #135)."""

    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    target_language: Mapped[str] = mapped_column(String(32))
    # "gentle", "steady" or "stretch". Named rather than numeric because it is
    # a choice the learner makes, and a number would be one they guess at.
    difficulty: Mapped[str] = mapped_column(String(16), default="steady")
    # Free text describing the situation, when the conversation has one. Used
    # by scenario role-play (#136), which builds on this transport.
    scenario: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list["ConversationMessageModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessageModel.id",
    )


class ConversationMessageModel(Base):
    """One turn, with any corrections attached to it.

    Corrections live on the message rather than in their own table: they are
    only ever read with the turn they belong to, and a separate table would be
    a join for no query anyone makes.
    """

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_sessions.id"), index=True
    )
    # "learner" or "tutor".
    speaker: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    # [{original, corrected, explanation}] — validated before storage so a
    # correction never quotes text the learner did not write.
    corrections: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    session: Mapped[ConversationSessionModel] = relationship(back_populates="messages")


class ScenarioAttemptModel(Base):
    """One run at a role-play scenario (issue #136).

    The conversation itself lives in `conversation_sessions` — this is the
    scenario wrapper around it. Keeping them separate means the transport,
    corrections and history from #135 are reused rather than reimplemented, and
    an attempt is deleted without taking the general conversation machinery
    with it.

    `evaluation` is null until the attempt is finished, and stays null when it
    was too short to judge. That is different from a zero score, which would be
    a claim the learner did badly.
    """

    __tablename__ = "scenario_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_sessions.id"), index=True, unique=True
    )
    # The catalog key, not a foreign key: the catalog is a code constant, so
    # there is no row to point at. Stored as text so an attempt survives a
    # scenario being renamed or retired.
    scenario_key: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # {scored, scores, summary, goals_met, detail} — validated before storage.
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LearningObservationModel(Base):
    """One recall attempt, recorded with enough context to diagnose *why* it
    went the way it did (AI Learning Diagnosis epic, #180, issue #182).

    Append-only, the same reasoning as MistakeEventModel above: a wrong
    observation is corrected by a later, separate row, never rewritten —
    the diagnosis engine (#183) needs the original alongside the
    correction, not just the corrected version.

    Only written when `RecallSettings.learning_diagnosis_enabled` is true
    for the account (ADR 0007): with the flag off, review submission never
    reaches this table at all.

    Indexes cover the five query axes issue #182 TODO 4 names — word, pair
    (an IN-list against the word index), time window, modality, and
    intervention — each already scoped by the `user_id` prefix so a query
    can never cross accounts by construction, not just by a WHERE clause a
    future edit could drop.
    """

    __tablename__ = "learning_observations"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_id", name="uq_learning_observation_user_operation"),
        Index("ix_learning_observations_user_word", "user_id", "word_id"),
        Index("ix_learning_observations_user_observed", "user_id", "observed_at"),
        Index("ix_learning_observations_user_modality", "user_id", "modality"),
        Index("ix_learning_observations_user_intervention", "user_id", "intervention_plan_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The domain contract's `observation_id` — a client-visible, stable
    # string identity distinct from this row's own primary key.
    observation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Client-generated and stable across retries, mirroring SyncOperationModel
    # (issue #90). Always populated by the repository even when a legacy
    # caller supplied none, so the unique constraint above always applies.
    operation_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    outcome: Mapped[str] = mapped_column(String(16))
    session_mode: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    attempted_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hint_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    answer_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intervention_plan_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    self_reported_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # A bounded fingerprint/reference, never raw source text — the context
    # snippet's storage/retention policy itself is issue #182 TODO 3's
    # scope, filed as a follow-up rather than guessed at here.
    context_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class KnowledgeEdgeModel(Base):
    """One relation between two of a learner's own words (issue #138, #203).

    `knowledge_graph.build_edges()` shipped in #138 without a table to put
    its output in — every read recomputed the whole graph. This is that
    table, written on word/mistake mutation rather than on read (#203
    TODO 2).

    Stored with the lower word id as `source_id`, matching
    `knowledge_graph._add()`'s existing canonical-ordering rule exactly —
    a relation is one row however it was discovered, never two.

    `strength` is denormalized rather than left to be recomputed from
    `occurrences` on every read: `KnowledgeEdge.strength` is a pure
    function of `relation` and `occurrences`, so storing it is never at
    risk of drifting from what re-deriving it would give, and TODO 1's
    per-item lookup needs it as a real, indexed, sortable column.
    """

    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_id", "target_id", "relation", name="uq_knowledge_edge"
        ),
        # TODO 1's stated access pattern, plus its mirror: canonical storage
        # means "edges touching word X" can land X in either column, and a
        # per-item lookup needs both directions indexed to avoid a
        # sequential scan regardless of which side X fell on.
        Index("ix_knowledge_edges_user_source_strength", "user_id", "source_id", "strength"),
        Index("ix_knowledge_edges_user_target_strength", "user_id", "target_id", "strength"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    target_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    relation: Mapped[str] = mapped_column(String(16))
    strength: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(String(255))
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class DiagnosisModel(Base):
    """A deterministic engine's conclusion about one word (issue #183).

    Append-only, the same reasoning as every other evidence table in this
    epic: a correction is a new row, not an edit to an old one — #183 TODO
    1's requirement that a diagnosis be reproducible depends on the row
    that was actually shown never silently changing under it.

    Only written when `RecallSettings.learning_diagnosis_enabled` is true
    (ADR 0007), the same gate #182's learning_observations table uses.
    """

    __tablename__ = "diagnoses"
    __table_args__ = (
        # The read pattern is always "this word's diagnoses, newest first".
        Index("ix_diagnoses_user_word_diagnosed", "user_id", "word_id", "diagnosed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    outcome: Mapped[str] = mapped_column(String(48))
    # [{"kind": ..., "observation_ids": [...], "weight": ..., "description": ...}, ...] —
    # JSON rather than a child table: evidence is read and displayed whole,
    # never queried by its own fields independently of the diagnosis it
    # belongs to.
    evidence: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rules_version: Mapped[int] = mapped_column(Integer)
    diagnosed_at: Mapped[datetime] = mapped_column(DateTime)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    competing_hypotheses: Mapped[list] = mapped_column(JSON, default=list)


class AcquisitionEventModel(Base):
    """One transition of a same-day acquisition ladder (issue #184).

    Append-only, like every other evidence table in this epic — a rung
    transition is a new row, never an edit to the previous one.
    `SqlAlchemyAcquisitionStateRepository.upsert()` (the name the #181-era
    `AcquisitionStateRepository` protocol already committed to) always
    inserts here; "the current state" is derived by reading the most
    recent row for (user_id, word_id), the same pattern `DiagnosisModel`
    uses for "latest diagnosis".

    `due_at` is denormalized rather than recomputed from `rung` and
    `ladder_version` on every read: it is a pure function of the row's own
    fields (`AcquisitionScheduler.due_at`), so storing it cannot drift, and
    the dispatch job's and the "due" endpoint's query both need it as a
    real, indexed, sortable column rather than a client-side filter over
    every ladder in the system.
    """

    __tablename__ = "acquisition_events"
    __table_args__ = (
        # Partial-unique in effect only: a NULL operation_id never
        # conflicts with another NULL on Postgres or SQLite, so a caller
        # with no idempotency key can still submit multiple transitions —
        # the same nullable-unique shape learning_observations already uses.
        UniqueConstraint("user_id", "operation_id", name="uq_acquisition_event_user_operation"),
        Index("ix_acquisition_events_user_word_updated", "user_id", "word_id", "updated_at"),
        # The dispatch job's and the due-endpoint's query: every
        # not-yet-graduated ladder due at or before now, across all users.
        Index("ix_acquisition_events_due", "graduated", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    rung: Mapped[int] = mapped_column(Integer)
    ladder_version: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    graduated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    due_at: Mapped[datetime] = mapped_column(DateTime)
    # Entry reason (#184 TODO 4), null only for rows this account created
    # before the field existed — never re-derived after the fact.
    entry_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
