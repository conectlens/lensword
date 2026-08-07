"""Regression test for issue #192's privacy bug.

`lensword://me/active-words` and `lensword://me/due` — the two MCP
resources the companion reads through `lensword_search_words` and
`lensword_get_due_reviews` — used to hand back `word_to_response`'s full
`WordResponse`, mnemonic included. A companion's own words are one thing;
a learner's private memory aid for a word is exactly what TODO 0 names as
something to redact by default. This file locks that down at the MCP
boundary while confirming the REST API, which is a different audience the
same data belongs to unredacted, is untouched.
"""
from app.infrastructure.models import MCPGrantModel

# mcp.py's `is_valid_workspace` now always uses `pathlib.PurePosixPath`
# regardless of host OS (issue #196 fixed the platform-dependent
# `pathlib.PurePath` bug this used to work around with `Path.cwd().anchor`
# — every workspace string in this codebase is written POSIX-style), so a
# plain "/approved" is absolute on every platform the tests run on.
_WORKSPACE = "/approved"


# Caller identity is derived server-side from the authenticated bearer token
# (issue #196 TODO 2) — a grant must be bound to the real "user:{id}"
# requester string, not an arbitrary caller-chosen label.
def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _grant(db_session, *, tool: str, user_id: int, workspace: str = _WORKSPACE):
    item = MCPGrantModel(requester=f"user:{user_id}", server="lensword", tool=tool, access="read", workspace=workspace, mode="always")
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, *, tool: str, payload: dict, workspace: str = _WORKSPACE):
    return client.post(
        "/api/v1/mcp/invoke",
        headers=headers,
        json={"workspace": workspace, "tool": tool, "payload": payload},
    )


def _word_with_mnemonic(client, headers) -> dict:
    group = client.post(
        "/api/v1/groups", json={"name": "Companion Group", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={
            "term": "gato",
            "target_language": "Spanish",
            "translations": ["cat"],
            "mnemonic": "Sounds like 'got a' cat stuck in a hat — deeply personal, do not share.",
        },
        headers=headers,
    ).json()
    assert word["mnemonic"], "fixture word must actually carry a mnemonic to be a meaningful regression test"
    return word


def test_mcp_search_words_never_exposes_a_mnemonic(client, auth_headers, db_session):
    headers = auth_headers()
    _word_with_mnemonic(client, headers)
    _grant(db_session, tool="lensword_search_words", user_id=_user_id(client, headers))

    response = _invoke(client, headers, tool="lensword_search_words", payload={"query": "gato"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert "mnemonic" not in items[0]
    # The rest of the word is still there — this is a redaction, not a
    # broken response.
    assert items[0]["term"] == "gato"


def test_mcp_get_due_reviews_never_exposes_a_mnemonic(client, auth_headers, db_session):
    headers = auth_headers()
    word = _word_with_mnemonic(client, headers)
    # Force the word due now so it appears in the due-reviews queue without
    # waiting on the scheduler.
    from datetime import datetime, timezone

    from app.infrastructure.models import WordModel

    model = db_session.get(WordModel, word["id"])
    model.due_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.flush()

    _grant(db_session, tool="lensword_get_due_reviews", user_id=_user_id(client, headers))

    response = _invoke(client, headers, tool="lensword_get_due_reviews", payload={})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert "mnemonic" not in items[0]
    assert items[0]["term"] == "gato"


def test_mcp_due_and_active_words_paginate_with_a_real_cursor(client, auth_headers, db_session):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "Many Words", "target_language": "Spanish"}, headers=headers
    ).json()
    for index in range(3):
        client.post(
            f"/api/v1/groups/{group['id']}/words",
            json={"term": f"palabra{index}", "target_language": "Spanish", "translations": ["word"]},
            headers=headers,
        )
    _grant(db_session, tool="lensword_search_words", user_id=_user_id(client, headers))

    first = _invoke(client, headers, tool="lensword_search_words", payload={"query": "palabra", "limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second = _invoke(
        client,
        headers,
        tool="lensword_search_words",
        payload={"query": "palabra", "limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None
    # No overlap between the two pages.
    first_terms = {item["term"] for item in first_body["items"]}
    second_terms = {item["term"] for item in second_body["items"]}
    assert not first_terms & second_terms


def test_rest_word_listing_still_includes_the_mnemonic(client, auth_headers):
    """The REST API is a different audience for the same data — the
    learner's own client, not a companion — and TODO 0's redaction must not
    leak into it."""
    headers = auth_headers()
    word = _word_with_mnemonic(client, headers)

    listed = client.get(f"/api/v1/groups/{word['group_id']}/words", headers=headers)

    assert listed.status_code == 200
    match = next(item for item in listed.json() if item["id"] == word["id"])
    assert match["mnemonic"] == word["mnemonic"]
