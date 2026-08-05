"""Conversation tutor sessions and messages (issue #135).

Revision ID: 20260730_18
Revises: 20260730_17

The transport scenario role-play (#136) will also use, which is why the session
carries an optional `scenario` from the start rather than gaining a column
later.

Corrections are stored on the message rather than in their own table: they are
only ever read with the turn they belong to, so a separate table would be a
join serving no query anyone makes.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_18"
down_revision = "20260730_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "conversation_sessions" not in tables:
        op.create_table(
            "conversation_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=True),
            sa.Column("target_language", sa.String(length=32), nullable=False),
            sa.Column("difficulty", sa.String(length=16), nullable=False, server_default="steady"),
            sa.Column("scenario", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_conversation_sessions_user_id", "conversation_sessions", ["user_id"])
        op.create_index(
            "ix_conversation_sessions_created_at", "conversation_sessions", ["created_at"]
        )

    if "conversation_messages" not in tables:
        op.create_table(
            "conversation_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("conversation_sessions.id"),
                nullable=False,
            ),
            sa.Column("speaker", sa.String(length=8), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("corrections", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_conversation_messages_session_id", "conversation_messages", ["session_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    # Messages first: they reference the sessions.
    if "conversation_messages" in tables:
        op.drop_table("conversation_messages")
    if "conversation_sessions" in tables:
        op.drop_table("conversation_sessions")
