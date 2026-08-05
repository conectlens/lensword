from app.application.mcp.contracts import CONTRACT_VERSION, TOOL_CONTRACTS, capabilities
from app.domain.services.mcp_policy import AccessClass
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
import pytest

def test_contracts_are_versioned_bounded_and_classified():
    assert CONTRACT_VERSION == "1.0.0" and len(TOOL_CONTRACTS) == 8
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

def test_dispatcher_only_allows_registered_and_bound_use_case_handlers():
    dispatcher = MCPDispatcher({"lensword.search_words": lambda user_id, payload: {"user": user_id, "query": payload["query"]}})
    assert dispatcher.dispatch(7, "lensword.search_words", {"query": "hola"}) == {"user": 7, "query": "hola"}
    with pytest.raises(UnboundMCPToolError): dispatcher.dispatch(7, "lensword.add_word", {})
    with pytest.raises(UnknownMCPToolError): dispatcher.dispatch(7, "lensword.nope", {})
