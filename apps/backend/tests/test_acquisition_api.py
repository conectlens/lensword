"""Acquisition-ladder endpoints (#180, issue #184 TODO 2/3/4).

Covers the flag-off guarantee (ADR 0007's "not just records nothing, the
repository is never wired in"), explicit entry, submitting rungs through
to graduation and the single bounded FSRS handoff, diagnosis-driven entry
from a real review answer, and the endpoints' tenant isolation / malformed
input / deleted-word behavior — the same bar #183's persistence tests set
for this epic's other read endpoints.
"""
from __future__ import annotations

from datetime import timedelta

from app.domain.services.acquisition import LADDER_OFFSETS, AcquisitionScheduler
from app.domain.value_objects import ReviewOutcome
from app.infrastructure.repositories import SqlAlchemyAcquisitionStateRepository, SqlAlchemyUserRepository


def _setup_word(client, headers, term="palabra"):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    return client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
        headers=headers,
    ).json()


def _enable(client, headers):
    resp = client.put(
        "/api/v1/recall-settings",
        json={"learning_diagnosis_enabled": True, "acquisition_loop_enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200


# --- Flag gating ---


def test_current_state_is_null_before_anything_starts(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)

    resp = client.get(f"/api/v1/words/{word['id']}/acquisition", headers=headers)
    assert resp.status_code == 200
    assert resp.json() is None


def test_start_is_forbidden_when_the_loop_is_disabled(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    # acquisition_loop_enabled left at its default (off).

    resp = client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)
    assert resp.status_code == 403


# --- Explicit entry and the rung ladder ---


def test_explicit_start_creates_a_ladder_at_rung_zero(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)

    resp = client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["rung"] == 0
    assert body["graduated"] is False
    assert body["entry_reason"] == "explicit_user_choice"


def test_starting_twice_does_not_restart_an_active_ladder(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)

    first = client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers).json()
    client.post(
        f"/api/v1/words/{word['id']}/acquisition/answer", json={"outcome": "correct"}, headers=headers
    )
    second = client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers).json()

    # The second call must not reset progress back to rung 0.
    assert second["rung"] == 1
    assert second["started_at"] == first["started_at"]


def test_answering_with_no_active_ladder_returns_null(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)

    resp = client.post(
        f"/api/v1/words/{word['id']}/acquisition/answer", json={"outcome": "correct"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json() is None


def test_climbing_every_rung_graduates_and_updates_the_words_review_state(
    client, auth_headers, db_session, monkeypatch
):
    """The end-to-end handoff: FSRSScheduler must actually have run once,
    which shows up as a real interval on the word."""
    headers = auth_headers()
    resp = client.put(
        "/api/v1/recall-settings",
        json={"learning_diagnosis_enabled": True, "acquisition_loop_enabled": True, "scheduler": "fsrs"},
        headers=headers,
    )
    assert resp.status_code == 200
    word = _setup_word(client, headers)

    client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyAcquisitionStateRepository(db_session)
    scheduler = AcquisitionScheduler()

    # Fast-forward the ladder by writing states with a real gap directly
    # through the repository — exercising the HTTP endpoint for every rung
    # would otherwise require the test to sleep for real wall-clock hours.
    state = repo.get_for_word(owner_id, word["id"])
    t = state.started_at
    for _ in range(len(LADDER_OFFSETS[1]) - 1):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)
        repo.upsert(state)

    # The final rung, submitted for real through the API — this is the one
    # that must trigger the bounded handoff. `utcnow` is patched only for
    # this one request, past the gap the ladder's own start already needed
    # real wall-clock time to satisfy.
    before = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert before["review_state"]["repetitions"] == 0

    final_time = t + timedelta(hours=1)
    import app.api.routers.acquisition as acquisition_router

    monkeypatch.setattr(acquisition_router, "utcnow", lambda: final_time)
    resp = client.post(
        f"/api/v1/words/{word['id']}/acquisition/answer", json={"outcome": "correct"}, headers=headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["graduated"] is True

    after = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert after["review_state"]["repetitions"] == 1
    assert after["review_state"]["interval_days"] > 0
    assert after["review_state"]["last_reviewed_at"] is not None


def test_a_failed_rung_backs_off_but_does_not_graduate(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)
    client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)

    resp = client.post(
        f"/api/v1/words/{word['id']}/acquisition/answer", json={"outcome": "incorrect"}, headers=headers
    )
    body = resp.json()
    assert body["rung"] == 0
    assert body["graduated"] is False


# --- Diagnosis-driven entry (TODO 4) ---


def test_a_weak_acquisition_diagnosis_auto_enters_the_loop(client, auth_headers, db_session):
    """End to end: a real review answer, through the real diagnosis
    engine, produces a weak_acquisition outcome for a word with no prior
    demonstrated recall — which should auto-enter the acquisition loop."""
    headers = auth_headers()
    _enable(client, headers)
    word = _setup_word(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    # Two failures with no prior correct answer: WeakAcquisitionRule's
    # exact firing condition (see test_diagnosis_engine.py).
    for _ in range(2):
        client.post(
            f"/api/v1/review/sessions/{session_id}/answers",
            json={"word_id": word["id"], "outcome": "incorrect"},
            headers=headers,
        )

    resp = client.get(f"/api/v1/words/{word['id']}/acquisition", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["entry_reason"] == "weak_acquisition_diagnosis"


def test_diagnosis_driven_entry_does_not_happen_when_the_loop_flag_is_off(client, auth_headers):
    """acquisition_loop_enabled off, learning_diagnosis_enabled on: a
    diagnosis is still produced, but it must never start a ladder."""
    headers = auth_headers()
    client.put("/api/v1/recall-settings", json={"learning_diagnosis_enabled": True}, headers=headers)
    word = _setup_word(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    for _ in range(2):
        client.post(
            f"/api/v1/review/sessions/{session_id}/answers",
            json={"word_id": word["id"], "outcome": "incorrect"},
            headers=headers,
        )

    resp = client.get(f"/api/v1/words/{word['id']}/acquisition", headers=headers)
    assert resp.json() is None


# --- Tenant isolation, malformed input, deleted word ---


def test_endpoints_404_for_a_nonexistent_word(client, auth_headers):
    headers = auth_headers()
    assert client.get("/api/v1/words/999999/acquisition", headers=headers).status_code == 404
    assert client.post("/api/v1/words/999999/acquisition/start", headers=headers).status_code == 404
    assert (
        client.post(
            "/api/v1/words/999999/acquisition/answer", json={"outcome": "correct"}, headers=headers
        ).status_code
        == 404
    )


def test_endpoints_404_for_another_users_word(client, auth_headers):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    word = _setup_word(client, owner_headers)

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    assert client.get(f"/api/v1/words/{word['id']}/acquisition", headers=stranger_headers).status_code == 404
    assert (
        client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=stranger_headers).status_code == 404
    )


def test_endpoint_404s_after_the_word_is_deleted(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)
    client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)

    assert client.delete(f"/api/v1/words/{word['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/words/{word['id']}/acquisition", headers=headers).status_code == 404


def test_answer_rejects_a_malformed_outcome(client, auth_headers):
    headers = auth_headers()
    word = _setup_word(client, headers)
    _enable(client, headers)
    client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)

    resp = client.post(
        f"/api/v1/words/{word['id']}/acquisition/answer", json={"outcome": "not-a-real-outcome"}, headers=headers
    )
    assert resp.status_code == 422


def test_due_endpoint_requires_authentication(client):
    resp = client.get("/api/v1/acquisition/due")
    assert resp.status_code in (401, 403)


def test_due_endpoint_only_returns_the_callers_own_due_ladders(client, auth_headers, monkeypatch):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    owner_word = _setup_word(client, owner_headers, term="uno")
    _enable(client, owner_headers)
    client.post(f"/api/v1/words/{owner_word['id']}/acquisition/start", headers=owner_headers)

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    _enable(client, stranger_headers)
    stranger_word = _setup_word(client, stranger_headers, term="dos")
    client.post(f"/api/v1/words/{stranger_word['id']}/acquisition/start", headers=stranger_headers)

    # Rung 0 is due 30 seconds after it starts — advance the clock past
    # that for the "due" check itself, not for the two /start calls above.
    import app.api.routers.acquisition as acquisition_router
    from app.domain.value_objects import utcnow as real_utcnow

    monkeypatch.setattr(acquisition_router, "utcnow", lambda: real_utcnow() + timedelta(minutes=1))

    resp = client.get("/api/v1/acquisition/due", headers=owner_headers)
    assert resp.status_code == 200
    word_ids = {row["word_id"] for row in resp.json()}
    assert owner_word["id"] in word_ids
    assert stranger_word["id"] not in word_ids
