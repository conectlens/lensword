"""Review workload and retention analytics (issue #141, split from #78).

The forecast is the part worth testing hardest. Spaced repetition front-loads:
a learner who adds fifty words today faces fifty reviews tomorrow, then a
trough, then a lump. An average would hide exactly the spike that makes people
quit, so the shape has to survive.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.services.review_analytics import (
    AT_RISK_RETRIEVABILITY,
    FORECAST_DAYS,
    ScheduledWord,
    build_analytics,
)

NOW = datetime(2026, 8, 2, 9, 0)


def _word(days_from_now: float | None = 1, retrievability: float | None = 0.9) -> ScheduledWord:
    return ScheduledWord(
        due_at=None if days_from_now is None else NOW + timedelta(days=days_from_now),
        retrievability=retrievability,
    )


# --- The forecast ----------------------------------------------------------


def test_the_forecast_keeps_its_shape_rather_than_averaging():
    """Fifty words due one day and none the next is the whole point. Averaging
    would report "3 a day" and hide the day that matters."""
    words = [_word(days_from_now=1) for _ in range(50)] + [_word(days_from_now=5)]

    analytics = build_analytics(words, NOW)

    tomorrow = analytics.forecast[1]
    assert tomorrow.due_count == 50
    assert analytics.forecast[2].due_count == 0


def test_the_busiest_day_is_reported():
    words = [_word(days_from_now=3) for _ in range(9)] + [_word(days_from_now=1)]

    busiest = build_analytics(words, NOW).busiest_day

    assert busiest is not None
    assert busiest.due_count == 9


def test_quiet_days_appear_in_the_forecast():
    """Omitting them compresses the axis and makes a spike look like a gentle
    slope."""
    analytics = build_analytics([_word(days_from_now=7)], NOW)

    assert len(analytics.forecast) == FORECAST_DAYS
    assert analytics.forecast[0].due_count == 0


def test_overdue_words_count_as_today_not_as_a_past_date():
    """A forecast row for last Tuesday is not a forecast."""
    analytics = build_analytics([_word(days_from_now=-5)], NOW)

    assert analytics.forecast[0].on == NOW.date()
    assert analytics.forecast[0].due_count == 1


def test_words_beyond_the_horizon_are_not_forecast():
    """Every figure that far out depends on reviews that have not happened."""
    analytics = build_analytics([_word(days_from_now=FORECAST_DAYS + 5)], NOW)

    assert sum(day.due_count for day in analytics.forecast) == 0


def test_a_word_with_no_due_date_is_not_forecast():
    analytics = build_analytics([_word(days_from_now=None)], NOW)

    assert sum(day.due_count for day in analytics.forecast) == 0


# --- Retention -------------------------------------------------------------


def test_average_retention_is_the_mean_of_reviewed_words():
    words = [_word(retrievability=0.8), _word(retrievability=1.0)]

    assert build_analytics(words, NOW).average_retention == pytest.approx(0.9)


def test_unreviewed_words_are_excluded_rather_than_counted_as_zero():
    """Counting them as zero would make a deck of new words look like
    catastrophic memory loss."""
    words = [_word(retrievability=0.9), _word(retrievability=None)]

    assert build_analytics(words, NOW).average_retention == pytest.approx(0.9)


def test_a_deck_with_nothing_reviewed_reports_no_retention_rather_than_zero():
    analytics = build_analytics([_word(retrievability=None)], NOW)

    assert analytics.average_retention is None


def test_words_below_the_risk_threshold_are_counted():
    """FSRS schedules toward 0.9, so a word materially under that is overdue in
    substance even if its due date has not arrived."""
    words = [
        _word(retrievability=AT_RISK_RETRIEVABILITY - 0.1),
        _word(retrievability=AT_RISK_RETRIEVABILITY + 0.1),
    ]

    assert build_analytics(words, NOW).at_risk_count == 1


# --- Now -------------------------------------------------------------------


def test_due_now_counts_only_what_has_actually_come_due():
    words = [_word(days_from_now=-1), _word(days_from_now=1)]

    assert build_analytics(words, NOW).due_now == 1


def test_an_empty_deck_reports_nothing_rather_than_failing():
    analytics = build_analytics([], NOW)

    assert analytics.total_words == 0
    assert analytics.average_retention is None
    assert analytics.busiest_day is None


# --- The default change, and who it must not touch -------------------------


def test_new_accounts_get_fsrs():
    from app.domain.entities import RecallSettings

    assert RecallSettings(user_id=1).scheduler == "fsrs"


def test_the_migration_pins_existing_accounts_to_sm2(tmp_path):
    """The claim this change rests on. Changing the dataclass default would
    otherwise switch every existing account that never opened the settings
    screen — which is most of them — onto a different algorithm mid-deck."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import create_engine, text

    backend_dir = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'existing.db'}"
    env = os.environ | {"DATABASE_URL": url}

    def alembic(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=backend_dir, env=env, check=True, capture_output=True, text=True,
        )

    # A database as it stood before this migration: an account, and no settings
    # row — the exact shape that the default silently applies to.
    alembic("upgrade", "20260730_13")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, role, created_at,"
                " is_active, streak_days, longest_streak_days, total_words_learned,"
                " total_study_seconds, time_zone)"
                " VALUES (1, 'alex', 'a@b.c', 'x', 'user', '2026-01-01 00:00:00', 1, 0, 0, 0, 0, 'UTC')"
            )
        )
        assert conn.execute(text("SELECT COUNT(*) FROM recall_settings")).scalar() == 0

    alembic("upgrade", "head")

    with engine.begin() as conn:
        scheduler = conn.execute(
            text("SELECT scheduler FROM recall_settings WHERE user_id = 1")
        ).scalar()
    assert scheduler == "sm2"


def test_the_migration_does_not_overwrite_a_saved_preference(tmp_path):
    """Someone who already chose FSRS must keep it."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import create_engine, text

    backend_dir = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'chosen.db'}"
    env = os.environ | {"DATABASE_URL": url}

    def alembic(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=backend_dir, env=env, check=True, capture_output=True, text=True,
        )

    alembic("upgrade", "20260730_13")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, role, created_at,"
                " is_active, streak_days, longest_streak_days, total_words_learned,"
                " total_study_seconds, time_zone)"
                " VALUES (1, 'alex', 'a@b.c', 'x', 'user', '2026-01-01 00:00:00', 1, 0, 0, 0, 0, 'UTC')"
            )
        )
        # Every non-nullable column has to be named: this bypasses the ORM,
        # so none of the Python-side defaults apply.
        conn.execute(
            text(
                "INSERT INTO recall_settings (user_id, enabled, intensity,"
                " morning_checkin_enabled, idle_time_enabled, walking_mode_enabled,"
                " walking_steps_threshold, study_breaks_enabled, study_blocks_before_break,"
                " night_winddown_enabled, night_start_time, night_end_time, push_enabled,"
                " email_enabled, desktop_enabled, in_app_enabled, hide_notification_details,"
                " notifications_paused, scheduler)"
                " VALUES (1, 1, 3, 1, 1, 0, 1000, 1, 2, 0, '22:00', '23:00', 1, 0, 0, 1, 0, 0, 'fsrs')"
            )
        )

    alembic("upgrade", "head")

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT scheduler FROM recall_settings WHERE user_id = 1")).all()
    assert [r[0] for r in rows] == ["fsrs"]
