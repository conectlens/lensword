"""Issue #199 TODO 2: audit-chain tampering must actually be detectable.

`redact_and_chain` (app/domain/services/mcp_policy.py) has produced a
tamper-evident hash chain since #196, and test_mcp_security.py already
proves two consecutive events link (`audits[1].previous_hash ==
audits[0].event_hash`). Neither file ever recomputes the chain and confirms
a mutated row is actually caught — a hash chain nothing ever re-verifies is
only tamper-*shaped*, not tamper-*evident*. This file adds the verification
half: `verify_chain` (added alongside this test) recomputes every link from
its stored `(previous_hash, event, event_hash)` and reports the first one
that no longer matches, then this test proves that report fires when a
stored event row is mutated directly (the same threat model as an attacker
or a buggy migration touching the audit table outside the normal
`_audit()`-append-only path in app/api/routers/mcp.py).
"""
from __future__ import annotations

import uuid

from app.domain.services.mcp_policy import verify_chain
from app.infrastructure.models import MCPAuditEventModel, MCPGrantModel


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _grant(db_session, *, requester, tool="lensword.search_words"):
    item = MCPGrantModel(requester=requester, server="lensword", tool=tool, access="read", workspace="/approved", mode="always")
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, *, tool="lensword.search_words", payload=None):
    body = {"query": "hola"} if payload is None else payload
    return client.post("/api/v1/mcp/invoke", headers=headers, json={"workspace": "/approved", "tool": tool, "payload": body})


def _links(db_session) -> list[tuple[str, dict, str]]:
    events = db_session.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id).all()
    return [(event.previous_hash, event.event, event.event_hash) for event in events]


def test_an_untampered_chain_verifies_clean(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, requester=f"user:{_user_id(client, headers)}")
    for _ in range(4):
        assert _invoke(client, headers).status_code == 200

    assert verify_chain(_links(db_session)) is None


def test_mutating_a_stored_audit_event_is_detected_and_localized(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, requester=f"user:{_user_id(client, headers)}")
    for _ in range(4):
        assert _invoke(client, headers).status_code == 200
    assert verify_chain(_links(db_session)) is None  # sanity: clean before tampering

    events = db_session.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id).all()
    assert len(events) == 4
    tampered_index = 2
    # Mutate a stored field on the third event in place - the same shape of
    # attack a direct database edit would take, distinct from ever calling
    # `_audit()`/`redact_and_chain` again (which would produce a self-
    # consistent but differently-valued row, not what a tamper attempt is).
    mutated = dict(events[tampered_index].event)
    mutated["payload_bytes"] = (mutated.get("payload_bytes") or 0) + 999_999
    events[tampered_index].event = mutated
    db_session.flush()

    broken_at = verify_chain(_links(db_session))
    assert broken_at == tampered_index


def test_forging_a_plausible_but_wrong_event_hash_is_also_detected(client, auth_headers, db_session):
    headers = auth_headers()
    _grant(db_session, requester=f"user:{_user_id(client, headers)}")
    for _ in range(3):
        assert _invoke(client, headers).status_code == 200

    events = db_session.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id).all()
    # A forged hash that is well-formed (64 lowercase hex characters, same as
    # a real sha256 digest) but was never actually produced by
    # `redact_and_chain` over this link's own previous_hash/event.
    events[1].event_hash = uuid.uuid4().hex + uuid.uuid4().hex
    db_session.flush()

    assert verify_chain(_links(db_session)) == 1
