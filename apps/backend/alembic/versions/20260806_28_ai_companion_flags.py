"""Add the four AI Companion opt-in flags (ADR 0008, issue #191 TODO 3).

Revision ID: 20260806_28
Revises: 20260806_27

ai_companion_enabled, companion_sampling_enabled, companion_remote_enabled,
and companion_multimodal_enabled are independently controllable: remote and
multimodal access are each their own opt-in, not implied by turning the
companion on at all.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_28"
down_revision = "20260806_27"
branch_labels = None
depends_on = None

_COLUMNS = (
    "ai_companion_enabled",
    "companion_sampling_enabled",
    "companion_remote_enabled",
    "companion_multimodal_enabled",
)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return

    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    for name in _COLUMNS:
        if name not in existing:
            # NOT NULL with a real server default — a Python-side `default=`
            # alone is not enough here, for the same reason as
            # 20260805_22's learning-diagnosis flags: a fresh database
            # bootstraps this table from the current ORM models
            # (20260730_01), so this column already exists by the time
            # migration 20260730_14's raw, historically-frozen backfill
            # INSERT runs; that INSERT's column list predates this field
            # and cannot name it, so only a real server-side default lets
            # it succeed (see the comment on this column in
            # app.infrastructure.models).
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
