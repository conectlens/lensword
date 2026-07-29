"""Concrete repository adapters (SQLAlchemy).

Each class implements the matching Protocol in app.domain.repositories and
is responsible for translating between ORM models and domain entities so
that no SQLAlchemy type ever leaks past this module.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities import (
    Group,
    MnemonicNote,
    RecallSettings,
    DailySessionPreference,
    PracticeExercise,
    WeeklyLearningReport,
    Reminder,
    ReviewAttempt,
    ReviewSession,
    Room,
    RoomPlacement,
    User,
    Word,
)
from app.domain.value_objects import (
    DEFAULT_TIME_ZONE,
    Recurrence,
    ReviewOutcome,
    ReviewState,
    SessionMode,
    SupportedLanguage,
    UserRole,
    utcnow,
)
from app.infrastructure.models import (
    GroupModel,
    MnemonicNoteModel,
    RecallSettingsModel,
    DailySessionPreferenceModel,
    PracticeExerciseModel,
    WeeklyLearningReportModel,
    ReminderModel,
    ReviewAttemptModel,
    ReviewSessionModel,
    RoomModel,
    RoomPlacementModel,
    UserModel,
    WordModel,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping helpers (ORM <-> domain). Kept private to this module.
# ---------------------------------------------------------------------------


def _user_to_domain(m: UserModel) -> User:
    return User(
        id=m.id,
        username=m.username,
        email=m.email,
        hashed_password=m.hashed_password,
        role=UserRole(m.role),
        created_at=m.created_at,
        is_active=m.is_active,
        streak_days=m.streak_days,
        longest_streak_days=m.longest_streak_days,
        last_activity_date=m.last_activity_date,
        total_words_learned=m.total_words_learned,
        total_study_seconds=m.total_study_seconds,
        time_zone=m.time_zone or DEFAULT_TIME_ZONE,
    )


def _apply_user(m: UserModel, e: User) -> None:
    m.username = e.username
    m.email = e.email
    m.hashed_password = e.hashed_password
    m.role = e.role.value
    m.created_at = e.created_at
    m.is_active = e.is_active
    m.streak_days = e.streak_days
    m.longest_streak_days = e.longest_streak_days
    m.last_activity_date = e.last_activity_date
    m.total_words_learned = e.total_words_learned
    m.total_study_seconds = e.total_study_seconds
    m.time_zone = e.time_zone


def _group_to_domain(m: GroupModel) -> Group:
    return Group(
        id=m.id,
        owner_id=m.owner_id,
        name=m.name,
        target_language=SupportedLanguage(m.target_language),
        created_at=m.created_at,
    )


def _apply_group(m: GroupModel, e: Group) -> None:
    m.owner_id = e.owner_id
    m.name = e.name
    m.target_language = e.target_language.value
    m.created_at = e.created_at


def _word_to_domain(m: WordModel) -> Word:
    return Word(
        id=m.id,
        group_id=m.group_id,
        term=m.term,
        target_language=SupportedLanguage(m.target_language),
        translations=list(m.translations or []),
        example_sentence=m.example_sentence,
        mnemonic=m.mnemonic,
        category=m.category,
        definition=m.definition,
        part_of_speech=m.part_of_speech,
        cefr_level=m.cefr_level,
        pronunciation=m.pronunciation,
        collocations=list(m.collocations or []),
        tags=list(m.tags or []),
        ai_confidence=m.ai_confidence,
        ai_provider=m.ai_provider,
        ai_model=m.ai_model,
        synonyms=list(m.synonyms or []),
        antonyms=list(m.antonyms or []),
        topics=list(m.topics or []),
        review_state=ReviewState(
            strength=m.strength,
            ease_factor=m.ease_factor,
            interval_days=m.interval_days,
            repetitions=m.repetitions,
            due_at=m.due_at,
            last_reviewed_at=m.last_reviewed_at,
        ),
        created_at=m.created_at,
    )


def _apply_word(m: WordModel, e: Word) -> None:
    m.group_id = e.group_id
    m.term = e.term
    m.target_language = e.target_language.value
    m.translations = list(e.translations)
    m.example_sentence = e.example_sentence
    m.mnemonic = e.mnemonic
    m.category = e.category
    m.definition = e.definition
    m.part_of_speech = e.part_of_speech
    m.cefr_level = e.cefr_level
    m.pronunciation = e.pronunciation
    m.collocations = list(e.collocations)
    m.tags = list(e.tags)
    m.ai_confidence = e.ai_confidence
    m.ai_provider = e.ai_provider
    m.ai_model = e.ai_model
    m.synonyms = list(e.synonyms)
    m.antonyms = list(e.antonyms)
    m.topics = list(e.topics)
    m.strength = e.review_state.strength
    m.ease_factor = e.review_state.ease_factor
    m.interval_days = e.review_state.interval_days
    m.repetitions = e.review_state.repetitions
    m.due_at = e.review_state.due_at
    m.last_reviewed_at = e.review_state.last_reviewed_at
    m.created_at = e.created_at


def _room_to_domain(m: RoomModel) -> Room:
    return Room(
        id=m.id,
        owner_id=m.owner_id,
        group_id=m.group_id,
        name=m.name,
        icon=m.icon,
        created_at=m.created_at,
        placements=[
            RoomPlacement(word_id=p.word_id, x_percent=p.x_percent, y_percent=p.y_percent, placed_at=p.placed_at)
            for p in m.placements
        ],
    )


def _session_to_domain(m: ReviewSessionModel) -> ReviewSession:
    return ReviewSession(
        id=m.id,
        user_id=m.user_id,
        mode=SessionMode(m.mode),
        started_at=m.started_at,
        ended_at=m.ended_at,
        new_words_learned_count=m.new_words_learned_count,
        attempts=[
            ReviewAttempt(
                word_id=a.word_id,
                outcome=ReviewOutcome(a.outcome),
                response_time_ms=a.response_time_ms,
                answered_at=a.answered_at,
            )
            for a in m.attempts
        ],
    )


def _mnemonic_to_domain(m: MnemonicNoteModel) -> MnemonicNote:
    return MnemonicNote(
        id=m.id,
        word_id=m.word_id,
        author_id=m.author_id,
        text=m.text,
        is_ai_generated=m.is_ai_generated,
        upvotes=m.upvotes,
        downvotes=m.downvotes,
        created_at=m.created_at,
    )


def _reminder_to_domain(m: ReminderModel) -> Reminder:
    return Reminder(
        id=m.id,
        user_id=m.user_id,
        group_id=m.group_id,
        trigger_time=m.trigger_time,
        recurrence=Recurrence(m.recurrence),
        enabled=m.enabled,
        created_at=m.created_at,
    )


def _readable_reminder(m: ReminderModel) -> Reminder | None:
    """Map a stored reminder, or report it as unreadable instead of raising.

    `reminders.recurrence` is an unconstrained string column, so a value the
    domain has no meaning for is a data possibility rather than a programming
    error. Reads must degrade one row at a time: these rows are loaded in
    bulk at application startup, and letting a single unreadable one propagate
    would cost every other user their reminders — or the application its boot.

    The row is skipped rather than coerced to some default schedule, because a
    reminder that fires at the wrong time is worse than one that stays silent
    while its problem is logged.
    """
    try:
        return _reminder_to_domain(m)
    except ValueError:
        logger.warning(
            "reminder %s stores an unusable recurrence %r and was skipped", m.id, m.recurrence
        )
        return None


def _readable_reminders(rows) -> list[Reminder]:
    return [reminder for reminder in map(_readable_reminder, rows) if reminder is not None]


def _apply_reminder(m: ReminderModel, e: Reminder) -> None:
    m.user_id = e.user_id
    m.group_id = e.group_id
    m.trigger_time = e.trigger_time
    m.recurrence = e.recurrence.value
    m.enabled = e.enabled
    m.created_at = e.created_at


def _settings_to_domain(m: RecallSettingsModel) -> RecallSettings:
    return RecallSettings(
        user_id=m.user_id,
        enabled=m.enabled,
        intensity=m.intensity,
        morning_checkin_enabled=m.morning_checkin_enabled,
        idle_time_enabled=m.idle_time_enabled,
        walking_mode_enabled=m.walking_mode_enabled,
        walking_steps_threshold=m.walking_steps_threshold,
        study_breaks_enabled=m.study_breaks_enabled,
        study_blocks_before_break=m.study_blocks_before_break,
        night_winddown_enabled=m.night_winddown_enabled,
        night_start_time=m.night_start_time,
        night_end_time=m.night_end_time,
        push_enabled=m.push_enabled,
        email_enabled=m.email_enabled,
        desktop_enabled=m.desktop_enabled,
        in_app_enabled=m.in_app_enabled,
        quiet_hours_start=m.quiet_hours_start,
        quiet_hours_end=m.quiet_hours_end,
        scheduler=m.scheduler,
    )


def _exercise_to_domain(m: PracticeExerciseModel) -> PracticeExercise:
    return PracticeExercise(
        id=m.id, user_id=m.user_id, word_id=m.word_id, kind=m.kind, prompt=m.prompt,
        answer=m.answer, options=m.options or [], answered=m.answered, correct=m.correct, created_at=m.created_at,
    )


def _daily_preference_to_domain(m: DailySessionPreferenceModel) -> DailySessionPreference:
    return DailySessionPreference(
        user_id=m.user_id, enabled=m.enabled, goal_minutes=m.goal_minutes, review_limit=m.review_limit,
    )


def _weekly_report_to_domain(m: WeeklyLearningReportModel) -> WeeklyLearningReport:
    return WeeklyLearningReport(
        id=m.id, user_id=m.user_id, week_start=m.week_start, week_end=m.week_end, time_zone=m.time_zone,
        snapshot=m.snapshot or {}, narration=m.narration, created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


class SqlAlchemyUserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        m = self.db.get(UserModel, user_id)
        return _user_to_domain(m) if m else None

    def get_by_email(self, email: str) -> User | None:
        m = self.db.scalar(select(UserModel).where(UserModel.email == email))
        return _user_to_domain(m) if m else None

    def get_by_username(self, username: str) -> User | None:
        m = self.db.scalar(select(UserModel).where(UserModel.username == username))
        return _user_to_domain(m) if m else None

    def add(self, user: User) -> User:
        m = UserModel()
        _apply_user(m, user)
        self.db.add(m)
        self.db.flush()
        return _user_to_domain(m)

    def update(self, user: User) -> User:
        m = self.db.get(UserModel, user.id)
        if m is None:
            raise ValueError(f"User {user.id} not found")
        _apply_user(m, user)
        self.db.flush()
        return _user_to_domain(m)

    def delete(self, user_id: int) -> None:
        m = self.db.get(UserModel, user_id)
        if m is not None:
            self.db.delete(m)
            self.db.flush()

    def list_all(self, search: str | None, limit: int, offset: int) -> list[User]:
        stmt = select(UserModel)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(UserModel.username.ilike(like), UserModel.email.ilike(like)))
        stmt = stmt.order_by(UserModel.created_at.desc()).limit(limit).offset(offset)
        return [_user_to_domain(m) for m in self.db.scalars(stmt)]

    def count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(UserModel)) or 0

    def count_registered_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(UserModel).where(UserModel.created_at >= since)
        return self.db.scalar(stmt) or 0


class SqlAlchemyGroupRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, group_id: int) -> Group | None:
        m = self.db.get(GroupModel, group_id)
        return _group_to_domain(m) if m else None

    def list_by_owner(self, owner_id: int) -> list[Group]:
        stmt = select(GroupModel).where(GroupModel.owner_id == owner_id).order_by(GroupModel.created_at.desc())
        return [_group_to_domain(m) for m in self.db.scalars(stmt)]

    def add(self, group: Group) -> Group:
        m = GroupModel()
        _apply_group(m, group)
        self.db.add(m)
        self.db.flush()
        return _group_to_domain(m)

    def update(self, group: Group) -> Group:
        m = self.db.get(GroupModel, group.id)
        if m is None:
            raise ValueError(f"Group {group.id} not found")
        _apply_group(m, group)
        self.db.flush()
        return _group_to_domain(m)

    def delete(self, group_id: int) -> None:
        m = self.db.get(GroupModel, group_id)
        if m is not None:
            self.db.delete(m)
            self.db.flush()


class SqlAlchemyWordRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, word_id: int) -> Word | None:
        m = self.db.get(WordModel, word_id)
        return _word_to_domain(m) if m else None

    def list_by_group(self, group_id: int) -> list[Word]:
        stmt = select(WordModel).where(WordModel.group_id == group_id).order_by(WordModel.created_at.desc())
        return [_word_to_domain(m) for m in self.db.scalars(stmt)]

    def list_due_for_user(self, user_id: int, limit: int, group_id: int | None = None) -> list[Word]:
        stmt = (
            select(WordModel)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id, WordModel.due_at <= utcnow())
        )
        if group_id is not None:
            stmt = stmt.where(WordModel.group_id == group_id)
        stmt = stmt.order_by(WordModel.due_at.asc()).limit(limit)
        return [_word_to_domain(m) for m in self.db.scalars(stmt)]

    def add(self, word: Word) -> Word:
        m = WordModel()
        _apply_word(m, word)
        self.db.add(m)
        self.db.flush()
        return _word_to_domain(m)

    def update(self, word: Word) -> Word:
        m = self.db.get(WordModel, word.id)
        if m is None:
            raise ValueError(f"Word {word.id} not found")
        _apply_word(m, word)
        self.db.flush()
        return _word_to_domain(m)

    def delete(self, word_id: int) -> None:
        m = self.db.get(WordModel, word_id)
        if m is not None:
            self.db.delete(m)
            self.db.flush()

    def count_by_group(self, group_id: int) -> int:
        stmt = select(func.count()).select_from(WordModel).where(WordModel.group_id == group_id)
        return self.db.scalar(stmt) or 0

    def count_mastered_by_group(self, group_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(WordModel)
            .where(WordModel.group_id == group_id, WordModel.strength >= 80)
        )
        return self.db.scalar(stmt) or 0

    def distinct_languages_for_user(self, user_id: int) -> int:
        stmt = (
            select(func.count(func.distinct(WordModel.target_language)))
            .select_from(WordModel)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id)
        )
        return self.db.scalar(stmt) or 0

    def total_learned_for_owner(self, owner_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(WordModel)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == owner_id, WordModel.strength >= 80)
        )
        return self.db.scalar(stmt) or 0

    def count_all(self) -> int:
        return self.db.scalar(select(func.count()).select_from(WordModel)) or 0


class SqlAlchemyRoomRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, room_id: int) -> Room | None:
        stmt = select(RoomModel).where(RoomModel.id == room_id).options(selectinload(RoomModel.placements))
        m = self.db.scalar(stmt)
        return _room_to_domain(m) if m else None

    def list_by_owner(self, owner_id: int) -> list[Room]:
        stmt = (
            select(RoomModel)
            .where(RoomModel.owner_id == owner_id)
            .options(selectinload(RoomModel.placements))
            .order_by(RoomModel.created_at.desc())
        )
        return [_room_to_domain(m) for m in self.db.scalars(stmt)]

    def add(self, room: Room) -> Room:
        m = RoomModel(
            owner_id=room.owner_id,
            group_id=room.group_id,
            name=room.name,
            icon=room.icon,
            created_at=room.created_at,
        )
        self.db.add(m)
        self.db.flush()
        return _room_to_domain(m)

    def update(self, room: Room) -> Room:
        m = self.db.scalar(
            select(RoomModel).where(RoomModel.id == room.id).options(selectinload(RoomModel.placements))
        )
        if m is None:
            raise ValueError(f"Room {room.id} not found")
        m.name = room.name
        m.icon = room.icon

        existing_by_word = {p.word_id: p for p in m.placements}
        incoming_word_ids = {p.word_id for p in room.placements}

        # Mutate the relationship collection itself (not a bare db.add/delete)
        # so the in-memory object stays consistent — SQLAlchemy's identity
        # map means a later query for this same room in this session would
        # otherwise keep returning the stale, previously-loaded collection.
        for p in list(m.placements):
            if p.word_id not in incoming_word_ids:
                m.placements.remove(p)  # cascade="all, delete-orphan" deletes the row on flush

        for placement in room.placements:
            if placement.word_id in existing_by_word:
                row = existing_by_word[placement.word_id]
                row.x_percent = placement.x_percent
                row.y_percent = placement.y_percent
                row.placed_at = placement.placed_at
            else:
                m.placements.append(
                    RoomPlacementModel(
                        word_id=placement.word_id,
                        x_percent=placement.x_percent,
                        y_percent=placement.y_percent,
                        placed_at=placement.placed_at,
                    )
                )
        self.db.flush()
        return _room_to_domain(m)

    def delete(self, room_id: int) -> None:
        m = self.db.get(RoomModel, room_id)
        if m is not None:
            self.db.delete(m)
            self.db.flush()


class SqlAlchemyReviewSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, session_id: int) -> ReviewSession | None:
        stmt = (
            select(ReviewSessionModel)
            .where(ReviewSessionModel.id == session_id)
            .options(selectinload(ReviewSessionModel.attempts))
        )
        m = self.db.scalar(stmt)
        return _session_to_domain(m) if m else None

    def add(self, session: ReviewSession) -> ReviewSession:
        m = ReviewSessionModel(
            user_id=session.user_id,
            mode=session.mode.value,
            started_at=session.started_at,
            ended_at=session.ended_at,
            new_words_learned_count=session.new_words_learned_count,
        )
        self.db.add(m)
        self.db.flush()
        return _session_to_domain(m)

    def update(self, session: ReviewSession) -> ReviewSession:
        stmt = (
            select(ReviewSessionModel)
            .where(ReviewSessionModel.id == session.id)
            .options(selectinload(ReviewSessionModel.attempts))
        )
        m = self.db.scalar(stmt)
        if m is None:
            raise ValueError(f"ReviewSession {session.id} not found")
        m.ended_at = session.ended_at
        m.new_words_learned_count = session.new_words_learned_count

        existing_count = len(m.attempts)
        for attempt in session.attempts[existing_count:]:
            m.attempts.append(
                ReviewAttemptModel(
                    word_id=attempt.word_id,
                    outcome=attempt.outcome.value,
                    response_time_ms=attempt.response_time_ms,
                    answered_at=attempt.answered_at,
                )
            )
        self.db.flush()
        return _session_to_domain(m)

    def list_recent_by_user(self, user_id: int, since: datetime) -> list[ReviewSession]:
        stmt = (
            select(ReviewSessionModel)
            .where(ReviewSessionModel.user_id == user_id, ReviewSessionModel.started_at >= since)
            .options(selectinload(ReviewSessionModel.attempts))
            .order_by(ReviewSessionModel.started_at.asc())
        )
        return [_session_to_domain(m) for m in self.db.scalars(stmt)]


class SqlAlchemyMnemonicRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, mnemonic_id: int) -> MnemonicNote | None:
        m = self.db.get(MnemonicNoteModel, mnemonic_id)
        return _mnemonic_to_domain(m) if m else None

    def list_by_word(self, word_id: int) -> list[MnemonicNote]:
        stmt = (
            select(MnemonicNoteModel)
            .where(MnemonicNoteModel.word_id == word_id)
            .order_by((MnemonicNoteModel.upvotes - MnemonicNoteModel.downvotes).desc())
        )
        return [_mnemonic_to_domain(m) for m in self.db.scalars(stmt)]

    def add(self, note: MnemonicNote) -> MnemonicNote:
        m = MnemonicNoteModel(
            word_id=note.word_id,
            author_id=note.author_id,
            text=note.text,
            is_ai_generated=note.is_ai_generated,
            upvotes=note.upvotes,
            downvotes=note.downvotes,
            created_at=note.created_at,
        )
        self.db.add(m)
        self.db.flush()
        return _mnemonic_to_domain(m)

    def update(self, note: MnemonicNote) -> MnemonicNote:
        m = self.db.get(MnemonicNoteModel, note.id)
        if m is None:
            raise ValueError(f"MnemonicNote {note.id} not found")
        m.text = note.text
        m.upvotes = note.upvotes
        m.downvotes = note.downvotes
        self.db.flush()
        return _mnemonic_to_domain(m)


class SqlAlchemyReminderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, reminder_id: int) -> Reminder | None:
        m = self.db.get(ReminderModel, reminder_id)
        return _readable_reminder(m) if m else None

    def list_by_user(self, user_id: int) -> list[Reminder]:
        stmt = select(ReminderModel).where(ReminderModel.user_id == user_id).order_by(ReminderModel.id.asc())
        return _readable_reminders(self.db.scalars(stmt))

    def list_enabled(self) -> list[Reminder]:
        stmt = select(ReminderModel).where(ReminderModel.enabled.is_(True)).order_by(ReminderModel.id.asc())
        return _readable_reminders(self.db.scalars(stmt))

    def add(self, reminder: Reminder) -> Reminder:
        m = ReminderModel()
        _apply_reminder(m, reminder)
        self.db.add(m)
        self.db.flush()
        return _reminder_to_domain(m)

    def update(self, reminder: Reminder) -> Reminder:
        m = self.db.get(ReminderModel, reminder.id)
        if m is None:
            raise ValueError(f"Reminder {reminder.id} not found")
        _apply_reminder(m, reminder)
        self.db.flush()
        return _reminder_to_domain(m)

    def delete(self, reminder_id: int) -> None:
        m = self.db.get(ReminderModel, reminder_id)
        if m is not None:
            self.db.delete(m)
            self.db.flush()


class SqlAlchemyRecallSettingsRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user(self, user_id: int) -> RecallSettings | None:
        m = self.db.get(RecallSettingsModel, user_id)
        return _settings_to_domain(m) if m else None

    def upsert(self, settings: RecallSettings) -> RecallSettings:
        m = self.db.get(RecallSettingsModel, settings.user_id)
        if m is None:
            m = RecallSettingsModel(user_id=settings.user_id)
            self.db.add(m)
        m.enabled = settings.enabled
        m.intensity = settings.intensity
        m.morning_checkin_enabled = settings.morning_checkin_enabled
        m.idle_time_enabled = settings.idle_time_enabled
        m.walking_mode_enabled = settings.walking_mode_enabled
        m.walking_steps_threshold = settings.walking_steps_threshold
        m.study_breaks_enabled = settings.study_breaks_enabled
        m.study_blocks_before_break = settings.study_blocks_before_break
        m.night_winddown_enabled = settings.night_winddown_enabled
        m.night_start_time = settings.night_start_time
        m.night_end_time = settings.night_end_time
        m.push_enabled = settings.push_enabled
        m.email_enabled = settings.email_enabled
        m.desktop_enabled = settings.desktop_enabled
        m.in_app_enabled = settings.in_app_enabled
        m.quiet_hours_start = settings.quiet_hours_start
        m.quiet_hours_end = settings.quiet_hours_end
        m.scheduler = settings.scheduler
        self.db.flush()
        return _settings_to_domain(m)


class SqlAlchemyPracticeExerciseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, exercise_id: int) -> PracticeExercise | None:
        model = self.db.get(PracticeExerciseModel, exercise_id)
        return _exercise_to_domain(model) if model else None

    def add(self, exercise: PracticeExercise) -> PracticeExercise:
        model = PracticeExerciseModel(
            user_id=exercise.user_id, word_id=exercise.word_id, kind=exercise.kind, prompt=exercise.prompt,
            answer=exercise.answer, options=exercise.options, answered=exercise.answered, correct=exercise.correct,
            created_at=exercise.created_at,
        )
        self.db.add(model)
        self.db.flush()
        return _exercise_to_domain(model)

    def update(self, exercise: PracticeExercise) -> PracticeExercise:
        model = self.db.get(PracticeExerciseModel, exercise.id)
        if model is None:
            raise ValueError(f"PracticeExercise {exercise.id} not found")
        model.answered = exercise.answered
        model.correct = exercise.correct
        self.db.flush()
        return _exercise_to_domain(model)


class SqlAlchemyDailySessionPreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user(self, user_id: int) -> DailySessionPreference | None:
        model = self.db.get(DailySessionPreferenceModel, user_id)
        return _daily_preference_to_domain(model) if model else None

    def upsert(self, preference: DailySessionPreference) -> DailySessionPreference:
        model = self.db.get(DailySessionPreferenceModel, preference.user_id)
        if model is None:
            model = DailySessionPreferenceModel(user_id=preference.user_id)
            self.db.add(model)
        model.enabled = preference.enabled
        model.goal_minutes = preference.goal_minutes
        model.review_limit = preference.review_limit
        self.db.flush()
        return _daily_preference_to_domain(model)


class SqlAlchemyWeeklyLearningReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, report_id: int) -> WeeklyLearningReport | None:
        model = self.db.get(WeeklyLearningReportModel, report_id)
        return _weekly_report_to_domain(model) if model else None

    def list_by_user(self, user_id: int) -> list[WeeklyLearningReport]:
        stmt = select(WeeklyLearningReportModel).where(WeeklyLearningReportModel.user_id == user_id).order_by(WeeklyLearningReportModel.created_at.desc())
        return [_weekly_report_to_domain(model) for model in self.db.scalars(stmt)]

    def add(self, report: WeeklyLearningReport) -> WeeklyLearningReport:
        model = WeeklyLearningReportModel(user_id=report.user_id, week_start=report.week_start, week_end=report.week_end, time_zone=report.time_zone, snapshot=report.snapshot, narration=report.narration, created_at=report.created_at)
        self.db.add(model)
        self.db.flush()
        return _weekly_report_to_domain(model)

    def update(self, report: WeeklyLearningReport) -> WeeklyLearningReport:
        model = self.db.get(WeeklyLearningReportModel, report.id)
        if model is None:
            raise ValueError(f"WeeklyLearningReport {report.id} not found")
        model.narration = report.narration
        self.db.flush()
        return _weekly_report_to_domain(model)
