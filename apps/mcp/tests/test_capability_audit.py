"""Issue #199 TODO 1: capability audit for the stdio MCP transport layer.

`test_mcp_capability_audit.py` in the backend suite audits the *tool*
surface (`TOOL_CONTRACTS` vs `_handlers()`). This file audits the
transport-local surface `apps/mcp/lensword_mcp/server.py` advertises on top
of that: every declared resource, every declared resource template, every
declared prompt, and the `initialize` handshake's protocol-version
negotiation - each walked exhaustively rather than spot-checked, so a future
entry added to `_RESOURCE_DESCRIPTORS`/`_RESOURCE_TEMPLATES`/`_PROMPTS`
without a working code path behind it fails here instead of only surfacing
the first time a real host tries it.
"""
from __future__ import annotations

import re

import pytest

from lensword_mcp.server import (
    _PROMPTS,
    _RESOURCE_DESCRIPTORS,
    _RESOURCE_TEMPLATES,
    SUPPORTED_PROTOCOL_VERSIONS,
    BackendError,
    MCPServer,
)


class _AuditBackend:
    """A permissive fake: everything resolves to a small, uniform payload
    except the one URI deliberately reserved to prove a lookup failure
    still degrades cleanly. The point of this file is not to re-verify
    per-resource business logic (test_server.py already covers the real
    `BackendClient.resource` URI-to-path mapping and its id-shape
    validation) - it is to prove every *declared* capability has *some*
    real code path behind it, not a silent 404 for every call."""

    def capabilities(self):
        return {"tools": []}

    def invoke(self, name, arguments):
        return {"tool": name, "arguments": arguments}

    def resource(self, uri):
        if uri == "lensword://deliberately-missing":
            raise BackendError(404, "Resource not found")
        return {"uri": uri, "items": []}

    def groups(self):
        return []

    def scenarios(self):
        return []


def _init(server):
    response = server.handle(
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}},
        }
    )
    assert response["result"]["protocolVersion"] == "2025-11-25"
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return server


def _server() -> MCPServer:
    return _init(MCPServer(_AuditBackend()))


# --- Resources ---------------------------------------------------------


@pytest.mark.parametrize("uri,_name", _RESOURCE_DESCRIPTORS)
def test_every_declared_resource_resolves_via_resources_read(uri, _name):
    server = _server()
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": uri}})
    assert "error" not in response, f"{uri}: {response.get('error')}"
    assert response["result"]["contents"][0]["uri"] == uri


def test_resources_list_advertises_exactly_the_audited_set():
    server = _server()
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    advertised = {item["uri"] for item in listed["result"]["resources"]}
    assert advertised == {uri for uri, _ in _RESOURCE_DESCRIPTORS}


# --- Resource templates --------------------------------------------------


_TEMPLATE_EXAMPLES = {
    "{group_id}": "1",
    "{word_id}": "1",
    "{path_id}": "1",
    "{session_id}": "a" * 32,
}


def _example_uri(template: str) -> str:
    example = template
    for placeholder, value in _TEMPLATE_EXAMPLES.items():
        example = example.replace(placeholder, value)
    assert "{" not in example, f"no example value registered for a placeholder in {template!r}"
    return example


@pytest.mark.parametrize("template,_name", _RESOURCE_TEMPLATES)
def test_every_resource_template_has_a_dispatchable_example(template, _name):
    server = _server()
    example_uri = _example_uri(template)
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": example_uri}})
    assert "error" not in response, f"{template} (example {example_uri}): {response.get('error')}"


def test_resource_templates_list_advertises_exactly_the_audited_set():
    server = _server()
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"})
    advertised = {item["uriTemplate"] for item in listed["result"]["resourceTemplates"]}
    assert advertised == {template for template, _ in _RESOURCE_TEMPLATES}


# --- Prompts ---------------------------------------------------------------


@pytest.mark.parametrize("name,_description", _PROMPTS)
def test_every_declared_prompt_resolves_via_prompts_get(name, _description):
    server = _server()
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": name, "arguments": {}}})
    assert "error" not in response, f"{name}: {response.get('error')}"
    assert response["result"]["messages"], f"{name} resolved but produced no messages"
    assert response["result"]["description"]


def test_prompts_list_advertises_exactly_the_audited_set():
    server = _server()
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})
    advertised = {item["name"] for item in listed["result"]["prompts"]}
    assert advertised == {name for name, _ in _PROMPTS}


# --- tools/list schema well-formedness -------------------------------------


def test_every_advertised_tool_has_a_well_formed_input_schema():
    server = _server()
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed["result"]["tools"]
    assert tools, "tools/list returned nothing to audit"
    for tool in tools:
        assert isinstance(tool["name"], str) and tool["name"]
        assert isinstance(tool["description"], str) and tool["description"]
        schema = tool["inputSchema"]
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties"), dict)


# --- Protocol version negotiation (TODO 1: "schema compatibility and
# version-negotiation tests... against multiple protocol version strings,
# confirm graceful negotiation/rejection") --------------------------------


@pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
def test_initialize_accepts_every_currently_supported_protocol_version(version):
    server = MCPServer(_AuditBackend())
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version}})
    assert response["result"]["protocolVersion"] == version


@pytest.mark.parametrize(
    "version",
    [
        "2024-01-01",  # a plausible but never-supported earlier revision
        "2099-01-01",  # a plausible but never-supported future revision
        "",
        "not-a-date-at-all",
        None,
    ],
)
def test_initialize_rejects_every_unsupported_or_malformed_protocol_version_gracefully(version):
    server = MCPServer(_AuditBackend())
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version}})
    assert "result" not in response
    assert response["error"]["code"] == -32602
    # The rejection names what IS supported, so a client can retry
    # correctly instead of guessing.
    assert set(response["error"]["data"]["supported"]) == set(SUPPORTED_PROTOCOL_VERSIONS)
    # And the server never half-initializes on a rejected handshake: every
    # method but `initialize` itself must still refuse to run.
    assert server.initialized is False
    follow_up = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert follow_up["error"]["code"] == -32002


def test_initialize_with_a_missing_protocol_version_field_is_also_rejected_gracefully():
    server = MCPServer(_AuditBackend())
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["error"]["code"] == -32602


def test_a_client_that_never_calls_initialize_gets_a_clean_error_not_a_crash():
    server = MCPServer(_AuditBackend())
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response["error"]["code"] == -32002
