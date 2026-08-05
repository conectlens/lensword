"""Bounding how often one caller may hit a class of endpoint (issue #163).

Four classes are budgeted independently — auth attempts, AI generations,
outbound fetches, uploads — because they cost the server wildly different
amounts and a single global number would be wrong for all four. A caller is
either an authenticated account (AI generation, imports) or an IP address
(login, where there is no account yet).

Sliding-window request log, one process, bounded. Deliberately not Redis, for
close to the reason AIResponseCache gives for the same choice (see
ai_cache.py) — but the trade-off is not identical. A stale cache entry costs a
slower response; a rate limit that only sees the traffic hitting one of
several processes behind a load balancer is a limit each instance enforces on
its own, so N instances let a caller through at up to N times the configured
budget. That is safe for the single-instance Compose deployment this project
ships by default, and a real gap for the "more than one instance" shape
docs/hosted-deployment.md already documents — see that file for the caveat
recorded alongside it.
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

# Keys tracked before the least-recently-active one is evicted. Bounded for
# the same reason AIResponseCache bounds its entries: an attacker rotating
# accounts or source IPs must not turn this into an unbounded memory leak.
DEFAULT_MAX_TRACKED_KEYS = 10_000


@dataclass(frozen=True)
class RateLimitRule:
    """How many requests one key may make within one rolling window."""

    limit: int
    window: timedelta


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    # Seconds until the oldest request in the window ages out and another
    # request would be allowed. 0 when allowed is True.
    retry_after_seconds: int


class InProcessRateLimiter:
    """Sliding-window counters keyed by (rule name, caller key)."""

    def __init__(self, max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS) -> None:
        self.max_tracked_keys = max_tracked_keys
        self._hits: "OrderedDict[tuple[str, str], deque[datetime]]" = OrderedDict()
        # Route handlers in this codebase are a mix of `def` and `async def`;
        # Starlette runs the former in a thread pool, so two requests can
        # genuinely call check() at the same instant from different threads
        # in one process. The dict/deque mutations below are not atomic
        # across that.
        self._lock = threading.Lock()

    def check(self, rule_name: str, key: str, rule: RateLimitRule, now: datetime) -> RateLimitResult:
        cache_key = (rule_name, key)
        with self._lock:
            hits = self._hits.get(cache_key, deque())
            cutoff = now - rule.window
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= rule.limit:
                # Not appended: a rejected request does not itself consume
                # budget, which is also what keeps this deque's length
                # bounded at `rule.limit` under sustained load.
                self._hits[cache_key] = hits
                self._hits.move_to_end(cache_key)
                retry_after = math.ceil((hits[0] + rule.window - now).total_seconds())
                return RateLimitResult(allowed=False, retry_after_seconds=max(retry_after, 1))

            hits.append(now)
            self._hits[cache_key] = hits
            self._hits.move_to_end(cache_key)
            while len(self._hits) > self.max_tracked_keys:
                self._hits.popitem(last=False)
            return RateLimitResult(allowed=True, retry_after_seconds=0)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
