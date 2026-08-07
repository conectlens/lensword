"""Accept/reject/edit feedback on a tutor correction (issue #194 TODO 3).

`app.domain.services.conversation`'s span-verification and
`MAX_CORRECTIONS_PER_TURN` (issue #135) are untouched by this — what is new
is a real endpoint recording what the *learner* decided about a correction
the tutor offered, as a low-trust telemetry fact, never a mutation of the
message or of any mastery-affecting state.
"""
from __future__ import annotations

from app.domain.services.conversation import CorrectionFeedback, CorrectionOutcome
from app.infrastructure.repositories import SqlAlchemyConversationRepository


def _seed_conversation_with_correction(db_session, user_id):
    repo = SqlAlchemyConversationRepository(db_session)
    session = repo.start(user_id=user_id, target_language="Spanish", difficulty="steady")
    message = repo.add_message(
        session.id, "tutor", "Corriste bien ayer.",
        corrections=[{"original": "corriste", "corrected": "corriste", "explanation": "already correct"}],
    )
    db_session.commit()
    return session.id, message.id


def _owner_id(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def test_accepting_a_correction_records_telemetry_without_mutating_the_message(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(client, headers)
    session_id, message_id = _seed_conversation_with_correction(db_session, owner_id)

    response = client.post(
        f"/api/v1/conversations/{session_id}/messages/{message_id}/corrections/0/feedback",
        json={"outcome": "accepted"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "accepted"
    assert body["message_id"] == message_id
    assert body["correction_index"] == 0

    # The message itself is untouched — this is a new fact, not an edit.
    fetched = client.get(f"/api/v1/conversations/{session_id}", headers=headers).json()
    stored_message = next(m for m in fetched["messages"] if m["id"] == message_id)
    assert stored_message["corrections"][0]["original"] == "corriste"


def test_editing_a_correction_requires_edited_text(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(client, headers)
    session_id, message_id = _seed_conversation_with_correction(db_session, owner_id)

    missing_text = client.post(
        f"/api/v1/conversations/{session_id}/messages/{message_id}/corrections/0/feedback",
        json={"outcome": "edited"},
        headers=headers,
    )
    assert missing_text.status_code == 422, missing_text.text

    with_text = client.post(
        f"/api/v1/conversations/{session_id}/messages/{message_id}/corrections/0/feedback",
        json={"outcome": "edited", "edited_text": "corrí bien ayer"},
        headers=headers,
    )
    assert with_text.status_code == 200, with_text.text
    assert with_text.json()["edited_text"] == "corrí bien ayer"


def test_feedback_on_an_out_of_range_correction_index_is_not_found(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(client, headers)
    session_id, message_id = _seed_conversation_with_correction(db_session, owner_id)

    response = client.post(
        f"/api/v1/conversations/{session_id}/messages/{message_id}/corrections/5/feedback",
        json={"outcome": "rejected"},
        headers=headers,
    )
    assert response.status_code == 404


def test_correction_feedback_domain_model_rejects_mismatched_edited_text():
    try:
        CorrectionFeedback(message_id=1, user_id=1, correction_index=0, outcome=CorrectionOutcome.ACCEPTED, edited_text="not allowed")
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        CorrectionFeedback(message_id=1, user_id=1, correction_index=0, outcome=CorrectionOutcome.EDITED, edited_text=None)
        assert False, "expected ValueError"
    except ValueError:
        pass
