import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from lensword_mcp.http_transport import MAX_HTTP_BODY_BYTES, SESSION_ID_HEADER, StreamableHTTPMCPServer


class FakeBackend:
    def capabilities(self):
        return {"tools": [{"name": "lensword.search_words", "input_schema": {"type": "object", "properties": {}}}]}

    def invoke(self, name, arguments):
        return {"ok": True}

    def resource(self, uri):
        return {"uri": uri}


@pytest.fixture()
def running_server():
    transport = StreamableHTTPMCPServer(lambda token: FakeBackend(), host="127.0.0.1", port=0, allowed_origins=frozenset({"https://allowed.example"}))
    port = transport.bind()
    thread = threading.Thread(target=transport.serve_forever, daemon=True)
    thread.start()
    try:
        yield transport, f"http://127.0.0.1:{port}/mcp"
    finally:
        transport.shutdown()
        thread.join(timeout=5)


def _post(url, body, *, headers=None, raw_body=None):
    data = raw_body if raw_body is not None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), (response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _initialize(url, *, token="user-token"):
    status, headers, body = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    return status, headers, json.loads(body)


def test_initialize_issues_a_session_id_and_tools_list_requires_it(running_server):
    _transport, url = running_server
    status, headers, payload = _initialize(url)
    assert status == 200
    assert payload["result"]["protocolVersion"] == "2025-11-25"
    session_id = headers[SESSION_ID_HEADER]
    assert session_id

    # A real client sends this notification (no "id") before any other
    # method; MCPServer.handle requires it before tools/list etc.
    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": "Bearer user-token", "Content-Type": "application/json", SESSION_ID_HEADER: session_id},
    )
    assert status == 202

    status, _, body = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Authorization": "Bearer user-token", "Content-Type": "application/json", SESSION_ID_HEADER: session_id},
    )
    assert status == 200
    assert json.loads(body)["result"]["tools"][0]["name"] == "lensword.search_words"


def test_missing_or_unknown_session_id_is_rejected(running_server):
    _transport, url = running_server
    status, _, _ = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers={"Authorization": "Bearer t", "Content-Type": "application/json"})
    assert status == 400

    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Authorization": "Bearer t", "Content-Type": "application/json", SESSION_ID_HEADER: "not-a-real-session"},
    )
    assert status == 404


def test_missing_bearer_token_is_rejected(running_server):
    _transport, url = running_server
    status, _, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}, headers={"Content-Type": "application/json"})
    assert status == 401


def test_a_session_bound_to_one_token_rejects_a_substituted_token(running_server):
    """Token-substitution protection (issue #196 TODO 4): a session id
    stolen and replayed with a different bearer token must not be honored,
    even though the session id itself is valid."""
    _transport, url = running_server
    _, headers, _ = _initialize(url, token="alice-token")
    session_id = headers[SESSION_ID_HEADER]

    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Authorization": "Bearer mallory-token", "Content-Type": "application/json", SESSION_ID_HEADER: session_id},
    )
    assert status == 404

    # The legitimate token still works.
    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Authorization": "Bearer alice-token", "Content-Type": "application/json", SESSION_ID_HEADER: session_id},
    )
    assert status == 200


def test_origin_allowlist_blocks_disallowed_browser_origins_but_allows_no_origin(running_server):
    _transport, url = running_server
    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        headers={"Authorization": "Bearer t", "Content-Type": "application/json", "Origin": "https://evil.example"},
    )
    assert status == 403

    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        headers={"Authorization": "Bearer t", "Content-Type": "application/json", "Origin": "https://allowed.example"},
    )
    assert status == 200


def test_oversized_request_body_is_rejected(running_server):
    _transport, url = running_server
    oversized = b"{" + b'"padding": "' + b"x" * (MAX_HTTP_BODY_BYTES + 1) + b'"}'
    status, _, _ = _post(url, None, headers={"Authorization": "Bearer t", "Content-Type": "application/json"}, raw_body=oversized)
    assert status == 413


def test_get_returns_405_since_sse_streaming_is_not_implemented(running_server):
    _transport, url = running_server
    request = urllib.request.Request(url, method="GET", headers={"Authorization": "Bearer t"})
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 405


def test_delete_closes_the_session(running_server):
    transport, url = running_server
    _, headers, _ = _initialize(url)
    session_id = headers[SESSION_ID_HEADER]
    assert transport.session_count() == 1

    request = urllib.request.Request(url, method="DELETE", headers={SESSION_ID_HEADER: session_id})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 204
    assert transport.session_count() == 0

    status, _, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Authorization": "Bearer user-token", "Content-Type": "application/json", SESSION_ID_HEADER: session_id},
    )
    assert status == 404
