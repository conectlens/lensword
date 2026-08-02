"""Pin existing accounts to SM-2 before FSRS becomes the default.

Revision ID: 20260730_14
Revises: 20260730_13

`RecallSettings.scheduler` now defaults to "fsrs". That default applies to any
account with no settings row — which includes every existing account that never
opened the settings screen, not only new ones.

Switching someone's scheduling algorithm mid-deck without asking is exactly
what "existing users can opt in" was meant to prevent, so this writes an
explicit "sm2" row for every account that has none. After it runs, the default
only reaches accounts created afterwards.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_14"
down_revision = "20260730_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"users", "recall_settings"} <= tables:
        return

    columns = {c["name"] for c in sa.inspect(bind).get_columns("recall_settings")}
    # Every non-nullable column without a server default has to be named, since
    # this inserts rows rather than relying on the ORM's Python-side defaults.
    # Building the statement from the live column set keeps it working if the
    # table gains columns before this migration runs on a given database.
    defaults = {
        "enabled": True,
        "intensity": 3,
        "morning_checkin_enabled": True,
        "idle_time_enabled": True,
        "walking_mode_enabled": False,
        "walking_steps_threshold": 1000,
        "study_breaks_enabled": True,
        "study_blocks_before_break": 2,
        "night_winddown_enabled": False,
        "night_start_time": "22:00",
        "night_end_time": "23:00",
        "push_enabled": True,
        "email_enabled": False,
        "desktop_enabled": False,
        "in_app_enabled": True,
        "hide_notification_details": False,
        "notifications_paused": False,
        "scheduler": "sm2",
    }
    present = {name: value for name, value in defaults.items() if name in columns}
    names = ", ".join(["user_id", *present])
    placeholders = ", ".join(["u.id", *(f":{name}" for name in present)])

    op.execute(
        sa.text(
            f"INSERT INTO recall_settings ({names}) "
            f"SELECT {placeholders} FROM users u "
            "WHERE NOT EXISTS (SELECT 1 FROM recall_settings r WHERE r.user_id = u.id)"
        ).bindparams(**present)
    )


def downgrade() -> None:
    # Deliberately not reversed. The rows are indistinguishable from settings a
    # user saved themselves, and deleting them would discard real preferences
    # to undo a default change.
    pass
