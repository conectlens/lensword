"""Issue #188 TODO 3: learner-aware developer-workflow MCP tools.

Covers the issue's own verify clause — an agent cannot mark a word mastered
or create a diagnosis through these tools, and `record_context_occurrence`
records a low-trust fact rather than mutating mastery-affecting state — plus
the standing privacy rule that no new tool response leaks `mnemonic`.
"""
from __future__ import annotations

import dataclasses
import os

from app.domain.value_objects import utcnow
from app.infrastructure.models import MCPGrantModel
from app.infrastructure.repositories import SqlAlchemyWordRepository

# `mcp.py`'s `_valid_workspace` uses `pathlib.PurePath`, which resolves to
# the *current OS's* path flavor rather than always POSIX — "/approved" is
# not absolute under `PureWindowsPath`. This is exactly why the run
# instructions for this issue exclude `test_mcp_security.py` on this
# machine; it is a pre-existing, out-of-scope platform quirk, not something
# issue #188 owns. Using an OS-appropriate absolute workspace here keeps
# these tests meaningful on both platforms without touching that code.
_WORKSPACE = "C:\\approved" if os.name == "nt" else "/approved"


def _group_and_word(client, headers, term, target_language="Spanish", mnemonic=None, **fields):
    group = client.post(
        "/api/v1/groups", json={"name": f"g-{term}", "target_language": target_language}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": target_language, "translations": ["x"], "mnemonic": mnemonic, **fields},
        headers=headers,
    ).json()
    return group, word


def _mark_mastered(db_session, word_id: int) -> None:
    """Directly set a word's ReviewState to mastered, bypassing the review
    flow — the fastest deterministic way to test "known" without running
    dozens of scheduler-driven review cycles."""
    repo = SqlAlchemyWordRepository(db_session)
    word = repo.get_by_id(word_id)
    word.review_state = dataclasses.replace(word.review_state, strength=90, repetitions=3, last_reviewed_at=utcnow())
    repo.update(word)


def _mark_started(db_session, word_id: int, *, strength: int = 20) -> None:
    repo = SqlAlchemyWordRepository(db_session)
    word = repo.get_by_id(word_id)
    word.review_state = dataclasses.replace(word.review_state, strength=strength, repetitions=1, last_reviewed_at=utcnow())
    repo.update(word)


def _grant(db_session, *, tool: str, workspace: str = _WORKSPACE, requester: str = "fixture-client", mode: str = "always") -> None:
    db_session.add(
        MCPGrantModel(requester=requester, server="lensword", tool=tool, access=_access_for(tool), workspace=workspace, mode=mode)
    )
    db_session.flush()


def _access_for(tool: str) -> str:
    return "write" if tool == "lensword.record_context_occurrence" else "read"


def _invoke(client, headers, *, tool: str, payload: dict, workspace: str = _WORKSPACE, requester: str = "fixture-client"):
    return client.post(
        "/api/v1/mcp/invoke",
        headers=headers,
        json={"requester": requester, "workspace": workspace, "tool": tool, "payload": payload},
    )


def _no_private_fields(value) -> bool:
    """Recursively assert no dict anywhere in the response carries a
    mnemonic or other private-field name (issue #188 TODO 0 / #192's leak,
    which these five new tools must not repeat)."""
    forbidden = {"mnemonic", "attempted_answer", "self_reported_confidence"}
    if isinstance(value, dict):
        return forbidden.isdisjoint(value) and all(_no_private_fields(v) for v in value.values())
    if isinstance(value, list):
        return all(_no_private_fields(v) for v in value)
    return True


# --- get_language_profile ---------------------------------------------------


def test_get_language_profile_reports_bounded_aggregate_counts_only(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.get_language_profile")
    _g, w1 = _group_and_word(client, headers, "correr", mnemonic="run like the wind, TOP SECRET")
    _g2, w2 = _group_and_word(client, headers, "saltar", target_language="Spanish")
    _mark_mastered(db_session, w1["id"])
    _mark_started(db_session, w2["id"])

    response = _invoke(client, headers, tool="lensword.get_language_profile", payload={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["known_word_count"] == 1
    assert body["active_word_count"] == 2
    assert body["total_word_count"] == 2
    assert body["target_languages"] == ["Spanish"]
    assert _no_private_fields(body)


def test_get_language_profile_is_scoped_to_the_caller_account(client, auth_headers, db_session):
    owner_headers = auth_headers()
    _group_and_word(client, owner_headers, "correr")
    intruder_headers = auth_headers(username="mallory", email="mallory@example.com")
    _grant(db_session, tool="lensword.get_language_profile", requester="intruder-client")

    response = _invoke(client, intruder_headers, tool="lensword.get_language_profile", payload={}, requester="intruder-client")
    assert response.status_code == 200
    assert response.json()["total_word_count"] == 0


# --- check_known_term --------------------------------------------------------


def test_check_known_term_distinguishes_known_active_and_unknown(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.check_known_term")
    _g, mastered_word = _group_and_word(client, headers, "asyncio", mnemonic="private note")
    _mark_mastered(db_session, mastered_word["id"])
    _group_and_word(client, headers, "fixture")

    known = _invoke(client, headers, tool="lensword.check_known_term", payload={"term": "asyncio"}).json()
    assert known["known"] is True and known["active"] is True
    assert known["matches"][0]["word_id"] == mastered_word["id"]
    assert _no_private_fields(known)

    unstarted = _invoke(client, headers, tool="lensword.check_known_term", payload={"term": "fixture"}).json()
    assert unstarted["known"] is False and unstarted["active"] is False

    unknown = _invoke(client, headers, tool="lensword.check_known_term", payload={"term": "nonexistent-term"}).json()
    assert unknown["known"] is False and unknown["matches"] == []


# --- explain_for_user ---------------------------------------------------------


def test_explain_for_user_is_deterministic_with_no_diagnosis_yet(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.explain_for_user")
    _g, word = _group_and_word(client, headers, "hogar", mnemonic="secret mnemonic")

    first = _invoke(client, headers, tool="lensword.explain_for_user", payload={"word_id": word["id"]}).json()
    second = _invoke(client, headers, tool="lensword.explain_for_user", payload={"word_id": word["id"]}).json()
    assert first == second
    assert first["has_diagnosis"] is False
    assert "hogar" in first["explanation"]
    assert _no_private_fields(first)


def test_explain_for_user_404s_for_a_word_owned_by_another_account(client, auth_headers, db_session):
    owner_headers = auth_headers()
    _g, word = _group_and_word(client, owner_headers, "hogar")
    intruder_headers = auth_headers(username="mallory2", email="mallory2@example.com")
    _grant(db_session, tool="lensword.explain_for_user", requester="intruder-client-2")

    response = _invoke(
        client, intruder_headers, tool="lensword.explain_for_user", payload={"word_id": word["id"]},
        requester="intruder-client-2",
    )
    assert response.status_code in (400, 404)


# --- suggest_stretch_vocabulary ------------------------------------------------


def test_suggest_stretch_vocabulary_excludes_mastered_words_and_is_ordered(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.suggest_stretch_vocabulary")
    _g, mastered = _group_and_word(client, headers, "mastered-word")
    _mark_mastered(db_session, mastered["id"])
    _g2, started = _group_and_word(client, headers, "started-word")
    _mark_started(db_session, started["id"])
    _g3, fresh = _group_and_word(client, headers, "fresh-word")

    response = _invoke(client, headers, tool="lensword.suggest_stretch_vocabulary", payload={"limit": 10})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    word_ids = [item["word_id"] for item in items]
    assert mastered["id"] not in word_ids
    assert fresh["id"] in word_ids and started["id"] in word_ids
    # Never-started words (repetitions == 0) sort before started-but-not-yet-mastered ones.
    assert word_ids.index(fresh["id"]) < word_ids.index(started["id"])
    assert _no_private_fields(items)


def test_suggest_stretch_vocabulary_never_writes_anything(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.suggest_stretch_vocabulary")
    _g, word = _group_and_word(client, headers, "unchanged-word")

    _invoke(client, headers, tool="lensword.suggest_stretch_vocabulary", payload={})

    unchanged = SqlAlchemyWordRepository(db_session).get_by_id(word["id"])
    assert unchanged.review_state.repetitions == 0
    assert unchanged.revision == 1


# --- record_context_occurrence -------------------------------------------------


def test_record_context_occurrence_requires_explicit_confirmation(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.record_context_occurrence")
    _g, word = _group_and_word(client, headers, "asyncio")

    response = _invoke(
        client, headers, tool="lensword.record_context_occurrence",
        payload={"word_id": word["id"], "context_kind": "commit_message", "outcome": "correct", "confirmed": False},
    )
    assert response.status_code == 400

    unchanged = SqlAlchemyWordRepository(db_session).get_by_id(word["id"])
    assert unchanged.review_state.repetitions == 0


def test_record_context_occurrence_writes_a_low_trust_observation_not_a_mastery_mutation(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.record_context_occurrence")
    _g, word = _group_and_word(client, headers, "asyncio")
    before = SqlAlchemyWordRepository(db_session).get_by_id(word["id"])

    response = _invoke(
        client, headers, tool="lensword.record_context_occurrence",
        payload={"word_id": word["id"], "context_kind": "commit_message", "outcome": "correct", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["context_source"] == "context:commit_message"
    assert body["outcome"] == "correct"
    assert _no_private_fields(body)

    # The word's mastery-affecting state (ReviewState) is untouched: this
    # tool records evidence, it does not schedule or grade anything.
    after = SqlAlchemyWordRepository(db_session).get_by_id(word["id"])
    assert after.review_state == before.review_state
    assert after.revision == before.revision


def test_record_context_occurrence_rejects_a_context_kind_outside_the_closed_set(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, tool="lensword.record_context_occurrence")
    _g, word = _group_and_word(client, headers, "asyncio")

    response = _invoke(
        client, headers, tool="lensword.record_context_occurrence",
        payload={"word_id": word["id"], "context_kind": "carrier-pigeon", "outcome": "correct", "confirmed": True},
    )
    assert response.status_code == 422


def test_record_context_occurrence_cannot_be_aimed_at_another_accounts_word(client, auth_headers, db_session):
    owner_headers = auth_headers()
    _g, word = _group_and_word(client, owner_headers, "asyncio")
    intruder_headers = auth_headers(username="mallory3", email="mallory3@example.com")
    _grant(db_session, tool="lensword.record_context_occurrence", requester="intruder-client-3")

    response = _invoke(
        client, intruder_headers, tool="lensword.record_context_occurrence",
        payload={"word_id": word["id"], "context_kind": "commit_message", "outcome": "correct", "confirmed": True},
        requester="intruder-client-3",
    )
    assert response.status_code in (400, 404)
