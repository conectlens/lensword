"""Unit coverage for `BackendClient`'s own URI-to-path mapping.

Moved from `apps/mcp/tests/test_server.py` (issue #311): these test
`BackendClient.resource()` itself — including its id-shape validation for
the `lensword://session/{session_id}` template — not anything MCP
transport/protocol-specific, so they belong alongside the class they test
now that `BackendClient` lives in this package. `apps/mcp/tests/test_server.py`
still covers the MCP-protocol-level behavior of exposing and reading that
same resource template through `MCPServer`, using a fake backend rather than
this real client.
"""
from __future__ import annotations

import pytest

from lensword_cli.backend_client import BackendClient, BackendError


class _RecordingBackendClient(BackendClient):
    """A BackendClient whose `_request` is captured instead of making a real
    HTTP call, so the URI-to-path mapping in `resource()` (#193 TODO 1) can
    be tested without a running backend."""

    def _request(self, path, body=None):
        self.calls.append(path)
        return {"path": path}


def _client():
    backend = _RecordingBackendClient(api_url="http://backend", token="t", workspace="/w")
    object.__setattr__(backend, "calls", [])
    return backend


def test_session_resource_template_forwards_to_the_companion_session_endpoint():
    backend = _client()
    result = backend.resource("lensword://session/" + "a" * 32)
    assert backend.calls == [f"/api/v1/companion/sessions/{'a' * 32}"]
    assert result == {"path": f"/api/v1/companion/sessions/{'a' * 32}"}


@pytest.mark.parametrize(
    "session_id",
    [
        "",
        "not-hex-not-32-chars",
        "a" * 31,
        "a" * 33,
        "../../etc/passwd",
        "A" * 32,  # CompanionSession.id is lowercase uuid4().hex only
    ],
)
def test_session_resource_template_rejects_malformed_ids_as_404_not_403(session_id):
    """Same disclosure shape as the word/group/learning-path templates: a
    session id that cannot possibly be valid never reaches the backend and
    never distinguishes "not yours" from "does not exist"."""
    backend = _client()
    with pytest.raises(BackendError) as excinfo:
        backend.resource(f"lensword://session/{session_id}")
    assert excinfo.value.status == 404
    assert backend.calls == []
