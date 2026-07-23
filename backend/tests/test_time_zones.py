"""Tests for the time-zone value object and local-time resolution (issue #44).

The interesting cases are the two days a year when a local wall-clock time
does not map cleanly to one instant: a spring-forward date where the time
never occurs, and an autumn fall-back date where it occurs twice.

The rule these tests pin: exactly one delivery per reminder, always. A
reminder is never silently lost to a gap and never doubled by a fold.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.exceptions import ValidationError
from app.domain.value_objects import (
    DEFAULT_TIME_ZONE,
    normalize_time_zone,
    resolve_local_time,
    zone_for,
)


def _utc(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# --- Validation -----------------------------------------------------------


def test_default_is_utc():
    assert DEFAULT_TIME_ZONE == "UTC"


@pytest.mark.parametrize(
    "value", ["UTC", "Europe/Istanbul", "America/New_York", "Asia/Tokyo", "Australia/Sydney"]
)
def test_known_iana_identifiers_are_accepted(value: str):
    assert normalize_time_zone(value) == value


def test_surrounding_whitespace_is_tolerated():
    assert normalize_time_zone("  Europe/Istanbul  ") == "Europe/Istanbul"


@pytest.mark.parametrize("value", ["", "   ", "Mars/Olympus_Mons", "GMT+3", "not a zone"])
def test_unknown_identifiers_are_rejected(value: str):
    with pytest.raises(ValidationError):
        normalize_time_zone(value)


def test_none_falls_back_to_the_default():
    """Existing rows predate the column and must keep their old behavior."""
    assert normalize_time_zone(None) == DEFAULT_TIME_ZONE


def test_zone_for_degrades_to_utc_rather_than_raising():
    """A stored identifier can become unknown when the system tz database is
    updated beneath it. Losing the reminder outright would be worse than
    delivering it on the previous convention, matching the existing rule that
    a malformed setting must not lose a review."""
    assert zone_for("Mars/Olympus_Mons") is zone_for("UTC")


# --- Ordinary conversion --------------------------------------------------


def test_local_time_converts_to_the_expected_utc_instant():
    """The issue's stated acceptance criterion: 09:00 for a UTC+3 user fires
    at 06:00 UTC."""
    resolved = resolve_local_time(datetime(2026, 7, 15, 9, 0), zone_for("Europe/Istanbul"))

    assert resolved == _utc(2026, 7, 15, 6, 0)


def test_utc_users_are_unaffected():
    resolved = resolve_local_time(datetime(2026, 7, 15, 9, 0), zone_for("UTC"))

    assert resolved == _utc(2026, 7, 15, 9, 0)


def test_a_zone_behind_utc_converts_forward():
    # New York in July is UTC-4.
    resolved = resolve_local_time(datetime(2026, 7, 15, 9, 0), zone_for("America/New_York"))

    assert resolved == _utc(2026, 7, 15, 13, 0)


# --- Spring forward: the local time does not exist ------------------------


def test_spring_forward_gap_fires_at_the_first_valid_instant():
    """On 2026-03-08 US Eastern jumps 02:00 EST -> 03:00 EDT, so 02:30 never
    occurs. The reminder fires at 03:00 local rather than being lost."""
    zone = zone_for("America/New_York")

    resolved = resolve_local_time(datetime(2026, 3, 8, 2, 30), zone)

    assert resolved == _utc(2026, 3, 8, 7, 0)  # 03:00 EDT
    assert resolved.astimezone(zone).strftime("%H:%M") == "03:00"


def test_spring_forward_gap_is_not_skipped_entirely():
    zone = zone_for("America/New_York")

    resolved = resolve_local_time(datetime(2026, 3, 8, 2, 30), zone)

    assert resolved is not None
    assert resolved.date() == datetime(2026, 3, 8).date()


def test_spring_forward_in_a_southern_hemisphere_zone():
    """Istanbul has no DST since 2016; use a zone that still transitions to
    confirm the rule is not hard-coded to one region. Sydney moves
    02:00 -> 03:00 AEDT on 2026-10-04."""
    zone = zone_for("Australia/Sydney")

    resolved = resolve_local_time(datetime(2026, 10, 4, 2, 30), zone)

    assert resolved.astimezone(zone).strftime("%H:%M") == "03:00"


# --- Fall back: the local time occurs twice -------------------------------


def test_fall_back_fold_fires_on_the_first_occurrence_only():
    """On 2026-11-01 US Eastern repeats 01:00-02:00, so 01:30 occurs twice:
    once at 05:30 UTC (EDT) and again at 06:30 UTC (EST). The earlier one
    wins, so the reminder is not delivered twice."""
    zone = zone_for("America/New_York")

    resolved = resolve_local_time(datetime(2026, 11, 1, 1, 30), zone)

    assert resolved == _utc(2026, 11, 1, 5, 30)


def test_fall_back_resolution_is_the_earlier_of_the_two_instants():
    zone = zone_for("America/New_York")
    local = datetime(2026, 11, 1, 1, 30)

    resolved = resolve_local_time(local, zone)
    later = local.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)

    assert resolved < later
    assert later - resolved == timedelta(hours=1)


# --- The unifying property ------------------------------------------------


@pytest.mark.parametrize(
    "zone_name,local",
    [
        ("UTC", datetime(2026, 7, 15, 9, 0)),
        ("Europe/Istanbul", datetime(2026, 7, 15, 9, 0)),
        ("America/New_York", datetime(2026, 3, 8, 2, 30)),  # gap
        ("America/New_York", datetime(2026, 11, 1, 1, 30)),  # fold
        ("Australia/Sydney", datetime(2026, 4, 5, 2, 30)),  # southern fold
    ],
)
def test_resolution_is_the_earliest_instant_reaching_the_requested_time(zone_name, local):
    """One rule covers gaps, folds and ordinary times alike: the earliest
    instant whose local clock has reached the requested time.

    Verified directly — one second earlier, the local clock has not reached it.
    """
    zone = zone_for(zone_name)

    resolved = resolve_local_time(local, zone)

    assert resolved.astimezone(zone).replace(tzinfo=None) >= local
    just_before = (resolved - timedelta(seconds=1)).astimezone(zone).replace(tzinfo=None)
    assert just_before < local


@pytest.mark.parametrize(
    "zone_name,local,expected_local",
    [
        # A 30-minute gap, queried away from its edges and away from its
        # midpoint — the case a one-hour gap queried at :30 cannot expose.
        ("Australia/Lord_Howe", datetime(2026, 10, 4, 2, 1), "02:30"),
        ("Australia/Lord_Howe", datetime(2026, 10, 4, 2, 17, 13), "02:30"),
        ("America/New_York", datetime(2026, 3, 8, 2, 3, 7), "03:00"),
    ],
)
def test_a_gap_resolves_onto_the_transition_exactly(zone_name, local, expected_local):
    """Not merely within a second of it.

    Halving a bracket lands on microseconds, so an off-centre query inside a
    gap would otherwise come back carrying a sub-second remainder.
    """
    zone = zone_for(zone_name)

    resolved = resolve_local_time(local, zone)

    assert resolved.microsecond == 0
    assert resolved.astimezone(zone).strftime("%H:%M:%S") == f"{expected_local}:00"


def test_resolution_returns_an_aware_utc_datetime():
    resolved = resolve_local_time(datetime(2026, 7, 15, 9, 0), zone_for("Europe/Istanbul"))

    assert resolved.tzinfo is timezone.utc


def test_a_naive_local_time_is_required():
    """Passing an already-aware datetime is a caller error, not something to
    silently reinterpret."""
    with pytest.raises(ValueError):
        resolve_local_time(datetime(2026, 7, 15, 9, 0, tzinfo=ZoneInfo("UTC")), zone_for("UTC"))
