"""Deleting a word or a group removes everything that references it.

Found by running the tenant-isolation audit against Postgres. `DELETE
/api/v1/words/{id}` on a word placed in a room raised ForeignKeyViolation — a
500 — while the identical request succeeded on SQLite, which does not enforce
foreign keys unless `PRAGMA foreign_keys` is on. The bug is as old as the
initial commit and was invisible for as long as SQLite was the only target.

The assertions check for leftover rows rather than only for a 2xx, so they
catch the regression on either dialect: Postgres fails on the constraint, and
SQLite — where the delete still "succeeds" — fails on the orphans. Reverting
the fix turns two of these red on SQLite and more than that on Postgres.
"""
from __future__ import annotations

from app.infrastructure.models import (
    DiagnosisModel,
    LearningObservationModel,
    MnemonicNoteModel,
    PracticeExerciseModel,
    ReviewAttemptModel,
    RoomModel,
    RoomPlacementModel,
    WordModel,
)


def _group_with_placed_word(client, headers):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    room = client.post(
        "/api/v1/rooms", json={"group_id": group["id"], "name": "R"}, headers=headers
    ).json()
    client.post(
        f"/api/v1/rooms/{room['id']}/placements",
        json={"word_id": word["id"], "x_percent": 10, "y_percent": 20},
        headers=headers,
    )
    client.post(f"/api/v1/words/{word['id']}/mnemonics", json={"text": "runner"}, headers=headers)
    client.post(
        "/api/v1/practice/exercises",
        json={"word_id": word["id"], "kind": "translation"},
        headers=headers,
    )
    return group, word, room


def test_deleting_a_placed_word_succeeds_and_leaves_no_references(client, auth_headers, db_session):
    headers = auth_headers()
    _group, word, _room = _group_with_placed_word(client, headers)

    response = client.delete(f"/api/v1/words/{word['id']}", headers=headers)

    assert response.status_code == 204, response.text
    assert db_session.query(WordModel).filter_by(id=word["id"]).count() == 0
    for model in (RoomPlacementModel, MnemonicNoteModel, PracticeExerciseModel, ReviewAttemptModel):
        assert db_session.query(model).filter_by(word_id=word["id"]).count() == 0, model.__name__


def test_deleting_a_word_reviewed_in_a_session_succeeds(client, auth_headers, db_session):
    """Review attempts reference words. Refusing to delete a reviewed word
    would make a vocabulary list permanently un-prunable."""
    headers = auth_headers()
    _group, word, _room = _group_with_placed_word(client, headers)
    session = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=headers
    ).json()
    client.post(
        f"/api/v1/review/sessions/{session['session_id']}/answers",
        json={"word_id": word["id"], "outcome": "correct", "response_time_ms": 100},
        headers=headers,
    )

    response = client.delete(f"/api/v1/words/{word['id']}", headers=headers)

    assert response.status_code == 204, response.text
    assert db_session.query(ReviewAttemptModel).filter_by(word_id=word["id"]).count() == 0


def test_deleting_a_group_removes_its_words_rooms_and_placements(client, auth_headers, db_session):
    headers = auth_headers()
    group, word, room = _group_with_placed_word(client, headers)

    response = client.delete(f"/api/v1/groups/{group['id']}", headers=headers)

    assert response.status_code == 204, response.text
    assert db_session.query(WordModel).filter_by(group_id=group["id"]).count() == 0
    assert db_session.query(RoomModel).filter_by(group_id=group["id"]).count() == 0
    assert db_session.query(RoomPlacementModel).filter_by(room_id=room["id"]).count() == 0
    assert db_session.query(MnemonicNoteModel).filter_by(word_id=word["id"]).count() == 0


def test_deleting_a_group_leaves_another_groups_data_alone(client, auth_headers, db_session):
    """The dependant cleanup selects by group and by word id. A predicate wide
    enough to be wrong here would take out the account's other decks."""
    headers = auth_headers()
    doomed, _word, _room = _group_with_placed_word(client, headers)
    keeper = client.post(
        "/api/v1/groups", json={"name": "Keep", "target_language": "French"}, headers=headers
    ).json()
    kept_word = client.post(
        f"/api/v1/groups/{keeper['id']}/words",
        json={"term": "Courir", "target_language": "French", "translations": ["to run"]},
        headers=headers,
    ).json()

    client.delete(f"/api/v1/groups/{doomed['id']}", headers=headers)

    assert db_session.query(WordModel).filter_by(id=kept_word["id"]).count() == 1
    assert client.get(f"/api/v1/words/{kept_word['id']}", headers=headers).status_code == 200


def _enable_diagnosis(client, headers):
    resp = client.put("/api/v1/recall-settings", json={"learning_diagnosis_enabled": True}, headers=headers)
    assert resp.status_code == 200


def test_deleting_a_word_with_diagnosis_history_succeeds_and_leaves_no_references(client, auth_headers, db_session):
    """#182/#183: learning_observations and diagnoses both carry a NOT
    NULL word_id — the same class of bug this file's docstring describes,
    just for two tables that shipped after it was written and were missed
    from the cleanup."""
    headers = auth_headers()
    _enable_diagnosis(client, headers)
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    session = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=headers
    ).json()
    client.post(
        f"/api/v1/review/sessions/{session['session_id']}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=headers,
    )

    response = client.delete(f"/api/v1/words/{word['id']}", headers=headers)

    assert response.status_code == 204, response.text
    assert db_session.query(LearningObservationModel).filter_by(word_id=word["id"]).count() == 0
    assert db_session.query(DiagnosisModel).filter_by(word_id=word["id"]).count() == 0


def test_deleting_an_unplaced_word_still_works(client, auth_headers):
    """The simple path, which had no dependants to trip over and so was the
    only one the old code was ever exercised on."""
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Saltar", "target_language": "Spanish", "translations": ["to jump"]},
        headers=headers,
    ).json()

    assert client.delete(f"/api/v1/words/{word['id']}", headers=headers).status_code == 204
