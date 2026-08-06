"""Durable companion session boundaries for issue #193."""


def _enable(client, headers):
    response = client.put(
        "/api/v1/recall-settings",
        json={"ai_companion_enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _start(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={
            "connection_id": "desktop-1",
            "client_id": "host-a",
            "goal": "technical vocabulary",
            "language": "Spanish",
            "consent_snapshot": {"read_profile": True},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_companion_session_is_disabled_by_default(client, auth_headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=auth_headers(),
    )
    assert response.status_code == 403


def test_session_turns_are_normalized_idempotent_and_exportable(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    turn = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "What does deploy mean?", "operation_id": "op-1"},
        headers=headers,
    )
    assert turn.status_code == 201, turn.text
    duplicate = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "different retry payload", "operation_id": "op-1"},
        headers=headers,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["content"] == "What does deploy mean?"

    fetched = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers)
    assert fetched.status_code == 200
    assert len(fetched.json()["turns"]) == 1
    exported = client.get(f"/api/v1/companion/sessions/{session['id']}/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["format"] == "lensword.companion-session.v1"


def test_session_lifecycle_rejects_reopening_finished_sessions(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    paused = client.post(f"/api/v1/companion/sessions/{session['id']}/pause", headers=headers)
    assert paused.status_code == 200
    resumed = client.post(f"/api/v1/companion/sessions/{session['id']}/resume", headers=headers)
    assert resumed.status_code == 200
    finished = client.post(f"/api/v1/companion/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200
    reopened = client.post(f"/api/v1/companion/sessions/{session['id']}/resume", headers=headers)
    assert reopened.status_code == 409


def test_deleting_content_preserves_redacted_session_metadata(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "assistant", "content": "A bounded answer", "operation_id": "op-2"},
        headers=headers,
    )
    deleted = client.delete(f"/api/v1/companion/sessions/{session['id']}/content", headers=headers)
    assert deleted.status_code == 204
    fetched = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers).json()
    assert fetched["turns"] == []
    assert fetched["summary"] == "[content deleted]"
