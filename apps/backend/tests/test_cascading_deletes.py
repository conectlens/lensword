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

from datetime import datetime, timezone

from app.infrastructure.models import (
    AcquisitionEventModel,
    ConversationMessageModel,
    ConversationSessionModel,
    DailySessionPreferenceModel,
    DesktopNotificationModel,
    DiagnosisModel,
    GroupModel,
    LearningObservationModel,
    LearningPathModel,
    MnemonicNoteModel,
    PathMilestoneModel,
    PracticeExerciseModel,
    RecallSettingsModel,
    ReminderModel,
    ReviewAttemptModel,
    RoomModel,
    RoomPlacementModel,
    ScenarioAttemptModel,
    SyncOperationModel,
    UserModel,
    WeeklyLearningReportModel,
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


def test_deleting_a_word_with_an_acquisition_ladder_succeeds_and_leaves_no_references(
    client, auth_headers, db_session
):
    """#184: acquisition_events also carries a NOT NULL word_id — added to
    the cleanup list from the start (see repositories.py's comment) rather
    than repeating the #182/#183 omission a third time."""
    headers = auth_headers()
    client.put(
        "/api/v1/recall-settings",
        json={"learning_diagnosis_enabled": True, "acquisition_loop_enabled": True},
        headers=headers,
    )
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    client.post(f"/api/v1/words/{word['id']}/acquisition/start", headers=headers)

    response = client.delete(f"/api/v1/words/{word['id']}", headers=headers)

    assert response.status_code == 204, response.text
    assert db_session.query(AcquisitionEventModel).filter_by(word_id=word["id"]).count() == 0


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


def _make_admin(client, db_session):
    """Register a normal user then promote them to admin directly via the
    repository, since there is no public signup path for admins (by
    design). Mirrors test_admin_api.py's helper of the same name."""
    resp = client.post(
        "/api/v1/auth/register", json={"username": "root", "email": "root@example.com", "password": "supersecret1"}
    )
    admin_id = resp.json()["user"]["id"]
    token = resp.json()["token"]["access_token"]

    db_user = db_session.get(UserModel, admin_id)
    db_user.role = "admin"
    db_session.commit()

    return {"Authorization": f"Bearer {token}"}


def test_deleting_a_user_removes_every_dependent_table(client, db_session):
    """#234: SqlAlchemyUserRepository.delete() removed only the `users` row
    itself, leaving every table that references a deleted user — directly,
    or through an owned group/word — pointing at an account that no longer
    exists. Same bug class as the word- and group-level fixes above, one
    level up: silently orphaned on SQLite, a `ForeignKeyViolation` on
    Postgres the moment the account being deleted owns so much as one group.

    Covers both the group/word-reachable tables (already exercised above at
    the group level) and the account-only tables that have no group or word
    to be reached through at all — review sessions, learning paths,
    conversations, recall settings and the rest are seeded directly via the
    ORM here because reaching them through their real endpoints would mean
    mocking an AI provider, which is incidental to this bug.
    """
    admin_headers = _make_admin(client, db_session)
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"},
    )
    user_id = resp.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {resp.json()['token']['access_token']}"}

    group, word, room = _group_with_placed_word(client, headers)
    session = client.post("/api/v1/review/sessions", json={"mode": "standard"}, headers=headers).json()
    client.post(
        f"/api/v1/review/sessions/{session['session_id']}/answers",
        json={"word_id": word["id"], "outcome": "correct", "response_time_ms": 100},
        headers=headers,
    )

    now = datetime.now(timezone.utc)
    path = LearningPathModel(
        user_id=user_id, group_id=group["id"], goal="Order coffee", target_language="Spanish", created_at=now
    )
    db_session.add(path)
    db_session.flush()
    db_session.add(
        PathMilestoneModel(path_id=path.id, position=1, title="Basics", topic="food", target_word_count=10)
    )

    conversation = ConversationSessionModel(
        user_id=user_id, group_id=group["id"], target_language="Spanish", created_at=now
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessageModel(session_id=conversation.id, speaker="learner", text="Hola", created_at=now)
    )
    db_session.add(
        ScenarioAttemptModel(user_id=user_id, session_id=conversation.id, scenario_key="cafe", started_at=now)
    )

    db_session.add(
        ReminderModel(
            user_id=user_id, group_id=group["id"], trigger_time="09:00", recurrence="daily", created_at=now
        )
    )
    db_session.add(RecallSettingsModel(user_id=user_id))
    db_session.add(DailySessionPreferenceModel(user_id=user_id))
    db_session.add(
        WeeklyLearningReportModel(
            user_id=user_id, week_start=now, week_end=now, time_zone="UTC", snapshot={}, created_at=now
        )
    )
    db_session.add(DesktopNotificationModel(user_id=user_id, message="Time to review", created_at=now))
    db_session.add(
        SyncOperationModel(
            user_id=user_id,
            operation_id="op-1",
            entity_type="word",
            operation="update",
            payload={},
            status="applied",
            server_sequence=1,
            created_at=now,
        )
    )
    db_session.commit()

    response = client.delete(f"/api/v1/admin/users/{user_id}", headers=admin_headers)
    assert response.status_code == 204, response.text

    assert db_session.query(UserModel).filter_by(id=user_id).count() == 0
    assert db_session.query(GroupModel).filter_by(owner_id=user_id).count() == 0
    assert db_session.query(WordModel).filter_by(group_id=group["id"]).count() == 0
    assert db_session.query(RoomModel).filter_by(id=room["id"]).count() == 0
    assert db_session.query(RoomPlacementModel).filter_by(room_id=room["id"]).count() == 0
    assert db_session.query(MnemonicNoteModel).filter_by(word_id=word["id"]).count() == 0
    assert db_session.query(PracticeExerciseModel).filter_by(word_id=word["id"]).count() == 0
    assert db_session.query(ReviewAttemptModel).filter_by(word_id=word["id"]).count() == 0
    assert db_session.query(LearningPathModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(PathMilestoneModel).filter_by(path_id=path.id).count() == 0
    assert db_session.query(ConversationSessionModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(ConversationMessageModel).filter_by(session_id=conversation.id).count() == 0
    assert db_session.query(ScenarioAttemptModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(ReminderModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(RecallSettingsModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(DailySessionPreferenceModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(WeeklyLearningReportModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(DesktopNotificationModel).filter_by(user_id=user_id).count() == 0
    assert db_session.query(SyncOperationModel).filter_by(user_id=user_id).count() == 0


def test_deleting_a_user_leaves_another_users_data_alone(client, db_session):
    """The account-deletion cleanup selects by user id (and by the groups it
    owns). A predicate wide enough to be wrong here would take out other
    accounts' vocabulary along with the one being deleted."""
    admin_headers = _make_admin(client, db_session)
    doomed = client.post(
        "/api/v1/auth/register",
        json={"username": "doomed", "email": "doomed@example.com", "password": "supersecret1"},
    ).json()
    doomed_headers = {"Authorization": f"Bearer {doomed['token']['access_token']}"}
    _group_with_placed_word(client, doomed_headers)

    keeper = client.post(
        "/api/v1/auth/register",
        json={"username": "keeper", "email": "keeper@example.com", "password": "supersecret1"},
    ).json()
    keeper_headers = {"Authorization": f"Bearer {keeper['token']['access_token']}"}
    _keeper_group, keeper_word, _keeper_room = _group_with_placed_word(client, keeper_headers)

    resp = client.delete(f"/api/v1/admin/users/{doomed['user']['id']}", headers=admin_headers)
    assert resp.status_code == 204

    assert db_session.query(UserModel).filter_by(id=keeper["user"]["id"]).count() == 1
    assert db_session.query(WordModel).filter_by(id=keeper_word["id"]).count() == 1
    assert client.get(f"/api/v1/words/{keeper_word['id']}", headers=keeper_headers).status_code == 200
