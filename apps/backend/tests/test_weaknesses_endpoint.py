"""`GET /api/v1/me/weaknesses`, end to end (issue #134).

Goes through the real review endpoint rather than writing mistake rows
directly, because the claim being tested is that answering wrong actually
records something — not that the profile can read rows a test planted.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


def _group(client, headers) -> int:
    resp = client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _word(client, headers, group_id: int, term: str, **fields) -> int:
    resp = client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"], **fields},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _answer(client, headers, session_id: int, word_id: int, outcome: str, attempted: str | None = None):
    payload = {"word_id": word_id, "outcome": outcome}
    if attempted is not None:
        payload["attempted_answer"] = attempted
    resp = client.post(f"/api/v1/review/sessions/{session_id}/answers", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp


def _session(client, headers, group_id: int, mode: str = "standard") -> int:
    resp = client.post(
        "/api/v1/review/sessions", json={"mode": mode, "group_id": group_id}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


# --- The empty case, which is the one most easily got wrong ----------------


def test_a_learner_with_no_mistakes_is_told_we_do_not_know_yet(client, headers):
    """Not an empty profile. "No weaknesses found" and "not enough evidence"
    are different claims, and only one of them is true here."""
    body = client.get("/api/v1/me/weaknesses", headers=headers).json()

    assert body["insufficient_data"] is True
    assert body["total_mistakes"] == 0


def test_the_endpoint_requires_authentication(client):
    assert client.get("/api/v1/me/weaknesses").status_code == 401


# --- Recording through a real review ---------------------------------------


def test_answering_wrong_records_a_mistake(client, headers):
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    session_id = _session(client, headers, group_id)

    _answer(client, headers, session_id, word_id, "incorrect", "perro")

    assert client.get("/api/v1/me/weaknesses", headers=headers).json()["total_mistakes"] == 1


def test_answering_correctly_records_nothing(client, headers):
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    session_id = _session(client, headers, group_id)

    _answer(client, headers, session_id, word_id, "correct")

    assert client.get("/api/v1/me/weaknesses", headers=headers).json()["total_mistakes"] == 0


def test_a_client_that_reports_no_attempted_answer_still_records_the_mistake(client, headers):
    """A flashcard client only knows right or wrong. That is less information,
    not a reason to lose the mistake."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    session_id = _session(client, headers, group_id)

    _answer(client, headers, session_id, word_id, "incorrect")

    body = client.get("/api/v1/me/weaknesses", headers=headers).json()
    assert body["total_mistakes"] == 1
    assert body["confused_pairs"] == []


def test_a_confusion_is_named_only_between_words_the_learner_studies(client, headers):
    group_id = _group(client, headers)
    gato = _word(client, headers, group_id, "gato")
    _word(client, headers, group_id, "gata")

    # Twice: one confusion is a slip, and the profile deliberately will not
    # call a pair confusable on a single occurrence. Both answers go in one
    # session because a reviewed word is no longer due, so a second session
    # would have nothing to offer.
    session_id = _session(client, headers, group_id)
    for _ in range(2):
        _answer(client, headers, session_id, gato, "incorrect", "gata")

    pairs = client.get("/api/v1/me/weaknesses", headers=headers).json()["confused_pairs"]
    assert len(pairs) == 1
    assert {pairs[0]["word_term"], pairs[0]["confused_with_term"]} == {"gato", "gata"}
    assert pairs[0]["occurrences"] == 2


def test_an_answer_that_is_not_a_word_they_study_makes_no_pair(client, headers):
    """A misspelling that happens to resemble a word must not manufacture a
    confusion pair out of a typo."""
    group_id = _group(client, headers)
    gato = _word(client, headers, group_id, "gato")

    session_id = _session(client, headers, group_id)
    for _ in range(3):
        _answer(client, headers, session_id, gato, "incorrect", "gatoo")

    body = client.get("/api/v1/me/weaknesses", headers=headers).json()
    assert body["confused_pairs"] == []
    assert body["total_mistakes"] == 3


def test_a_repeated_category_is_named_once_it_recurs(client, headers):
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")

    session_id = _session(client, headers, group_id)
    for _ in range(3):
        _answer(client, headers, session_id, word_id, "skipped")

    body = client.get("/api/v1/me/weaknesses", headers=headers).json()
    assert body["insufficient_data"] is False
    assert body["categories"][0]["category"] == "not_recalled"
    assert body["categories"][0]["occurrences"] == 3


# --- Freshness and provenance (issue #192 TODO 0) --------------------------


def test_the_profile_carries_a_freshness_timestamp(client, headers):
    body = client.get("/api/v1/me/weaknesses", headers=headers).json()

    assert body["generated_at"] is not None


def test_a_named_category_carries_the_mistake_row_ids_behind_it(client, headers):
    """A companion (or any other reader) can trace the claim back to the
    rows it was derived from — the same "evidence/provenance" requirement
    `DiagnosisResponse.evidence[].observation_ids` already satisfies for
    diagnoses."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")

    session_id = _session(client, headers, group_id)
    for _ in range(3):
        _answer(client, headers, session_id, word_id, "skipped")

    category = client.get("/api/v1/me/weaknesses", headers=headers).json()["categories"][0]
    assert len(category["evidence_ids"]) == 3
    assert len(set(category["evidence_ids"])) == 3  # each mistake is its own row


def test_a_confused_pair_carries_the_mistake_row_ids_behind_it(client, headers):
    group_id = _group(client, headers)
    gato = _word(client, headers, group_id, "gato")
    _word(client, headers, group_id, "gata")

    session_id = _session(client, headers, group_id)
    for _ in range(2):
        _answer(client, headers, session_id, gato, "incorrect", "gata")

    pair = client.get("/api/v1/me/weaknesses", headers=headers).json()["confused_pairs"][0]
    assert len(pair["evidence_ids"]) == 2


def test_shares_are_reported_alongside_counts(client, headers):
    """60% of five mistakes and 60% of five hundred are different claims, so
    the count travels with the share rather than being replaced by it."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")

    session_id = _session(client, headers, group_id)
    for _ in range(3):
        _answer(client, headers, session_id, word_id, "skipped")

    category = client.get("/api/v1/me/weaknesses", headers=headers).json()["categories"][0]
    assert category["occurrences"] == 3
    assert category["share"] == pytest.approx(1.0)


# --- Cross-association error rate (issue #207 TODO 0) ----------------------


def test_a_learner_with_no_mistakes_gets_no_cross_association_rate(client, headers):
    body = client.get("/api/v1/me/weaknesses", headers=headers).json()

    assert body["cross_association"]["insufficient_data"] is True
    assert body["cross_association"]["resolved_errors"] == 0


def test_a_few_confusions_are_too_few_to_report_a_rate(client, headers):
    group_id = _group(client, headers)
    borrow = _word(client, headers, group_id, "borrow", synonyms=["lend"])
    _word(client, headers, group_id, "lend")
    session_id = _session(client, headers, group_id)
    for _ in range(2):
        _answer(client, headers, session_id, borrow, "incorrect", "lend")

    cross_association = client.get("/api/v1/me/weaknesses", headers=headers).json()["cross_association"]

    assert cross_association["insufficient_data"] is True


def test_confusing_a_word_with_its_synonym_is_reported_as_a_related_error(client, headers):
    group_id = _group(client, headers)
    borrow = _word(client, headers, group_id, "borrow", synonyms=["lend"])
    _word(client, headers, group_id, "lend")
    session_id = _session(client, headers, group_id)
    for _ in range(5):
        _answer(client, headers, session_id, borrow, "incorrect", "lend")

    cross_association = client.get("/api/v1/me/weaknesses", headers=headers).json()["cross_association"]

    assert cross_association["insufficient_data"] is False
    assert cross_association["resolved_errors"] == 5
    assert cross_association["related_errors"] == 5
    assert cross_association["error_rate"] == pytest.approx(1.0)
    assert {r["relation"] for r in cross_association["by_relation"]} == {"synonym"}


def test_confusing_two_unrelated_words_is_not_reported_as_a_related_error(client, headers):
    group_id = _group(client, headers)
    borrow = _word(client, headers, group_id, "borrow")
    _word(client, headers, group_id, "table")
    session_id = _session(client, headers, group_id)
    for _ in range(5):
        _answer(client, headers, session_id, borrow, "incorrect", "table")

    cross_association = client.get("/api/v1/me/weaknesses", headers=headers).json()["cross_association"]

    assert cross_association["insufficient_data"] is False
    assert cross_association["related_errors"] == 0
    assert cross_association["error_rate"] == pytest.approx(0.0)
    assert cross_association["by_relation"] == []


# --- Isolation -------------------------------------------------------------


def test_one_learners_profile_never_contains_anothers_mistakes(client, auth_headers):
    alex = auth_headers()
    group_id = _group(client, alex)
    word_id = _word(client, alex, group_id, "gato")
    session_id = _session(client, alex, group_id)
    _answer(client, alex, session_id, word_id, "incorrect", "perro")

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get("/api/v1/me/weaknesses", headers=sam).json()["total_mistakes"] == 0
    assert client.get("/api/v1/me/weaknesses", headers=alex).json()["total_mistakes"] == 1


# --- The "review my mistakes" session (issue #142) --------------------------


def test_a_mistakes_session_offers_a_word_that_is_not_due(client, headers):
    """The point of the mode. A word you know you got wrong is worth
    revisiting whether or not the scheduler has come round to it — and
    answering it just now pushed its due date into the future."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    session_id = _session(client, headers, group_id)
    _answer(client, headers, session_id, word_id, "incorrect", "perro")

    # A standard session has nothing: the word was just reviewed.
    assert client.post(
        "/api/v1/review/sessions",
        json={"mode": "standard", "group_id": group_id},
        headers=headers,
    ).status_code == 409

    resp = client.post(
        "/api/v1/review/sessions", json={"mode": "mistakes", "group_id": group_id}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert [w["id"] for w in resp.json()["words"]] == [word_id]


def test_a_learner_with_no_mistakes_gets_no_mistakes_session(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "gato")

    resp = client.post(
        "/api/v1/review/sessions", json={"mode": "mistakes", "group_id": group_id}, headers=headers
    )

    assert resp.status_code == 409


def test_a_relearned_word_drops_out_of_the_mistakes_session(client, headers):
    """Three correct answers retire the mistake. A session that kept offering
    words the learner has demonstrably fixed would stop being worth opening."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    first = _session(client, headers, group_id)
    _answer(client, headers, first, word_id, "incorrect", "perro")

    relearn = _session(client, headers, group_id, mode="mistakes")
    for _ in range(3):
        _answer(client, headers, relearn, word_id, "correct")

    resp = client.post(
        "/api/v1/review/sessions", json={"mode": "mistakes", "group_id": group_id}, headers=headers
    )
    assert resp.status_code == 409


def test_one_correct_answer_does_not_retire_a_mistake(client, headers):
    """Answering right immediately after being shown the answer is often
    repetition rather than recall."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "gato")
    first = _session(client, headers, group_id)
    _answer(client, headers, first, word_id, "incorrect", "perro")

    relearn = _session(client, headers, group_id, mode="mistakes")
    _answer(client, headers, relearn, word_id, "correct")

    resp = client.post(
        "/api/v1/review/sessions", json={"mode": "mistakes", "group_id": group_id}, headers=headers
    )
    assert resp.status_code == 201


def test_a_mistakes_session_never_offers_another_learners_words(client, auth_headers):
    alex = auth_headers()
    group_id = _group(client, alex)
    word_id = _word(client, alex, group_id, "gato")
    session_id = _session(client, alex, group_id)
    _answer(client, alex, session_id, word_id, "incorrect", "perro")

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.post(
        "/api/v1/review/sessions", json={"mode": "mistakes"}, headers=sam
    ).status_code == 409
