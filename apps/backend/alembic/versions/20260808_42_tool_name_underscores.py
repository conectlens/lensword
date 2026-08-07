"""Repoint existing MCP grants at the underscore tool names.

Tool identifiers changed from `lensword.add_word` to `lensword_add_word`
because a dot is not a legal character in a tool name for the Anthropic API
(`^[a-zA-Z0-9_-]{1,64}$`), which silently excluded every LensWord tool from
Claude with "26 tools with unsupported names". MCP's own spec is looser here
(it lists `admin.tools.list` as valid), so the constraint comes from the
client, not the protocol — but a tool the client refuses to load is not a
tool, so the stricter rule wins.

`mcp_grants.tool` stores those identifiers verbatim, and MCPPolicyGate
matches on them exactly. Without this migration every already-authorized
connection keeps rows naming tools that no longer exist: nothing errors, the
grant lookup simply never matches, and every call fails `no_grant` until the
user notices and re-runs consent. Rewriting the rows preserves exactly the
permissions the user already approved — it grants nothing new.

`mcp_audit_events.tool` is deliberately NOT rewritten. Those rows are
hash-chained (`redact_and_chain` in domain/services/mcp_policy.py) and each
event's hash covers the previous one, so editing any historical row would
invalidate the chain from that point on and make a tamper-evident log report
tampering — which is precisely what it is designed to do. The audit trail is
a record of what happened under the names in force at the time, and it stays
that way.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260808_42_tool_underscores"
down_revision = "20260807_41_notif_deep_link"
branch_labels = None
depends_on = None

# Anchored to the `lensword.` prefix rather than replacing every dot, so a
# tool name that legitimately contains one elsewhere is untouched.
_RENAME = sa.text(
    "UPDATE mcp_grants SET tool = 'lensword_' || SUBSTR(tool, 10) WHERE tool LIKE 'lensword.%'"
)
_REVERT = sa.text(
    "UPDATE mcp_grants SET tool = 'lensword.' || SUBSTR(tool, 10) WHERE tool LIKE 'lensword\\_%' ESCAPE '\\'"
)


def upgrade() -> None:
    # `||` and SUBSTR are standard SQL and behave identically on both
    # dialects this project runs on (SQLite locally, Postgres deployed), so
    # no per-dialect branch is needed. SUBSTR is 1-indexed: 10 is the
    # character right after "lensword.".
    op.get_bind().execute(_RENAME)


def downgrade() -> None:
    op.get_bind().execute(_REVERT)
