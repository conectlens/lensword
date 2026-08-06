"""MCP 2025-11-25 stdio transport for the LensWord HTTP API.

The transport is deliberately small. LensWord's backend remains the source of
truth for tool schemas and enforces authentication, grants, rate limits,
tenant scoping, audit chaining and write idempotency.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, TextIO

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")


class BackendError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class BackendClient:
    api_url: str
    token: str
    requester: str
    workspace: str
    timeout: float = 30.0

    def _request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(
            f"{self.api_url.rstrip('/')}{path}",
            data=data,
            method="POST" if body is not None else "GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail", "LensWord request failed")
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = "LensWord request failed"
            raise BackendError(exc.code, str(detail)) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendError(503, "LensWord API unavailable") from exc

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
                "requester": self.requester,
                "workspace": self.workspace,
                "payload": payload,
            },
        )


class MCPServer:
    """Stateful MCP request handler, independent of the stdio streams."""

    def __init__(self, backend: BackendClient, *, server_version: str = "0.1.0"):
        self.backend = backend
        self.server_version = server_version
        self.initialized = False
        self.protocol_version: str | None = None
        self._capabilities: dict[str, Any] | None = None

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("jsonrpc") != "2.0":
            return self._error(message.get("id"), -32600, "Invalid Request")
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        if method == "initialize":
            return self._initialize(request_id, message.get("params") or {})
        if not self.initialized:
            return self._error(request_id, -32002, "Server not initialized")
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return self._tools_list(request_id)
        if method == "tools/call":
            return self._tools_call(request_id, message.get("params") or {})
        return self._error(request_id, -32601, f"Method not found: {method}")

    def _initialize(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        if requested not in SUPPORTED_PROTOCOL_VERSIONS:
            return self._error(
                request_id,
                -32602,
                "Unsupported protocol version",
                {"supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
            )
        self.protocol_version = requested
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lensword", "version": self.server_version},
            },
        }

    def _tools_list(self, request_id: Any) -> dict[str, Any]:
        try:
            capabilities = self._get_capabilities()
        except BackendError as exc:
            return self._error(request_id, -32003, exc.detail)
        tools = []
        for descriptor in capabilities.get("tools", []):
            tools.append(
                {
                    "name": descriptor["name"],
                    "description": f"LensWord {descriptor['name']}",
                    "inputSchema": descriptor["input_schema"],
                }
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

    def _tools_call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(request_id, -32602, "tools/call requires name and object arguments")
        try:
            result = self.backend.invoke(name, arguments)
        except BackendError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"isError": True, "content": [{"type": "text", "text": exc.detail}]},
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "isError": False,
                "structuredContent": result,
                "content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
            },
        }

    def _get_capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            self._capabilities = self.backend.capabilities()
        return self._capabilities

    @staticmethod
    def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


class StdioMCPServer:
    def __init__(self, server: MCPServer, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout):
        self.server = server
        self.input_stream = input_stream
        self.output_stream = output_stream

    def run(self) -> None:
        for line in self.input_stream:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                response = self.server.handle(message)
            except (json.JSONDecodeError, TypeError):
                response = self.server._error(None, -32700, "Parse error")
            if response is not None:
                self.output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
                self.output_stream.flush()


def main() -> int:
    required = {
        "LENSWORD_API_URL": os.environ.get("LENSWORD_API_URL"),
        "LENSWORD_TOKEN": os.environ.get("LENSWORD_TOKEN"),
        "LENSWORD_MCP_REQUESTER": os.environ.get("LENSWORD_MCP_REQUESTER"),
        "LENSWORD_MCP_WORKSPACE": os.environ.get("LENSWORD_MCP_WORKSPACE"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2
    backend = BackendClient(
        required["LENSWORD_API_URL"],
        required["LENSWORD_TOKEN"],
        required["LENSWORD_MCP_REQUESTER"],
        required["LENSWORD_MCP_WORKSPACE"],
    )
    StdioMCPServer(MCPServer(backend)).run()
    return 0
