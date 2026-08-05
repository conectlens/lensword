"""Persist recorded mistakes (issue #134).

Revision ID: 20260730_15
Revises: 20260730_14

The weakness profile already knows how to aggregate mistakes; until now there
was nothing to aggregate, because errors were computed at review time and
thrown away. This is the table that keeps them.

Append-only by intent. Nothing in the application updates a row: a mistake is
history, and rewriting it when the learner later gets the word right would
erase exactly the signal the profile is built from.

`confused_with_word_id` is nullable and stays nullable. When the word someone
was confusing this one with is deleted, the mistake still happened — it
degrades to a plain wrong-word error rather than vanishing with the other word
or leaving a reference to a row that no longer exists.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_15"
down_revision = "20260730_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "mistake_events" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "mistake_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("attempted_answer", sa.String(length=255), nullable=True),
        sa.Column(
            "confused_with_word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=True
        ),
        sa.Column("context", sa.String(length=32), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mistake_events_user_id", "mistake_events", ["user_id"])
    op.create_index("ix_mistake_events_word_id", "mistake_events", ["word_id"])
    op.create_index("ix_mistake_events_category", "mistake_events", ["category"])
    op.create_index(
        "ix_mistake_events_confused_with_word_id", "mistake_events", ["confused_with_word_id"]
    )
    op.create_index("ix_mistake_events_occurred_at", "mistake_events", ["occurred_at"])
    # The profile query is always "this learner's mistakes, recent first".
    op.create_index(
        "ix_mistake_events_user_occurred", "mistake_events", ["user_id", "occurred_at"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "mistake_events" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table("mistake_events")
