"""Caching the per-user language profile (issue #342).

`GetLanguageProfileUseCase.execute` reads *every* group and *every* word the
learner owns to produce five integers and a tuple of language names, and it
is reachable through `lensword_get_language_profile`, which an agent may call
before or after each word lookup or exercise. Uncached, that is one
whole-collection scan per call, repeatedly, inside a single session.

The tests that matter here are the ones about being *wrong* rather than the
one about being fast: a cache that serves one learner's counts to another, or
that keeps reporting a word count the learner has already changed, is worse
than the scan it replaced.
"""
from __future__ import annotations

from datetime import timedelta

from app.application.use_cases.mcp_dev_workflow import (
    LANGUAGE_PROFILE_CACHE,
    GetLanguageProfileUseCase,
)
from app.application.use_cases.vocabulary import (
    AddWordUseCase,
    CreateGroupUseCase,
    DeleteGroupUseCase,
    DeleteWordUseCase,
    WordInput,
)
from app.domain.services.per_user_cache import PerUserTTLCache
from app.domain.value_objects import SupportedLanguage, utcnow
from app.infrastructure.repositories import SqlAlchemyGroupRepository, SqlAlchemyWordRepository


class _CountingGroupRepository:
    """Counts the scans the cache exists to avoid, delegating the rest."""

    def __init__(self, inner):
        self._inner = inner
        self.scans = 0

    def list_by_owner(self, owner_id):
        self.scans += 1
        return self._inner.list_by_owner(owner_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _repos(db_session):
    return SqlAlchemyGroupRepository(db_session), SqlAlchemyWordRepository(db_session)


def _seed(db_session, owner_id: int, terms: tuple[str, ...] = ("uno", "dos")):
    groups, words = _repos(db_session)
    group = CreateGroupUseCase(groups).execute(owner_id, "G", SupportedLanguage("Spanish"))
    for term in terms:
        AddWordUseCase(words, groups).execute(
            owner_id,
            group.id,
            WordInput(term=term, target_language=SupportedLanguage("Spanish"), translations=["x"]),
        )
    return group


def test_a_repeated_lookup_inside_the_ttl_does_not_rescan_the_collection(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    counting = _CountingGroupRepository(groups)
    use_case = GetLanguageProfileUseCase(counting, words)

    first = use_case.execute(owner_id)
    for _ in range(9):
        assert use_case.execute(owner_id) == first

    # Ten calls, one scan — the whole point.
    assert counting.scans == 1


def test_the_cached_profile_is_the_same_answer_the_scan_would_have_given(client, auth_headers, db_session):
    """A fast wrong answer is not an improvement."""
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id, terms=("uno", "dos", "tres"))
    groups, words = _repos(db_session)

    cached = GetLanguageProfileUseCase(groups, words).execute(owner_id)
    uncached = GetLanguageProfileUseCase(groups, words, cache=None).execute(owner_id)

    assert cached == uncached
    assert cached.total_word_count == 3


def test_adding_a_word_invalidates_the_profile(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    group = _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).total_word_count == 2

    AddWordUseCase(words, groups).execute(
        owner_id,
        group.id,
        WordInput(term="tres", target_language=SupportedLanguage("Spanish"), translations=["three"]),
    )

    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).total_word_count == 3


def test_deleting_a_word_invalidates_the_profile(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    group = _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    GetLanguageProfileUseCase(groups, words).execute(owner_id)
    doomed = words.list_by_group(group.id)[0]

    DeleteWordUseCase(words, groups).execute(owner_id, doomed.id)

    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).total_word_count == 1


def test_creating_a_group_invalidates_the_profile(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).group_count == 1

    CreateGroupUseCase(groups).execute(owner_id, "Second", SupportedLanguage("French"))

    profile = GetLanguageProfileUseCase(groups, words).execute(owner_id)
    assert profile.group_count == 2
    # A new language shows up too, not just the count.
    assert profile.target_languages == ("French", "Spanish")


def test_deleting_a_group_invalidates_the_profile(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    group = _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    GetLanguageProfileUseCase(groups, words).execute(owner_id)

    DeleteGroupUseCase(groups).execute(owner_id, group.id)

    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).group_count == 0


def test_one_learners_profile_is_never_served_to_another(client, auth_headers, db_session):
    """The rule `ai_cache.py` states for its own entries, which is the one
    whose failure nobody wants to explain."""
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id, terms=("uno", "dos", "tres"))

    other = auth_headers(username="mallory", email="mallory@example.com", password="supersecret2")
    other_id = _user_id(client, other)
    _seed(db_session, other_id, terms=("eins",))

    groups, words = _repos(db_session)
    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).total_word_count == 3
    assert GetLanguageProfileUseCase(groups, words).execute(other_id).total_word_count == 1
    # And again, now that both are cached.
    assert GetLanguageProfileUseCase(groups, words).execute(owner_id).total_word_count == 3


def test_an_expired_entry_falls_back_to_a_fresh_read(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    counting = _CountingGroupRepository(groups)
    # A TTL of zero expires an entry the instant it is written, which is the
    # cheapest way to assert the expiry path without sleeping through a
    # fifteen-minute default.
    expiring: PerUserTTLCache = PerUserTTLCache(ttl=timedelta(seconds=0))
    use_case = GetLanguageProfileUseCase(counting, words, cache=expiring)

    use_case.execute(owner_id)
    use_case.execute(owner_id)

    assert counting.scans == 2


def test_passing_no_cache_disables_caching_entirely(client, auth_headers, db_session):
    """The escape hatch for a caller that must not see a stale count."""
    headers = auth_headers()
    owner_id = _user_id(client, headers)
    _seed(db_session, owner_id)
    groups, words = _repos(db_session)
    counting = _CountingGroupRepository(groups)
    use_case = GetLanguageProfileUseCase(counting, words, cache=None)

    use_case.execute(owner_id)
    use_case.execute(owner_id)

    assert counting.scans == 2


def test_the_mcp_tool_reflects_a_word_added_after_its_first_call(client, auth_headers, db_session):
    """End to end through the surface the issue is actually about."""
    import uuid

    from app.infrastructure.models import MCPGrantModel

    headers = auth_headers()
    owner_id = _user_id(client, headers)
    for tool in ("lensword_get_language_profile", "lensword_add_word"):
        db_session.add(
            MCPGrantModel(
                requester=f"user:{owner_id}", server="lensword", tool=tool,
                access="read" if tool.endswith("profile") else "write",
                workspace="/approved", mode="always",
            )
        )
    db_session.flush()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()

    def profile():
        return client.post(
            "/api/v1/mcp/invoke", headers=headers,
            json={"workspace": "/approved", "tool": "lensword_get_language_profile", "payload": {}},
        ).json()

    assert profile()["total_word_count"] == 0

    added = client.post(
        "/api/v1/mcp/invoke", headers=headers,
        json={
            "workspace": "/approved", "tool": "lensword_add_word",
            "payload": {
                "group_id": group["id"], "term": "hola", "target_language": "Spanish",
                "request_id": str(uuid.uuid4()),
            },
        },
    )
    assert added.status_code == 200, added.text

    assert profile()["total_word_count"] == 1


def test_the_shared_cache_starts_empty_for_each_test():
    """Guards the conftest fixture that makes every other test here honest."""
    assert LANGUAGE_PROFILE_CACHE.get(1, utcnow()) is None
