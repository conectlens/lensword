"""Persist deterministic diagnoses (AI Learning Diagnosis epic, issue #183).

Revision ID: 20260806_25
Revises: 20260806_24

Append-only, the same reasoning as learning_observations (#182) and
knowledge_edges (#203): a corrected diagnosis is a new row, never a
rewrite of the one that was actually shown.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_25"
down_revision = "20260806_24"
branch_labels = None
depends_on = None

_TABLE = "diagnoses"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("outcome", sa.String(length=48), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("diagnosed_at", sa.DateTime(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("competing_hypotheses", sa.JSON(), nullable=False),
    )
    op.create_index("ix_diagnoses_user_word_diagnosed", _TABLE, ["user_id", "word_id", "diagnosed_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table(_TABLE)
