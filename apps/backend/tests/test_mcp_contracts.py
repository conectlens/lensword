from app.application.mcp.contracts import CONTRACT_VERSION, TOOL_CONTRACTS, capabilities
from app.domain.services.mcp_policy import AccessClass
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
import pytest

def test_contracts_are_versioned_bounded_and_classified():
    # 8 original tools plus 5 durable-companion-session tools (#193 TODO 1):
    # start/get/resume/pause/finish_companion_session.
    assert CONTRACT_VERSION == "1.0.0" and len(TOOL_CONTRACTS) == 13
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
    assert by_name["lensword.start_companion_session"].input_schema["required"] == ["connection_id", "client_id"]


def test_dispatcher_only_allows_registered_and_bound_use_case_handlers():
    dispatcher = MCPDispatcher({"lensword.search_words": lambda user_id, payload: {"user": user_id, "query": payload["query"]}})
    assert dispatcher.dispatch(7, "lensword.search_words", {"query": "hola"}) == {"user": 7, "query": "hola"}
    with pytest.raises(UnboundMCPToolError): dispatcher.dispatch(7, "lensword.add_word", {})
    with pytest.raises(UnknownMCPToolError): dispatcher.dispatch(7, "lensword.nope", {})
