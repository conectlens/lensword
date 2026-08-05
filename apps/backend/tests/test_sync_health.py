"""Sync observability, quarantine and redaction (issue #91).

The issue's verification names three things: a forced permanent failure does
not block later valid mutations, users can export pending changes, and
diagnostics identify operation ids and error classes without leaking tokens or
captured text. The first and third are decided here; the export is an endpoint
over the same data.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.services.sync_health import (
    BASE_BACKOFF,
    MAX_ATTEMPTS,
    MAX_BACKOFF,
    ConnectivityMode,
    SyncErrorClass,
    SyncHealth,
    backoff_for,
    redact,
    should_quarantine,
)


def _health(**overrides) -> SyncHealth:
    fields = dict(
        last_synced_at=datetime(2026, 8, 2, 9, 0),
        pending_count=0,
        conflict_count=0,
        quarantined_count=0,
        connectivity=ConnectivityMode.ONLINE,
    )
    fields.update(overrides)
    return SyncHealth(**fields)


# --- Quarantine: the property the issue names ------------------------------


def test_a_permanently_failing_operation_is_eventually_set_aside():
    """Without this, one poison operation at the head of the queue blocks every
    later one forever and the only recourse is a reinstall."""
    assert should_quarantine(MAX_ATTEMPTS, SyncErrorClass.SERVER) is True


def test_a_transient_failure_keeps_being_retried():
    assert should_quarantine(MAX_ATTEMPTS - 1, SyncErrorClass.NETWORK) is False


def test_a_malformed_payload_is_quarantined_immediately():
    """It will be just as malformed on the ninth attempt. Retrying only delays
    the point at which someone is told."""
    assert should_quarantine(1, SyncErrorClass.VALIDATION) is True


def test_a_conflict_is_never_quarantined():
    """A conflict is not a failure. It already has a resolution path (#90) and
    is counted separately."""
    assert should_quarantine(MAX_ATTEMPTS * 3, SyncErrorClass.CONFLICT) is False


@pytest.mark.parametrize(
    "error_class",
    [SyncErrorClass.NETWORK, SyncErrorClass.AUTHENTICATION, SyncErrorClass.SERVER],
)
def test_recoverable_classes_get_their_full_allowance(error_class):
    """Networks and tokens recover; quarantining them early would strand work
    that would have succeeded."""
    assert should_quarantine(MAX_ATTEMPTS - 1, error_class) is False
    assert should_quarantine(MAX_ATTEMPTS, error_class) is True


# --- Backoff ---------------------------------------------------------------


def test_backoff_grows_with_each_attempt():
    assert backoff_for(2) > backoff_for(1)


def test_the_first_attempt_is_immediate():
    assert backoff_for(0) == timedelta(0)


def test_backoff_is_capped():
    """Uncapped exponential backoff reaches implausible delays in a handful of
    failures, and a client that will next try in four hours is
    indistinguishable from one that has given up."""
    assert backoff_for(50) == MAX_BACKOFF


def test_the_first_retry_is_soon_enough_to_be_useful():
    assert backoff_for(1) == BASE_BACKOFF


# --- What the status screen says -------------------------------------------


def test_pending_work_alone_is_not_a_problem():
    """That is sync working. Flagging it would train people to ignore the
    indicator."""
    assert _health(pending_count=40).needs_attention is False


def test_conflicts_draw_attention():
    assert _health(conflict_count=1).needs_attention is True


def test_quarantined_operations_draw_attention():
    """Neither resolves without a person, which is exactly what an indicator is
    for."""
    assert _health(quarantined_count=1).needs_attention is True


def test_a_clean_state_is_quiet():
    assert _health().needs_attention is False


def test_degraded_is_distinct_from_offline():
    """Reachable but refusing work — a deploy, a rate limit, an expired token.
    The remedies differ, so collapsing them would misdirect the user."""
    assert ConnectivityMode.DEGRADED != ConnectivityMode.OFFLINE


# --- Redaction -------------------------------------------------------------


def test_vocabulary_never_reaches_a_diagnostic():
    redacted = redact({"term": "gato", "translations": ["cat", "tomcat"]})

    assert "gato" not in str(redacted)
    assert "cat" not in str(redacted)


def test_secrets_are_replaced_outright():
    redacted = redact({"token": "eyJhbGciOi", "password": "hunter2"})

    assert redacted == {"token": "[secret]", "password": "[secret]"}


def test_shape_survives_so_a_malformed_payload_is_still_diagnosable():
    """"This operation had a term and three translations" is useful; the values
    are not."""
    redacted = redact({"term": "gato", "translations": ["a", "b", "c"]})

    assert redacted["translations"] == "[3 redacted item(s)]"
    assert "4 chars" in redacted["term"]


def test_nesting_does_not_leak():
    """A payload one level deeper is the obvious way for this to fail."""
    redacted = redact({"word": {"definition": "a small cat", "meta": {"token": "abc"}}})

    assert "small cat" not in str(redacted)
    assert "abc" not in str(redacted)


def test_lists_of_objects_are_walked():
    redacted = redact({"records": [{"term": "gato"}, {"term": "perro"}]})

    assert "gato" not in str(redacted) and "perro" not in str(redacted)


def test_operational_fields_survive_because_support_needs_them():
    """The bundle exists to identify which operation failed and why."""
    redacted = redact(
        {"operation_id": "op-42", "entity_type": "word", "attempts": 3, "term": "gato"}
    )

    assert redacted["operation_id"] == "op-42"
    assert redacted["entity_type"] == "word"
    assert redacted["attempts"] == 3


def test_key_matching_is_case_insensitive():
    """A client sending `Token` rather than `token` must not slip through."""
    assert redact({"Token": "abc", "TERM": "gato"}) == {
        "Token": "[secret]",
        "TERM": "[redacted 4 chars]",
    }


# --- The API ---------------------------------------------------------------
#
# These endpoints take no resource identifier, so the tenant-isolation audit
# does not cover them. Scoping is asserted here instead.


def _seed(client, db_session, headers, **overrides):
    from app.infrastructure.repositories import SqlAlchemySyncOperationRepository

    me = client.get("/api/v1/auth/me", headers=headers).json()
    fields = dict(
        user_id=me["id"],
        operation_id="op-1",
        entity_type="word",
        entity_id=1,
        operation="update",
        payload={"term": "gato", "token": "secret-value"},
        base_revision=1,
        status="pending",
        conflict_reason=None,
    )
    fields.update(overrides)
    stored = SqlAlchemySyncOperationRepository(db_session).record(**fields)
    db_session.commit()
    return me["id"], stored


def test_health_reports_counts_and_whether_to_worry(client, auth_headers, db_session):
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="a", status="pending")
    _seed(client, db_session, headers, operation_id="b", status="conflict")

    body = client.get("/api/v1/sync/health", headers=headers).json()

    assert body["pending_count"] == 1
    assert body["conflict_count"] == 1
    assert body["needs_attention"] is True


def test_health_reports_the_connectivity_the_client_states(client, auth_headers):
    headers = auth_headers()

    body = client.get("/api/v1/sync/health?connectivity=offline", headers=headers).json()

    assert body["connectivity"] == "offline"


def test_health_shows_no_last_sync_before_anything_has_synced(client, auth_headers):
    body = client.get("/api/v1/sync/health", headers=auth_headers()).json()

    assert body["last_synced_at"] is None


def test_export_returns_the_users_own_payloads_intact(client, auth_headers, db_session):
    """Not redacted: this is their work being handed back, and a redacted
    export would be worthless for recovering it."""
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="a", status="pending")

    body = client.get("/api/v1/sync/export", headers=headers).json()

    assert body["operations"][0]["payload"]["term"] == "gato"


def test_export_covers_conflicted_and_quarantined_work_too(client, auth_headers, db_session):
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="a", status="conflict")
    _seed(client, db_session, headers, operation_id="b", status="quarantined")

    body = client.get("/api/v1/sync/export", headers=headers).json()

    assert {o["operation_id"] for o in body["operations"]} == {"a", "b"}


def test_applied_work_is_not_exported(client, auth_headers, db_session):
    """It is already on the server. Including it would make the export a full
    database dump rather than the thing at risk."""
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="done", status="applied")

    assert client.get("/api/v1/sync/export", headers=headers).json()["operations"] == []


def test_the_diagnostic_bundle_leaks_neither_content_nor_credentials(
    client, auth_headers, db_session
):
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="a", status="conflict")

    raw = client.get("/api/v1/sync/diagnostics", headers=headers).text

    assert "gato" not in raw
    assert "secret-value" not in raw


def test_the_bundle_still_identifies_the_operation_and_why_it_failed(
    client, auth_headers, db_session
):
    """Which is the whole point — a bundle that says nothing is not safer, it
    is just useless."""
    headers = auth_headers()
    _seed(client, db_session, headers, operation_id="op-42", status="quarantined")

    entry = client.get("/api/v1/sync/diagnostics", headers=headers).json()["entries"][0]

    assert entry["operation_id"] == "op-42"
    assert entry["entity_type"] == "word"
    assert entry["status"] == "quarantined"


def test_the_bundle_says_what_it_redacts(client, auth_headers):
    """Stated in the bundle so a recipient knows what it contains without
    having to trust the sender."""
    body = client.get("/api/v1/sync/diagnostics", headers=auth_headers()).json()

    assert "credentials are removed" in body["redaction_note"]


def test_one_account_sees_nothing_of_anothers_sync_state(client, auth_headers, db_session):
    alex = auth_headers()
    sam = auth_headers(username="sam", email="sam@example.com")
    _seed(client, db_session, sam, operation_id="theirs", status="conflict")

    assert client.get("/api/v1/sync/health", headers=alex).json()["conflict_count"] == 0
    assert client.get("/api/v1/sync/export", headers=alex).json()["operations"] == []
    assert client.get("/api/v1/sync/diagnostics", headers=alex).json()["entries"] == []


def test_every_sync_endpoint_requires_authentication(client):
    for path in ("/api/v1/sync/health", "/api/v1/sync/export", "/api/v1/sync/diagnostics"):
        assert client.get(path).status_code == 401, path
