"""Concrete repository adapters (SQLAlchemy).

Each class implements the matching Protocol in app.domain.repositories and
is responsible for translating between ORM models and domain entities so
that no SQLAlchemy type ever leaks past this module.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities import (
    DesktopNotification,
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
from app.domain.services.cefr_progress import MASTERY_STRENGTH
from app.domain.services.acquisition import AcquisitionScheduler
from app.domain.services.companion_sessions import (
    CompanionSession,
    CompanionSessionStatus,
    CompanionTurn,
    CompanionTurnRole,
)
from app.domain.services.companion_activities import ActivityStatus, ActivityType, LearningActivity
from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType
from app.domain.services.diagnosis_contracts import (
    AcquisitionState,
    Diagnosis,
    DiagnosisEvidence,
    InterventionOutcome,
    InterventionPlan,
    LearningObservation,
    ObservationCorrection,
    ObservationCorrectionReason,
)
from app.domain.services.knowledge_graph import KnowledgeEdge, Relation
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
    DesktopNotificationModel,
    SyncOperationModel,
    GroupModel,
    ConversationMessageModel,
    ScenarioAttemptModel,
    ConversationSessionModel,
    LearningPathModel,
    MistakeEventModel,
    PathMilestoneModel,
    WordFieldRevisionModel,
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
    LearningObservationModel,
    ObservationCorrectionModel,
    KnowledgeEdgeModel,
    DiagnosisModel,
    InterventionPlanModel,
    InterventionOutcomeModel,
    AcquisitionEventModel,
    CompanionSessionModel,
    CompanionTurnModel,
    CompanionActivityModel,
    CompanionTaskModel,
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
        ai_verified_at=m.ai_verified_at,
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
            stability=m.stability,
        ),
        created_at=m.created_at,
        revision=m.revision,
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
    m.ai_verified_at = e.ai_verified_at
    m.synonyms = list(e.synonyms)
    m.antonyms = list(e.antonyms)
    m.topics = list(e.topics)
    m.strength = e.review_state.strength
    m.ease_factor = e.review_state.ease_factor
    m.interval_days = e.review_state.interval_days
    m.repetitions = e.review_state.repetitions
    m.due_at = e.review_state.due_at
    m.last_reviewed_at = e.review_state.last_reviewed_at
    m.stability = e.review_state.stability
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
        revision=m.revision,
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
    # `revision` is deliberately absent. It is server-authoritative (issue
    # #87): a client that could set it could claim to be newer than it is and
    # win every convergence. It is bumped in update() instead.


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
        hide_notification_details=m.hide_notification_details,
        notifications_paused=m.notifications_paused,
        scheduler=m.scheduler,
        semantic_relatedness_enabled=m.semantic_relatedness_enabled,
        contrast_cards_enabled=m.contrast_cards_enabled,
        contrast_min_stability=m.contrast_min_stability,
        learning_diagnosis_enabled=m.learning_diagnosis_enabled,
        acquisition_loop_enabled=m.acquisition_loop_enabled,
        ai_coach_enabled=m.ai_coach_enabled,
        ai_companion_enabled=m.ai_companion_enabled,
        companion_sampling_enabled=m.companion_sampling_enabled,
        companion_remote_enabled=m.companion_remote_enabled,
        companion_multimodal_enabled=m.companion_multimodal_enabled,
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


# ---------------------------------------------------------------------------
# Cascading deletes
#
# Postgres enforces foreign keys; SQLite does not, unless PRAGMA foreign_keys
# is turned on, which this project never does. Deleting a word that is placed
# in a room therefore appeared to work for the entire life of the SQLite
# deployment and raises ForeignKeyViolation — a 500 — the moment the same
# request runs against Postgres.
#
# Dependants are removed explicitly here rather than through ON DELETE CASCADE
# so the behaviour is identical on both dialects and needs no constraint
# migration, and so the choice to discard each dependant is visible in code
# rather than implied by a schema attribute.
# ---------------------------------------------------------------------------


def _delete_word_dependents(db: Session, word_ids: list[int]) -> None:
    """Remove every row that references these words.

    Review attempts are deleted with the word, which does lose a little session
    history. The alternative is refusing to delete a word that has ever been
    reviewed, which would make a vocabulary list permanently un-prunable — a
    worse answer for a learning tool whose whole point is editing what you
    study.
    """
    if not word_ids:
        return
    # An observation correction (#229) references its observation's
    # observation_id, not a word_id, so it cannot be swept up by the
    # word_id-keyed loop below — it has to go first, or deleting the
    # observation it points at would be the same dangling-FK bug this
    # whole function exists to close off, one join further out.
    observation_ids = list(
        db.scalars(
            select(LearningObservationModel.observation_id).where(LearningObservationModel.word_id.in_(word_ids))
        )
    )
    if observation_ids:
        for row in db.scalars(
            select(ObservationCorrectionModel).where(ObservationCorrectionModel.observation_id.in_(observation_ids))
        ):
            db.delete(row)

    for model in (
        RoomPlacementModel,
        ReviewAttemptModel,
        MnemonicNoteModel,
        PracticeExerciseModel,
        MistakeEventModel,
        WordFieldRevisionModel,
        # #182/#183/#184: all three carry a NOT NULL word_id, so — like
        # ReviewAttemptModel above — they cannot be dereferenced the way
        # MistakeEventModel's confused_with_word_id is; they are deleted
        # with the word. This was missed for the first two when each table
        # shipped, which SQLite (never enforcing PRAGMA foreign_keys)
        # would not catch but Postgres would — AcquisitionEventModel is
        # added here from the start rather than repeating that.
        LearningObservationModel,
        DiagnosisModel,
        InterventionPlanModel,
        InterventionOutcomeModel,
        AcquisitionEventModel,
    ):
        for row in db.scalars(select(model).where(model.word_id.in_(word_ids))):
            db.delete(row)

    # A mistake *about another word* that named one of these as the confusion
    # is kept, with the reference cleared. The mistake still happened; it
    # degrades to a plain wrong-word error rather than being deleted along with
    # a word it was only mentioned by. Left as a dangling id it would be a
    # foreign-key violation on Postgres and a silently orphaned row on SQLite —
    # the same divergence the tenant-isolation audit caught for placements.
    for row in db.scalars(
        select(MistakeEventModel).where(MistakeEventModel.confused_with_word_id.in_(word_ids))
    ):
        row.confused_with_word_id = None

    # A knowledge edge always has two endpoints (#203); unlike the mistake
    # case above, there is no "keep it with the reference cleared" option
    # for a relation whose whole meaning is which two words it joins.
    for row in db.scalars(
        select(KnowledgeEdgeModel).where(
            or_(KnowledgeEdgeModel.source_id.in_(word_ids), KnowledgeEdgeModel.target_id.in_(word_ids))
        )
    ):
        db.delete(row)

    db.flush()


def _delete_group_dependents(db: Session, group_id: int) -> None:
    """Remove every row that references this group: its words (and each
    word's own dependants via `_delete_word_dependents`), rooms and their
    placements, and reminders. Does not delete the group row itself, so
    callers can run this ahead of a bulk delete (e.g. the owning account)
    that will remove the group separately.

    A learning path or conversation's `group_id` is optional — a goal or a
    tutoring session can be about a language studied across several groups,
    not pinned to one — so losing the group it happened to reference is not
    losing anything the path/conversation means. The reference is cleared
    rather than the row deleted, the same choice already made for
    `MistakeEventModel.confused_with_word_id`, and for the same two reasons:
    the row still has a life of its own, and leaving the id in place would
    be a dangling foreign key on Postgres the moment this group is gone.
    """
    for path in db.scalars(select(LearningPathModel).where(LearningPathModel.group_id == group_id)):
        path.group_id = None
    for conversation in db.scalars(
        select(ConversationSessionModel).where(ConversationSessionModel.group_id == group_id)
    ):
        conversation.group_id = None
    word_ids = list(db.scalars(select(WordModel.id).where(WordModel.group_id == group_id)))
    _delete_word_dependents(db, word_ids)
    for room in db.scalars(select(RoomModel).where(RoomModel.group_id == group_id)):
        for placement in list(room.placements):
            db.delete(placement)
        db.delete(room)
    for reminder in db.scalars(select(ReminderModel).where(ReminderModel.group_id == group_id)):
        db.delete(reminder)
    for word in db.scalars(select(WordModel).where(WordModel.group_id == group_id)):
        db.delete(word)


def _delete_user_dependents(db: Session, user_id: int) -> None:
    """Remove every row that references this account, directly or through
    an owned group/word, so the account row can be deleted without
    orphaning data — silently on SQLite, a `ForeignKeyViolation` on
    Postgres, the same bug class `_delete_word_dependents` and
    `_delete_group_dependents` exist to close off at the word/group level.

    Dependants are removed explicitly rather than through
    `UserModel`'s `cascade="all, delete-orphan"` relationships (`groups`,
    `rooms`, `review_sessions`): those only cascade one level, and several
    of the tables below (learning observations, diagnoses, acquisition
    events, knowledge edges) are not declared as relationships at all, so
    an ORM-only cascade would still leave them behind.

    Rooms, reminders, mistakes and practice exercises are not deleted by
    `user_id` here: every use case that creates one requires group or word
    ownership first (`_require_group_owner`/`_require_word_owner`), so they
    are always reachable through the owned-group loop below — a room and
    reminder through their `group_id`, a mistake or practice exercise
    through their (NOT NULL) `word_id` via `_delete_word_dependents`.
    """
    for group_id in list(db.scalars(select(GroupModel.id).where(GroupModel.owner_id == user_id))):
        _delete_group_dependents(db, group_id)
        db.delete(db.get(GroupModel, group_id))

    for review_session in db.scalars(select(ReviewSessionModel).where(ReviewSessionModel.user_id == user_id)):
        for attempt in db.scalars(
            select(ReviewAttemptModel).where(ReviewAttemptModel.session_id == review_session.id)
        ):
            db.delete(attempt)
        db.delete(review_session)

    for path in db.scalars(select(LearningPathModel).where(LearningPathModel.user_id == user_id)):
        for milestone in db.scalars(select(PathMilestoneModel).where(PathMilestoneModel.path_id == path.id)):
            db.delete(milestone)
        db.delete(path)

    for conversation in db.scalars(
        select(ConversationSessionModel).where(ConversationSessionModel.user_id == user_id)
    ):
        for attempt in db.scalars(
            select(ScenarioAttemptModel).where(ScenarioAttemptModel.session_id == conversation.id)
        ):
            db.delete(attempt)
        for message in db.scalars(
            select(ConversationMessageModel).where(ConversationMessageModel.session_id == conversation.id)
        ):
            db.delete(message)
        db.delete(conversation)

    for model in (
        RecallSettingsModel,
        DailySessionPreferenceModel,
        WeeklyLearningReportModel,
        DesktopNotificationModel,
        SyncOperationModel,
    ):
        for row in db.scalars(select(model).where(model.user_id == user_id)):
            db.delete(row)

    db.flush()


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
            _delete_user_dependents(self.db, user_id)
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
        if m is None:
            return
        _delete_group_dependents(self.db, group_id)
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

    def list_all_for_user(self, user_id: int, limit: int = 5000) -> list[Word]:
        """Every word this learner studies, across all their groups.

        Feeds the knowledge graph and the CEFR view (#143), both of which are
        whole-vocabulary questions — a graph built from one group would report
        that words in different groups are unrelated, which is a statement
        about the learner's filing rather than their language.

        Bounded because both callers aggregate in memory.
        """
        stmt = (
            select(WordModel)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id)
            .order_by(WordModel.id.asc())
            .limit(limit)
        )
        return [_word_to_domain(m) for m in self.db.scalars(stmt)]

    def find_id_by_term(self, user_id: int, term: str) -> int | None:
        """Look up one of this learner's words by its exact term.

        Exists so classifying a wrong answer costs a single indexed lookup
        rather than loading the learner's whole vocabulary to build a term map
        on every mistake.

        Case-insensitive, because "Gato" and "gato" are the same word to a
        learner and a confusion pair that depended on capitalisation would be
        an artefact of typing rather than of memory.
        """
        cleaned = (term or "").strip()
        if not cleaned:
            return None
        stmt = (
            select(WordModel.id)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id, func.lower(WordModel.term) == cleaned.lower())
            .order_by(WordModel.id.asc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_due_for_user(self, user_id: int, limit: int, group_id: int | None = None) -> list[Word]:
        # Ordered strictly by due_at, and deliberately not by issue #204's
        # semantic-diversity policy: that policy only acts at word
        # introduction, where no observed errors exist yet (its own boundary
        # with #180 Sec. 3). The review queue is #176's territory, and #204
        # TODO 5 explicitly excludes it — considered and rejected, not an
        # oversight.
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
        # Bumped here rather than taken from the caller (issue #90), so the
        # number a sync conflict decision rests on cannot be chosen by
        # whoever is asking — same reasoning as ReminderRepository.update().
        m.revision = (m.revision or 1) + 1
        self.db.flush()
        return _word_to_domain(m)

    def delete(self, word_id: int) -> None:
        m = self.db.get(WordModel, word_id)
        if m is not None:
            _delete_word_dependents(self.db, [word_id])
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

    def correct_answer_times(self, user_id: int, word_ids: list[int]) -> dict[int, list[datetime]]:
        """When each of these words was answered correctly by this learner.

        Feeds mistake decay (#142), which counts successes rather than elapsed
        time. Scoped through the session's owner so one account's review
        history can never retire another's mistakes.
        """
        if not word_ids:
            return {}
        stmt = (
            select(ReviewAttemptModel.word_id, ReviewAttemptModel.answered_at)
            .join(ReviewSessionModel, ReviewAttemptModel.session_id == ReviewSessionModel.id)
            .where(
                ReviewSessionModel.user_id == user_id,
                ReviewAttemptModel.word_id.in_(word_ids),
                ReviewAttemptModel.outcome == ReviewOutcome.CORRECT.value,
            )
        )
        times: dict[int, list[datetime]] = {}
        for word_id, answered_at in self.db.execute(stmt):
            times.setdefault(word_id, []).append(answered_at)
        return times

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
        # Bumped here rather than taken from the caller, so the number a
        # failover decision rests on cannot be chosen by whoever is asking.
        m.revision = (m.revision or 1) + 1
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
        m.hide_notification_details = settings.hide_notification_details
        m.notifications_paused = settings.notifications_paused
        m.scheduler = settings.scheduler
        m.semantic_relatedness_enabled = settings.semantic_relatedness_enabled
        m.contrast_cards_enabled = settings.contrast_cards_enabled
        m.contrast_min_stability = settings.contrast_min_stability
        m.learning_diagnosis_enabled = settings.learning_diagnosis_enabled
        m.acquisition_loop_enabled = settings.acquisition_loop_enabled
        m.ai_coach_enabled = settings.ai_coach_enabled
        m.ai_companion_enabled = settings.ai_companion_enabled
        m.companion_sampling_enabled = settings.companion_sampling_enabled
        m.companion_remote_enabled = settings.companion_remote_enabled
        m.companion_multimodal_enabled = settings.companion_multimodal_enabled
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


def _desktop_notification_to_domain(m: DesktopNotificationModel) -> DesktopNotification:
    return DesktopNotification(
        id=m.id,
        user_id=m.user_id,
        message=m.message,
        created_at=m.created_at,
        delivered_at=m.delivered_at,
        reminder_id=m.reminder_id,
        expires_at=m.expires_at,
        action=m.action,
        action_at=m.action_at,
    )


class SqlAlchemyDesktopNotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_pending(self, user_id: int, not_before: datetime, limit: int) -> list[DesktopNotification]:
        stmt = (
            select(DesktopNotificationModel)
            .where(
                DesktopNotificationModel.user_id == user_id,
                DesktopNotificationModel.delivered_at.is_(None),
                DesktopNotificationModel.created_at >= not_before,
            )
            # Oldest first: a shell that collects a truncated page gets the
            # notifications it missed earliest, and repeated collection walks
            # forward through the backlog instead of re-reading the newest page.
            .order_by(DesktopNotificationModel.created_at.asc(), DesktopNotificationModel.id.asc())
            .limit(limit)
        )
        return [_desktop_notification_to_domain(m) for m in self.db.scalars(stmt)]

    def add(self, notification: DesktopNotification) -> DesktopNotification:
        model = DesktopNotificationModel(
            user_id=notification.user_id,
            message=notification.message,
            created_at=notification.created_at,
            delivered_at=notification.delivered_at,
            reminder_id=notification.reminder_id,
            expires_at=notification.expires_at,
            action=notification.action,
            action_at=notification.action_at,
        )
        self.db.add(model)
        self.db.flush()
        return _desktop_notification_to_domain(model)

    def get_owned(self, user_id: int, notification_id: int) -> DesktopNotification | None:
        """Fetch scoped by owner in the query, not checked afterwards, so a
        guessed id cannot even be read."""
        model = self.db.get(DesktopNotificationModel, notification_id)
        if model is None or model.user_id != user_id:
            return None
        return _desktop_notification_to_domain(model)

    def record_action(self, user_id: int, notification_id: int, action: str) -> str | None:
        """Record the action, or report the one already recorded.

        Returns whichever action now stands: the caller's if it won, or the
        existing one if this notification was already answered. That is what
        makes a repeated OS callback harmless — the second call is not an
        error, it simply does not change anything.
        """
        model = self.db.get(DesktopNotificationModel, notification_id)
        if model is None or model.user_id != user_id:
            return None
        if model.action is None:
            model.action = action
            model.action_at = utcnow()
            self.db.flush()
        return model.action

    def list_engagement_history(
        self, user_id: int, since: datetime, limit: int = 500
    ) -> list[DesktopNotification]:
        """Delivered notifications, for working out when this account responds.

        Only delivered rows: a notification that was never shown says nothing
        about whether its hour was a good one. Bounded by both age and count so
        a long-lived account cannot turn a recommendation into a table scan.
        """
        stmt = (
            select(DesktopNotificationModel)
            .where(
                DesktopNotificationModel.user_id == user_id,
                DesktopNotificationModel.delivered_at.is_not(None),
                DesktopNotificationModel.created_at >= since,
            )
            .order_by(DesktopNotificationModel.created_at.desc())
            .limit(limit)
        )
        return [_desktop_notification_to_domain(m) for m in self.db.scalars(stmt)]

    def dismiss_pending_for_reminder(self, user_id: int, reminder_id: int) -> int:
        """Retire every un-collected notification from one reminder.

        Marked delivered rather than deleted: the record that the prompt was
        owed is worth keeping, and `delivered_at` is already what stops a row
        being shown. Returns how many were retired.
        """
        stmt = select(DesktopNotificationModel).where(
            DesktopNotificationModel.user_id == user_id,
            DesktopNotificationModel.reminder_id == reminder_id,
            DesktopNotificationModel.delivered_at.is_(None),
        )
        now = utcnow()
        retired = 0
        for model in self.db.scalars(stmt):
            model.delivered_at = now
            retired += 1
        self.db.flush()
        return retired

    def mark_delivered(self, user_id: int, notification_ids: list[int]) -> int:
        """Acknowledge collection. Returns the number of rows actually moved.

        The `user_id` predicate is not redundant with the id list: without it,
        a caller could acknowledge — and so hide — another account's pending
        notifications by guessing ids. Rows already delivered are excluded, so
        a repeated acknowledgement is a no-op returning 0 rather than
        overwriting the first collection's timestamp.
        """
        if not notification_ids:
            return 0
        stmt = select(DesktopNotificationModel).where(
            DesktopNotificationModel.user_id == user_id,
            DesktopNotificationModel.id.in_(notification_ids),
            DesktopNotificationModel.delivered_at.is_(None),
        )
        now = utcnow()
        moved = 0
        for model in self.db.scalars(stmt):
            model.delivered_at = now
            moved += 1
        self.db.flush()
        return moved

    def purge_delivered_before(self, cutoff: datetime) -> int:
        """Drop collected rows older than `cutoff`, across all accounts.

        Only delivered rows are removed. A pending row is never purged by age
        here — deciding that a notification is too old to still be worth
        showing is the collecting caller's policy (`not_before`), and applying
        it destructively would also discard the record that it was owed.
        """
        stmt = select(DesktopNotificationModel).where(
            DesktopNotificationModel.delivered_at.is_not(None),
            DesktopNotificationModel.delivered_at < cutoff,
        )
        removed = 0
        for model in self.db.scalars(stmt):
            self.db.delete(model)
            removed += 1
        self.db.flush()
        return removed


class SqlAlchemySyncOperationRepository:
    """Append-only log of submitted offline mutations (issue #90)."""

    def __init__(self, db: Session):
        self.db = db

    def find(self, user_id: int, operation_id: str) -> SyncOperationModel | None:
        stmt = select(SyncOperationModel).where(
            SyncOperationModel.user_id == user_id,
            SyncOperationModel.operation_id == operation_id,
        )
        return self.db.scalars(stmt).first()

    def next_sequence(self, user_id: int) -> int:
        """Per-account monotonic cursor.

        Scoped to the account rather than global so one busy user does not
        advance everyone else's cursor and force pointless re-pulls.
        """
        stmt = select(func.max(SyncOperationModel.server_sequence)).where(
            SyncOperationModel.user_id == user_id
        )
        return (self.db.scalar(stmt) or 0) + 1

    def record(
        self,
        user_id: int,
        operation_id: str,
        entity_type: str,
        entity_id: int | None,
        operation: str,
        payload: dict,
        base_revision: int | None,
        status: str,
        conflict_reason: str | None,
    ) -> SyncOperationModel:
        model = SyncOperationModel(
            user_id=user_id,
            operation_id=operation_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            payload=payload,
            base_revision=base_revision,
            status=status,
            conflict_reason=conflict_reason,
            server_sequence=self.next_sequence(user_id),
            created_at=utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def list_since(self, user_id: int, cursor: int, limit: int = 200) -> list[SyncOperationModel]:
        """Everything this account has recorded above `cursor`, oldest first."""
        stmt = (
            select(SyncOperationModel)
            .where(
                SyncOperationModel.user_id == user_id,
                SyncOperationModel.server_sequence > cursor,
            )
            .order_by(SyncOperationModel.server_sequence.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def counts_by_status(self, user_id: int) -> dict[str, int]:
        stmt = (
            select(SyncOperationModel.status, func.count())
            .where(SyncOperationModel.user_id == user_id)
            .group_by(SyncOperationModel.status)
        )
        return {status: count for status, count in self.db.execute(stmt)}

    def last_applied_at(self, user_id: int) -> datetime | None:
        """When sync last actually succeeded — not when it was last attempted.

        A client that has been failing for a day should show yesterday, not a
        timestamp that keeps refreshing while nothing gets through.
        """
        stmt = select(func.max(SyncOperationModel.created_at)).where(
            SyncOperationModel.user_id == user_id,
            SyncOperationModel.status == "applied",
        )
        return self.db.scalar(stmt)

    def list_by_status(self, user_id: int, status: str) -> list[SyncOperationModel]:
        stmt = (
            select(SyncOperationModel)
            .where(
                SyncOperationModel.user_id == user_id,
                SyncOperationModel.status == status,
            )
            .order_by(SyncOperationModel.server_sequence.asc())
        )
        return list(self.db.scalars(stmt))

    def list_conflicts(self, user_id: int) -> list[SyncOperationModel]:
        stmt = (
            select(SyncOperationModel)
            .where(
                SyncOperationModel.user_id == user_id,
                SyncOperationModel.status == "conflict",
            )
            .order_by(SyncOperationModel.server_sequence.asc())
        )
        return list(self.db.scalars(stmt))


class SqlAlchemyMistakeEventRepository:
    """Append-only store of recorded mistakes (issue #134).

    There is no `update`. A mistake is history: rewriting a row when the
    learner later gets the word right would erase the signal the weakness
    profile exists to read.
    """

    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        user_id: int,
        word_id: int,
        category: str,
        attempted_answer: str | None = None,
        confused_with_word_id: int | None = None,
        context: str | None = None,
        occurred_at: datetime | None = None,
    ) -> MistakeEventModel:
        model = MistakeEventModel(
            user_id=user_id,
            word_id=word_id,
            category=category,
            # Truncated rather than rejected. A pathological answer must not be
            # able to fail a review submission — the review is the user's
            # actual work and the mistake record is bookkeeping beside it.
            attempted_answer=(attempted_answer or None) and attempted_answer[:255],
            confused_with_word_id=confused_with_word_id,
            context=context,
            occurrence_count=1,
            occurred_at=occurred_at or utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def list_for_user(self, user_id: int, since: datetime | None = None, limit: int = 1000) -> list[MistakeEventModel]:
        """Recent mistakes, newest first.

        Bounded because the profile aggregates in memory, and a learner with
        years of history should not load all of it to answer one question. The
        cap is on rows rather than time so the answer stays useful for someone
        who reviews rarely.
        """
        stmt = select(MistakeEventModel).where(MistakeEventModel.user_id == user_id)
        if since is not None:
            stmt = stmt.where(MistakeEventModel.occurred_at >= since)
        stmt = stmt.order_by(MistakeEventModel.occurred_at.desc(), MistakeEventModel.id.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def count_for_user(self, user_id: int) -> int:
        stmt = select(func.count()).select_from(MistakeEventModel).where(
            MistakeEventModel.user_id == user_id
        )
        return self.db.scalar(stmt) or 0


class SqlAlchemyWordRevisionRepository:
    """Append-only history of AI-authored field changes (issue #140).

    No update and no delete-by-id. A history whose rows can be rewritten
    cannot answer the one question it exists for.
    """

    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        word_id: int,
        field: str,
        before_value: str | None,
        after_value: str | None,
        source: str,
        changed_at: datetime | None = None,
    ) -> WordFieldRevisionModel:
        model = WordFieldRevisionModel(
            word_id=word_id,
            field=field,
            before_value=before_value,
            after_value=after_value,
            source=source,
            changed_at=changed_at or utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def list_for_word(self, word_id: int, limit: int = 200) -> list[WordFieldRevisionModel]:
        """Newest first.

        Bounded because a card enriched repeatedly could accumulate a long
        history, and the answer to "what did this say before?" is almost always
        in the last few entries.
        """
        stmt = (
            select(WordFieldRevisionModel)
            .where(WordFieldRevisionModel.word_id == word_id)
            .order_by(WordFieldRevisionModel.changed_at.desc(), WordFieldRevisionModel.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))


class SqlAlchemyLearningPathRepository:
    """Learning paths and their milestones (issue #137).

    Stores no progress. Progress is counted from the learner's vocabulary at
    read time — a stored percentage is a number that was true once.
    """

    def __init__(self, db: Session):
        self.db = db

    def add(
        self,
        user_id: int,
        goal: str,
        target_language: str,
        milestones: list,
        group_id: int | None = None,
        ai_provider: str | None = None,
        ai_model: str | None = None,
    ) -> LearningPathModel:
        path = LearningPathModel(
            user_id=user_id,
            group_id=group_id,
            goal=goal,
            target_language=target_language,
            ai_provider=ai_provider,
            ai_model=ai_model,
            created_at=utcnow(),
        )
        for index, plan in enumerate(milestones):
            path.milestones.append(
                PathMilestoneModel(
                    position=index,
                    title=plan.title,
                    description=plan.description,
                    topic=plan.topic,
                    target_word_count=plan.target_word_count,
                    cefr_level=plan.cefr_level,
                )
            )
        self.db.add(path)
        self.db.flush()
        return path

    def get(self, path_id: int) -> LearningPathModel | None:
        stmt = (
            select(LearningPathModel)
            .where(LearningPathModel.id == path_id)
            .options(selectinload(LearningPathModel.milestones))
        )
        return self.db.scalar(stmt)

    def list_for_user(self, user_id: int) -> list[LearningPathModel]:
        stmt = (
            select(LearningPathModel)
            .where(LearningPathModel.user_id == user_id)
            .options(selectinload(LearningPathModel.milestones))
            .order_by(LearningPathModel.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def delete(self, path_id: int) -> None:
        path = self.db.get(LearningPathModel, path_id)
        if path is not None:
            # Milestones go with it through the cascade — a milestone without
            # its path is a step toward nothing.
            self.db.delete(path)
            self.db.flush()

    def words_by_topic(self, user_id: int) -> dict[str, tuple[int, int]]:
        """Count this learner's words per topic, and how many are mastered.

        Counted here rather than in the domain service so the service stays
        pure, and computed from the same strength threshold the CEFR view uses
        so two screens cannot disagree about what "mastered" means.
        """
        stmt = (
            select(WordModel.topics, WordModel.strength, WordModel.repetitions)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id)
        )
        counts: dict[str, tuple[int, int]] = {}
        for topics, strength, repetitions in self.db.execute(stmt):
            mastered = bool(repetitions) and (strength or 0) >= MASTERY_STRENGTH
            for topic in topics or []:
                key = str(topic).strip().casefold()
                if not key:
                    continue
                held_count, mastered_count = counts.get(key, (0, 0))
                counts[key] = (held_count + 1, mastered_count + (1 if mastered else 0))
        return counts


class SqlAlchemyConversationRepository:
    """Tutoring conversations and their turns (issue #135)."""

    def __init__(self, db: Session):
        self.db = db

    def start(
        self,
        user_id: int,
        target_language: str,
        difficulty: str,
        group_id: int | None = None,
        scenario: str | None = None,
    ) -> ConversationSessionModel:
        model = ConversationSessionModel(
            user_id=user_id,
            group_id=group_id,
            target_language=target_language,
            difficulty=difficulty,
            scenario=scenario,
            created_at=utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get(self, session_id: int) -> ConversationSessionModel | None:
        stmt = (
            select(ConversationSessionModel)
            .where(ConversationSessionModel.id == session_id)
            .options(selectinload(ConversationSessionModel.messages))
            # populate_existing because messages are appended by id rather than
            # through the relationship, so an instance already in the identity
            # map keeps whatever collection it was first loaded with. Without
            # this, a turn added earlier in the same request is invisible to a
            # read later in it — which looks like the message was never stored.
            .execution_options(populate_existing=True)
        )
        return self.db.scalar(stmt)

    def list_for_user(self, user_id: int, limit: int = 50) -> list[ConversationSessionModel]:
        stmt = (
            select(ConversationSessionModel)
            .where(ConversationSessionModel.user_id == user_id)
            .options(selectinload(ConversationSessionModel.messages))
            .order_by(ConversationSessionModel.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def add_message(
        self,
        session_id: int,
        speaker: str,
        text: str,
        corrections: list | None = None,
    ) -> ConversationMessageModel:
        model = ConversationMessageModel(
            session_id=session_id,
            speaker=speaker,
            text=text,
            corrections=corrections or None,
            created_at=utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def end(self, session_id: int) -> None:
        session = self.db.get(ConversationSessionModel, session_id)
        if session is not None and session.ended_at is None:
            session.ended_at = utcnow()
            self.db.flush()

    def delete(self, session_id: int) -> None:
        session = self.db.get(ConversationSessionModel, session_id)
        if session is None:
            return
        # A role-play attempt (#136) wraps this conversation, and the attempt is
        # unreadable without its transcript — so it goes too. Deleted
        # explicitly rather than left to a cascade that does not exist: without
        # this the delete is a ForeignKeyViolation on Postgres and a silently
        # orphaned row on SQLite, which is the same divergence the
        # tenant-isolation audit caught for room placements and mistake events.
        for attempt in self.db.scalars(
            select(ScenarioAttemptModel).where(ScenarioAttemptModel.session_id == session_id)
        ):
            self.db.delete(attempt)
        # Messages go with the session through the cascade — a turn without its
        # conversation is unreadable.
        self.db.delete(session)
        self.db.flush()

    def recent_terms(self, user_id: int, limit: int = 40) -> list[str]:
        """Words the learner is currently studying, most recently added first.

        Ordered by recency rather than alphabetically because it is what the
        tutor should weave in, and the newest words are the ones needing
        practice.
        """
        stmt = (
            select(WordModel.term)
            .join(GroupModel, WordModel.group_id == GroupModel.id)
            .where(GroupModel.owner_id == user_id)
            .order_by(WordModel.created_at.desc())
            .limit(limit)
        )
        return [term for term in self.db.scalars(stmt) if term]


class SqlAlchemyScenarioAttemptRepository:
    """Role-play attempts (issue #136).

    Thin on purpose: the conversation itself is handled by the conversation
    repository, and this only owns the scenario wrapper around it.
    """

    def __init__(self, db: Session):
        self.db = db

    def add(self, user_id: int, session_id: int, scenario_key: str) -> ScenarioAttemptModel:
        model = ScenarioAttemptModel(
            user_id=user_id,
            session_id=session_id,
            scenario_key=scenario_key,
            started_at=utcnow(),
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get(self, attempt_id: int) -> ScenarioAttemptModel | None:
        return self.db.get(ScenarioAttemptModel, attempt_id)

    def get_by_session(self, session_id: int) -> ScenarioAttemptModel | None:
        stmt = select(ScenarioAttemptModel).where(ScenarioAttemptModel.session_id == session_id)
        return self.db.scalars(stmt).first()

    def list_for_user(self, user_id: int, limit: int = 50) -> list[ScenarioAttemptModel]:
        stmt = (
            select(ScenarioAttemptModel)
            .where(ScenarioAttemptModel.user_id == user_id)
            .order_by(ScenarioAttemptModel.started_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def finish(self, attempt_id: int, evaluation: dict) -> ScenarioAttemptModel | None:
        attempt = self.db.get(ScenarioAttemptModel, attempt_id)
        if attempt is None:
            return None
        attempt.finished_at = utcnow()
        attempt.evaluation = evaluation
        self.db.flush()
        return attempt


def _learning_observation_to_domain(m: LearningObservationModel) -> LearningObservation:
    return LearningObservation(
        observation_id=m.observation_id,
        word_id=m.word_id,
        user_id=m.user_id,
        outcome=ReviewOutcome(m.outcome),
        session_mode=SessionMode(m.session_mode),
        observed_at=m.observed_at,
        operation_id=m.operation_id,
        attempted_answer=m.attempted_answer,
        response_time_ms=m.response_time_ms,
        prompt_direction=m.prompt_direction,
        hint_used=m.hint_used,
        answer_format=m.answer_format,
        modality=m.modality,
        intervention_plan_ref=m.intervention_plan_ref,
        self_reported_confidence=m.self_reported_confidence,
        context_source=m.context_source,
        schema_version=m.schema_version,
    )


def _observation_correction_to_domain(m: ObservationCorrectionModel) -> ObservationCorrection:
    return ObservationCorrection(
        correction_id=m.correction_id,
        observation_id=m.observation_id,
        user_id=m.user_id,
        reason=ObservationCorrectionReason(m.reason),
        note=m.note,
        created_at=m.created_at,
    )


def _not_corrected():
    """A correlated NOT EXISTS clause, added to every diagnosis-facing
    query below so a flagged observation (issue #229 TODO 5) stops being
    evidence without its row ever being touched — the query-time half of
    "corrections are new records, not edits"."""
    return ~exists().where(ObservationCorrectionModel.observation_id == LearningObservationModel.observation_id)


class SqlAlchemyLearningObservationRepository:
    """Append-only store of learning observations (issue #182).

    No update, no delete-by-id — the same append-only reasoning as
    MistakeEventRepository and WordRevisionRepository above: a diagnosis
    built from history that can be silently rewritten cannot be audited.
    """

    def __init__(self, db: Session):
        self.db = db

    def add(self, observation: LearningObservation) -> LearningObservation:
        model = LearningObservationModel(
            observation_id=observation.observation_id or uuid.uuid4().hex,
            # Always populated even when the caller supplied none, so the
            # (user_id, operation_id) unique constraint always applies —
            # a legacy caller's observation is still exactly-once, just
            # under an identity it never chose itself.
            operation_id=observation.operation_id or uuid.uuid4().hex,
            user_id=observation.user_id,
            word_id=observation.word_id,
            outcome=observation.outcome.value,
            session_mode=observation.session_mode.value,
            observed_at=observation.observed_at,
            attempted_answer=observation.attempted_answer,
            response_time_ms=observation.response_time_ms,
            prompt_direction=observation.prompt_direction,
            hint_used=observation.hint_used,
            answer_format=observation.answer_format,
            modality=observation.modality,
            intervention_plan_ref=observation.intervention_plan_ref,
            self_reported_confidence=observation.self_reported_confidence,
            context_source=observation.context_source,
            schema_version=observation.schema_version,
        )
        self.db.add(model)
        self.db.flush()
        return _learning_observation_to_domain(model)

    def get_by_id(self, user_id: int, observation_id: str) -> LearningObservation | None:
        stmt = select(LearningObservationModel).where(
            LearningObservationModel.user_id == user_id,
            LearningObservationModel.observation_id == observation_id,
        )
        model = self.db.scalars(stmt).first()
        return _learning_observation_to_domain(model) if model else None

    def find_by_operation(self, user_id: int, operation_id: str) -> LearningObservation | None:
        stmt = select(LearningObservationModel).where(
            LearningObservationModel.user_id == user_id,
            LearningObservationModel.operation_id == operation_id,
        )
        model = self.db.scalars(stmt).first()
        return _learning_observation_to_domain(model) if model else None

    def list_for_word(self, user_id: int, word_id: int, limit: int = 500) -> list[LearningObservation]:
        stmt = (
            select(LearningObservationModel)
            .where(
                LearningObservationModel.user_id == user_id,
                LearningObservationModel.word_id == word_id,
                _not_corrected(),
            )
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def list_for_pair(
        self, user_id: int, word_id_a: int, word_id_b: int, limit: int = 500
    ) -> list[LearningObservation]:
        stmt = (
            select(LearningObservationModel)
            .where(
                LearningObservationModel.user_id == user_id,
                LearningObservationModel.word_id.in_((word_id_a, word_id_b)),
                _not_corrected(),
            )
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def list_in_window(
        self, user_id: int, since: datetime, until: datetime, limit: int = 1000
    ) -> list[LearningObservation]:
        stmt = (
            select(LearningObservationModel)
            .where(
                LearningObservationModel.user_id == user_id,
                LearningObservationModel.observed_at >= since,
                LearningObservationModel.observed_at <= until,
                _not_corrected(),
            )
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def list_by_modality(self, user_id: int, modality: str, limit: int = 500) -> list[LearningObservation]:
        stmt = (
            select(LearningObservationModel)
            .where(
                LearningObservationModel.user_id == user_id,
                LearningObservationModel.modality == modality,
                _not_corrected(),
            )
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def list_by_intervention(
        self, user_id: int, intervention_plan_ref: str, limit: int = 500
    ) -> list[LearningObservation]:
        stmt = (
            select(LearningObservationModel)
            .where(
                LearningObservationModel.user_id == user_id,
                LearningObservationModel.intervention_plan_ref == intervention_plan_ref,
                _not_corrected(),
            )
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def list_for_user(self, user_id: int, limit: int = 50, offset: int = 0) -> list[LearningObservation]:
        # Deliberately no _not_corrected() filter — see the protocol
        # docstring: a learner's own history view must still show what
        # they already flagged.
        stmt = (
            select(LearningObservationModel)
            .where(LearningObservationModel.user_id == user_id)
            .order_by(LearningObservationModel.observed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_learning_observation_to_domain(m) for m in self.db.scalars(stmt)]

    def add_correction(self, correction: ObservationCorrection) -> ObservationCorrection:
        model = ObservationCorrectionModel(
            correction_id=correction.correction_id or uuid.uuid4().hex,
            user_id=correction.user_id,
            observation_id=correction.observation_id,
            reason=correction.reason.value,
            note=correction.note,
            created_at=correction.created_at,
        )
        self.db.add(model)
        self.db.flush()
        return _observation_correction_to_domain(model)

    def correction_for(self, user_id: int, observation_id: str) -> ObservationCorrection | None:
        stmt = select(ObservationCorrectionModel).where(
            ObservationCorrectionModel.user_id == user_id,
            ObservationCorrectionModel.observation_id == observation_id,
        )
        model = self.db.scalars(stmt).first()
        return _observation_correction_to_domain(model) if model else None

    def corrections_for(self, user_id: int, observation_ids: list[str]) -> dict[str, ObservationCorrection]:
        if not observation_ids:
            return {}
        stmt = select(ObservationCorrectionModel).where(
            ObservationCorrectionModel.user_id == user_id,
            ObservationCorrectionModel.observation_id.in_(observation_ids),
        )
        return {m.observation_id: _observation_correction_to_domain(m) for m in self.db.scalars(stmt)}


def _knowledge_edge_to_domain(m: KnowledgeEdgeModel) -> KnowledgeEdge:
    return KnowledgeEdge(
        source_id=m.source_id,
        target_id=m.target_id,
        relation=Relation(m.relation),
        evidence=m.evidence,
        occurrences=m.occurrences,
    )


class SqlAlchemyKnowledgeEdgeRepository:
    """Persisted knowledge-graph edges (issue #138 completion, #203).

    `strength` is stored but never accepted as an argument here — it is
    `KnowledgeEdge.strength`, a pure function of relation and occurrences,
    computed fresh from the domain object being written so the column can
    never drift from what re-deriving it would give.
    """

    def __init__(self, db: Session):
        self.db = db

    def list_all_for_user(self, user_id: int) -> list[KnowledgeEdge]:
        stmt = select(KnowledgeEdgeModel).where(KnowledgeEdgeModel.user_id == user_id)
        return [_knowledge_edge_to_domain(m) for m in self.db.scalars(stmt)]

    def list_related(self, user_id: int, word_id: int, limit: int) -> list[KnowledgeEdge]:
        stmt = (
            select(KnowledgeEdgeModel)
            .where(
                KnowledgeEdgeModel.user_id == user_id,
                or_(KnowledgeEdgeModel.source_id == word_id, KnowledgeEdgeModel.target_id == word_id),
            )
            .order_by(
                KnowledgeEdgeModel.strength.desc(), KnowledgeEdgeModel.source_id, KnowledgeEdgeModel.target_id
            )
            .limit(limit)
        )
        return [_knowledge_edge_to_domain(m) for m in self.db.scalars(stmt)]

    def replace_for_word(self, user_id: int, word_id: int, edges: list[KnowledgeEdge]) -> None:
        self.db.execute(
            delete(KnowledgeEdgeModel).where(
                KnowledgeEdgeModel.user_id == user_id,
                or_(KnowledgeEdgeModel.source_id == word_id, KnowledgeEdgeModel.target_id == word_id),
            )
        )
        now = utcnow()
        for edge in edges:
            # Defensive, not trusting: only ever write rows that actually
            # touch word_id, regardless of what the caller passed in —
            # otherwise a caller's bug could silently bump `updated_at` on
            # an edge between two unrelated words.
            if word_id not in (edge.source_id, edge.target_id):
                continue
            self.db.add(
                KnowledgeEdgeModel(
                    user_id=user_id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relation=edge.relation.value,
                    strength=edge.strength,
                    evidence=edge.evidence,
                    occurrences=edge.occurrences,
                    updated_at=now,
                )
            )
        self.db.flush()

    def delete_for_word(self, user_id: int, word_id: int) -> None:
        self.db.execute(
            delete(KnowledgeEdgeModel).where(
                KnowledgeEdgeModel.user_id == user_id,
                or_(KnowledgeEdgeModel.source_id == word_id, KnowledgeEdgeModel.target_id == word_id),
            )
        )
        self.db.flush()

    def replace_all_for_user(self, user_id: int, edges: list[KnowledgeEdge]) -> None:
        self.db.execute(delete(KnowledgeEdgeModel).where(KnowledgeEdgeModel.user_id == user_id))
        now = utcnow()
        for edge in edges:
            self.db.add(
                KnowledgeEdgeModel(
                    user_id=user_id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relation=edge.relation.value,
                    strength=edge.strength,
                    evidence=edge.evidence,
                    occurrences=edge.occurrences,
                    updated_at=now,
                )
            )
        self.db.flush()


def _evidence_to_json(evidence: tuple[DiagnosisEvidence, ...]) -> list[dict]:
    return [
        {"kind": e.kind, "observation_ids": list(e.observation_ids), "weight": e.weight, "description": e.description}
        for e in evidence
    ]


def _evidence_from_json(payload: list[dict]) -> tuple[DiagnosisEvidence, ...]:
    return tuple(
        DiagnosisEvidence(
            kind=item["kind"],
            observation_ids=tuple(item["observation_ids"]),
            weight=item["weight"],
            description=item["description"],
        )
        for item in payload
    )


def _diagnosis_to_domain(m: DiagnosisModel) -> Diagnosis:
    return Diagnosis(
        word_id=m.word_id,
        user_id=m.user_id,
        outcome=m.outcome,
        evidence=_evidence_from_json(m.evidence),
        confidence=m.confidence,
        rules_version=m.rules_version,
        diagnosed_at=m.diagnosed_at,
        sample_size=m.sample_size,
        competing_hypotheses=tuple(m.competing_hypotheses),
        related_word_id=m.related_word_id,
    )


class SqlAlchemyDiagnosisRepository:
    """Append-only store of deterministic diagnoses (issue #183)."""

    def __init__(self, db: Session):
        self.db = db

    def add(self, diagnosis: Diagnosis) -> Diagnosis:
        model = DiagnosisModel(
            user_id=diagnosis.user_id,
            word_id=diagnosis.word_id,
            outcome=diagnosis.outcome,
            evidence=_evidence_to_json(diagnosis.evidence),
            confidence=diagnosis.confidence,
            rules_version=diagnosis.rules_version,
            diagnosed_at=diagnosis.diagnosed_at,
            sample_size=diagnosis.sample_size,
            competing_hypotheses=list(diagnosis.competing_hypotheses),
            related_word_id=diagnosis.related_word_id,
        )
        self.db.add(model)
        self.db.flush()
        return _diagnosis_to_domain(model)

    def latest_for_word(self, user_id: int, word_id: int) -> Diagnosis | None:
        stmt = (
            select(DiagnosisModel)
            .where(DiagnosisModel.user_id == user_id, DiagnosisModel.word_id == word_id)
            .order_by(DiagnosisModel.diagnosed_at.desc())
            .limit(1)
        )
        model = self.db.scalars(stmt).first()
        return _diagnosis_to_domain(model) if model else None

    def list_for_word(self, user_id: int, word_id: int, limit: int = 50) -> list[Diagnosis]:
        stmt = (
            select(DiagnosisModel)
            .where(DiagnosisModel.user_id == user_id, DiagnosisModel.word_id == word_id)
            .order_by(DiagnosisModel.diagnosed_at.desc())
            .limit(limit)
        )
        return [_diagnosis_to_domain(m) for m in self.db.scalars(stmt)]


def _prerequisite_ids_to_column(ids: tuple[int, ...]) -> str | None:
    return ",".join(str(i) for i in ids) if ids else None


def _prerequisite_ids_from_column(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part) for part in value.split(","))


def _intervention_plan_to_domain(m: InterventionPlanModel) -> InterventionPlan:
    return InterventionPlan(
        id=m.id,
        word_id=m.word_id,
        user_id=m.user_id,
        diagnosis_outcome=m.diagnosis_outcome,
        strategy=m.strategy,
        policy_version=m.policy_version,
        eligible=m.eligible,
        rationale=m.rationale,
        planned_at=m.planned_at,
        scheduled_for=m.scheduled_for,
        second_word_id=m.second_word_id,
        prerequisite_ids=_prerequisite_ids_from_column(m.prerequisite_ids),
    )


def _intervention_outcome_to_domain(m: InterventionOutcomeModel) -> InterventionOutcome:
    return InterventionOutcome(
        word_id=m.word_id,
        user_id=m.user_id,
        strategy=m.strategy,
        completed=m.completed,
        result=m.result,
        recorded_at=m.recorded_at,
        completed_at=m.completed_at,
        horizon=m.horizon,
    )


class SqlAlchemyInterventionRepository:
    """Append-only store of intervention plans and their outcomes (issue
    #185) — the same shape `SqlAlchemyDiagnosisRepository` above uses."""

    def __init__(self, db: Session):
        self.db = db

    def add_plan(self, plan: InterventionPlan) -> InterventionPlan:
        model = InterventionPlanModel(
            user_id=plan.user_id,
            word_id=plan.word_id,
            diagnosis_outcome=plan.diagnosis_outcome,
            strategy=plan.strategy,
            policy_version=plan.policy_version,
            eligible=plan.eligible,
            rationale=plan.rationale,
            planned_at=plan.planned_at,
            scheduled_for=plan.scheduled_for,
            second_word_id=plan.second_word_id,
            prerequisite_ids=_prerequisite_ids_to_column(plan.prerequisite_ids),
        )
        self.db.add(model)
        self.db.flush()
        return _intervention_plan_to_domain(model)

    def add_outcome(self, outcome: InterventionOutcome) -> InterventionOutcome:
        model = InterventionOutcomeModel(
            user_id=outcome.user_id,
            word_id=outcome.word_id,
            strategy=outcome.strategy,
            completed=outcome.completed,
            result=outcome.result,
            recorded_at=outcome.recorded_at,
            completed_at=outcome.completed_at,
            horizon=outcome.horizon,
        )
        self.db.add(model)
        self.db.flush()
        return _intervention_outcome_to_domain(model)

    def list_plans_for_word(self, user_id: int, word_id: int) -> list[InterventionPlan]:
        stmt = (
            select(InterventionPlanModel)
            .where(InterventionPlanModel.user_id == user_id, InterventionPlanModel.word_id == word_id)
            .order_by(InterventionPlanModel.planned_at.desc())
        )
        return [_intervention_plan_to_domain(m) for m in self.db.scalars(stmt)]

    def list_outcomes_for_word(self, user_id: int, word_id: int) -> list[InterventionOutcome]:
        stmt = (
            select(InterventionOutcomeModel)
            .where(InterventionOutcomeModel.user_id == user_id, InterventionOutcomeModel.word_id == word_id)
            .order_by(InterventionOutcomeModel.recorded_at.desc())
        )
        return [_intervention_outcome_to_domain(m) for m in self.db.scalars(stmt)]

    def get_plan(self, user_id: int, plan_id: int) -> InterventionPlan | None:
        stmt = select(InterventionPlanModel).where(
            InterventionPlanModel.user_id == user_id, InterventionPlanModel.id == plan_id
        )
        model = self.db.scalars(stmt).first()
        return _intervention_plan_to_domain(model) if model is not None else None

    def list_all_for_user(self, user_id: int) -> list[InterventionPlan]:
        stmt = (
            select(InterventionPlanModel)
            .where(InterventionPlanModel.user_id == user_id)
            .order_by(InterventionPlanModel.planned_at.desc())
        )
        return [_intervention_plan_to_domain(m) for m in self.db.scalars(stmt)]

    def list_all_outcomes_for_user(self, user_id: int) -> list[InterventionOutcome]:
        stmt = (
            select(InterventionOutcomeModel)
            .where(InterventionOutcomeModel.user_id == user_id)
            .order_by(InterventionOutcomeModel.recorded_at.desc())
        )
        return [_intervention_outcome_to_domain(m) for m in self.db.scalars(stmt)]


def _companion_session_to_domain(m: CompanionSessionModel) -> CompanionSession:
    return CompanionSession(
        id=m.id,
        user_id=m.user_id,
        connection_id=m.connection_id,
        client_id=m.client_id,
        goal=m.goal,
        language=m.language,
        group_id=m.group_id,
        difficulty=m.difficulty,
        active_activity=m.active_activity,
        consent_snapshot=dict(m.consent_snapshot or {}),
        summary=m.summary,
        status=CompanionSessionStatus(m.status),
        revision=m.revision,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _companion_turn_to_domain(m: CompanionTurnModel) -> CompanionTurn:
    return CompanionTurn(
        id=m.id,
        session_id=m.session_id,
        role=CompanionTurnRole(m.role),
        content=m.content,
        activity_id=m.activity_id,
        operation_id=m.operation_id,
        created_at=m.created_at,
    )


class SqlAlchemyCompanionSessionRepository:
    """Tenant-scoped persistence for normalized companion sessions (#193)."""

    def __init__(self, db: Session):
        self.db = db

    def add(self, session: CompanionSession) -> CompanionSession:
        model = CompanionSessionModel(
            id=session.id,
            user_id=session.user_id,
            connection_id=session.connection_id,
            client_id=session.client_id,
            goal=session.goal,
            language=session.language,
            group_id=session.group_id,
            difficulty=session.difficulty,
            active_activity=session.active_activity,
            consent_snapshot=session.consent_snapshot,
            summary=session.summary,
            status=session.status.value,
            revision=session.revision,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        self.db.add(model)
        self.db.flush()
        return _companion_session_to_domain(model)

    def get(self, user_id: int, session_id: str) -> CompanionSession | None:
        model = self.db.scalar(
            select(CompanionSessionModel).where(
                CompanionSessionModel.id == session_id,
                CompanionSessionModel.user_id == user_id,
            )
        )
        return _companion_session_to_domain(model) if model else None

    def update(self, session: CompanionSession) -> CompanionSession:
        model = self.db.scalar(
            select(CompanionSessionModel).where(
                CompanionSessionModel.id == session.id,
                CompanionSessionModel.user_id == session.user_id,
            )
        )
        if model is None:
            raise ValueError("Companion session not found")
        model.goal = session.goal
        model.language = session.language
        model.group_id = session.group_id
        model.difficulty = session.difficulty
        model.active_activity = session.active_activity
        model.consent_snapshot = session.consent_snapshot
        model.summary = session.summary
        model.status = session.status.value
        model.revision = session.revision
        model.updated_at = session.updated_at
        self.db.flush()
        return _companion_session_to_domain(model)

    def list_turns(self, user_id: int, session_id: str, limit: int = 100) -> list[CompanionTurn]:
        if self.get(user_id, session_id) is None:
            return []
        stmt = (
            select(CompanionTurnModel)
            .join(CompanionSessionModel, CompanionSessionModel.id == CompanionTurnModel.session_id)
            .where(CompanionSessionModel.id == session_id, CompanionSessionModel.user_id == user_id)
            .order_by(CompanionTurnModel.created_at.asc(), CompanionTurnModel.id.asc())
            .limit(min(max(limit, 1), 100))
        )
        return [_companion_turn_to_domain(model) for model in self.db.scalars(stmt)]

    def add_turn(self, turn: CompanionTurn) -> CompanionTurn:
        model = CompanionTurnModel(
            session_id=turn.session_id,
            role=turn.role.value,
            content=turn.content,
            activity_id=turn.activity_id,
            operation_id=turn.operation_id,
            created_at=turn.created_at,
        )
        self.db.add(model)
        self.db.flush()
        return _companion_turn_to_domain(model)

    def find_turn_by_operation(self, user_id: int, session_id: str, operation_id: str) -> CompanionTurn | None:
        model = self.db.scalar(
            select(CompanionTurnModel)
            .join(CompanionSessionModel, CompanionSessionModel.id == CompanionTurnModel.session_id)
            .where(
                CompanionSessionModel.id == session_id,
                CompanionSessionModel.user_id == user_id,
                CompanionTurnModel.operation_id == operation_id,
            )
        )
        return _companion_turn_to_domain(model) if model else None

    def delete_content(self, user_id: int, session_id: str) -> None:
        session = self.db.scalar(
            select(CompanionSessionModel).where(
                CompanionSessionModel.id == session_id,
                CompanionSessionModel.user_id == user_id,
            )
        )
        if session is None:
            return
        self.db.query(CompanionTurnModel).filter(CompanionTurnModel.session_id == session_id).delete()
        session.summary = "[content deleted]"
        session.revision += 1
        session.updated_at = utcnow()
        self.db.flush()


def _companion_activity_to_domain(m: CompanionActivityModel) -> LearningActivity:
    return LearningActivity(
        id=m.id,
        session_id=m.session_id,
        user_id=m.user_id,
        activity_type=ActivityType(m.activity_type),
        prompt=m.prompt,
        expected_evaluation=dict(m.expected_evaluation or {}),
        status=ActivityStatus(m.status),
        response=m.response,
        result=dict(m.result) if m.result is not None else None,
        operation_id=m.operation_id,
        started_at=m.started_at,
        updated_at=m.updated_at,
        revision=m.revision,
    )


class SqlAlchemyCompanionActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, activity: LearningActivity) -> LearningActivity:
        model = CompanionActivityModel(
            id=activity.id,
            session_id=activity.session_id,
            user_id=activity.user_id,
            activity_type=activity.activity_type.value,
            prompt=activity.prompt,
            expected_evaluation=activity.expected_evaluation,
            status=activity.status.value,
            response=activity.response,
            result=activity.result,
            operation_id=activity.operation_id,
            started_at=activity.started_at,
            updated_at=activity.updated_at,
            revision=activity.revision,
        )
        self.db.add(model)
        self.db.flush()
        return _companion_activity_to_domain(model)

    def get(self, user_id: int, session_id: str, activity_id: str) -> LearningActivity | None:
        model = self.db.scalar(
            select(CompanionActivityModel).where(
                CompanionActivityModel.id == activity_id,
                CompanionActivityModel.session_id == session_id,
                CompanionActivityModel.user_id == user_id,
            )
        )
        return _companion_activity_to_domain(model) if model else None

    def update(self, activity: LearningActivity) -> LearningActivity:
        model = self.db.get(CompanionActivityModel, activity.id)
        if model is None or model.user_id != activity.user_id or model.session_id != activity.session_id:
            raise ValueError("Companion activity not found")
        model.status = activity.status.value
        model.response = activity.response
        model.result = activity.result
        model.updated_at = activity.updated_at
        model.revision = activity.revision
        self.db.flush()
        return _companion_activity_to_domain(model)

    def find_by_operation(self, user_id: int, session_id: str, operation_id: str) -> LearningActivity | None:
        model = self.db.scalar(
            select(CompanionActivityModel).where(
                CompanionActivityModel.user_id == user_id,
                CompanionActivityModel.session_id == session_id,
                CompanionActivityModel.operation_id == operation_id,
            )
        )
        return _companion_activity_to_domain(model) if model else None


def _companion_task_to_domain(m: CompanionTaskModel) -> CompanionTask:
    return CompanionTask(
        id=m.id,
        session_id=m.session_id,
        user_id=m.user_id,
        task_type=CompanionTaskType(m.task_type),
        status=CompanionTaskStatus(m.status),
        total_units=m.total_units,
        completed_units=m.completed_units,
        result=dict(m.result) if m.result is not None else None,
        error=m.error,
        operation_id=m.operation_id,
        expires_at=m.expires_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
        revision=m.revision,
    )


class SqlAlchemyCompanionTaskRepository:
    """Owner/session-scoped durable task state (#197)."""

    def __init__(self, db: Session):
        self.db = db

    def add(self, task: CompanionTask) -> CompanionTask:
        model = CompanionTaskModel(
            id=task.id,
            session_id=task.session_id,
            user_id=task.user_id,
            task_type=task.task_type.value,
            status=task.status.value,
            total_units=task.total_units,
            completed_units=task.completed_units,
            result=task.result,
            error=task.error,
            operation_id=task.operation_id,
            expires_at=task.expires_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
            revision=task.revision,
        )
        self.db.add(model)
        self.db.flush()
        return _companion_task_to_domain(model)

    def get(self, user_id: int, session_id: str, task_id: str) -> CompanionTask | None:
        model = self.db.scalar(
            select(CompanionTaskModel).where(
                CompanionTaskModel.id == task_id,
                CompanionTaskModel.session_id == session_id,
                CompanionTaskModel.user_id == user_id,
            )
        )
        return _companion_task_to_domain(model) if model else None

    def update(self, task: CompanionTask) -> CompanionTask:
        model = self.db.get(CompanionTaskModel, task.id)
        if model is None or model.user_id != task.user_id or model.session_id != task.session_id:
            raise ValueError("Companion task not found")
        model.status = task.status.value
        model.completed_units = task.completed_units
        model.result = task.result
        model.error = task.error
        model.expires_at = task.expires_at
        model.updated_at = task.updated_at
        model.revision = task.revision
        self.db.flush()
        return _companion_task_to_domain(model)

    def list_for_session(self, user_id: int, session_id: str, limit: int = 50) -> list[CompanionTask]:
        stmt = (
            select(CompanionTaskModel)
            .where(
                CompanionTaskModel.user_id == user_id,
                CompanionTaskModel.session_id == session_id,
            )
            .order_by(CompanionTaskModel.created_at.desc(), CompanionTaskModel.id.desc())
            .limit(min(max(limit, 1), 100))
        )
        return [_companion_task_to_domain(model) for model in self.db.scalars(stmt)]

    def find_by_operation(self, user_id: int, session_id: str, operation_id: str) -> CompanionTask | None:
        model = self.db.scalar(
            select(CompanionTaskModel).where(
                CompanionTaskModel.user_id == user_id,
                CompanionTaskModel.session_id == session_id,
                CompanionTaskModel.operation_id == operation_id,
            )
        )
        return _companion_task_to_domain(model) if model else None


def _acquisition_state_to_domain(m: AcquisitionEventModel) -> AcquisitionState:
    return AcquisitionState(
        word_id=m.word_id,
        user_id=m.user_id,
        rung=m.rung,
        ladder_version=m.ladder_version,
        started_at=m.started_at,
        updated_at=m.updated_at,
        graduated=m.graduated,
        entry_reason=m.entry_reason,
        operation_id=m.operation_id,
    )


class SqlAlchemyAcquisitionStateRepository:
    """Append-only store of ladder transitions (issue #184). `upsert`
    always inserts a new row; "the current state" `get_for_word` returns
    is the most recent one — see `AcquisitionEventModel`'s docstring."""

    def __init__(self, db: Session):
        self.db = db

    def get_for_word(self, user_id: int, word_id: int) -> AcquisitionState | None:
        stmt = (
            select(AcquisitionEventModel)
            .where(AcquisitionEventModel.user_id == user_id, AcquisitionEventModel.word_id == word_id)
            .order_by(AcquisitionEventModel.updated_at.desc())
            .limit(1)
        )
        model = self.db.scalars(stmt).first()
        return _acquisition_state_to_domain(model) if model else None

    def upsert(self, state: AcquisitionState) -> AcquisitionState:
        if state.operation_id is not None:
            # #184 TODO 2's "retries do not duplicate observations": a
            # retried submission with the same operation_id returns the
            # transition it already produced rather than recording a
            # second one.
            existing = self.db.scalars(
                select(AcquisitionEventModel).where(
                    AcquisitionEventModel.user_id == state.user_id,
                    AcquisitionEventModel.operation_id == state.operation_id,
                )
            ).first()
            if existing is not None:
                return _acquisition_state_to_domain(existing)

        model = AcquisitionEventModel(
            user_id=state.user_id,
            word_id=state.word_id,
            rung=state.rung,
            ladder_version=state.ladder_version,
            started_at=state.started_at,
            updated_at=state.updated_at,
            graduated=state.graduated,
            due_at=AcquisitionScheduler().due_at(state),
            entry_reason=state.entry_reason,
            operation_id=state.operation_id,
        )
        self.db.add(model)
        self.db.flush()
        return _acquisition_state_to_domain(model)

    def delete_for_word(self, user_id: int, word_id: int) -> None:
        for row in self.db.scalars(
            select(AcquisitionEventModel).where(
                AcquisitionEventModel.user_id == user_id, AcquisitionEventModel.word_id == word_id
            )
        ):
            self.db.delete(row)
        self.db.flush()

    def list_due(self, now, user_id: int | None = None, limit: int = 500) -> list[AcquisitionState]:
        # Every word's *current* state (the row with the greatest id within
        # its (user_id, word_id) group, append-only so id order and
        # updated_at order agree) is resolved first via the subquery below,
        # and only that row is checked against due_at/graduated — filtering
        # the raw table directly would risk matching an old, since-
        # superseded row that happened to be due when a newer, not-yet-due
        # transition for the same word should shadow it.
        group_by = [AcquisitionEventModel.user_id, AcquisitionEventModel.word_id]
        latest_ids_query = select(func.max(AcquisitionEventModel.id).label("id"))
        if user_id is not None:
            latest_ids_query = latest_ids_query.where(AcquisitionEventModel.user_id == user_id)
        latest_ids = latest_ids_query.group_by(*group_by).subquery()

        stmt = (
            select(AcquisitionEventModel)
            .join(latest_ids, AcquisitionEventModel.id == latest_ids.c.id)
            .where(AcquisitionEventModel.graduated.is_(False), AcquisitionEventModel.due_at <= now)
            .order_by(AcquisitionEventModel.due_at)
            .limit(limit)
        )
        return [_acquisition_state_to_domain(m) for m in self.db.scalars(stmt)]
