"""Verification state and field history for AI-written cards (issue #140).

Revision ID: 20260730_16
Revises: 20260730_15

Words already record which model wrote them. This adds whether a human has
since checked that text, and what it said before.

`ai_verified_at` is a timestamp rather than a boolean. "Verified" with no
"when" cannot be reasoned about once the card changes again — and the
application clears it when a model rewrites a field, so the moment matters.

Existing rows get NULL, which is correct rather than convenient: nobody has
verified them, and defaulting to verified would silently vouch for every card
already in the database.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_16"
down_revision = "20260730_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "words" in tables:
        columns = {c["name"] for c in inspector.get_columns("words")}
        if "ai_verified_at" not in columns:
            op.add_column("words", sa.Column("ai_verified_at", sa.DateTime(), nullable=True))

    if "word_field_revisions" not in tables:
        op.create_table(
            "word_field_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
            sa.Column("field", sa.String(length=32), nullable=False),
            sa.Column("before_value", sa.Text(), nullable=True),
            sa.Column("after_value", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=8), nullable=False),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_word_field_revisions_word_id", "word_field_revisions", ["word_id"])
        op.create_index("ix_word_field_revisions_field", "word_field_revisions", ["field"])
        op.create_index("ix_word_field_revisions_source", "word_field_revisions", ["source"])
        op.create_index("ix_word_field_revisions_changed_at", "word_field_revisions", ["changed_at"])
        op.create_index(
            "ix_word_field_revisions_word_changed", "word_field_revisions", ["word_id", "changed_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "word_field_revisions" in tables:
        op.drop_table("word_field_revisions")

    if "words" in tables:
        columns = {c["name"] for c in inspector.get_columns("words")}
        if "ai_verified_at" in columns:
            # batch_alter_table because SQLite cannot drop a column in place on
            # a table carrying foreign keys.
            with op.batch_alter_table("words") as batch:
                batch.drop_column("ai_verified_at")
