import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

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


def test_reminders_table_has_expected_columns():
    column_names = {c.name for c in ReminderModel.__table__.columns}
    assert column_names == {"id", "user_id", "group_id", "trigger_time", "recurrence", "enabled", "created_at"}


def test_migration_applies_cleanly_on_a_copy_of_backend_data(tmp_path):
    """The 'migration' here is Base.metadata.create_all() (this project has
    no Alembic yet — see README's Known Gaps), which is additive. This
    proves it runs cleanly against a copy of the real on-disk database
    without altering any existing table's row count, regardless of whether
    `reminders` already exists there (the app's lifespan calls init_db()
    against whatever DATABASE_URL resolves to — the real file by default —
    so other tests in the same run may have already created it here)."""
    source_db = Path(__file__).parent.parent / "data" / "lensword.db"
    if not source_db.exists():
        pytest.skip("no backend/data/lensword.db present to copy")

    copy_path = tmp_path / "lensword_copy.db"
    shutil.copy(source_db, copy_path)
    engine = create_engine(f"sqlite:///{copy_path}")

    tables_before = set(inspect(engine).get_table_names())

    with engine.connect() as conn:
        row_counts_before = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables_before
        }

    Base.metadata.create_all(bind=engine)

    tables_after = set(inspect(engine).get_table_names())
    assert "reminders" in tables_after
    assert tables_before <= tables_after  # additive only: nothing pre-existing disappears

    with engine.connect() as conn:
        for table, count_before in row_counts_before.items():
            count_after = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert count_after == count_before, f"{table} row count changed after migration"

    engine.dispose()

    engine.dispose()
