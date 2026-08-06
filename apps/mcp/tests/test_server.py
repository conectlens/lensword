import io
import json

from lensword_mcp.server import MCPServer, StdioMCPServer


class FakeBackend:
    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {
            "tools": [
                {
                    "name": "lensword.search_words",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        }

    def invoke(self, name, arguments):
        self.calls.append((name, arguments))
        return {"words": [{"term": "hola"}]}


def test_lifecycle_and_tool_call_are_mcp_json_rpc_messages():
    backend = FakeBackend()
    server = MCPServer(backend)
    assert server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})["result"]["protocolVersion"] == "2025-11-25"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed["result"]["tools"][0]["name"] == "lensword.search_words"
    called = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "lensword.search_words", "arguments": {"query": "hola"}}})
    assert called["result"]["structuredContent"] == {"words": [{"term": "hola"}]}
    assert backend.calls[0][0] == "lensword.search_words"
    assert backend.calls[0][1] == {"query": "hola"}


def test_stdio_keeps_notifications_off_stdout():
    incoming = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ]
    ) + "\n"
    output = io.StringIO()
    StdioMCPServer(MCPServer(FakeBackend()), io.StringIO(incoming), output).run()
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [message["id"] for message in messages] == [1, 2]
    assert all(message["jsonrpc"] == "2.0" for message in messages)
