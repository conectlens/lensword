"""Add user_ai_credentials (Bring-Your-Own-Key AI credentials).

Revision ID: 20260808_01_user_ai_credentials
Revises: 20260807_41_notif_deep_link

One row per (user_id, provider) — a user's own encrypted Gemini/OpenAI/
Vertex AI credential, used for their own AI requests since the cloud
deployment has no billing/credits system to pay for everyone's usage. See
app/infrastructure/models.py's UserAICredentialModel docstring for why the
payload is reversibly encrypted rather than hashed like every other secret
column in this database.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260808_01_user_ai_credentials"
down_revision = "20260807_41_notif_deep_link"
branch_labels = None
depends_on = None

_TABLE = "user_ai_credentials"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "provider", name="uq_user_ai_credential_provider"),
        )
        op.create_index("ix_user_ai_credentials_user_id", _TABLE, ["user_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE in tables:
        op.drop_table(_TABLE)
