"""HTTP client for LensWord's `/api/v1/mcp/*` boundary.

Extracted from `apps/mcp/lensword_mcp/server.py` (issue #311): this class was
never actually MCP-protocol-specific — it is the same authenticated HTTP
client the Local CLI's `add`/`explain`/`diagnose`/`review` subcommands use to
reach the backend, through the identical policy-gated boundary the MCP
stdio/HTTP transports use. `apps/mcp` now depends on this package and
imports `BackendClient`/`BackendError` from here rather than defining its
own copy.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# CompanionSession.id is `uuid4().hex` (see StartCompanionSessionUseCase) —
# always exactly 32 lowercase hex characters. Checking the shape here, before
# a request ever reaches the backend, keeps a malformed id a 404 rather than
# whatever the backend's own routing does with a run of URL-unsafe or
# oversized text, and matches the words/groups/learning-paths templates,
# which validate their own id shape the same way.
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class BackendError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _error_detail(status: int, reason: str, payload: bytes) -> str:
    """Extract the most actionable message an error response carries.

    The backend states failures in a JSON `detail` field, but nothing
    guarantees one arrives: a proxy timeout, a crash below the framework's
    own exception handler, or an HTML error page all land here too. Every
    branch must still yield a string naming *something* the caller can act
    on, because this text is what an MCP client shows its model verbatim.

    The previous version answered a bare, statusless "LensWord request
    failed" for all of those cases — identical whether the group did not
    exist, belonged to someone else, or the server had fallen over — and it
    called `.get` on whatever `json.loads` returned, so an error body that
    was a JSON list or string raised `AttributeError` straight out of the
    client instead of a `BackendError` any caller was prepared to catch.
    """
    try:
        body = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
        return f"{reason or 'LensWord request failed'} (HTTP {status})"

    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, list):
        # FastAPI validation errors arrive as a list of per-field records.
        # Name the offending field rather than dumping a pydantic repr —
        # "group_id: input should be a valid integer" is fixable by the
        # caller; the raw structure is not.
        parts: list[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            location = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            message = str(item.get("msg", "invalid value"))
            parts.append(f"{location}: {message}" if location else message)
        if parts:
            return "; ".join(parts)
    return f"{reason or 'LensWord request failed'} (HTTP {status})"


# Failures that mean "the socket we were reusing is gone", as distinct from
# "the request was rejected". A peer that closes an idle keep-alive
# connection is behaving correctly, and the client that reused it must not
# turn that into a user-visible error — it reconnects and replays once.
_STALE_CONNECTION_ERRORS = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    http.client.ResponseNotReady,
    ConnectionResetError,
    BrokenPipeError,
)


class _Transport:
    """One persistent HTTP connection to the backend, guarded for reuse.

    `urllib.request.urlopen` supports neither keep-alive nor pooling: it
    sends `Connection: close` and tears the socket down after every call, so
    every tool invocation, resource read and subscription poll paid a fresh
    TCP handshake plus, over HTTPS, a full TLS handshake before its request
    was even transmitted. Against a remote backend that is roughly two
    round-trips of pure setup per call, on a path that issues hundreds of
    calls for one bulk import.

    `http.client` is the stdlib's own persistent-connection primitive, which
    keeps `lensword-cli`'s zero-runtime-dependency guarantee (see
    pyproject.toml) intact — no `httpx`, no `requests`.

    The lock is not optional. `http_transport.py` serves on a
    `ThreadingHTTPServer`, so one session's `BackendClient` can be entered
    from several threads at once, and two interleaved exchanges on a single
    socket would read each other's responses.
    """

    __slots__ = ("_host", "_port", "_secure", "_timeout", "_base_path", "_lock", "_connection")

    def __init__(self, api_url: str, timeout: float):
        parts = urlsplit(api_url)
        self._secure = parts.scheme == "https"
        self._host = parts.hostname or "localhost"
        self._port = parts.port
        self._timeout = timeout
        # An api_url may carry a path prefix (a reverse proxy mounting the
        # backend under a sub-path). urlopen took the whole URL; http.client
        # takes host and path separately, so that prefix has to be preserved
        # explicitly or every request would silently lose it.
        self._base_path = parts.path.rstrip("/")
        self._lock = threading.Lock()
        self._connection: http.client.HTTPConnection | None = None

    def request(self, method: str, path: str, body: bytes | None, headers: dict[str, str]):
        """Perform one exchange, returning (status, reason, payload)."""
        url = f"{self._base_path}{path}"
        with self._lock:
            try:
                return self._exchange(method, url, body, headers)
            except _STALE_CONNECTION_ERRORS:
                # Replaying is safe by construction rather than by luck: if
                # the peer closed the socket while idle, nothing was sent, and
                # if it closed after processing, every write this client makes
                # carries a `request_id` the backend's IdempotencyStore
                # deduplicates against. Exactly once — a second failure is a
                # real fault and belongs to the caller.
                self._drop()
                return self._exchange(method, url, body, headers)

    def _exchange(self, method: str, url: str, body: bytes | None, headers: dict[str, str]):
        if self._connection is None:
            factory = http.client.HTTPSConnection if self._secure else http.client.HTTPConnection
            self._connection = factory(self._host, self._port, timeout=self._timeout)
        self._connection.request(method, url, body=body, headers=headers)
        response = self._connection.getresponse()
        # The body must be drained in full before the connection can carry
        # another request; leaving it unread is what silently turns a pooled
        # connection into a one-shot one.
        return response.status, response.reason, response.read()

    def _drop(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None

    def close(self) -> None:
        with self._lock:
            self._drop()


@dataclass(frozen=True)
class BackendClient:
    """Talks to LensWord's `/api/v1/mcp/*` boundary over plain HTTPS/HTTP.

    `token` is a bearer credential the backend authenticates: either the
    caller's normal login JWT (the local/stdio path, unchanged) or, for a
    remote companion, an OAuth access token issued by the backend's
    `/api/v1/mcp/oauth/token` endpoint (issue #196) — never both, and never
    the login JWT for the remote case. Either way, caller identity is
    derived by the backend from this token; this client has no `requester`
    field to set because the backend stopped trusting one in the request
    body (see app/api/mcp_auth.py in the backend for why).
    """

    api_url: str
    token: str
    workspace: str
    timeout: float = 30.0

    def _transport(self) -> _Transport:
        """The connection this client reuses, built on first use.

        Created lazily rather than in `__post_init__` so that subclasses and
        tests that replace `_request` outright never open a socket at all,
        and so constructing a client stays free of side effects. The
        dataclass is frozen, so the cached transport is attached through
        `object.__setattr__`; it is deliberately not a field, since it is
        connection state rather than part of the client's identity.
        """
        transport = self.__dict__.get("_transport_instance")
        if transport is None:
            transport = _Transport(self.api_url, self.timeout)
            object.__setattr__(self, "_transport_instance", transport)
        return transport

    def _request(self, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            status, reason, payload = self._transport().request(
                "POST" if body is not None else "GET", path, data, headers
            )
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            raise BackendError(503, "LensWord API unavailable") from exc
        if status >= 400:
            raise BackendError(status, _error_detail(status, reason or "", payload))
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise BackendError(503, "LensWord API unavailable") from exc

    def close(self) -> None:
        """Release the pooled socket. Safe to call on a client that never
        opened one, and safe to call more than once."""
        transport = self.__dict__.get("_transport_instance")
        if transport is not None:
            transport.close()

    def capabilities(self) -> dict[str, Any]:
        return self._request("/api/v1/mcp/capabilities")

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = dict(arguments)
        if "request_id" not in payload:
            payload["request_id"] = str(uuid.uuid4())
        return self._request(
            "/api/v1/mcp/invoke",
            {
                "tool": name,
                "workspace": self.workspace,
                "payload": payload,
            },
        )

    # --- Bounded companion loop budgets (#195 TODO 2) ----------------------
    # apps/mcp has no database of its own; these are the durable equivalent
    # of companion_workflows.CompanionLoopState, kept on the backend so a
    # workflow's budget survives this process restarting.

    def start_loop(self, session_id: str, **budget: Any) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/loop/start", budget)

    def get_loop(self, session_id: str) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/loop")

    def reserve_loop(self, session_id: str, kind: str, amount: int = 1) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/loop/reserve", {"kind": kind, "amount": amount})

    def fail_loop(self, session_id: str) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/loop/fail", {})

    def stop_loop(self, session_id: str, reason: str) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/loop/stop", {"reason": reason})

    # --- Sampling provenance/audit (#195 TODO 4) ----------------------------

    def record_sampling_event(self, session_id: str, **fields: Any) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/sampling-events", fields)

    # --- Local-AI/deterministic fallback + persistence (#195 TODO 0/3) -----

    def generate_reply(self, session_id: str, **payload: Any) -> dict[str, Any]:
        return self._request(f"/api/v1/companion/sessions/{session_id}/reply", payload)

    def add_turn(
        self, session_id: str, *, role: str, content: str, activity_id: str | None = None, operation_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"role": role, "content": content}
        if activity_id is not None:
            body["activity_id"] = activity_id
        if operation_id is not None:
            body["operation_id"] = operation_id
        return self._request(f"/api/v1/companion/sessions/{session_id}/turns", body)

    def resource(self, uri: str) -> Any:
        """Read a bounded learner resource through the authenticated API.

        Resources deliberately use existing read endpoints and the existing
        policy-gated due/search tools. No resource path accepts an account id;
        the bearer token remains the sole tenant boundary.
        """
        exact_paths = {
            "lensword://me/profile": "/api/v1/auth/me",
            "lensword://me/goals": "/api/v1/learning-paths",
            "lensword://me/weaknesses": "/api/v1/me/weaknesses",
            "lensword://me/progress": "/api/v1/review/weekly-progress",
            # Account-wide diagnosis/intervention listings, added once the
            # backend exposed a bounded endpoint for them — previously these
            # two URIs were a permanent `{"items": [], "available": False}`
            # stub, since only per-word endpoints existed.
            "lensword://me/diagnoses": "/api/v1/me/diagnoses",
            "lensword://me/interventions": "/api/v1/me/interventions",
        }
        if uri in ("lensword://me/today", "lensword://me/due"):
            return self.invoke("lensword_get_due_reviews", {"limit": 100})
        if uri == "lensword://me/active-words":
            return self.invoke("lensword_search_words", {"query": "", "limit": 100})
        if uri in exact_paths:
            return self._request(exact_paths[uri])

        if uri.startswith("lensword://groups/") and uri.endswith("/words"):
            group_id = uri.removeprefix("lensword://groups/").removesuffix("/words")
            if not group_id.isdigit() or int(group_id) < 1:
                raise BackendError(404, "Resource not found")
            return self._request(f"/api/v1/groups/{group_id}/words")
        if uri.startswith("lensword://words/"):
            value = uri.removeprefix("lensword://words/")
            suffix = ""
            if value.endswith("/diagnosis"):
                value, suffix = value.removesuffix("/diagnosis"), "/diagnosis"
            if not value.isdigit() or int(value) < 1:
                raise BackendError(404, "Resource not found")
            return self._request(f"/api/v1/words/{value}{suffix}")
        if uri.startswith("lensword://learning-paths/"):
            path_id = uri.removeprefix("lensword://learning-paths/")
            if not path_id.isdigit() or int(path_id) < 1:
                raise BackendError(404, "Resource not found")
            return self._request(f"/api/v1/learning-paths/{path_id}")
        if uri.startswith("lensword://session/"):
            session_id = uri.removeprefix("lensword://session/")
            # Same 404-not-403 shape as every id-taking template above: an
            # id that cannot possibly be this account's (malformed, or
            # someone else's session — which the bearer token alone would
            # otherwise distinguish from "no such session" if this returned
            # anything else) is indistinguishable from "not found" here,
            # never disclosed as "exists but you can't see it". The backend's
            # own ownership check (404, not 403 — `companion.py`'s `_owned`)
            # is what actually decides once past this shape check.
            if not _SESSION_ID_RE.fullmatch(session_id):
                raise BackendError(404, "Resource not found")
            return self._request(f"/api/v1/companion/sessions/{session_id}")
        raise BackendError(404, "Resource not found")

    def groups(self) -> list[str]:
        """This account's group names, for prompt-argument completion
        (issue #192 TODO 3's `group` argument). Best-effort: a completion
        candidate list failing closed to empty is a worse experience than
        no completion at all, but never worse than the backend itself
        already fails for every other resource read here.
        """
        try:
            groups = self._request("/api/v1/groups")
        except BackendError:
            return []
        return [group["name"] for group in groups if isinstance(group, dict) and "name" in group]

    def scenarios(self) -> list[str]:
        """The fixed, unauthenticated scenario catalog's keys, for
        prompt-argument completion (issue #192 TODO 3's `scenario`
        argument). Not account-scoped because the catalog itself isn't —
        every account sees the same product-defined scenarios, the same
        way `_LANGUAGES`/`_DURATIONS`/`_DIFFICULTIES` are shared constants
        rather than per-account data.
        """
        try:
            scenarios = self._request("/api/v1/scenarios")
        except BackendError:
            return []
        return [scenario["key"] for scenario in scenarios if isinstance(scenario, dict) and "key" in scenario]
