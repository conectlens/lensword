"""Persist MCP grants and tamper-evident audit events.

Revision ID: 20260730_06
Revises: 20260730_05
"""
from alembic import op
import sqlalchemy as sa
revision = "20260730_06"
down_revision = "20260730_05"
branch_labels = None
depends_on = None
def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "mcp_grants" not in tables:
        op.create_table("mcp_grants", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("requester", sa.String(255), nullable=False), sa.Column("server", sa.String(255), nullable=False), sa.Column("tool", sa.String(255), nullable=False), sa.Column("access", sa.String(32), nullable=False), sa.Column("workspace", sa.String(1024), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("expires_at", sa.DateTime()), sa.Column("revoked_at", sa.DateTime()), sa.Column("consumed_at", sa.DateTime()))
        op.create_index("ix_mcp_grants_requester", "mcp_grants", ["requester"])
    if "mcp_audit_events" not in tables:
        op.create_table("mcp_audit_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("requester", sa.String(255), nullable=False), sa.Column("tool", sa.String(255), nullable=False), sa.Column("decision", sa.String(64), nullable=False), sa.Column("event", sa.JSON(), nullable=False), sa.Column("previous_hash", sa.String(64), nullable=False), sa.Column("event_hash", sa.String(64), nullable=False, unique=True), sa.Column("created_at", sa.DateTime(), nullable=False))
        op.create_index("ix_mcp_audit_events_requester", "mcp_audit_events", ["requester"])
def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "mcp_audit_events" in tables: op.drop_table("mcp_audit_events")
    if "mcp_grants" in tables: op.drop_table("mcp_grants")
