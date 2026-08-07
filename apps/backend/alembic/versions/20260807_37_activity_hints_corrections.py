"""Add companion activity hints and correction feedback telemetry (#194).

Revision ID: 20260807_37
Revises: 20260807_36

Two independent additions for issue #194:

- `companion_activities.hints_used` — how many times `request_hint` has
  been used on an activity (TODO 1), bounded by
  `MAX_HINTS_PER_ACTIVITY` at the domain layer.
- `conversation_correction_feedback` — a new append-only table recording a
  learner's accept/reject/edit outcome on a tutor correction (TODO 3), the
  same "a correction is a new record, not an edit" posture
  `observation_corrections` already uses.

Kept short (see 20260807_36's own note): Postgres's default
`alembic_version.version_num` is VARCHAR(32).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_37"
down_revision = "20260807_36"
branch_labels = None
depends_on = None

_COLUMN = "hints_used"
_TABLE = "conversation_correction_feedback"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "companion_activities" in tables:
        existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companion_activities")}
        if _COLUMN not in existing:
            op.add_column(
                "companion_activities",
                sa.Column(_COLUMN, sa.Integer(), nullable=False, server_default="0"),
            )

    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "message_id",
                sa.Integer(),
                sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("correction_index", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(16), nullable=False),
            sa.Column("edited_text", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_conversation_correction_feedback_message",
            _TABLE,
            ["message_id", "correction_index"],
        )
        op.create_index(
            f"ix_{_TABLE}_message_id",
            _TABLE,
            ["message_id"],
        )
        op.create_index(
            f"ix_{_TABLE}_user_id",
            _TABLE,
            ["user_id"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if _TABLE in tables:
        op.drop_table(_TABLE)

    if "companion_activities" in tables:
        present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companion_activities")}
        with op.batch_alter_table("companion_activities") as batch:
            if _COLUMN in present:
                batch.drop_column(_COLUMN)
