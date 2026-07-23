"""Forced Recall delivery policy.

Answers one question: given a user's recall settings and the current time,
which channels may this notification take? A channel *set* rather than a
yes/no, because the interesting cases are partial — quiet hours silence some
routes without silencing the reminder.

The product rule this encodes: during quiet hours the interruptive channels
(push, email, desktop) are stripped, but the in-app channel survives. The
notification never interrupts, yet the review is never lost — it is simply
waiting in the app the next time it is opened.

A pure domain service: no repositories, no clock of its own, no framework.
Callers pass the time so the whole policy is testable at any instant.
"""
from __future__ import annotations

from datetime import datetime, time

from app.domain.entities import RecallSettings
from app.domain.value_objects import Channel

# Channels that reach out and demand attention. These are what quiet hours
# exist to stop.
INTERRUPTIVE_CHANNELS = frozenset({Channel.PUSH, Channel.EMAIL, Channel.DESKTOP})

_CHANNEL_FLAGS: tuple[tuple[Channel, str], ...] = (
    (Channel.PUSH, "push_enabled"),
    (Channel.EMAIL, "email_enabled"),
    (Channel.DESKTOP, "desktop_enabled"),
    (Channel.IN_APP, "in_app_enabled"),
)


def is_within_quiet_hours(start: time | None, end: time | None, now: time) -> bool:
    """Is `now` inside the quiet-hours window that runs from `start` to `end`?

    The window includes its start and excludes its end: at exactly `start` the
    user is already in quiet hours, and at exactly `end` they are no longer.

    A window whose end is earlier than its start spans midnight. "22:00 to
    07:00" means from ten at night until seven the *next* morning, so it is
    satisfied by times on either side of midnight rather than between the two
    values.

    Equal endpoints ("22:00" to "22:00") describe a zero-length window and
    never suppress anything. The alternative reading — a full twenty-four
    hours of silence — would let a single mistyped setting quietly disable
    every notification a user gets, which is the more damaging failure.

    An unset endpoint means quiet hours are not configured, so nothing is
    suppressed.
    """
    if start is None or end is None:
        return False
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class RecallDeliveryPolicy:
    """Stateless domain service (Pure Fabrication): channel-selection rules
    belong neither to RecallSettings, which is a preferences record, nor to
    any single notification adapter, which must not decide whether it is
    allowed to run."""

    @staticmethod
    def decide(settings: RecallSettings, now: datetime) -> set[Channel]:
        if not settings.enabled:
            return set()

        allowed = {channel for channel, flag in _CHANNEL_FLAGS if getattr(settings, flag)}

        start, end = _quiet_hours_bounds(settings)
        if is_within_quiet_hours(start, end, now.time()):
            allowed -= INTERRUPTIVE_CHANNELS
        return allowed


def _quiet_hours_bounds(settings: RecallSettings) -> tuple[time | None, time | None]:
    """Read the configured window, treating an unparseable endpoint as if the
    window were never configured.

    Refusing to deliver on account of a malformed setting would lose the
    review outright, which is precisely what the in-app survival rule above
    exists to prevent.
    """
    return _parse_time_of_day(settings.quiet_hours_start), _parse_time_of_day(settings.quiet_hours_end)


def _parse_time_of_day(value: str | None) -> time | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) < 2:
        return None
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except ValueError:
        return None
