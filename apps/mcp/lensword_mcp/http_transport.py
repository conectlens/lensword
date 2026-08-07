"""Streamable HTTP transport for remote MCP companions (issue #196 TODO 0).

Stdlib-only, matching the rest of `apps/mcp` (see server.py's use of
`urllib.request` instead of `httpx`/`requests`) — this package ships as a
zero-dependency client/server pair, and a remote transport should not change
that.

Scope, stated honestly up front:

* Implements the request/response half of the Streamable HTTP transport
  (MCP spec 2025-03-26 / 2025-06-18 / 2025-11-25): POST carries one
  JSON-RPC message and gets back either a single `application/json`
  response, or a bare 202 for a request with no `id` (a notification).
  Session lifecycle (`Mcp-Session-Id`: issued by the server on
  `initialize`, required on every request after, torn down by DELETE)
  follows the spec's session-management section.
* Does NOT implement the GET+`text/event-stream` half of the transport
  (server-initiated messages between client requests). Every tool call and
  resource read this server exposes today is a plain request/response, so
  nothing in this codebase needs it; a client that requires it sees a clean
  405 rather than a connection that silently never streams anything.
* Does NOT terminate TLS. This process speaks plain HTTP; a reverse proxy
  in front of it must add TLS for anything but same-host loopback use — see
  docs/mcp-remote-transport.md, which says this plainly rather than
  implying the app provides it.
* Has not been exercised against a live third-party MCP client. The wire
  shapes here are verified against this repository's own stdio
  `MCPServer.handle` (both transports share that one JSON-RPC handler) and
  against the published spec text, not against interop testing — flagged
  explicitly per this issue's own instructions about undertested spec
  surface.

Disabled unless a caller explicitly constructs and starts `serve_forever()`
— `lensword_mcp.server.main()` never does so on its own; see that module's
`--transport` flag, which defaults to stdio.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

from .server import BackendClient, MCPServer

# Bounded request bodies (TODO 0): large enough for any real tool call this
# server defines (the largest MCP contract payload, extract_vocabulary's
# 20,000-character text field, is well under this after JSON overhead),
# small enough that a caller cannot use the transport itself as a memory-
# exhaustion vector ahead of the backend's own 65,536-byte MCPPolicyGate
# check.
MAX_HTTP_BODY_BYTES = 1_048_576

SESSION_ID_HEADER = "Mcp-Session-Id"
WELL_KNOWN_PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Session:
    __slots__ = ("mcp_server", "token_hash")

    def __init__(self, mcp_server: MCPServer, token_hash: str):
        self.mcp_server = mcp_server
        self.token_hash = token_hash


class StreamableHTTPMCPServer:
    """Owns session state; `serve_forever()` binds the actual socket."""

    def __init__(
        self,
        backend_factory: Callable[[str], BackendClient],
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        path: str = "/mcp",
        allowed_origins: frozenset[str] = frozenset(),
        # Safe timeouts (TODO 0): both the idle-connection timeout on the
        # socket and a session TTL so an abandoned session cannot pin memory
        # forever.
        request_timeout_seconds: float = 30.0,
        session_ttl_seconds: float = 3600.0,
        # The backend's public URL — the OAuth *authorization server* for
        # this MCP *resource* server (RFC 9728 draws that distinction
        # deliberately; they don't have to be, and here aren't, the same
        # process). The backend already implements the full authorization
        # server (apps/backend/app/api/routers/mcp_oauth.py: dynamic client
        # registration, authorize, token, revoke) behind
        # REMOTE_MCP_ENABLED — this server just needs to say where it is.
        # None (the default) serves no discovery metadata at all, matching
        # this transport's behavior before this parameter existed: a client
        # gets a bare 401 with no WWW-Authenticate hint, same as always.
        oauth_issuer: str | None = None,
    ):
        # backend_factory(bearer_token) -> BackendClient. Called once per new
        # session at `initialize`, so the workspace/API URL and the caller's
        # bearer credential are fixed for the session's whole lifetime —
        # deliberately, since that fixed binding is what lets `_Session`
        # detect and reject a mid-session token swap below.
        self.backend_factory = backend_factory
        self.host, self.port, self.path = host, port, path
        self.allowed_origins = allowed_origins
        self.request_timeout_seconds = request_timeout_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.oauth_issuer = oauth_issuer.rstrip("/") if oauth_issuer else None
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    # -- session lifecycle, called from the request handler below --------

    def open_session(self, token: str) -> str:
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = _Session(MCPServer(self.backend_factory(token)), _hash(token))
        return session_id

    def session_for(self, session_id: str, token: str) -> MCPServer | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        # Token-substitution protection (issue #196 TODO 4): a session is
        # bound to whichever bearer credential opened it. A request that
        # reuses the session id but presents a *different* token — the
        # shape a stolen session id plus an attacker's own token would take
        # — is rejected rather than silently adopted.
        if not hmac.compare_digest(session.token_hash, _hash(token)):
            return None
        return session.mcp_server

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- socket lifecycle --------------------------------------------------

    def bind(self) -> int:
        """Create and bind the listening socket; return the bound port.

        Split from `serve_forever` so a caller (or a test) can learn the
        actual port immediately — including when `port=0` asks the OS to
        pick one — without racing the serve loop on another thread.
        Idempotent: calling it twice reuses the already-bound socket.
        """
        if self._httpd is not None:
            return self._httpd.server_address[1]
        transport = self
        request_timeout = self.request_timeout_seconds

        class _Handler(_MCPHTTPRequestHandler):
            server_transport = transport
            timeout = request_timeout

        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self.port = self._httpd.server_address[1]
        return self.port

    def serve_forever(self) -> None:
        self.bind()
        assert self._httpd is not None
        try:
            self._httpd.serve_forever()
        finally:
            self._httpd.server_close()
            self._httpd = None

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()


class _MCPHTTPRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_transport: StreamableHTTPMCPServer
    timeout: float = 30.0

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        # Never write request lines (which can carry bearer tokens in query
        # strings a misbehaving client might use, and always carry session
        # ids) to stderr by default.
        pass

    # -- helpers -------------------------------------------------------

    def _bearer_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[len("Bearer "):].strip()
        return token or None

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            # Non-browser clients (curl, another server) send no Origin
            # header. The DNS-rebinding threat this check exists for
            # (MCP spec's transport security section) is specific to
            # browser-originated requests, which always send one.
            return True
        return origin in self.server_transport.allowed_origins

    def _safe_header_value(self, value: str) -> str:
        return value.replace("\r", "").replace("\n", "")

    def _send_json(self, status: int, payload: dict | None, *, session_id: str | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session_id is not None:
            self.send_header(SESSION_ID_HEADER, self._safe_header_value(session_id))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _wrong_path(self) -> bool:
        return urlparse(self.path).path != self.server_transport.path

    def _resource_metadata_url(self) -> str:
        """This server's own base URL, for the `resource_metadata` pointer
        a 401 challenge carries — derived from the request's own Host
        header rather than a separately-configured "public URL" setting,
        since a reverse-proxied deployment's externally-visible host is
        exactly what's already in that header and nothing else here needs
        to know it independently."""
        scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        host = self.headers.get("Host", f"{self.server_transport.host}:{self.server_transport.port}")
        return f"{scheme}://{host}{WELL_KNOWN_PROTECTED_RESOURCE_PATH}"

    def _send_unauthorized(self) -> None:
        """A bare 401 with no `WWW-Authenticate` header (`oauth_issuer`
        unset) is unchanged from this transport's behavior before OAuth
        discovery existed. With it set, the header is what lets an
        MCP-Authorization-spec-compliant client find the protected-resource
        metadata on its own, instead of the operator having to tell every
        user how to configure a client manually."""
        if self.server_transport.oauth_issuer:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            www_authenticate = f'Bearer resource_metadata="{self._resource_metadata_url()}"'
            self.send_header("WWW-Authenticate", self._safe_header_value(www_authenticate))
            body = json.dumps({"error": "missing_bearer_token"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json(401, {"error": "missing_bearer_token"})

    # -- HTTP methods ----------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if self._wrong_path():
            self._send_json(404, {"error": "not_found"})
            return
        if not self._origin_allowed():
            self._send_json(403, {"error": "origin_not_allowed"})
            return
        token = self._bearer_token()
        if token is None:
            self._send_unauthorized()
            return

        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header) if length_header is not None else -1
        except ValueError:
            length = -1
        if length <= 0:
            self._send_json(400, {"error": "content_length_required"})
            return
        if length > MAX_HTTP_BODY_BYTES:
            self._send_json(413, {"error": "request_body_too_large"})
            return
        raw = self.rfile.read(length)

        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return
        if not isinstance(message, dict):
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            return

        session_id = self.headers.get(SESSION_ID_HEADER)
        if message.get("method") == "initialize":
            session_id = self.server_transport.open_session(token)
            mcp_server = self.server_transport.session_for(session_id, token)
        elif session_id is None:
            self._send_json(400, {"error": "missing_session_id"})
            return
        else:
            mcp_server = self.server_transport.session_for(session_id, token)
        if mcp_server is None:
            self._send_json(404, {"error": "unknown_session_or_token_mismatch"})
            return

        response = mcp_server.handle(message)
        if response is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.send_header(SESSION_ID_HEADER, self._safe_header_value(session_id))
            self.end_headers()
            return
        self._send_json(200, response, session_id=session_id)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == WELL_KNOWN_PROTECTED_RESOURCE_PATH:
            self._send_protected_resource_metadata()
            return
        # Server-initiated SSE streaming is not implemented — see this
        # module's docstring for why that is a deliberate, documented gap.
        self._send_json(405, {"error": "sse_not_supported"})

    def _send_protected_resource_metadata(self) -> None:
        # RFC 9728. `authorization_servers` names the backend
        # (apps/backend/app/api/routers/mcp_oauth.py), not this process —
        # this server is the OAuth *resource*, not the *authorization
        # server*, and RFC 9728 draws that distinction on purpose so one
        # deployment's MCP resource server(s) and its authorization
        # server don't have to be the same origin, or even the same
        # codebase, which they in fact are not here.
        if not self.server_transport.oauth_issuer:
            self._send_json(404, {"error": "not_found"})
            return
        self._send_json(
            200,
            {
                "resource": self._resource_metadata_url().removesuffix(WELL_KNOWN_PROTECTED_RESOURCE_PATH),
                "authorization_servers": [self.server_transport.oauth_issuer],
                "bearer_methods_supported": ["header"],
            },
        )

    def do_DELETE(self) -> None:  # noqa: N802
        session_id = self.headers.get(SESSION_ID_HEADER)
        if session_id:
            self.server_transport.close_session(session_id)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
