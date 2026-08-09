"""Batched siblings of the single-item MCP write tools (issue #348).

Three tools accepted exactly one target per call, so an operation over N
items cost N invocations. The batched forms added beside them are tested
here on the three properties that make batching worth doing and the two that
make it safe:

* **One aggregate write.** `place_words_in_room` is the case that motivated
  the issue: placing N words into one room used to load, mutate and save the
  *same* Room N times, which is N chances to lose an update as well as N
  round trips. The first test counts repository calls rather than asserting
  on timing, because the number of loads and saves is the actual claim.
* **Partial success.** One bad item must not discard the good ones. This
  matters more than for a batched read: a placement batch that rolled back
  wholesale would throw away work the caller cannot see it lost.
* **Explicit skips.** A batch that quietly did less than it was asked is
  worse than one that says so, so every declined item is reported with a
  reason.
* **Ownership, per item.** Batching changes how often ownership is checked,
  never whether. No batch may place, drill or record against another
  account's word.
* **Idempotency.** `record_context_occurrences` shares one `request_id`
  across items but writes observations that dedupe individually, so a retry
  of a partially-applied batch must converge rather than duplicate.
"""
from __future__ import annotations

import uuid

from app.application.mcp.contracts import TOOL_CONTRACTS
from app.application.use_cases.vocabulary import PlacementInput, PlaceWordsUseCase
from app.domain.services.mcp_policy import AccessClass
from app.domain.services.mcp_scopes import SCOPE_TOOLS, MCPScope
from app.infrastructure.models import MCPGrantModel
from app.infrastructure.repositories import (
    SqlAlchemyGroupRepository,
    SqlAlchemyRoomRepository,
    SqlAlchemyWordRepository,
)

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


def _invoke(client, headers, *, tool: str, payload: dict, request_id: str | None = None):
    payload = dict(payload)
    if _ACCESS[tool] != AccessClass.READ and "request_id" not in payload:
        payload["request_id"] = request_id or str(uuid.uuid4())
    return client.post(
        "/api/v1/mcp/invoke", headers=headers,
        json={"workspace": _WORKSPACE, "tool": tool, "payload": payload},
    )


def _other_account(auth_headers):
    """A genuinely separate account — `auth_headers()` defaults to one fixed
    identity, so calling it twice would quietly make a cross-account test a
    same-account test that proves nothing."""
    return auth_headers(username="mallory", email="mallory@example.com", password="supersecret2")


def _group(client, headers, name: str = "G") -> dict:
    return client.post(
        "/api/v1/groups", json={"name": name, "target_language": "Spanish"}, headers=headers
    ).json()


def _word(client, headers, group_id: int, term: str) -> dict:
    return client.post(
        f"/api/v1/groups/{group_id}/words", headers=headers,
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
    ).json()


def _room(client, headers, db_session, group_id: int, name: str = "Kitchen") -> int:
    _granted(client, headers, db_session, "lensword_create_room")
    return _invoke(
        client, headers, tool="lensword_create_room", payload={"group_id": group_id, "name": name}
    ).json()["room_id"]


# --- place_words_in_room ----------------------------------------------------


class _CountingRoomRepository:
    """Counts aggregate loads and saves, delegating everything else.

    The acceptance criterion for this issue is stated in repository calls,
    not in elapsed time, so the test asserts on exactly that.
    """

    def __init__(self, inner):
        self._inner = inner
        self.loads = 0
        self.saves = 0

    def get_by_id(self, room_id):
        self.loads += 1
        return self._inner.get_by_id(room_id)

    def update(self, room):
        self.saves += 1
        return self._inner.update(room)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_placing_many_words_loads_and_saves_the_room_aggregate_exactly_once(
    client, auth_headers, db_session
):
    headers = auth_headers()
    user_id = _user_id(client, headers)
    group = _group(client, headers)
    words = [_word(client, headers, group["id"], f"w{index}") for index in range(25)]
    room_id = _room(client, headers, db_session, group["id"])

    rooms = _CountingRoomRepository(SqlAlchemyRoomRepository(db_session))
    result = PlaceWordsUseCase(
        rooms, SqlAlchemyWordRepository(db_session), SqlAlchemyGroupRepository(db_session)
    ).execute(
        user_id, room_id,
        [PlacementInput(word_id=word["id"], x_percent=10.0, y_percent=20.0) for word in words],
    )

    assert len(result.applied) == 25 and result.skipped == ()
    # The whole point of the batch: not 25 loads and 25 saves.
    assert (rooms.loads, rooms.saves) == (1, 1)


def test_an_invalid_word_id_is_skipped_with_a_reason_and_the_rest_still_apply(
    client, auth_headers, db_session
):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    first = _word(client, headers, group["id"], "uno")
    second = _word(client, headers, group["id"], "dos")
    room_id = _room(client, headers, db_session, group["id"])

    response = _invoke(
        client, headers, tool="lensword_place_words_in_room",
        payload={
            "room_id": room_id,
            "placements": [
                {"word_id": first["id"], "x_percent": 10, "y_percent": 10},
                {"word_id": 9_999_999, "x_percent": 20, "y_percent": 20},
                {"word_id": second["id"], "x_percent": 30, "y_percent": 30},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [first["id"], second["id"]]
    assert body["skipped"] == [{"word_id": 9_999_999, "reason": "word_not_found"}]
    assert body["placed_count"] == 2


def test_a_word_owned_by_another_account_is_skipped_never_placed(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    mine = _word(client, headers, group["id"], "mio")
    room_id = _room(client, headers, db_session, group["id"])

    intruder = _other_account(auth_headers)
    theirs = _word(client, intruder, _group(client, intruder, "Theirs")["id"], "suyo")

    response = _invoke(
        client, headers, tool="lensword_place_words_in_room",
        payload={
            "room_id": room_id,
            "placements": [
                {"word_id": mine["id"], "x_percent": 10, "y_percent": 10},
                {"word_id": theirs["id"], "x_percent": 20, "y_percent": 20},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [mine["id"]]
    # Reported exactly as a word that does not exist. Distinguishing the two
    # would turn a batch into a cross-account existence oracle, one item at a
    # time — see PlaceWordsUseCase._miss_reason.
    assert body["skipped"] == [{"word_id": theirs["id"], "reason": "word_not_found"}]


def test_a_word_the_caller_owns_but_filed_elsewhere_says_so(client, auth_headers, db_session):
    """The ordinary mistake, named precisely — it discloses nothing the
    caller cannot already read."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    elsewhere = _group(client, headers, "Elsewhere")
    stray = _word(client, headers, elsewhere["id"], "otro")
    room_id = _room(client, headers, db_session, group["id"])

    response = _invoke(
        client, headers, tool="lensword_place_words_in_room",
        payload={
            "room_id": room_id,
            "placements": [{"word_id": stray["id"], "x_percent": 10, "y_percent": 10}],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == [
        {"word_id": stray["id"], "reason": "word_in_different_group"}
    ]


def test_re_placing_a_word_moves_it_rather_than_duplicating_it(client, auth_headers, db_session):
    """Matches the single-item tool's documented behaviour."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    word = _word(client, headers, group["id"], "hola")
    room_id = _room(client, headers, db_session, group["id"])

    _invoke(client, headers, tool="lensword_place_words_in_room",
            payload={"room_id": room_id,
                     "placements": [{"word_id": word["id"], "x_percent": 10, "y_percent": 10}]})
    moved = _invoke(client, headers, tool="lensword_place_words_in_room",
                    payload={"room_id": room_id,
                             "placements": [{"word_id": word["id"], "x_percent": 80, "y_percent": 90}]})

    body = moved.json()
    assert body["placed_count"] == 1
    assert body["applied"] == [{"word_id": word["id"], "x_percent": 80.0, "y_percent": 90.0}]


def test_a_placement_batch_is_bounded(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    room_id = _room(client, headers, db_session, group["id"])

    response = _invoke(
        client, headers, tool="lensword_place_words_in_room",
        payload={
            "room_id": room_id,
            "placements": [{"word_id": n, "x_percent": 1, "y_percent": 1} for n in range(1, 102)],
        },
    )

    assert response.status_code == 422, response.text


def test_a_placement_item_with_an_out_of_range_coordinate_is_rejected(
    client, auth_headers, db_session
):
    """Array items are validated as strictly as top-level fields. Before
    issue #348 the contract validator understood only string items, so an
    array of objects passed through entirely unvalidated."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_place_words_in_room")
    group = _group(client, headers)
    word = _word(client, headers, group["id"], "hola")
    room_id = _room(client, headers, db_session, group["id"])

    response = _invoke(
        client, headers, tool="lensword_place_words_in_room",
        payload={
            "room_id": room_id,
            "placements": [{"word_id": word["id"], "x_percent": 140, "y_percent": 10}],
        },
    )

    assert response.status_code == 422, response.text


# --- record_context_occurrences ---------------------------------------------


def test_one_passage_records_every_known_word_it_contained(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_record_context_occurrences")
    group = _group(client, headers)
    words = [_word(client, headers, group["id"], term) for term in ("uno", "dos", "tres")]

    response = _invoke(
        client, headers, tool="lensword_record_context_occurrences",
        payload={
            "word_ids": [word["id"] for word in words],
            "context_kind": "reading", "outcome": "correct", "confirmed": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [word["id"] for word in words]
    assert body["skipped"] == []
    assert all(item["context_source"] == "context:reading" for item in body["applied"])
    # Distinct observations, not one deduped against another: the per-item
    # operation ids are what keeps them apart.
    assert len({item["observation_id"] for item in body["applied"]}) == 3


def test_retrying_a_batch_with_the_same_request_id_creates_no_duplicate_observations(
    client, auth_headers, db_session
):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_record_context_occurrences")
    group = _group(client, headers)
    words = [_word(client, headers, group["id"], term) for term in ("uno", "dos")]
    payload = {
        "word_ids": [word["id"] for word in words],
        "context_kind": "conversation", "outcome": "correct", "confirmed": True,
    }
    request_id = str(uuid.uuid4())

    first = _invoke(client, headers, tool="lensword_record_context_occurrences",
                    payload=payload, request_id=request_id)
    retry = _invoke(client, headers, tool="lensword_record_context_occurrences",
                    payload=payload, request_id=request_id)

    assert first.status_code == 200 and retry.status_code == 200, retry.text
    assert [item["observation_id"] for item in retry.json()["applied"]] == [
        item["observation_id"] for item in first.json()["applied"]
    ]


def test_an_unknown_word_is_skipped_and_the_rest_of_the_passage_still_records(
    client, auth_headers, db_session
):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_record_context_occurrences")
    group = _group(client, headers)
    known = _word(client, headers, group["id"], "uno")

    response = _invoke(
        client, headers, tool="lensword_record_context_occurrences",
        payload={
            "word_ids": [known["id"], 9_999_999],
            "context_kind": "subtitle", "outcome": "correct", "confirmed": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [known["id"]]
    assert body["skipped"] == [{"word_id": 9_999_999, "reason": "word_not_found"}]


def test_a_batch_cannot_record_against_another_accounts_word(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_record_context_occurrences")
    group = _group(client, headers)
    mine = _word(client, headers, group["id"], "mio")

    intruder = _other_account(auth_headers)
    theirs = _word(client, intruder, _group(client, intruder, "Theirs")["id"], "suyo")

    response = _invoke(
        client, headers, tool="lensword_record_context_occurrences",
        payload={
            "word_ids": [mine["id"], theirs["id"]],
            "context_kind": "reading", "outcome": "correct", "confirmed": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [mine["id"]]
    assert body["skipped"] == [{"word_id": theirs["id"], "reason": "word_not_found"}]


def test_an_unconfirmed_batch_is_refused_wholesale(client, auth_headers, db_session):
    """`confirmed` describes the whole passage, so failing it is fatal for
    every item rather than a per-item skip."""
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_record_context_occurrences")
    group = _group(client, headers)
    word = _word(client, headers, group["id"], "uno")

    response = _invoke(
        client, headers, tool="lensword_record_context_occurrences",
        payload={
            "word_ids": [word["id"]],
            "context_kind": "reading", "outcome": "correct", "confirmed": False,
        },
    )

    assert response.status_code == 400, response.text


# --- generate_exercises_for_words -------------------------------------------


def test_exercises_are_generated_for_every_owned_word_in_the_batch(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_generate_exercises_for_words")
    group = _group(client, headers)
    words = [_word(client, headers, group["id"], term) for term in ("uno", "dos")]

    response = _invoke(
        client, headers, tool="lensword_generate_exercises_for_words",
        payload={"word_ids": [word["id"] for word in words], "kind": "cloze"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [word["id"] for word in words]
    assert all(item["kind"] == "cloze" for item in body["applied"])
    assert body["skipped"] == []


def test_an_exercise_batch_skips_words_it_does_not_own(client, auth_headers, db_session):
    headers = auth_headers()
    _granted(client, headers, db_session, "lensword_generate_exercises_for_words")
    group = _group(client, headers)
    mine = _word(client, headers, group["id"], "mio")

    intruder = _other_account(auth_headers)
    theirs = _word(client, intruder, _group(client, intruder, "Theirs")["id"], "suyo")

    response = _invoke(
        client, headers, tool="lensword_generate_exercises_for_words",
        payload={"word_ids": [mine["id"], theirs["id"]]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["word_id"] for item in body["applied"]] == [mine["id"]]
    assert body["skipped"] == [{"word_id": theirs["id"], "reason": "word_not_found"}]


# --- registration -----------------------------------------------------------


def test_each_batch_tool_shares_the_scope_of_the_tool_it_batches():
    """A scope is what a resource owner approves on a consent screen. Filing
    a batch under a different scope from its single-item counterpart would
    make consent depend on call shape rather than on what the call can do."""
    assert set(SCOPE_TOOLS[MCPScope.CARD_WRITE]) >= {
        "lensword_place_word_in_room", "lensword_place_words_in_room",
        "lensword_generate_exercises", "lensword_generate_exercises_for_words",
    }
    assert set(SCOPE_TOOLS[MCPScope.CONTEXT_IMPORT]) >= {
        "lensword_record_context_occurrence", "lensword_record_context_occurrences",
    }


def test_the_single_item_tools_survive_alongside_their_batches():
    """Removing one would invalidate every OAuth grant keyed on its name."""
    names = {tool.name for tool in TOOL_CONTRACTS}
    assert {
        "lensword_place_word_in_room",
        "lensword_record_context_occurrence",
        "lensword_generate_exercises",
    } <= names
