"""Reusing recent AI responses (issue #139).

Most of these are about what the cache refuses to reuse. A cache that returns
something plausible but wrong is worse than no cache, because the wrong answer
only appears when a stale entry happens to exist — which is exactly the bug
nobody can reproduce.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.ai_cache import (
    DEFAULT_TTL,
    AIResponseCache,
    CacheKey,
)

NOW = datetime(2026, 8, 2, 9, 0)


def _key(user_id=1, provider="ollama", model="llama3.2", operation="enrich", payload=None):
    return CacheKey.build(user_id, provider, model, operation, payload or {"term": "gato"})


# --- Reuse ------------------------------------------------------------------


def test_an_identical_question_is_answered_from_the_cache():
    cache = AIResponseCache()
    cache.put(_key(), {"definition": "a cat"}, NOW)

    assert cache.get(_key(), NOW) == {"definition": "a cat"}


def test_a_payload_built_in_a_different_order_still_matches():
    """Otherwise the cache misses constantly and quietly does nothing."""
    first = CacheKey.build(1, "ollama", "llama3.2", "enrich", {"a": 1, "b": 2})
    second = CacheKey.build(1, "ollama", "llama3.2", "enrich", {"b": 2, "a": 1})

    assert first == second


def test_a_different_question_is_a_miss():
    cache = AIResponseCache()
    cache.put(_key(payload={"term": "gato"}), "cat", NOW)

    assert cache.get(_key(payload={"term": "perro"}), NOW) is None


# --- What must never be reused ---------------------------------------------


def test_another_model_never_answers_for_this_one():
    """A response from llama3.2 is not an answer from mistral, and serving one
    for the other makes the model setting look broken in a way nobody can
    reproduce."""
    cache = AIResponseCache()
    cache.put(_key(model="llama3.2"), "cat", NOW)

    assert cache.get(_key(model="mistral"), NOW) is None


def test_another_provider_never_answers_for_this_one():
    cache = AIResponseCache()
    cache.put(_key(provider="ollama"), "cat", NOW)

    assert cache.get(_key(provider="openai"), NOW) is None


def test_one_learners_response_is_never_served_to_another():
    """Prompts carry the learner's own vocabulary and context."""
    cache = AIResponseCache()
    cache.put(_key(user_id=1), "cat", NOW)

    assert cache.get(_key(user_id=2), NOW) is None


def test_a_different_operation_is_a_miss():
    cache = AIResponseCache()
    cache.put(_key(operation="enrich"), "cat", NOW)

    assert cache.get(_key(operation="mnemonic"), NOW) is None


def test_nothing_is_cached_when_there_is_nothing_to_cache():
    """An empty result is not an answer worth repeating, and caching it would
    keep serving that emptiness for the whole TTL."""
    cache = AIResponseCache()
    for empty in (None, "", [], {}):
        cache.put(_key(payload={"v": str(empty)}), empty, NOW)

    assert len(cache) == 0


# --- Expiry -----------------------------------------------------------------


def test_an_entry_expires():
    """A model's answer is not a fact — it is one sample from a generator, and
    holding it for hours would make the product feel frozen to anyone trying to
    get a better suggestion by asking again."""
    cache = AIResponseCache()
    cache.put(_key(), "cat", NOW)

    assert cache.get(_key(), NOW + DEFAULT_TTL + timedelta(seconds=1)) is None


def test_an_entry_is_still_good_just_before_it_expires():
    cache = AIResponseCache()
    cache.put(_key(), "cat", NOW)

    assert cache.get(_key(), NOW + DEFAULT_TTL - timedelta(seconds=1)) == "cat"


def test_an_expired_entry_is_dropped_rather_than_left_in_place():
    cache = AIResponseCache()
    cache.put(_key(), "cat", NOW)
    cache.get(_key(), NOW + DEFAULT_TTL + timedelta(minutes=1))

    assert len(cache) == 0


# --- Bounds -----------------------------------------------------------------


def test_the_cache_does_not_grow_without_limit():
    """An unbounded cache in a long-running server is a memory leak with a
    friendly name."""
    cache = AIResponseCache(max_entries=10)
    for index in range(50):
        cache.put(_key(payload={"term": str(index)}), index, NOW)

    assert len(cache) == 10


def test_the_least_recently_used_entry_is_the_one_dropped():
    cache = AIResponseCache(max_entries=2)
    cache.put(_key(payload={"term": "a"}), "A", NOW)
    cache.put(_key(payload={"term": "b"}), "B", NOW)

    # Touch "a" so "b" becomes least recent.
    cache.get(_key(payload={"term": "a"}), NOW)
    cache.put(_key(payload={"term": "c"}), "C", NOW)

    assert cache.get(_key(payload={"term": "a"}), NOW) == "A"
    assert cache.get(_key(payload={"term": "b"}), NOW) is None


# --- Invalidation -----------------------------------------------------------


def test_a_learners_entries_can_be_dropped_without_touching_anyone_elses():
    """Data removal that left a cache holding the same content would not be
    removal."""
    cache = AIResponseCache()
    cache.put(_key(user_id=1), "mine", NOW)
    cache.put(_key(user_id=2), "theirs", NOW)

    removed = cache.invalidate_user(1)

    assert removed == 1
    assert cache.get(_key(user_id=2), NOW) == "theirs"


def test_changing_model_drops_that_models_entries():
    """An administrator who switches model and immediately tests it should see
    the new model's output, not the old one's for another quarter hour."""
    cache = AIResponseCache()
    cache.put(_key(model="llama3.2"), "old", NOW)
    cache.put(_key(model="mistral"), "new", NOW)

    cache.invalidate_model("ollama", "llama3.2")

    assert cache.get(_key(model="llama3.2"), NOW) is None
    assert cache.get(_key(model="mistral"), NOW) == "new"


def test_invalidating_something_absent_is_harmless():
    assert AIResponseCache().invalidate_user(999) == 0


# --- Counters ---------------------------------------------------------------


def test_hits_and_misses_are_counted():
    cache = AIResponseCache()
    cache.get(_key(), NOW)
    cache.put(_key(), "cat", NOW)
    cache.get(_key(), NOW)

    assert (cache.hits, cache.misses) == (1, 1)
