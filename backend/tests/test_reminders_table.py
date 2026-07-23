from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.domain.value_objects import utcnow
from app.infrastructure.db import Base
from app.infrastructure.models import GroupModel, ReminderModel, UserModel


def test_reminder_model_persists_and_reads_back(db_session):
    user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
    db_session.add(user)
    db_session.flush()

    group = GroupModel(owner_id=user.id, name="Spanish Verbs", target_language="Spanish", created_at=utcnow())
    db_session.add(group)
    db_session.flush()

    reminder = ReminderModel(
        user_id=user.id,
        group_id=group.id,
        trigger_time="09:00",
        recurrence="daily",
        created_at=utcnow(),
    )
    db_session.add(reminder)
    db_session.commit()

    fetched = db_session.query(ReminderModel).one()
    assert fetched.trigger_time == "09:00"
    assert fetched.recurrence == "daily"
    assert fetched.enabled is True
    assert fetched.user_id == user.id
    assert fetched.group_id == group.id


EXPECTED_REMINDER_COLUMNS = {
    "id",
    "user_id",
    "group_id",
    "trigger_time",
    "recurrence",
    "enabled",
    "created_at",
}


def test_reminders_table_has_expected_columns():
    column_names = {c.name for c in ReminderModel.__table__.columns}
    assert column_names == EXPECTED_REMINDER_COLUMNS


def _database_as_it_stood_before_the_reminders_migration(path):
    """Build the previous schema: every table except `reminders`.

    Deriving it from the current metadata keeps the fixture from rotting as
    other tables change, and needs nothing outside the temporary directory it
    is handed — no copy of anyone's real database, and no assumption that some
    earlier test happened to leave one lying around.
    """
    engine = create_engine(f"sqlite:///{path}")
    earlier_tables = [
        table for name, table in Base.metadata.tables.items() if name != ReminderModel.__tablename__
    ]
    Base.metadata.create_all(bind=engine, tables=earlier_tables)
    return engine


def _row_counts(engine, tables):
    with engine.connect() as conn:
        return {table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables}


def test_migration_adds_the_reminders_table_to_an_existing_database(tmp_path):
    """The 'migration' here is Base.metadata.create_all() (this project has no
    Alembic yet — see README's Known Gaps), which is additive and, because
    create_all defaults to checkfirst=True, skips tables already present.

    The database under test is built here rather than copied from
    backend/data/, so this runs on a clean checkout and on continuous
    integration. It previously copied the developer's real database and skipped
    when there was none, which meant it only ever ran because an unrelated test
    created that file as a side effect.
    """
    engine = _database_as_it_stood_before_the_reminders_migration(tmp_path / "lensword.db")

    tables_before = set(inspect(engine).get_table_names())
    assert "reminders" not in tables_before, "the fixture must start from the pre-migration schema"

    # Existing data whose survival is the whole point of an additive migration.
    with Session(engine) as session:
        user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
        session.add(user)
        session.flush()
        session.add(
            GroupModel(owner_id=user.id, name="Spanish Verbs", target_language="Spanish", created_at=utcnow())
        )
        session.commit()

    row_counts_before = _row_counts(engine, tables_before)
    assert row_counts_before["users"] == 1
    assert row_counts_before["groups"] == 1

    Base.metadata.create_all(bind=engine)

    tables_after = set(inspect(engine).get_table_names())
    assert "reminders" in tables_after
    assert tables_before <= tables_after  # additive only: nothing pre-existing disappears
    assert _row_counts(engine, tables_before) == row_counts_before

    created_columns = {c["name"] for c in inspect(engine).get_columns("reminders")}
    assert created_columns == EXPECTED_REMINDER_COLUMNS

    engine.dispose()


def test_migration_can_be_applied_twice_without_failing(tmp_path):
    """create_all documents checkfirst=True — it will not re-issue CREATE for a
    table already present — so re-running it is a guarantee worth holding it
    to: the app calls init_db() on every single startup.
    """
    engine = _database_as_it_stood_before_the_reminders_migration(tmp_path / "lensword.db")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        user = UserModel(username="alex", email="alex@example.com", hashed_password="x", created_at=utcnow())
        session.add(user)
        session.flush()
        group = GroupModel(
            owner_id=user.id, name="Spanish Verbs", target_language="Spanish", created_at=utcnow()
        )
        session.add(group)
        session.flush()
        session.add(
            ReminderModel(
                user_id=user.id,
                group_id=group.id,
                trigger_time="09:00",
                recurrence="daily",
                created_at=utcnow(),
            )
        )
        session.commit()

    tables_before = set(inspect(engine).get_table_names())
    row_counts_before = _row_counts(engine, tables_before)

    Base.metadata.create_all(bind=engine)  # must not raise

    assert set(inspect(engine).get_table_names()) == tables_before
    assert _row_counts(engine, tables_before) == row_counts_before
    assert row_counts_before["reminders"] == 1  # the stored reminder survived re-running it

    engine.dispose()
