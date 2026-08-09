import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from lensword_mcp.http_transport import MAX_HTTP_BODY_BYTES, SESSION_ID_HEADER, StreamableHTTPMCPServer


class FakeBackend:
    def capabilities(self):
        return {"tools": [{"name": "lensword_search_words", "input_schema": {"type": "object", "properties": {}}}]}

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
    assert json.loads(body)["result"]["tools"][0]["name"] == "lensword_search_words"


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
    """The body must be refused, and the server must survive refusing it.

    The handler deliberately does *not* read an oversized body before
    answering — draining attacker-controlled bytes would defeat the limit —
    so it sends 413 and closes the connection immediately. Whether the client
    manages to read that 413 or has its own write fail first is a
    socket-buffer race the operating system decides: on Linux a megabyte
    usually fits in the send buffer and the response comes back, while on
    macOS the close lands mid-write and urllib raises instead. Asserting on
    only one of those made this test pass or fail by platform.

    Both outcomes mean the same thing — the body was refused. What must never
    happen is it being accepted, and what the follow-up request rules out is
    the server having fallen over rather than rejected cleanly.
    """
    _transport, url = running_server
    oversized = b"{" + b'"padding": "' + b"x" * (MAX_HTTP_BODY_BYTES + 1) + b'"}'

    try:
        status, _, _ = _post(
            url, None,
            headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
            raw_body=oversized,
        )
    except urllib.error.URLError:
        status = None
    assert status in (413, None)

    healthy, _, body = _initialize(url)
    assert healthy == 200
    assert body["result"]["protocolVersion"]


def test_a_post_to_the_wrong_path_does_not_corrupt_the_next_request_on_the_same_connection(running_server):
    """Real production incident: a client POSTing OAuth dynamic-client-
    registration to this server's root path (not /mcp) got a 404, but the
    request body was never drained off the socket before answering. On the
    HTTP/1.1 keep-alive connection, those unread bytes corrupted the next
    request's own request line, producing a garbled method string and a
    bizarre stdlib 501 instead of a clean response to either request."""
    transport, url = running_server
    body = json.dumps({"redirect_uris": ["https://example.com/callback"], "client_name": "Example"}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", transport.port, timeout=5)
    try:
        conn.request("POST", "/", body=body, headers={"Content-Type": "application/json"})
        first = conn.getresponse()
        assert first.status == 404
        first.read()

        # The same connection, reused: if the first request's body wasn't
        # fully drained, this request line arrives corrupted.
        conn.request("GET", "/.well-known/oauth-protected-resource")
        second = conn.getresponse()
        assert second.status in (404, 200)  # never a stdlib 501/400 from a garbled request line
        second.read()
    finally:
        conn.close()


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


# -- OAuth discovery (RFC 9728) — this server is the *resource*, the
# backend named by oauth_issuer is the *authorization server*. -------------


@pytest.fixture()
def running_server_with_oauth():
    transport = StreamableHTTPMCPServer(
        lambda token: FakeBackend(),
        host="127.0.0.1",
        port=0,
        allowed_origins=frozenset({"https://allowed.example"}),
        oauth_issuer="https://backend.example",
    )
    port = transport.bind()
    thread = threading.Thread(target=transport.serve_forever, daemon=True)
    thread.start()
    try:
        yield transport, f"http://127.0.0.1:{port}"
    finally:
        transport.shutdown()
        thread.join(timeout=5)


def _get(url, *, headers=None):
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), (response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_protected_resource_metadata_names_the_backend_as_the_authorization_server(running_server_with_oauth):
    _transport, base = running_server_with_oauth
    status, headers, body = _get(f"{base}/.well-known/oauth-protected-resource")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body)
    assert payload["authorization_servers"] == ["https://backend.example"]
    assert payload["resource"] == base


def test_protected_resource_metadata_is_404_when_oauth_issuer_not_configured(running_server):
    """The default (issue #196's existing behavior, unchanged): an operator
    who hasn't set an issuer gets no discovery metadata at all, not a
    metadata document pointing nowhere useful."""
    _transport, url = running_server
    base = url.removesuffix("/mcp")
    status, _, _ = _get(f"{base}/.well-known/oauth-protected-resource")
    assert status == 404


def test_401_carries_a_www_authenticate_challenge_when_oauth_issuer_is_configured(running_server_with_oauth):
    _transport, base = running_server_with_oauth
    status, headers, _ = _post(f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers={"Content-Type": "application/json"})
    assert status == 401
    assert headers["WWW-Authenticate"] == f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'


def test_401_has_no_www_authenticate_header_when_oauth_issuer_not_configured(running_server):
    """Matches this test file's pre-existing test_missing_bearer_token_is_rejected
    — restated here specifically to pin the *absence* of the new header
    when nothing asked for it, so this transport's default (unconfigured)
    behavior provably didn't change."""
    _transport, url = running_server
    status, headers, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers={"Content-Type": "application/json"})
    assert status == 401
    assert "WWW-Authenticate" not in headers
