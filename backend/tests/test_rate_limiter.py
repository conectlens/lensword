"""Bounding how often one caller may hit a class of endpoint (issue #163).

These are about the limiter itself: a sliding window of `limit` requests per
`window`, isolated per (rule, key), bounded in how many keys it remembers.
The endpoint-level behaviour — which class each route belongs to, 429 with
Retry-After, per-account isolation over HTTP — is covered separately in
test_rate_limiting_api.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.rate_limiter import InProcessRateLimiter, RateLimitRule

NOW = datetime(2026, 8, 2, 9, 0, 0)


def _rule(limit=3, seconds=60):
    return RateLimitRule(limit=limit, window=timedelta(seconds=seconds))


# --- Within budget ------------------------------------------------------------


def test_requests_under_the_limit_are_all_allowed():
    limiter = InProcessRateLimiter()
    rule = _rule(limit=3)

    for i in range(3):
        result = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=i))
        assert result.allowed is True
        assert result.retry_after_seconds == 0


# --- Over budget ---------------------------------------------------------------


def test_the_request_that_exceeds_the_limit_is_rejected():
    limiter = InProcessRateLimiter()
    rule = _rule(limit=3)

    for i in range(3):
        limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=i))
    result = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=3))

    assert result.allowed is False
    assert result.retry_after_seconds > 0


def test_retry_after_matches_when_the_oldest_hit_ages_out():
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1, seconds=60)

    limiter.check("bucket", "caller", rule, NOW)
    result = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=10))

    # The one hit that counts against the caller expires 60s after NOW; 10s
    # have passed, so 50 remain.
    assert result.retry_after_seconds == 50


def test_a_rejected_request_does_not_itself_consume_budget():
    """Otherwise a caller hammering the endpoint after being limited would
    keep pushing their own reset time further into the future forever."""
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1, seconds=60)

    limiter.check("bucket", "caller", rule, NOW)
    for i in range(1, 10):
        limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=i))
    result = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=60))

    assert result.allowed is True


# --- The window slides ----------------------------------------------------------


def test_a_blocked_caller_is_allowed_again_once_the_window_passes():
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1, seconds=60)

    limiter.check("bucket", "caller", rule, NOW)
    blocked = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=30))
    allowed = limiter.check("bucket", "caller", rule, NOW + timedelta(seconds=61))

    assert blocked.allowed is False
    assert allowed.allowed is True


# --- Isolation -------------------------------------------------------------------


def test_two_callers_in_the_same_bucket_do_not_share_a_budget():
    """A global limiter would let one user deny service to everyone."""
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1)

    limiter.check("bucket", "alex", rule, NOW)
    result = limiter.check("bucket", "sam", rule, NOW)

    assert result.allowed is True


def test_two_buckets_for_the_same_caller_do_not_share_a_budget():
    """Exhausting the AI budget must not also block that account's imports."""
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1)

    limiter.check("ai_generation", "user:1", rule, NOW)
    result = limiter.check("import_url", "user:1", rule, NOW)

    assert result.allowed is True


# --- Memory bound ----------------------------------------------------------------


def test_the_oldest_key_is_evicted_once_the_tracked_bound_is_exceeded():
    limiter = InProcessRateLimiter(max_tracked_keys=2)
    rule = _rule(limit=10)

    limiter.check("bucket", "first", rule, NOW)
    limiter.check("bucket", "second", rule, NOW)
    limiter.check("bucket", "third", rule, NOW)

    # "first" was evicted to make room, so it starts a fresh window rather
    # than resuming its old one — observable as a full-budget allow that
    # would otherwise still be counting from the earlier check() above.
    assert len(limiter._hits) == 2
    assert ("bucket", "first") not in limiter._hits


def test_reset_clears_every_tracked_caller():
    limiter = InProcessRateLimiter()
    rule = _rule(limit=1)
    limiter.check("bucket", "caller", rule, NOW)

    limiter.reset()

    assert limiter.check("bucket", "caller", rule, NOW).allowed is True
