"""Bulk vocabulary write tools over MCP (issue #347 Bug 5).

`lensword_add_word` accepted one scalar `term`, so importing N words cost N
full tool invocations — the multiplier on top of the transport defects the
rest of that issue fixes. And a bulk capability already existed in the
backend but had never been exposed here: `PATCH /api/v1/words/bulk` (issue
#140) appeared in no contract, binding, or handler map entry, so an agent
retagging forty cards had to issue forty `update_word` calls to reach
something the product could already do in one.

`update_words` and the REST route now run the same `BulkEditWordsUseCase`
rather than two implementations that agree until one is edited, so the test
asserting they agree is the point rather than a formality.
"""
from __future__ import annotations

import uuid

from app.application.mcp.contracts import TOOL_CONTRACTS
from app.domain.services.mcp_policy import AccessClass
from app.domain.services.mcp_scopes import SCOPE_TOOLS, MCPScope
from app.infrastructure.models import MCPGrantModel

_WORKSPACE = "/approved"

_ACCESS = {tool.name: tool.access for tool in TOOL_CONTRACTS}


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _granted(client, headers, db_session, *tools: str) -> int:
    user_id = _user_id(client, headers)
    for tool in tools:
        db_session.add(
            MCPGrantModel(
                requester=f"user:{user_id}", server="lensword", tool=tool,
                access=_ACCESS[tool].value, workspace=_WORKSPACE, mode="always",
            )
        )
    db_session.flush()
    return user_id


def _invoke(client, headers, *, tool: str, payload: dict):
    payload = dict(payload)
    if _ACCESS[tool] != AccessClass.READ and "request_id" not in payload:
        payload["request_id"] = str(uuid.uuid4())
    return client.post(
        "/api/v1/mcp/invoke", headers=headers,
        json={"workspace": _WORKSPACE, "tool": tool, "payload": payload},
    )


def _group(client, headers, name: str = "G") -> dict:
    return client.post(
        "/api/v1/groups", json={"name": name, "target_language": "Spanish"}, headers=headers
    ).json()


def _word(client, headers, group_id: int, term: str) -> dict:
    return client.post(
        f"/api/v1/groups/{group_id}/words", headers=headers,
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
    ).json()


def _other_account(auth_headers):
    return auth_headers(username="mallory", email="mallory@example.com", password="supersecret2")


# --- add_words --------------------------------------------------------------


def test_a_whole_import_is_one_call(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_add_words")
    group = _group(client, headers)

    response = _invoke(
        client, headers, tool="lensword_add_words",
        payload={
            "group_id": group["id"], "target_language": "Spanish",
            "items": [
                {"term": "uno", "translations": ["one"]},
                {"term": "dos", "translations": ["two"]},
                {"term": "tres"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["term"] for item in body["added"]] == ["uno", "dos", "tres"]
    assert body["skipped"] == []
    # Really persisted, not just echoed back.
    listed = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()
    assert {item["term"] for item in listed} == {"uno", "dos", "tres"}


def test_every_word_in_an_import_lands_in_the_groups_language(client, auth_headers, db_session):
    """`target_language` is top-level precisely so a batch cannot disagree
    with itself about the language its own group is in."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_add_words")
    group = _group(client, headers)

    response = _invoke(
        client, headers, tool="lensword_add_words",
        payload={
            "group_id": group["id"], "target_language": "Spanish",
            "items": [{"term": "uno"}, {"term": "dos"}],
        },
    )

    assert {item["target_language"] for item in response.json()["added"]} == {"Spanish"}


def test_an_import_into_another_accounts_group_is_refused_wholesale(client, auth_headers, db_session):
    """Group ownership is a property of the call, not of each item, so it
    fails the batch rather than skipping every item in turn."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_add_words")
    victim = _other_account(auth_headers)
    theirs = _group(client, victim, "Theirs")

    response = _invoke(
        client, headers, tool="lensword_add_words",
        payload={
            "group_id": theirs["id"], "target_language": "Spanish",
            "items": [{"term": "uno"}],
        },
    )

    # 400 rather than 403: `PermissionDeniedError` is a `DomainError`, and on
    # this surface those reach main.py's fallback handler, which is the same
    # status the single-item `add_word` already answers for this case. What
    # matters for this test is that the batch is refused and writes nothing.
    assert response.status_code == 400, response.text
    assert client.get(f"/api/v1/groups/{theirs['id']}/words", headers=victim).json() == []


def test_an_import_batch_is_bounded(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_add_words")
    group = _group(client, headers)

    response = _invoke(
        client, headers, tool="lensword_add_words",
        payload={
            "group_id": group["id"], "target_language": "Spanish",
            "items": [{"term": f"w{index}"} for index in range(101)],
        },
    )

    assert response.status_code == 422, response.text


def test_an_import_item_missing_its_term_is_rejected_by_the_contract(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_add_words")
    group = _group(client, headers)

    response = _invoke(
        client, headers, tool="lensword_add_words",
        payload={
            "group_id": group["id"], "target_language": "Spanish",
            "items": [{"translations": ["one"]}],
        },
    )

    assert response.status_code == 422, response.text


# --- update_words -----------------------------------------------------------


def test_one_call_retags_many_cards(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_words")
    group = _group(client, headers)
    words = [_word(client, headers, group["id"], term) for term in ("uno", "dos", "tres")]

    response = _invoke(
        client, headers, tool="lensword_update_words",
        payload={
            "word_ids": [word["id"] for word in words],
            "cefr_level": "B1", "tags": ["numbers"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 3, "skipped": []}
    listed = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()
    assert {item["cefr_level"] for item in listed} == {"B1"}
    assert all(item["tags"] == ["numbers"] for item in listed)


def test_an_omitted_field_is_left_alone_not_cleared(client, auth_headers, db_session):
    """`None` means "leave alone", which is different from setting a field to
    empty — an edit that omitted a field must not wipe it."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_words")
    group = _group(client, headers)
    word = _word(client, headers, group["id"], "uno")
    _invoke(client, headers, tool="lensword_update_words",
            payload={"word_ids": [word["id"]], "category": "counting", "cefr_level": "A2"})

    _invoke(client, headers, tool="lensword_update_words",
            payload={"word_ids": [word["id"]], "cefr_level": "B1"})

    updated = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert updated["cefr_level"] == "B1"
    assert updated["category"] == "counting"


def test_another_accounts_word_is_skipped_and_reported(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_words")
    group = _group(client, headers)
    mine = _word(client, headers, group["id"], "mio")
    intruder = _other_account(auth_headers)
    theirs = _word(client, intruder, _group(client, intruder, "Theirs")["id"], "suyo")

    response = _invoke(
        client, headers, tool="lensword_update_words",
        payload={"word_ids": [mine["id"], theirs["id"]], "cefr_level": "C1"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 1, "skipped": [theirs["id"]]}
    untouched = client.get(f"/api/v1/words/{theirs['id']}", headers=intruder).json()
    assert untouched["cefr_level"] != "C1"


def test_the_mcp_tool_and_the_rest_route_agree(client, auth_headers, db_session):
    """Both now run `BulkEditWordsUseCase`. This is what stops the tool and
    the web UI's own bulk edit from drifting apart."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_words")
    group = _group(client, headers)
    left = _word(client, headers, group["id"], "uno")
    right = _word(client, headers, group["id"], "dos")

    over_mcp = _invoke(
        client, headers, tool="lensword_update_words",
        payload={"word_ids": [left["id"], 9_999_999], "part_of_speech": "noun"},
    ).json()
    over_rest = client.patch(
        "/api/v1/words/bulk", headers=headers,
        json={"word_ids": [right["id"], 9_999_999], "part_of_speech": "noun"},
    ).json()

    assert over_mcp == over_rest


def test_term_and_translations_cannot_be_set_in_bulk(client, auth_headers, db_session):
    """Excluded on purpose: they are what makes a card that card, and one
    value cannot be right for a hundred of them."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_words")
    group = _group(client, headers)
    word = _word(client, headers, group["id"], "uno")

    response = _invoke(
        client, headers, tool="lensword_update_words",
        payload={"word_ids": [word["id"]], "term": "overwritten"},
    )

    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/words/{word['id']}", headers=headers).json()["term"] == "uno"


# --- registration -----------------------------------------------------------


def test_the_bulk_vocabulary_tools_share_card_write_with_their_single_item_forms():
    assert set(SCOPE_TOOLS[MCPScope.CARD_WRITE]) >= {
        "lensword_add_word", "lensword_add_words",
        "lensword_update_word", "lensword_update_words",
    }
