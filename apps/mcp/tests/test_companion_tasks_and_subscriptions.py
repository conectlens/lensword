"""#197 TODO 1 (resource subscriptions) and TODO 2 (capability-gated task
tools) at the MCP transport layer.

`FakeBackend` here plays the same role `test_server.py`'s `FakeBackend`
does: a stand-in for the real LensWord HTTP API so these tests exercise the
JSON-RPC handling in `lensword_mcp/server.py` without a running backend.
"""
from __future__ import annotations

import io
import itertools
import json

from lensword_cli.backend_client import BackendError
from lensword_mcp.server import MCPServer, StdioMCPServer

_TASK_TOOL_NAMES = (
    "lensword_start_extraction_task",
    "lensword_get_companion_task",
    "lensword_cancel_companion_task",
)


class FakeBackend:
    def __init__(self, due_items=None, session_status="active"):
        self.calls = []
        # Every uri actually fetched, in order. Notification counts alone
        # cannot tell a poll that was cheap from one that issued a request
        # and then threw the payload away, which is precisely the defect
        # issue #347 Bug 2 describes — so these tests assert on both.
        self.resource_calls = []
        self.due_items = due_items if due_items is not None else ["uno", "dos"]
        self.session_status = session_status

    def capabilities(self):
        return {
            "tools": [
                {"name": "lensword_search_words", "input_schema": {"type": "object", "properties": {}}},
                *(
                    {"name": name, "input_schema": {"type": "object", "properties": {}}}
                    for name in _TASK_TOOL_NAMES
                ),
            ]
        }

    def invoke(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "lensword_start_extraction_task":
            return {"id": "task-1", "status": "pending"}
        return {"ok": True}

    def resource(self, uri):
        self.resource_calls.append(uri)
        if uri in ("lensword://me/today", "lensword://me/due"):
            return {"uri": uri, "items": [{"term": term} for term in self.due_items]}
        if uri.startswith("lensword://session/"):
            return {"uri": uri, "status": self.session_status}
        if uri == "lensword://other-user/profile":
            raise BackendError(404, "Resource not found")
        return {"uri": uri, "items": []}


def _initialized(server, *, client_capabilities=None):
    params = {"protocolVersion": "2025-11-25"}
    if client_capabilities is not None:
        params["capabilities"] = client_capabilities
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_initialize_advertises_real_subscription_support():
    server = MCPServer(FakeBackend())
    result = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
    )
    # listChanged stays False: the resource *catalog* is still a fixed set
    # (issue #192 TODO 4) — only per-resource content subscriptions are new.
    assert result["result"]["capabilities"]["resources"] == {"subscribe": True, "listChanged": False}


def test_task_tools_are_hidden_and_refused_without_client_task_capability():
    server = MCPServer(FakeBackend())
    _initialized(server)  # no capabilities.tasks declared

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    # companion_reply/companion_elicit are always appended locally (#195) —
    # unrelated to task capability, so they're present either way.
    assert names == {"lensword_search_words", "lensword_companion_reply", "lensword_companion_elicit"}

    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "lensword_start_extraction_task", "arguments": {}},
        }
    )
    assert called["result"]["isError"] is True
    assert "task capability" in called["result"]["content"][0]["text"]


def test_task_tools_are_exposed_and_callable_with_client_task_capability():
    backend = FakeBackend()
    server = MCPServer(backend)
    _initialized(server, client_capabilities={"tasks": {}})

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "lensword_search_words", "lensword_companion_reply", "lensword_companion_elicit", *_TASK_TOOL_NAMES,
    }

    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "lensword_start_extraction_task", "arguments": {"text": "hola"}},
        }
    )
    assert called["result"]["isError"] is False
    assert backend.calls[0][0] == "lensword_start_extraction_task"


def test_subscribe_rejects_uris_that_do_not_support_it():
    server = MCPServer(FakeBackend())
    _initialized(server)
    result = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": "lensword://me/profile"}}
    )
    assert result["error"]["code"] == -32602


def test_subscribe_and_poll_notifies_only_on_material_change_and_coalesces_bursts():
    backend = FakeBackend(due_items=["uno", "dos"])
    clock = {"now": 0.0}
    server = MCPServer(
        backend, clock=lambda: clock["now"], coalesce_seconds=5.0, min_poll_seconds=5.0
    )
    _initialized(server)

    ack = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": "lensword://me/due"}}
    )
    assert ack["result"] == {}

    # No change yet: nothing to notify.
    clock["now"] = 10.0
    assert server.poll_subscriptions() == []

    # A due-count drop (2 -> 1) is material.
    backend.due_items = ["uno"]
    clock["now"] = 20.0
    first = server.poll_subscriptions()
    assert len(first) == 1
    assert first[0]["method"] == "notifications/resources/updated"
    assert first[0]["params"]["uri"] == "lensword://me/due"
    assert "id" not in first[0]

    # A further change inside the coalescing window is swallowed — and, since
    # #347 moved that guard above the fetch, costs no request either. Before
    # the move the window suppressed only the notification, so the HTTP cost
    # had already been paid by the time it applied.
    backend.due_items = []
    clock["now"] = 21.0
    before = len(backend.resource_calls)
    assert server.poll_subscriptions() == []
    assert len(backend.resource_calls) == before

    # ...but the change is still detected, not lost, once the window elapses.
    clock["now"] = 30.0
    second = server.poll_subscriptions()
    assert len(second) == 1


def test_a_burst_of_messages_cannot_drive_one_fetch_per_message():
    """The minimum poll interval is separate from the notification-coalesce
    window: coalescing bounds how often the host is told, this bounds how
    often the backend is asked. `StdioMCPServer.run` polls after every
    processed message, so without it a rapid burst costs one fetch each."""
    backend = FakeBackend(due_items=["uno", "dos"])
    clock = {"now": 0.0}
    server = MCPServer(
        backend, clock=lambda: clock["now"], coalesce_seconds=5.0, min_poll_seconds=5.0
    )
    _initialized(server)
    server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": "lensword://me/due"}}
    )
    backend.resource_calls.clear()

    # Twenty messages processed within one second of each other.
    for step in range(20):
        clock["now"] = 0.05 * step
        server.poll_subscriptions()

    assert backend.resource_calls == []


def test_today_and_due_are_fetched_once_per_pass_not_twice():
    """Both uris resolve to an identical `lensword_get_due_reviews` call, so
    a host subscribed to both used to issue two byte-for-byte identical
    100-row queries per pass and discard both payloads to keep one integer
    each."""
    backend = FakeBackend(due_items=["uno", "dos"])
    clock = {"now": 0.0}
    server = MCPServer(
        backend, clock=lambda: clock["now"], coalesce_seconds=5.0, min_poll_seconds=5.0
    )
    _initialized(server)
    for uri in ("lensword://me/today", "lensword://me/due"):
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": uri}})
    backend.resource_calls.clear()

    backend.due_items = ["uno"]
    clock["now"] = 10.0
    updates = server.poll_subscriptions()

    # One fetch serving both subscriptions...
    assert len(backend.resource_calls) == 1
    # ...and both subscribers still notified, so deduping the request did not
    # quietly dedupe the notification.
    assert {update["params"]["uri"] for update in updates} == {
        "lensword://me/today",
        "lensword://me/due",
    }


def test_unsubscribe_stops_further_notifications():
    backend = FakeBackend(due_items=["uno", "dos"])
    server = MCPServer(backend)
    _initialized(server)
    server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": "lensword://me/due"}})
    server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/unsubscribe", "params": {"uri": "lensword://me/due"}})

    backend.due_items = []
    assert server.poll_subscriptions() == []


def test_session_subscription_fingerprints_on_status_not_content():
    backend = FakeBackend(session_status="active")
    clock = {"now": 0.0}
    server = MCPServer(backend, clock=lambda: clock["now"])
    _initialized(server)
    server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/subscribe",
            "params": {"uri": "lensword://session/abc123"},
        }
    )
    # The clock is advanced past the minimum poll interval before each poll
    # that is expected to reach the backend at all (#347 Bug 2).
    clock["now"] = 10.0
    assert server.poll_subscriptions() == []
    backend.session_status = "paused"
    clock["now"] = 20.0
    updates = server.poll_subscriptions()
    assert len(updates) == 1
    assert updates[0]["params"]["uri"] == "lensword://session/abc123"


def test_stdio_transport_writes_subscription_notifications_between_responses():
    backend = FakeBackend(due_items=["uno", "dos"])
    # Ten seconds of simulated gap between messages, so each poll pass clears
    # the minimum poll interval — a real host driving this transport sends
    # messages at human cadence, not in a tight loop.
    ticks = itertools.count(0.0, 10.0)
    server = MCPServer(backend, clock=lambda: next(ticks))
    incoming = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "resources/subscribe", "params": {"uri": "lensword://me/due"}}
            ),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
        ]
    ) + "\n"
    output = io.StringIO()

    def _run_and_mutate():
        transport = StdioMCPServer(server, io.StringIO(incoming), output)
        # A change happens between the subscribe call's own baseline read
        # and every read after it, simulating a real gap between client
        # messages: the first resource() call (the subscribe baseline) sees
        # two due items, and every call after that sees one.
        original_resource = backend.resource
        calls = {"count": 0}

        def resource(uri):
            calls["count"] += 1
            if uri == "lensword://me/due" and calls["count"] > 1:
                backend.due_items = ["uno"]
            return original_resource(uri)

        backend.resource = resource
        transport.run()

    _run_and_mutate()
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    updates = [line for line in lines if line.get("method") == "notifications/resources/updated"]
    assert len(updates) >= 1
    assert all("id" not in update for update in updates)
