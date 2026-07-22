"""SQLAlchemy ORM models.

These are transport/persistence models only. They are deliberately kept
separate from app.domain.entities so the domain layer has zero dependency
on SQLAlchemy; mapping between the two happens in
app.infrastructure.repositories.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
