"""Session TTL enforcement in the Streamable HTTP transport (issue #347 Bug 4).

`session_ttl_seconds` was assigned in `__init__` and never read anywhere in
the package, and `_Session.__slots__` carried no timestamp — so the TTL was
not merely unenforced, it could not be computed. Every `initialize` inserted
a `_Session` holding a whole `MCPServer` and `BackendClient`, and entries
were evicted only by an explicit `DELETE`. Any client that reconnected
without issuing one leaked a session per reconnect for the process lifetime,
while the constructor's own comment promised the opposite.

The clock is monkeypatched rather than slept through: these assert the
eviction *policy*, and a test that waits an hour to prove a one-hour TTL
would never be run.
"""
from __future__ import annotations

import pytest

from lensword_mcp import http_transport
from lensword_mcp.http_transport import StreamableHTTPMCPServer


class FakeBackend:
    def __init__(self):
        self.closed = 0

    def capabilities(self):
        return {"tools": []}

    def invoke(self, name, arguments):
        return {"ok": True}

    def resource(self, uri):
        return {"uri": uri}

    def close(self):
        self.closed += 1


@pytest.fixture()
def clock(monkeypatch):
    now = {"value": 1000.0}
    monkeypatch.setattr(http_transport.time, "monotonic", lambda: now["value"])
    return now


def _transport(ttl: float = 60.0):
    created: list[FakeBackend] = []

    def factory(token):
        backend = FakeBackend()
        created.append(backend)
        return backend

    return StreamableHTTPMCPServer(factory, port=0, session_ttl_seconds=ttl), created


def test_a_session_idle_past_the_ttl_is_evicted(clock):
    transport, _ = _transport(ttl=60.0)
    session_id = transport.open_session("token")
    assert transport.session_count() == 1

    clock["value"] += 61.0

    assert transport.session_for(session_id, "token") is None
    assert transport.session_count() == 0


def test_an_expired_session_is_indistinguishable_from_an_unknown_one(clock):
    """Expiry must not be detectable. Both answer None, which the request
    handler renders as the same `unknown_session_or_token_mismatch` — a
    caller that could tell them apart would learn that a given session id
    once existed."""
    transport, _ = _transport(ttl=60.0)
    session_id = transport.open_session("token")
    clock["value"] += 61.0

    assert transport.session_for(session_id, "token") is None
    assert transport.session_for("never-existed", "token") is None


def test_a_session_in_continuous_use_is_never_evicted(clock):
    """The TTL is idle time since the last authenticated request, not a
    fixed lifetime — an active session must not be dropped mid-conversation."""
    transport, _ = _transport(ttl=60.0)
    session_id = transport.open_session("token")

    for _ in range(10):
        clock["value"] += 59.0
        assert transport.session_for(session_id, "token") is not None

    assert transport.session_count() == 1


def test_eviction_releases_the_sessions_pooled_backend_connection(clock):
    """Bug 1 gave `BackendClient` a persistent socket, so dropping a session
    without closing it would trade a leaked object for a leaked connection."""
    transport, created = _transport(ttl=60.0)
    transport.open_session("token")
    clock["value"] += 61.0

    transport.open_session("other-token")  # any lookup or creation evicts

    assert created[0].closed == 1


def test_an_explicit_delete_also_closes_the_backend_connection():
    transport, created = _transport(ttl=60.0)
    session_id = transport.open_session("token")

    transport.close_session(session_id)

    assert transport.session_count() == 0
    assert created[0].closed == 1


def test_reconnecting_without_a_delete_does_not_leak_a_session_per_reconnect(clock):
    """The leak the issue describes, stated as a test: a client that keeps
    reconnecting and never issues DELETE used to grow `_sessions` without
    bound for the process lifetime."""
    transport, _ = _transport(ttl=60.0)
    for _ in range(50):
        transport.open_session("token")
        clock["value"] += 61.0

    # The final creation evicted all previous ones; only it remains.
    assert transport.session_count() == 1


def test_a_wrong_token_cannot_keep_someone_elses_session_alive(clock):
    """Refreshing `last_seen` before the token check would let anyone
    holding a stolen session id pin it in memory indefinitely without ever
    proving they own it."""
    transport, _ = _transport(ttl=60.0)
    session_id = transport.open_session("token")

    clock["value"] += 59.0
    assert transport.session_for(session_id, "attacker-token") is None
    clock["value"] += 2.0  # 61s since the last *authenticated* request

    assert transport.session_for(session_id, "token") is None


def test_a_non_positive_ttl_disables_eviction(clock):
    transport, _ = _transport(ttl=0.0)
    session_id = transport.open_session("token")

    clock["value"] += 100_000.0

    assert transport.session_for(session_id, "token") is not None
