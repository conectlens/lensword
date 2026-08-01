"""Persist idempotency keys for MCP writes.

Revision ID: 20260730_07
Revises: 20260730_06
"""
from alembic import op
import sqlalchemy as sa
revision = "20260730_07"
down_revision = "20260730_06"
branch_labels = None
depends_on = None
def upgrade() -> None:
    if "mcp_idempotency_keys" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table("mcp_idempotency_keys", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("requester", sa.String(255), nullable=False), sa.Column("request_id", sa.String(128), nullable=False), sa.Column("tool", sa.String(255), nullable=False), sa.Column("response", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("requester", "request_id", name="uq_mcp_requester_request_id"))
        op.create_index("ix_mcp_idempotency_keys_requester", "mcp_idempotency_keys", ["requester"])
def downgrade() -> None:
    if "mcp_idempotency_keys" in set(sa.inspect(op.get_bind()).get_table_names()): op.drop_table("mcp_idempotency_keys")
