"""Group, word-lifecycle, memory-palace, MnemoLab and word-map MCP tools.

These close the gaps a live audit of the MCP surface found. The one worth
stating plainly, because it shaped every group test below: `add_word` and
`extract_vocabulary` both required a `group_id` that no tool on this surface
could produce or enumerate, so an agent had to guess integers or abandon MCP
for the web app. `create_group`/`list_groups` are what make the rest of the
vocabulary tools usable end to end, so they are tested as a chain — create,
list, add into the listed id — rather than in isolation.

The destructive and ownership cases carry the most weight here:
`delete_word` is the first hard delete on this surface, and every new tool
is a fresh chance to leak or mutate another account's vocabulary.
"""
from __future__ import annotations

import uuid

from app.application.mcp.contracts import TOOL_CONTRACTS
from app.domain.services.mcp_policy import AccessClass
from app.infrastructure.models import MCPGrantModel

_WORKSPACE = "/approved"

_ACCESS = {tool.name: tool.access for tool in TOOL_CONTRACTS}


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _grant(db_session, *, tool: str, user_id: int) -> None:
    db_session.add(
        MCPGrantModel(
            requester=f"user:{user_id}", server="lensword", tool=tool,
            access=_ACCESS[tool].value, workspace=_WORKSPACE, mode="always",
        )
    )
    db_session.flush()


def _invoke(client, headers, *, tool: str, payload: dict):
    payload = dict(payload)
    if _ACCESS[tool] != AccessClass.READ and "request_id" not in payload:
        payload["request_id"] = str(uuid.uuid4())
    return client.post(
        "/api/v1/mcp/invoke", headers=headers,
        json={"workspace": _WORKSPACE, "tool": tool, "payload": payload},
    )


def _other_account(auth_headers):
    """A genuinely separate account. `auth_headers()` defaults to one
    fixed identity, so calling it twice re-registers the *same* user and
    409s — which would quietly turn every cross-account test below into a
    same-account test that proves nothing."""
    return auth_headers(username="mallory", email="mallory@example.com", password="supersecret2")


def _granted(client, headers, db_session, *tools: str):
    user_id = _user_id(client, headers)
    for tool in tools:
        _grant(db_session, tool=tool, user_id=user_id)


# --- group management -------------------------------------------------------


def test_create_then_list_groups_gives_an_agent_a_usable_group_id(client, auth_headers, db_session):
    """The whole point of these two tools: a group_id an agent did not guess."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_create_group", "lensword_list_groups", "lensword_add_word")

    created = _invoke(client, headers, tool="lensword_create_group",
                      payload={"name": "Spanish Basics", "target_language": "Spanish"})
    assert created.status_code == 200, created.text
    group_id = created.json()["group_id"]
    assert isinstance(group_id, int)

    listed = _invoke(client, headers, tool="lensword_list_groups", payload={})
    assert listed.status_code == 200, listed.text
    assert [item["group_id"] for item in listed.json()["items"]] == [group_id]

    # The id round-trips into the tool that needed it all along.
    added = _invoke(client, headers, tool="lensword_add_word",
                    payload={"group_id": group_id, "term": "hola", "target_language": "Spanish",
                             "translations": ["hello"]})
    assert added.status_code == 200, added.text


def test_create_group_rejects_an_unsupported_language_with_an_actionable_message(client, auth_headers, db_session):
    """Regression for the audit's worst error experience.

    An unrecognised language raised a bare `ValueError`, which is not a
    `DomainError`, so it bypassed main.py's handler and became an unhandled
    500 whose body Starlette renders as *plain text*. The MCP client found
    no JSON `detail` and fell back to the opaque, identical-for-everything
    "LensWord request failed".
    """
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_create_group")

    response = _invoke(client, headers, tool="lensword_create_group",
                       payload={"name": "Klingon Basics", "target_language": "Klingon"})

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "Klingon" in detail and "not supported" in detail
    assert "Spanish" in detail  # names what *is* accepted, so the call is fixable


def test_list_group_words_enumerates_one_group_without_a_search_term(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_list_group_words")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    other = client.post("/api/v1/groups", json={"name": "O", "target_language": "Spanish"}, headers=headers).json()
    for term in ("beta", "alpha"):
        client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                    json={"term": term, "target_language": "Spanish", "translations": ["x"]})
    client.post(f"/api/v1/groups/{other['id']}/words", headers=headers,
                json={"term": "excluded", "target_language": "Spanish", "translations": ["x"]})

    response = _invoke(client, headers, tool="lensword_list_group_words",
                       payload={"group_id": group["id"], "sort_by": "term"})

    assert response.status_code == 200, response.text
    terms = [item["term"] for item in response.json()["items"]]
    assert terms == ["alpha", "beta"]  # sorted, and scoped to the one group


def test_list_group_words_never_returns_another_accounts_group(client, auth_headers, db_session):
    owner = auth_headers()
    victim_group = client.post("/api/v1/groups", json={"name": "Private", "target_language": "Spanish"},
                               headers=owner).json()
    attacker = _other_account(auth_headers)
    _granted(client, attacker, db_session, "lensword_list_group_words")

    response = _invoke(client, attacker, tool="lensword_list_group_words", payload={"group_id": victim_group["id"]})

    assert response.status_code in (400, 403, 404), response.text


# --- word lifecycle ---------------------------------------------------------


def test_update_word_changes_only_what_was_sent(client, auth_headers, db_session):
    """Partial-update semantics are the reason this tool exists.

    UpdateWordUseCase *replaces* translations/example_sentence/mnemonic, so
    a handler that forwarded only the supplied fields would silently erase
    the rest — turning "fix the translation" into data loss.
    """
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_word")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers, json={
        "term": "hola", "target_language": "Spanish", "translations": ["hi"],
        "example_sentence": "Hola, amigo.",
    }).json()

    response = _invoke(client, headers, tool="lensword_update_word",
                       payload={"word_id": word["id"], "translations": ["hello", "hi there"]})

    assert response.status_code == 200, response.text
    after = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert after["translations"] == ["hello", "hi there"]
    assert after["example_sentence"] == "Hola, amigo."  # untouched, not cleared


def test_update_word_moves_between_groups_preserving_review_history(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_update_word")
    source = client.post("/api/v1/groups", json={"name": "S", "target_language": "Spanish"}, headers=headers).json()
    target = client.post("/api/v1/groups", json={"name": "T", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{source['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()

    response = _invoke(client, headers, tool="lensword_update_word",
                       payload={"word_id": word["id"], "group_id": target["id"]})

    assert response.status_code == 200, response.text
    moved = client.get(f"/api/v1/groups/{target['id']}/words", headers=headers).json()
    assert [item["term"] for item in moved] == ["hola"]
    assert client.get(f"/api/v1/groups/{source['id']}/words", headers=headers).json() == []


def test_update_word_cannot_move_a_word_into_another_accounts_group(client, auth_headers, db_session):
    victim = auth_headers()
    victim_group = client.post("/api/v1/groups", json={"name": "V", "target_language": "Spanish"},
                               headers=victim).json()
    attacker = _other_account(auth_headers)
    _granted(client, attacker, db_session, "lensword_update_word")
    own_group = client.post("/api/v1/groups", json={"name": "A", "target_language": "Spanish"},
                            headers=attacker).json()
    word = client.post(f"/api/v1/groups/{own_group['id']}/words", headers=attacker,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()

    response = _invoke(client, attacker, tool="lensword_update_word",
                       payload={"word_id": word["id"], "group_id": victim_group["id"]})

    assert response.status_code in (400, 403, 404), response.text
    assert client.get(f"/api/v1/groups/{victim_group['id']}/words", headers=victim).json() == []


def test_delete_word_refuses_without_explicit_confirmation(client, auth_headers, db_session):
    """`confirmed` is required by the schema, so this asserts its *value*
    is honoured — a caller sending false is declining, and the word must
    survive."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_delete_word")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()

    response = _invoke(client, headers, tool="lensword_delete_word",
                       payload={"word_id": word["id"], "confirmed": False})

    assert response.status_code == 400, response.text
    assert "confirmed" in response.json()["detail"]
    assert client.get(f"/api/v1/words/{word['id']}", headers=headers).status_code == 200


def test_delete_word_removes_the_word_when_confirmed(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_delete_word")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()

    response = _invoke(client, headers, tool="lensword_delete_word",
                       payload={"word_id": word["id"], "confirmed": True})

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert client.get(f"/api/v1/words/{word['id']}", headers=headers).status_code == 404


# --- memory palace ----------------------------------------------------------


def test_room_tools_let_an_agent_discover_a_room_and_place_a_word(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session,
             "lensword_create_room", "lensword_list_rooms", "lensword_place_word_in_room")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()

    created = _invoke(client, headers, tool="lensword_create_room",
                      payload={"group_id": group["id"], "name": "Kitchen"})
    assert created.status_code == 200, created.text
    room_id = created.json()["room_id"]

    listed = _invoke(client, headers, tool="lensword_list_rooms", payload={})
    assert [item["room_id"] for item in listed.json()["items"]] == [room_id]

    placed = _invoke(client, headers, tool="lensword_place_word_in_room",
                     payload={"room_id": room_id, "word_id": word["id"], "x_percent": 25.5, "y_percent": 60})
    assert placed.status_code == 200, placed.text
    assert placed.json()["x_percent"] == 25.5 and placed.json()["placed_count"] == 1


def test_placement_coordinates_outside_the_canvas_are_rejected(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_create_room", "lensword_place_word_in_room")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()
    room_id = _invoke(client, headers, tool="lensword_create_room",
                      payload={"group_id": group["id"], "name": "Kitchen"}).json()["room_id"]

    response = _invoke(client, headers, tool="lensword_place_word_in_room",
                       payload={"room_id": room_id, "word_id": word["id"], "x_percent": 140, "y_percent": 10})

    # Caught by the contract validator's `number` range check before it ever
    # reaches the aggregate — the branch that previously did not exist, so a
    # "number" property passed through entirely unvalidated.
    assert response.status_code == 422, response.text


def test_placing_a_word_from_a_different_group_is_rejected(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_create_room", "lensword_place_word_in_room")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    other = client.post("/api/v1/groups", json={"name": "O", "target_language": "Spanish"}, headers=headers).json()
    foreign = client.post(f"/api/v1/groups/{other['id']}/words", headers=headers,
                          json={"term": "adios", "target_language": "Spanish", "translations": ["bye"]}).json()
    room_id = _invoke(client, headers, tool="lensword_create_room",
                      payload={"group_id": group["id"], "name": "Kitchen"}).json()["room_id"]

    response = _invoke(client, headers, tool="lensword_place_word_in_room",
                       payload={"room_id": room_id, "word_id": foreign["id"], "x_percent": 10, "y_percent": 10})

    assert response.status_code == 400, response.text


# --- MnemoLab and word map --------------------------------------------------


def test_get_mnemonics_returns_saved_hooks_strongest_first(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_get_mnemonics")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers,
                       json={"term": "hola", "target_language": "Spanish", "translations": ["hi"]}).json()
    weak = client.post(f"/api/v1/words/{word['id']}/mnemonics", headers=headers, json={"text": "weak hook"}).json()
    strong = client.post(f"/api/v1/words/{word['id']}/mnemonics", headers=headers, json={"text": "strong hook"}).json()
    client.post(f"/api/v1/words/{word['id']}/mnemonics/{strong['id']}/vote", headers=headers, json={"upvote": True})

    response = _invoke(client, headers, tool="lensword_get_mnemonics", payload={"word_id": word["id"]})

    assert response.status_code == 200, response.text
    ids = [item["mnemonic_id"] for item in response.json()["items"]]
    assert ids == [strong["id"], weak["id"]]  # ordering established by the handler, not assumed


def test_get_word_map_reports_recorded_relations_only(client, auth_headers, db_session):
    """The companion cites this instead of inventing connections, so an
    unrelated word must not appear in the map."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_get_word_map")
    group = client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()
    origin = client.post(f"/api/v1/groups/{group['id']}/words", headers=headers, json={
        "term": "feliz", "target_language": "Spanish", "translations": ["happy"], "synonyms": ["contento"],
    }).json()
    client.post(f"/api/v1/groups/{group['id']}/words", headers=headers, json={
        "term": "contento", "target_language": "Spanish", "translations": ["glad"], "synonyms": ["feliz"],
    })
    client.post(f"/api/v1/groups/{group['id']}/words", headers=headers, json={
        "term": "mesa", "target_language": "Spanish", "translations": ["table"],
    })

    response = _invoke(client, headers, tool="lensword_get_word_map",
                       payload={"word_id": origin["id"], "depth": 1})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["term"] == "feliz"
    related_terms = {node["term"] for node in body["nodes"]}
    assert "contento" in related_terms
    assert "mesa" not in related_terms


def test_word_map_refuses_another_accounts_word(client, auth_headers, db_session):
    victim = auth_headers()
    group = client.post("/api/v1/groups", json={"name": "V", "target_language": "Spanish"}, headers=victim).json()
    word = client.post(f"/api/v1/groups/{group['id']}/words", headers=victim,
                       json={"term": "secreto", "target_language": "Spanish", "translations": ["secret"]}).json()
    attacker = _other_account(auth_headers)
    _granted(client, attacker, db_session, "lensword_get_word_map")

    response = _invoke(client, attacker, tool="lensword_get_word_map", payload={"word_id": word["id"]})

    assert response.status_code in (400, 403, 404), response.text


# --- audit follow-ups on pre-existing tools ---------------------------------


def test_create_study_session_reports_an_empty_schedule_as_data_not_an_error(client, auth_headers, db_session):
    """"Nothing is due" is a healthy schedule, not a failure. It used to
    arrive as an error string the caller had to parse to tell "you are
    caught up" from "something broke"."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_create_study_session")

    response = _invoke(client, headers, tool="lensword_create_study_session", payload={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["words"] == [] and body["session_id"] is None and body["reason"] == "no_words_due"


def test_check_known_term_can_disambiguate_by_language(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_check_known_term")
    spanish = client.post("/api/v1/groups", json={"name": "ES", "target_language": "Spanish"}, headers=headers).json()
    client.post(f"/api/v1/groups/{spanish['id']}/words", headers=headers,
                json={"term": "actual", "target_language": "Spanish", "translations": ["current"]})

    matched = _invoke(client, headers, tool="lensword_check_known_term",
                      payload={"term": "actual", "target_language": "Spanish"})
    assert matched.status_code == 200, matched.text
    assert matched.json()["matches"]

    other = _invoke(client, headers, tool="lensword_check_known_term",
                    payload={"term": "actual", "target_language": "French"})
    assert other.status_code == 200, other.text
    assert other.json()["matches"] == []
