"""Persist FSRS stability as first-class state (issue #173).

Revision ID: 20260805_20
Revises: 20260730_19

`FSRSScheduler` re-derived stability from the previous (already-clamped)
interval on every review, which pins every FSRS word's interval at 1.00 day
forever — see the ADR for the math. The fix stores stability directly, but
every word already reviewed under the broken scheduler has no stored value.

Backfill only the words a fix should actually touch: rows belonging to an
account whose effective scheduler is "fsrs" (an explicit `recall_settings`
row saying so, or no row at all — `RecallSettings.scheduler` defaults to
"fsrs" for those, per #20260730_14) that have been reviewed at least once
(`interval_days > 0`; a never-reviewed word has nothing to recompute).

The backfilled value inverts the scheduler's own interval formula
(`interval_days = stability * -log(0.9)`) rather than guessing from
`repetitions`: every affected row converged to the same interval_days
regardless of how many times it was reviewed, so repetitions carries no
signal the interval formula does not already destroy. This is a deliberate
"let it converge" remediation, not a reset to zero — see ADR 0004.
"""
from math import log

from alembic import op
import sqlalchemy as sa

revision = "20260805_20"
down_revision = "20260730_19"
branch_labels = None
depends_on = None

# Matches FSRSScheduler.target_retrievability. Duplicated rather than
# imported: migrations must keep working against whatever the app code
# becomes later, so they take no dependency on it.
_TARGET_RETRIEVABILITY = 0.9


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "words" not in tables:
        return

    if "stability" not in _columns("words"):
        op.add_column("words", sa.Column("stability", sa.Float(), nullable=True))

    if not {"words", "groups", "users"} <= tables:
        return

    scheduler_by_user: dict[int, str] = {}
    if "recall_settings" in tables:
        for user_id, scheduler in bind.execute(
            sa.text("SELECT user_id, scheduler FROM recall_settings")
        ):
            scheduler_by_user[user_id] = scheduler

    rows = bind.execute(
        sa.text(
            "SELECT w.id, w.interval_days, g.owner_id FROM words w "
            "JOIN groups g ON g.id = w.group_id "
            "WHERE w.interval_days > 0"
        )
    ).fetchall()

    factor = -log(_TARGET_RETRIEVABILITY)
    for word_id, interval_days, owner_id in rows:
        # No recall_settings row means the account is on the entity default,
        # "fsrs" — see RecallSettings.scheduler and #20260730_14's docstring.
        scheduler = scheduler_by_user.get(owner_id, "fsrs")
        if scheduler != "fsrs":
            continue
        stability = max(1.0, interval_days / factor)
        bind.execute(
            sa.text("UPDATE words SET stability = :stability WHERE id = :id"),
            {"stability": stability, "id": word_id},
        )


def downgrade() -> None:
    if "words" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "stability" in _columns("words"):
        with op.batch_alter_table("words") as batch:
            batch.drop_column("stability")
