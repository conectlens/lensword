"""Add the domain-kernel spike developer flag (#189 TODO 2).

Revision ID: 20260807_36
Revises: 20260807_35

Kept short (revision ids over 32 characters overflow Postgres's default
alembic_version.version_num VARCHAR(32), which failed CI for a similarly
long merge-revision id earlier in this history — see the fix on
20260807_32).

domain_kernel_spike_enabled gates the software-concepts domain-kernel
spike (app.domain.services.software_concepts_spike), the one non-language
architecture proof for the domain-neutral kernel
(docs/adr/0009-domain-neutral-kernel.md). Off by default like every other
RecallSettings flag; unlike the others, it is not surfaced in the public
settings API — there is nothing for an end user to opt into here.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_36"
down_revision = "20260807_35"
branch_labels = None
depends_on = None

_COLUMN = "domain_kernel_spike_enabled"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return

    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    if _COLUMN not in existing:
        # NOT NULL with a real server default — a Python-side `default=`
        # alone is not enough, for the same reason as 20260805_22's and
        # 20260806_28's own flag columns: a fresh database bootstraps this
        # table from the current ORM models (20260730_01), so this column
        # already exists by the time migration 20260730_14's raw,
        # historically-frozen backfill INSERT runs; that INSERT's column
        # list predates this field and cannot name it, so only a real
        # server-side default lets it succeed.
        op.add_column(
            "recall_settings",
            sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    with op.batch_alter_table("recall_settings") as batch:
        if _COLUMN in present:
            batch.drop_column(_COLUMN)
