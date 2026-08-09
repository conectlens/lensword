"""Connection reuse in `BackendClient` (issue #347 Bug 1).

`_request` was built on `urllib.request.urlopen`, which supports neither
keep-alive nor pooling: it sends `Connection: close` and tears the socket
down after every call. Because every tool invocation, resource read and
subscription poll funnels through that one method, a bulk import paid a
fresh TCP handshake — and, over HTTPS, a full TLS handshake — before each of
several hundred requests was even transmitted.

These tests assert the property that actually matters and that a latency
measurement could not state without being flaky: **how many connections N
requests open**. They run against a real loopback HTTP server rather than a
mocked socket, because keep-alive is a property of the protocol exchange
(response framing, `Connection` headers, draining the body) and a mock would
happily "reuse" a connection that a real server had already closed.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lensword_cli.backend_client import BackendClient, BackendError


class _CountingHandler(BaseHTTPRequestHandler):
    """Counts connections and requests separately.

    One handler instance is constructed per accepted connection, and it
    loops over `handle_one_request` for as long as the connection stays
    alive — so instances counted in `setup()` are exactly connections, while
    `do_GET`/`do_POST` calls are requests.
    """

    protocol_version = "HTTP/1.1"  # without this, no response is persistent
    connections = 0
    requests = 0
    close_after_each = False
    status = 200
    body: bytes = b'{"ok": true}'

    def setup(self):
        super().setup()
        type(self).connections += 1

    def _respond(self):
        type(self).requests += 1
        cls = type(self)
        self.send_response(cls.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cls.body)))
        if cls.close_after_each:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(cls.body)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *args):  # keep the test output readable
        pass


@pytest.fixture
def server():
    """A fresh loopback server, with the handler's class-level counters
    reset so tests cannot contaminate one another."""
    handler = type("_Handler", (_CountingHandler,), {"connections": 0, "requests": 0})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _client(httpd, **kwargs) -> BackendClient:
    host, port = httpd.server_address[:2]
    return BackendClient(api_url=f"http://{host}:{port}", token="t", workspace="/w", **kwargs)


def test_ten_sequential_requests_open_exactly_one_connection(server):
    """The headline claim of Bug 1. Measured against the previous
    implementation, ten requests produced ten TCP connections."""
    httpd, handler = server
    backend = _client(httpd)

    for _ in range(10):
        assert backend.capabilities() == {"ok": True}

    assert handler.requests == 10
    assert handler.connections == 1
    backend.close()


def test_a_connection_closed_by_the_peer_is_replaced_without_surfacing_an_error(server):
    """A keep-alive connection dropped by an idle timeout on the peer is the
    peer behaving correctly. It must not reach the caller as a
    `BackendError`, which is what a naive persistent client would do on its
    second request."""
    httpd, handler = server
    handler.close_after_each = True
    backend = _client(httpd)

    for _ in range(3):
        assert backend.capabilities() == {"ok": True}

    # One connection per request here, because the *server* insists on
    # closing each one — the point is that the client recovered silently
    # rather than that it reused anything.
    assert handler.requests == 3
    backend.close()


def test_the_backend_error_contract_is_unchanged_for_http_failures(server):
    """Switching transports must not change what a caller catches. The
    status and the parsed `detail` are the whole contract."""
    httpd, handler = server
    handler.status = 404
    handler.body = json.dumps({"detail": "Group not found"}).encode()
    backend = _client(httpd)

    with pytest.raises(BackendError) as excinfo:
        backend.capabilities()

    assert excinfo.value.status == 404
    assert excinfo.value.detail == "Group not found"
    backend.close()


def test_an_error_body_that_is_not_a_json_object_still_names_something_actionable(server):
    """A proxy timeout or an HTML error page lands here too, and every
    branch must still yield a string a caller can act on."""
    httpd, handler = server
    handler.status = 502
    handler.body = b"<html>Bad Gateway</html>"
    backend = _client(httpd)

    with pytest.raises(BackendError) as excinfo:
        backend.capabilities()

    assert excinfo.value.status == 502
    assert "502" in excinfo.value.detail
    backend.close()


def test_a_validation_error_list_still_names_the_offending_field(server):
    httpd, handler = server
    handler.status = 422
    handler.body = json.dumps(
        {"detail": [{"loc": ["body", "group_id"], "msg": "input should be a valid integer"}]}
    ).encode()
    backend = _client(httpd)

    with pytest.raises(BackendError) as excinfo:
        backend.capabilities()

    assert excinfo.value.detail == "group_id: input should be a valid integer"
    backend.close()


def test_an_unreachable_backend_is_still_a_503(server):
    """Transport failure keeps mapping to 503, exactly as the urllib-based
    implementation did."""
    httpd, _ = server
    host, port = httpd.server_address[:2]
    httpd.shutdown()
    httpd.server_close()
    backend = BackendClient(api_url=f"http://{host}:{port}", token="t", workspace="/w")

    with pytest.raises(BackendError) as excinfo:
        backend.capabilities()

    assert excinfo.value.status == 503


def test_a_path_prefix_in_the_api_url_is_preserved(server):
    """`urlopen` took a whole URL; `http.client` takes host and path
    separately, so a backend mounted under a sub-path by a reverse proxy
    would silently lose its prefix if that were not handled explicitly."""
    httpd, handler = server
    seen: list[str] = []
    original = handler._respond

    def _record(self):
        seen.append(self.path)
        return original(self)

    handler.do_GET = _record
    backend = _client(httpd)
    object.__setattr__(backend, "api_url", f"{backend.api_url}/lensword/")

    backend.capabilities()

    assert seen == ["/lensword/api/v1/mcp/capabilities"]
    backend.close()


def test_close_is_safe_on_a_client_that_never_connected():
    BackendClient(api_url="http://127.0.0.1:1", token="t", workspace="/w").close()


def test_close_is_idempotent(server):
    httpd, _ = server
    backend = _client(httpd)
    backend.capabilities()
    backend.close()
    backend.close()


def test_concurrent_callers_share_one_connection_without_interleaving(server):
    """`http_transport.py` serves on a `ThreadingHTTPServer`, so one
    session's client really can be entered from several threads at once. Each
    caller must get its own response, not another thread's."""
    httpd, handler = server
    backend = _client(httpd)
    results: list[object] = []
    errors: list[BaseException] = []

    def _call():
        try:
            results.append(backend.capabilities())
        except BaseException as exc:  # noqa: BLE001 - recorded and re-asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert results == [{"ok": True}] * 8
    assert handler.connections == 1
    backend.close()
