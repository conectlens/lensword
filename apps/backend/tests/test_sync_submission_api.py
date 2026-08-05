"""Reconciling offline mutations end-to-end (issue #90).

Covers the issue's own verification list: retry, reordering, duplicated
requests, concurrent edits, delete-vs-edit, and multi-device review events —
with zero lost acknowledged mutations.
"""
from __future__ import annotations


def _group(client, headers) -> int:
    return client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    ).json()["id"]


def _word(client, headers, group_id: int, term: str = "perro") -> dict:
    return client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["dog"]},
        headers=headers,
    ).json()


def _submit(client, headers, *ops):
    return client.post("/api/v1/sync/operations", json={"operations": list(ops)}, headers=headers)


def _op(operation_id, entity_type, operation, payload, entity_id=None, base_revision=None):
    return {
        "operation_id": operation_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "operation": operation,
        "payload": payload,
        "base_revision": base_revision,
    }


def test_a_word_created_offline_is_applied(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)

    resp = _submit(
        client,
        headers,
        _op("op-1", "word", "create", {"group_id": group_id, "term": "gato", "translations": ["cat"]}),
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity_id"] is not None

    created = client.get(f"/api/v1/words/{result['entity_id']}", headers=headers).json()
    assert created["term"] == "gato"
    assert created["revision"] == 1


def test_retrying_the_same_operation_id_does_not_apply_twice(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    op = _op("op-retry", "word", "create", {"group_id": group_id, "term": "gato"})

    first = _submit(client, headers, op).json()["results"][0]
    second = _submit(client, headers, op).json()["results"][0]

    assert first == second
    words = client.get(f"/api/v1/groups/{group_id}/words", headers=headers).json()
    assert len(words) == 1


def test_a_duplicated_request_in_the_same_batch_applies_once(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    op = _op("op-dupe-batch", "word", "create", {"group_id": group_id, "term": "gato"})

    resp = _submit(client, headers, op, op)

    results = resp.json()["results"]
    assert [r["status"] for r in results] == ["applied", "applied"]
    assert results[0]["entity_id"] == results[1]["entity_id"]
    words = client.get(f"/api/v1/groups/{group_id}/words", headers=headers).json()
    assert len(words) == 1


def test_an_edit_against_the_current_revision_applies(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    resp = _submit(
        client,
        headers,
        _op(
            "op-edit",
            "word",
            "update",
            {"definition": "a domesticated canine"},
            entity_id=word["id"],
            base_revision=word["revision"],
        ),
    )

    result = resp.json()["results"][0]
    assert result["status"] == "applied"
    updated = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert updated["definition"] == "a domesticated canine"
    assert updated["revision"] == word["revision"] + 1


def test_concurrent_edits_from_two_devices_the_second_conflicts(client, auth_headers):
    """Both devices read revision 1. Device A's edit lands first and moves
    the word to revision 2; device B's edit, still naming revision 1, must
    conflict rather than silently overwrite A's change."""
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    device_a = _op(
        "op-device-a", "word", "update", {"definition": "from device A"},
        entity_id=word["id"], base_revision=word["revision"],
    )
    device_b = _op(
        "op-device-b", "word", "update", {"definition": "from device B"},
        entity_id=word["id"], base_revision=word["revision"],
    )

    result_a = _submit(client, headers, device_a).json()["results"][0]
    result_b = _submit(client, headers, device_b).json()["results"][0]

    assert result_a["status"] == "applied"
    assert result_b["status"] == "conflict"
    assert result_b["conflict_reason"]

    final = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert final["definition"] == "from device A"

    conflicts = client.get("/api/v1/sync/conflicts", headers=headers).json()["conflicts"]
    assert any(c["operation_id"] == "op-device-b" for c in conflicts)


def test_reordering_two_independent_edits_does_not_change_the_outcome(client, auth_headers):
    """The same two operations, submitted in the opposite order, must reach
    the same final decision each — the outcome depends on the revision each
    names, not on submission order."""
    forward_headers = auth_headers(email="forward@example.com", username="forward")
    forward_group = _group(client, forward_headers)
    word_1 = _word(client, forward_headers, forward_group, term="uno")
    word_2 = _word(client, forward_headers, forward_group, term="dos")

    op_1 = _op("op-reorder-1", "word", "update", {"definition": "first"}, entity_id=word_1["id"], base_revision=word_1["revision"])
    op_2 = _op("op-reorder-2", "word", "update", {"definition": "second"}, entity_id=word_2["id"], base_revision=word_2["revision"])

    forward = _submit(client, forward_headers, op_1, op_2)
    # Independent words, independent accounts is overkill for this property —
    # what matters is that processing [1, 2] and [2, 1] against the *same*
    # starting state reach the same per-operation verdicts.
    reversed_headers = auth_headers(email="reversed@example.com", username="reversed")
    reversed_group = _group(client, reversed_headers)
    r_word_1 = _word(client, reversed_headers, reversed_group, term="uno")
    r_word_2 = _word(client, reversed_headers, reversed_group, term="dos")
    r_op_1 = _op("op-reorder-1", "word", "update", {"definition": "first"}, entity_id=r_word_1["id"], base_revision=r_word_1["revision"])
    r_op_2 = _op("op-reorder-2", "word", "update", {"definition": "second"}, entity_id=r_word_2["id"], base_revision=r_word_2["revision"])
    backward = _submit(client, reversed_headers, r_op_2, r_op_1)

    forward_statuses = {r["operation_id"]: r["status"] for r in forward.json()["results"]}
    backward_statuses = {r["operation_id"]: r["status"] for r in backward.json()["results"]}
    assert forward_statuses == backward_statuses == {"op-reorder-1": "applied", "op-reorder-2": "applied"}


def test_editing_a_word_deleted_on_another_device_is_surfaced_not_discarded(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    delete_result = _submit(
        client, headers, _op("op-delete", "word", "delete", {}, entity_id=word["id"], base_revision=word["revision"])
    ).json()["results"][0]
    assert delete_result["status"] == "applied"

    edit_result = _submit(
        client,
        headers,
        _op("op-edit-after-delete", "word", "update", {"definition": "still trying to edit"}, entity_id=word["id"], base_revision=word["revision"]),
    ).json()["results"][0]

    assert edit_result["status"] == "conflict"
    assert "deleted" in edit_result["conflict_reason"]
    conflicts = client.get("/api/v1/sync/conflicts", headers=headers).json()["conflicts"]
    assert any(c["operation_id"] == "op-edit-after-delete" for c in conflicts)


def test_deleting_something_already_deleted_converges_rather_than_conflicting(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    first = _submit(client, headers, _op("op-del-1", "word", "delete", {}, entity_id=word["id"], base_revision=word["revision"])).json()["results"][0]
    second = _submit(client, headers, _op("op-del-2", "word", "delete", {}, entity_id=word["id"], base_revision=word["revision"])).json()["results"][0]

    assert first["status"] == "applied"
    assert second["status"] == "applied"


def test_collections_from_two_devices_both_survive(client, auth_headers):
    """Adding a synonym on one device and a different one on another is not a
    conflict — both belong."""
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    device_a = _op("op-syn-a", "word", "update", {"synonyms": ["canino"]}, entity_id=word["id"], base_revision=word["revision"])
    result_a = _submit(client, headers, device_a).json()["results"][0]
    assert result_a["status"] == "applied"

    after_a = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    device_b = _op("op-syn-b", "word", "update", {"synonyms": ["chucho"]}, entity_id=word["id"], base_revision=after_a["revision"])
    result_b = _submit(client, headers, device_b).json()["results"][0]
    assert result_b["status"] == "applied"

    final = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert set(final["synonyms"]) == {"canino", "chucho"}


def test_multi_device_review_events_all_apply_with_zero_lost(client, auth_headers):
    """Reviews are appends: two devices reviewing the same word offline both
    have their attempts land, in any order, with no version check to fail."""
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)
    session_id = client.post("/api/v1/review/sessions", json={"group_id": group_id}, headers=headers).json()["session_id"]

    device_a = _op(
        "op-review-a", "review", "append",
        {"session_id": session_id, "word_id": word["id"], "outcome": "correct", "response_time_ms": 900},
    )
    device_b = _op(
        "op-review-b", "review", "append",
        {"session_id": session_id, "word_id": word["id"], "outcome": "correct", "response_time_ms": 1200},
    )

    resp = _submit(client, headers, device_a, device_b)

    statuses = [r["status"] for r in resp.json()["results"]]
    assert statuses == ["applied", "applied"]


def test_a_review_replayed_by_operation_id_is_not_double_applied(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)
    session_id = client.post("/api/v1/review/sessions", json={"group_id": group_id}, headers=headers).json()["session_id"]
    op = _op(
        "op-review-retry", "review", "append",
        {"session_id": session_id, "word_id": word["id"], "outcome": "correct", "response_time_ms": 900},
    )

    first = _submit(client, headers, op).json()["results"][0]
    second = _submit(client, headers, op).json()["results"][0]

    assert first["status"] == second["status"] == "applied"
    after = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    # One review applied, not two: repetitions advanced by exactly one step.
    assert after["review_state"]["repetitions"] == 1


def test_an_operation_for_a_word_you_do_not_own_conflicts_but_does_not_abort_the_batch(client, auth_headers):
    owner = auth_headers()
    group_id = _group(client, owner)
    someone_elses_word = _word(client, owner, group_id)

    intruder = auth_headers(email="intruder@example.com", username="intruder")
    intruder_group = _group(client, intruder)

    resp = _submit(
        client,
        intruder,
        _op(
            "op-steal",
            "word",
            "update",
            {"definition": "hijacked"},
            entity_id=someone_elses_word["id"],
            base_revision=someone_elses_word["revision"],
        ),
        _op("op-legit", "word", "create", {"group_id": intruder_group, "term": "legit"}),
    )

    results = {r["operation_id"]: r for r in resp.json()["results"]}
    assert results["op-steal"]["status"] == "conflict"
    assert results["op-legit"]["status"] == "applied"

    untouched = client.get(f"/api/v1/words/{someone_elses_word['id']}", headers=owner).json()
    assert untouched["definition"] != "hijacked"


def test_an_edit_that_names_no_base_revision_conflicts_rather_than_last_write_wins(client, auth_headers):
    headers = auth_headers()
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    result = _submit(
        client,
        headers,
        _op("op-no-base", "word", "update", {"definition": "sneaky"}, entity_id=word["id"], base_revision=None),
    ).json()["results"][0]

    assert result["status"] == "conflict"
