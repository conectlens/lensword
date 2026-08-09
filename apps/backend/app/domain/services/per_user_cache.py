"""A bounded, expiring, per-user cache of derived values (issue #342).

`ai_cache.py` established this shape for model responses, and its three rules
apply verbatim to anything else keyed by learner: entries are per user so a
key collision cannot hand one person's material to another, entries expire so
staleness is bounded, and the whole thing is bounded in size so a
long-running server does not grow a memory leak with a friendly name.

What differs is what is being avoided. `AIResponseCache` exists because a
local model takes seconds to answer; this exists because some reads are
expensive to *derive* — a full scan of a learner's groups and words to
produce a handful of counts — and are called repeatedly within one sitting.
There is no provider or model in the key, because the value is computed from
the database rather than sampled from a generator, which is also why the same
inputs always give the same answer and the TTL is about *change*, not variety.

Generic rather than tied to one value type, so a second caller does not have
to choose between copying this file and widening it to `object` and casting.

In-process and pure: a dict with bounds. Deliberately not Redis, for the same
reason `ai_cache.py` gives — a cache that needs its own service deployed is a
cache most self-hosted installs will not have.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, TypeVar

# Matches `ai_cache.DEFAULT_TTL`. A different number here would be a claim
# that derived counts go stale at a different rate than model answers, and
# nothing about this data supports that claim — what actually bounds it is
# invalidation on the mutations that change it, with the TTL as the backstop
# for the ones that are not worth wiring.
DEFAULT_TTL = timedelta(minutes=15)

# Matches `ai_cache.DEFAULT_MAX_ENTRIES`. One entry per active learner, so
# five hundred is a large number of simultaneous users for a single process
# and a small amount of memory.
DEFAULT_MAX_ENTRIES = 500

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: datetime


class PerUserTTLCache(Generic[T]):
    """Least-recently-used, time-bounded, one entry per user."""

    def __init__(
        self, ttl: timedelta = DEFAULT_TTL, max_entries: int = DEFAULT_MAX_ENTRIES
    ) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[int, _Entry[T]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, user_id: int, now: datetime) -> T | None:
        entry = self._entries.get(user_id)
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at <= now:
            # Dropped on read rather than swept on a timer, following
            # `AIResponseCache`: a background sweep is a second thing to get
            # wrong for no benefit, since an expired entry costs nothing until
            # someone asks for it.
            del self._entries[user_id]
            self.misses += 1
            return None
        self._entries.move_to_end(user_id)
        self.hits += 1
        return entry.value

    def put(self, user_id: int, value: T, now: datetime) -> None:
        self._entries[user_id] = _Entry(value=value, expires_at=now + self.ttl)
        self._entries.move_to_end(user_id)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def invalidate(self, user_id: int) -> None:
        """Drop one learner's entry.

        Called by the use cases that change what the value is derived from.
        Deliberately those use cases rather than this cache guessing from
        unrelated signals: the code performing a mutation is the only place
        that reliably knows a mutation happened.

        Also the hook account deletion needs — data removal that left a cache
        holding the same derived facts would not be removal.
        """
        self._entries.pop(user_id, None)

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0
