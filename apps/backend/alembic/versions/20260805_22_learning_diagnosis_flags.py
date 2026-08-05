"""Add the three AI Learning Diagnosis opt-in flags (ADR 0007, issue #181).

Revision ID: 20260805_22
Revises: 20260805_21

learning_diagnosis_enabled, acquisition_loop_enabled, and ai_coach_enabled
are independently controllable (issue #181 TODO 1): deterministic diagnosis
must not require the AI coach, so these are three flags, not one.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_22"
down_revision = "20260805_21"
branch_labels = None
depends_on = None

_COLUMNS = ("learning_diagnosis_enabled", "acquisition_loop_enabled", "ai_coach_enabled")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return

    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    for name in _COLUMNS:
        if name not in existing:
            # NOT NULL with a real server default — a Python-side `default=`
            # alone is not enough here. A fresh database bootstraps this
            # table from the current ORM models (20260730_01), so this
            # column already exists by the time migration 20260730_14's raw,
            # historically-frozen backfill INSERT runs; that INSERT's column
            # list predates this field and cannot name it, so only a real
            # server-side default lets it succeed (see the comment on this
            # column in app.infrastructure.models).
            op.add_column(
                "recall_settings",
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    with op.batch_alter_table("recall_settings") as batch:
        for name in _COLUMNS:
            if name in present:
                batch.drop_column(name)
