"""Issue #199 TODO 1: provider-neutral, deterministic session export/import.

#193 already built `GET /{session_id}/export` and `DELETE /{session_id}/content`;
test_companion_sessions.py checks each exists and returns the right shape.
Neither file proves the two things #199's success metrics ask for by name:

1. Round-trip fidelity — everything a second client would need to
   reconstruct where a session left off (turns, order, content, status,
   revision, consent) survives the export unchanged, not just "the response
   is 200."
2. No provider-specific field leaks in — the exported shape is closed
   (`CompanionExportResponse`/`CompanionSessionResponse`/
   `CompanionTurnResponse` are fixed Pydantic models with a bounded field
   set; nothing here is a raw ORM dump), so a future field added for one MCP
   host or one AI provider's own bookkeeping cannot silently ride along
   inside `session.export()` output without this test's field-set assertion
   catching it.
"""
from __future__ import annotations


def _enable(client, headers):
    assert client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers).status_code == 200


def _start(client, headers, **overrides):
    body = {"connection_id": "export-conn", "client_id": "export-host", "goal": "order food", "language": "Spanish"}
    body.update(overrides)
    response = client.post("/api/v1/companion/sessions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


_ALLOWED_SESSION_FIELDS = {
    "id", "connection_id", "client_id", "goal", "language", "group_id", "difficulty",
    "active_activity", "consent_snapshot", "summary", "status", "revision",
    "created_at", "updated_at", "turns",
}
_ALLOWED_TURN_FIELDS = {"id", "session_id", "role", "content", "activity_id", "operation_id", "created_at"}


def test_export_is_a_closed_provider_neutral_shape(client, auth_headers):
    """No raw model name, host bearer token, sampling provenance, or
    internal-only bookkeeping field is present anywhere in the export — only
    the fixed, documented session/turn shape. A field appearing here that
    isn't in the allow-list is exactly the kind of leak this test exists to
    catch before it ships."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "Quisiera pedir comida", "operation_id": "op-1"},
        headers=headers,
    )

    exported = client.get(f"/api/v1/companion/sessions/{session['id']}/export", headers=headers)
    assert exported.status_code == 200
    body = exported.json()
    assert set(body.keys()) == {"session", "format"}
    assert body["format"] == "lensword.companion-session.v1"
    assert set(body["session"].keys()) == _ALLOWED_SESSION_FIELDS
    for turn in body["session"]["turns"]:
        assert set(turn.keys()) == _ALLOWED_TURN_FIELDS


def test_export_round_trips_every_turn_in_order_with_full_fidelity(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers, goal="practice ordering food", language="Spanish", difficulty="beginner")

    turns = [
        ("user", "Hola, quisiera pedir comida", "op-1"),
        ("assistant", "Claro, que le gustaria?", "op-2"),
        ("user", "Una hamburguesa, por favor", "op-3"),
    ]
    for role, content, operation_id in turns:
        response = client.post(
            f"/api/v1/companion/sessions/{session['id']}/turns",
            json={"role": role, "content": content, "operation_id": operation_id},
            headers=headers,
        )
        assert response.status_code == 201, response.text

    exported = client.get(f"/api/v1/companion/sessions/{session['id']}/export", headers=headers).json()
    live = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers).json()

    # The export is not a second, possibly-stale store - it is the same
    # session the live GET returns, field for field.
    assert exported["session"] == live

    exported_turns = exported["session"]["turns"]
    assert len(exported_turns) == len(turns)
    assert [(t["role"], t["content"], t["operation_id"]) for t in exported_turns] == turns
    # Order is preserved (ascending by creation), not merely "all present."
    assert [t["id"] for t in exported_turns] == sorted(t["id"] for t in exported_turns)
    # Session-level facts a second client needs to resume correctly.
    assert exported["session"]["goal"] == "practice ordering food"
    assert exported["session"]["language"] == "Spanish"
    assert exported["session"]["difficulty"] == "beginner"
    assert exported["session"]["status"] == "active"


def test_delete_content_removes_turns_but_the_session_stays_exportable_for_audit(client, auth_headers):
    """#193 TODO 4's provider-neutral export must keep working after a
    content deletion (privacy request) - the session's own existence,
    status and revision history remain visible for audit even once the
    conversational content itself is gone."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "sensitive content", "operation_id": "op-1"},
        headers=headers,
    )
    revision_before_delete = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers).json()["revision"]

    deleted = client.delete(f"/api/v1/companion/sessions/{session['id']}/content", headers=headers)
    assert deleted.status_code == 204

    exported = client.get(f"/api/v1/companion/sessions/{session['id']}/export", headers=headers)
    assert exported.status_code == 200
    body = exported.json()["session"]
    assert body["turns"] == []
    assert "sensitive content" not in str(body)
    assert body["summary"] == "[content deleted]"
    assert body["revision"] > revision_before_delete
    # The shape is still the same closed, provider-neutral contract - a
    # deletion does not open the door to a different, looser export format.
    assert set(body.keys()) == _ALLOWED_SESSION_FIELDS
