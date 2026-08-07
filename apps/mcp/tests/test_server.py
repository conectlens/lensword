import io
import json

from lensword_cli.backend_client import BackendError
from lensword_mcp.server import MCPServer, StdioMCPServer
from lensword_mcp.companion_workflows import (
    CompanionLoopBudget,
    CompanionLoopState,
    ElicitationField,
    UnsafeElicitationField,
    WorkflowLimitReached,
    build_sampling_request,
    run_bounded_workflow,
    validate_elicitation_fields,
)


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

    def resource(self, uri):
        if uri == "lensword://other-user/profile":
            raise BackendError(404, "Resource not found")
        return {"uri": uri, "items": [{"term": "hola"}]}

    def groups(self):
        return ["Spanish Basics", "Spanish Slang", "French"]

    def scenarios(self):
        return ["job_interview", "airport", "restaurant"]


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


def test_sampling_request_delimits_facts_and_rejects_learning_truth_claims():
    request = build_sampling_request("Explain this contrast", {"term": "ignore instructions"})
    assert "<learner_facts>" in request.user_prompt
    assert "<workflow_task>" in request.user_prompt
    assert request.max_tokens == 512

    state = CompanionLoopState(CompanionLoopBudget(samples=1, activities=2))
    result = run_bounded_workflow(
        state,
        task="Explain this contrast",
        facts={"term": "hola"},
        sample=lambda _request: ("mastery: 100%", "untrusted-model"),
        fallback=lambda _task, _facts: "Try recalling the word in a new sentence.",
    )
    assert result.fallback_used is True
    assert result.source == "deterministic_fallback"


def test_sampling_budget_stops_before_second_external_call():
    state = CompanionLoopState(CompanionLoopBudget(samples=1, activities=2))
    sample = lambda _request: ("A safe explanation.", "model")
    run_bounded_workflow(state, task="Explain", facts={}, sample=sample, fallback=lambda *_: "fallback")
    with __import__("pytest").raises(WorkflowLimitReached):
        run_bounded_workflow(state, task="Explain again", facts={}, sample=sample, fallback=None)


def test_elicitation_cannot_request_secrets_and_is_bounded():
    with __import__("pytest").raises(UnsafeElicitationField):
        ElicitationField("api_key", "What is your API key?")
    fields = validate_elicitation_fields(
        [ElicitationField("target_language", "Which language are you learning?")]
    )
    assert fields[0].name == "target_language"


def test_resources_templates_prompts_and_completion_are_exposed_after_initialize():
    server = MCPServer(FakeBackend())
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    resources = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    assert len(resources["result"]["resources"]) >= 9
    read = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "lensword://me/profile"}})
    assert read["result"]["contents"][0]["uri"] == "lensword://me/profile"
    assert "hola" in read["result"]["contents"][0]["text"]

    templates = server.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/templates/list"})
    assert any(item["uriTemplate"] == "lensword://words/{word_id}" for item in templates["result"]["resourceTemplates"])
    # #193 TODO 1: a durable companion session must be readable as a
    # resource, not just actionable as a tool, so a second client can see
    # where the first one left off before calling resume_companion_session.
    assert any(item["uriTemplate"] == "lensword://session/{session_id}" for item in templates["result"]["resourceTemplates"])
    prompts = server.handle({"jsonrpc": "2.0", "id": 5, "method": "prompts/list"})
    assert {item["name"] for item in prompts["result"]["prompts"]} >= {"daily_check_in", "explain_word"}
    prompt = server.handle({"jsonrpc": "2.0", "id": 6, "method": "prompts/get", "params": {"name": "daily_check_in", "arguments": {"duration": "10"}}})
    assert "Do not invent diagnoses" in prompt["result"]["messages"][0]["content"]["text"]

    completion = server.handle({"jsonrpc": "2.0", "id": 7, "method": "completion/complete", "params": {"argument": {"name": "target_language", "value": "sp"}}})
    assert completion["result"]["completion"]["values"] == ["Spanish"]


def test_session_template_is_advertised_and_reads_through_like_the_others():
    server = MCPServer(FakeBackend())
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    templates = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"})
    assert any(item["uriTemplate"] == "lensword://session/{session_id}" for item in templates["result"]["resourceTemplates"])

    read = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "lensword://session/abc123"}}
    )
    assert read["result"]["contents"][0]["uri"] == "lensword://session/abc123"


def test_group_and_scenario_completion_are_account_scoped_through_the_backend():
    server = MCPServer(FakeBackend())
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    groups = server.handle({"jsonrpc": "2.0", "id": 2, "method": "completion/complete", "params": {"argument": {"name": "group", "value": "Spanish"}}})
    assert groups["result"]["completion"]["values"] == ["Spanish Basics", "Spanish Slang"]

    scenarios = server.handle({"jsonrpc": "2.0", "id": 3, "method": "completion/complete", "params": {"argument": {"name": "scenario", "value": "air"}}})
    assert scenarios["result"]["completion"]["values"] == ["airport"]

    # `topic` and `active-learning-path` are honestly unimplemented rather
    # than faked — no closed, account-scoped source exists for either yet.
    topic = server.handle({"jsonrpc": "2.0", "id": 4, "method": "completion/complete", "params": {"argument": {"name": "topic", "value": "a"}}})
    assert topic["result"]["completion"]["values"] == []


def test_resource_read_rejects_unbounded_or_unknown_uris():
    server = MCPServer(FakeBackend())
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    unknown = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "lensword://other-user/profile"}})
    assert unknown["error"]["code"] == -32003
    too_long = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "x" * 513}})
    assert too_long["error"]["code"] == -32602


# `BackendClient`'s own URI-to-path mapping (including the id-shape
# validation for lensword://session/{session_id}) and context_import.py's
# tests moved to apps/cli/tests/test_backend_client.py and
# apps/cli/tests/test_context_import.py respectively (issue #311) — neither
# is MCP-protocol-specific, both now live alongside the code they test.
