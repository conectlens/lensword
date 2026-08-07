from app.application.mcp.contracts import CONTRACT_VERSION, TOOL_CONTRACTS, capabilities
from app.domain.services.mcp_policy import AccessClass
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
import pytest

def test_contracts_are_versioned_bounded_and_classified():
    # 8 original tools, 5 learner-aware dev-workflow tools (#188 TODO 3), 5
    # durable-companion-session tools (#193 TODO 1): start/get/resume/
    # pause/finish_companion_session, and 6 measurable-activity/companion-
    # action tools (#194 TODO 1): begin_learning_activity/
    # submit_activity_response/get_activity_result/finish_learning_activity/
    # request_hint/explain_evidence.
    assert CONTRACT_VERSION == "1.0.0" and len(TOOL_CONTRACTS) == 24
    for tool in TOOL_CONTRACTS:
        assert tool.schema_id.endswith(".schema.json")
        assert tool.input_schema["additionalProperties"] is False
        assert tool.access in AccessClass
        if tool.access == AccessClass.WRITE: assert "request_id" in tool.input_schema["properties"]

def test_capability_metadata_only_advertises_registered_tools():
    advertised = capabilities()
    assert advertised["version"] == CONTRACT_VERSION
    assert {item["name"] for item in advertised["tools"]} == {tool.name for tool in TOOL_CONTRACTS}

def test_capabilities_are_published_over_the_api(client):
    response = client.get("/api/v1/mcp/capabilities")
    assert response.status_code == 200
    assert response.json()["version"] == CONTRACT_VERSION

def test_companion_session_tools_are_registered_with_the_right_access_class():
    by_name = {tool.name: tool for tool in TOOL_CONTRACTS}
    expected = {
        "lensword.start_companion_session": AccessClass.WRITE,
        "lensword.get_companion_session": AccessClass.READ,
        "lensword.resume_companion_session": AccessClass.WRITE,
        "lensword.pause_companion_session": AccessClass.WRITE,
        "lensword.finish_companion_session": AccessClass.WRITE,
    }
    for name, access in expected.items():
        assert name in by_name, f"{name} is missing from TOOL_CONTRACTS"
        assert by_name[name].access == access
    assert by_name["lensword.get_companion_session"].input_schema["required"] == ["session_id"]
    # "request_id" is appended for every write tool as of issue #196 TODO 4
    # (mandatory idempotency), on top of the tool's own required fields.
    assert by_name["lensword.start_companion_session"].input_schema["required"] == ["connection_id", "client_id", "request_id"]


def test_dispatcher_only_allows_registered_and_bound_use_case_handlers():
    dispatcher = MCPDispatcher({"lensword.search_words": lambda user_id, payload: {"user": user_id, "query": payload["query"]}})
    assert dispatcher.dispatch(7, "lensword.search_words", {"query": "hola"}) == {"user": 7, "query": "hola"}
    with pytest.raises(UnboundMCPToolError): dispatcher.dispatch(7, "lensword.add_word", {})
    with pytest.raises(UnknownMCPToolError): dispatcher.dispatch(7, "lensword.nope", {})


# --- Issue #188 TODO 3: learner-aware developer-workflow tools -------------

_DEV_WORKFLOW_TOOLS = (
    "lensword.get_language_profile",
    "lensword.check_known_term",
    "lensword.explain_for_user",
    "lensword.suggest_stretch_vocabulary",
    "lensword.record_context_occurrence",
)


def test_developer_workflow_tools_are_registered_and_read_mostly():
    by_name = {tool.name: tool for tool in TOOL_CONTRACTS}
    assert set(_DEV_WORKFLOW_TOOLS) <= set(by_name)
    for name in _DEV_WORKFLOW_TOOLS:
        contract = by_name[name]
        if name == "lensword.record_context_occurrence":
            # The only write among these five, and its schema requires
            # explicit confirmation plus a bounded, closed context_kind —
            # never a free-text field a caller could use to smuggle a
            # mastery mutation through.
            assert contract.access == AccessClass.WRITE
            # "request_id" is appended for every write tool as of issue #196
            # TODO 4 (mandatory idempotency), on top of the tool's own
            # required fields.
            assert contract.input_schema["required"] == ["word_id", "context_kind", "outcome", "confirmed", "request_id"]
            assert "request_id" in contract.input_schema["properties"]
        else:
            assert contract.access == AccessClass.READ


def test_record_context_occurrence_schema_never_accepts_mastery_or_diagnosis_fields():
    contract = next(tool for tool in TOOL_CONTRACTS if tool.name == "lensword.record_context_occurrence")
    forbidden = {"strength", "repetitions", "mastered", "diagnosis", "ease_factor", "interval_days"}
    assert forbidden.isdisjoint(contract.input_schema["properties"])
