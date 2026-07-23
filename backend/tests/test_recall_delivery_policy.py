from datetime import datetime, time

import pytest

from app.domain.entities import RecallSettings
from app.domain.services.recall_delivery import RecallDeliveryPolicy, is_within_quiet_hours
from app.domain.value_objects import Channel

ALL_CHANNELS = {Channel.PUSH, Channel.EMAIL, Channel.DESKTOP, Channel.IN_APP}
INTERRUPTIVE = {Channel.PUSH, Channel.EMAIL, Channel.DESKTOP}


def _settings(**overrides) -> RecallSettings:
    defaults = dict(
        user_id=1,
        enabled=True,
        push_enabled=True,
        email_enabled=True,
        desktop_enabled=True,
        in_app_enabled=True,
        quiet_hours_start=None,
        quiet_hours_end=None,
    )
    defaults.update(overrides)
    return RecallSettings(**defaults)


def _at(hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime(2026, 3, 1, hour, minute)


# ---------------------------------------------------------------------------
# The quiet-hours predicate, as a table.
#
# Window start is inclusive, window end is exclusive. A window whose end is
# earlier than its start spans midnight.
# ---------------------------------------------------------------------------

QUIET_HOURS_CASES = [
    # (case id, start, end, now, expected inside?)
    ("spans midnight | 23:30 is well inside", "22:00", "07:00", "23:30", True),
    ("spans midnight | 03:00 is inside after midnight", "22:00", "07:00", "03:00", True),
    ("spans midnight | 06:59 is the last minute inside", "22:00", "07:00", "06:59", True),
    ("spans midnight | 22:00 start boundary is inside", "22:00", "07:00", "22:00", True),
    ("spans midnight | 07:00 end boundary is outside", "22:00", "07:00", "07:00", False),
    ("spans midnight | 21:59 is just before the window", "22:00", "07:00", "21:59", False),
    ("spans midnight | 12:00 is far outside", "22:00", "07:00", "12:00", False),
    ("same day | 12:00 is inside", "09:00", "17:00", "12:00", True),
    ("same day | 09:00 start boundary is inside", "09:00", "17:00", "09:00", True),
    ("same day | 16:59 is the last minute inside", "09:00", "17:00", "16:59", True),
    ("same day | 17:00 end boundary is outside", "09:00", "17:00", "17:00", False),
    ("same day | 08:59 is just before the window", "09:00", "17:00", "08:59", False),
    ("same day | 23:00 is outside", "09:00", "17:00", "23:00", False),
    ("equal endpoints | zero-length window never applies at its own value", "22:00", "22:00", "22:00", False),
    ("equal endpoints | zero-length window never applies later", "22:00", "22:00", "23:00", False),
    ("equal endpoints | zero-length window never applies earlier", "22:00", "22:00", "03:00", False),
    ("unset | neither endpoint configured", None, None, "03:00", False),
    ("unset | only a start configured", "22:00", None, "23:00", False),
    ("unset | only an end configured", None, "07:00", "03:00", False),
]


def _parse(value: str | None) -> time | None:
    if value is None:
        return None
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


@pytest.mark.parametrize(
    "start,end,now,expected",
    [case[1:] for case in QUIET_HOURS_CASES],
    ids=[case[0] for case in QUIET_HOURS_CASES],
)
def test_quiet_hours_window(start, end, now, expected):
    assert is_within_quiet_hours(_parse(start), _parse(end), _parse(now)) is expected


def test_a_midnight_spanning_window_is_inside_at_both_of_its_edges_in_the_right_direction():
    """Both boundaries asserted together, so a change to one cannot silently
    invert the other."""
    start, end = time(22, 0), time(7, 0)

    assert is_within_quiet_hours(start, end, start) is True
    assert is_within_quiet_hours(start, end, end) is False


def test_a_same_day_window_is_inside_at_its_start_and_outside_at_its_end():
    start, end = time(9, 0), time(17, 0)

    assert is_within_quiet_hours(start, end, start) is True
    assert is_within_quiet_hours(start, end, end) is False


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


def test_the_master_switch_silences_every_channel():
    decided = RecallDeliveryPolicy.decide(_settings(enabled=False), _at("12:00"))

    assert decided == set()


def test_the_master_switch_wins_even_over_an_otherwise_deliverable_moment():
    settings = _settings(enabled=False, quiet_hours_start=None, quiet_hours_end=None)

    assert RecallDeliveryPolicy.decide(settings, _at("12:00")) == set()


def test_outside_quiet_hours_every_enabled_channel_is_used():
    decided = RecallDeliveryPolicy.decide(
        _settings(quiet_hours_start="22:00", quiet_hours_end="07:00"), _at("12:00")
    )

    assert decided == ALL_CHANNELS


def test_outside_quiet_hours_disabled_channels_stay_disabled():
    settings = _settings(
        email_enabled=False, desktop_enabled=False, quiet_hours_start="22:00", quiet_hours_end="07:00"
    )

    decided = RecallDeliveryPolicy.decide(settings, _at("12:00"))

    assert decided == {Channel.PUSH, Channel.IN_APP}


def test_inside_quiet_hours_only_the_in_app_channel_survives():
    settings = _settings(quiet_hours_start="22:00", quiet_hours_end="07:00")

    decided = RecallDeliveryPolicy.decide(settings, _at("23:30"))

    assert decided == {Channel.IN_APP}
    assert decided & INTERRUPTIVE == set()


def test_inside_quiet_hours_after_midnight_only_the_in_app_channel_survives():
    settings = _settings(quiet_hours_start="22:00", quiet_hours_end="07:00")

    assert RecallDeliveryPolicy.decide(settings, _at("03:00")) == {Channel.IN_APP}


def test_inside_quiet_hours_nothing_is_delivered_when_in_app_is_also_disabled():
    settings = _settings(in_app_enabled=False, quiet_hours_start="22:00", quiet_hours_end="07:00")

    assert RecallDeliveryPolicy.decide(settings, _at("23:30")) == set()


def test_unconfigured_quiet_hours_never_suppress_anything():
    assert RecallDeliveryPolicy.decide(_settings(), _at("03:00")) == ALL_CHANNELS


@pytest.mark.parametrize(
    "malformed",
    [
        "tonight",  # no separator at all
        "",  # empty string
        "25:00",  # separates and converts, but is not a real hour
        "12:61",  # ... nor a real minute
        "ab:cd",  # separates, but neither part is a number
        "-1:00",  # negative hour
    ],
    ids=repr,
)
def test_an_unparseable_quiet_hours_value_is_treated_as_unconfigured(malformed):
    """A malformed setting must not silently swallow every notification; the
    documented product rule is that a review is never lost.

    The cases deliberately span both rejection paths — the values that never
    split into two parts, and the values that split cleanly but are not a real
    time of day.
    """
    starts_bad = _settings(quiet_hours_start=malformed, quiet_hours_end="07:00")
    ends_bad = _settings(quiet_hours_start="22:00", quiet_hours_end=malformed)

    assert RecallDeliveryPolicy.decide(starts_bad, _at("03:00")) == ALL_CHANNELS
    assert RecallDeliveryPolicy.decide(ends_bad, _at("03:00")) == ALL_CHANNELS
