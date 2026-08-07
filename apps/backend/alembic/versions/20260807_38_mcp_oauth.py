"""Remote MCP OAuth clients, authorization codes, and tokens (issue #196).

Revision ID: 20260807_38_mcp_oauth
Revises: 20260807_37

Originally chained onto 20260807_33_companion_tasks (the head at the time
this branch started); renumbered and re-pointed at 20260807_37 once
development had moved past it — 20260807_34 was already claimed by
intervention_plan_pairs by the time this was rebased, so this keeps
history linear instead of adding another merge-heads migration for a fork
that was never actually run against a shared database.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_38_mcp_oauth"
down_revision = "20260807_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "mcp_oauth_clients" not in tables:
        op.create_table(
            "mcp_oauth_clients",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("client_id", sa.String(64), nullable=False),
            sa.Column("client_name", sa.String(255), nullable=False),
            sa.Column("redirect_uris", sa.JSON(), nullable=False),
            sa.Column("client_secret_hash", sa.String(255), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_mcp_oauth_clients_client_id", "mcp_oauth_clients", ["client_id"], unique=True)

    if "mcp_oauth_authorization_codes" not in tables:
        op.create_table(
            "mcp_oauth_authorization_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("client_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("redirect_uri", sa.String(2048), nullable=False),
            sa.Column("code_challenge", sa.String(128), nullable=False),
            sa.Column("code_challenge_method", sa.String(16), nullable=False),
            sa.Column("scope", sa.String(512), nullable=False),
            sa.Column("workspace", sa.String(1024), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_mcp_oauth_authorization_codes_code_hash", "mcp_oauth_authorization_codes", ["code_hash"], unique=True)
        op.create_index("ix_mcp_oauth_authorization_codes_client_id", "mcp_oauth_authorization_codes", ["client_id"])
        op.create_index("ix_mcp_oauth_authorization_codes_user_id", "mcp_oauth_authorization_codes", ["user_id"])

    if "mcp_oauth_tokens" not in tables:
        op.create_table(
            "mcp_oauth_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("access_token_hash", sa.String(64), nullable=False),
            sa.Column("refresh_token_hash", sa.String(64), nullable=True),
            sa.Column("client_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("scope", sa.String(512), nullable=False),
            sa.Column("workspace", sa.String(1024), nullable=False),
            sa.Column("access_expires_at", sa.DateTime(), nullable=False),
            sa.Column("refresh_expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("rotated_from_id", sa.Integer(), sa.ForeignKey("mcp_oauth_tokens.id"), nullable=True),
            sa.Column("family_id", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_mcp_oauth_tokens_access_token_hash", "mcp_oauth_tokens", ["access_token_hash"], unique=True)
        op.create_index("ix_mcp_oauth_tokens_refresh_token_hash", "mcp_oauth_tokens", ["refresh_token_hash"], unique=True)
        op.create_index("ix_mcp_oauth_tokens_client_id", "mcp_oauth_tokens", ["client_id"])
        op.create_index("ix_mcp_oauth_tokens_user_id", "mcp_oauth_tokens", ["user_id"])
        op.create_index("ix_mcp_oauth_tokens_family_id", "mcp_oauth_tokens", ["family_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    # batch_alter_table not needed here (no column drops, only whole tables),
    # but dropping the self-referencing table first avoids an FK conflict.
    if "mcp_oauth_tokens" in tables:
        op.drop_table("mcp_oauth_tokens")
    if "mcp_oauth_authorization_codes" in tables:
        op.drop_table("mcp_oauth_authorization_codes")
    if "mcp_oauth_clients" in tables:
        op.drop_table("mcp_oauth_clients")
