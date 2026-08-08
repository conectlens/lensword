from app.application.mcp.contracts import CONTRACT_VERSION, TOOL_CONTRACTS, capabilities
from app.domain.services.mcp_policy import AccessClass
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
import pytest

def test_contracts_are_versioned_bounded_and_classified():
    # 8 original tools, 3 companion task tools (#197 TODO 2):
    # start_extraction_task/get_companion_task/cancel_companion_task (no
    # start_plan_generation_task — #194 TODO 4 already gave plan_generation
    # tasks a real generate-plan/confirm-plan lifecycle, so this doesn't
    # duplicate it), 5 learner-aware dev-workflow tools (#188 TODO 3), 5
    # durable-companion-session tools (#193 TODO 1): start/get/resume/pause/
    # finish_companion_session, and 6 measurable-activity/companion-action
    # tools (#194 TODO 1): begin_learning_activity/submit_activity_response/
    # get_activity_result/finish_learning_activity/request_hint/
    # explain_evidence.
    assert CONTRACT_VERSION == "1.0.0" and len(TOOL_CONTRACTS) == 27
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
        "lensword_start_companion_session": AccessClass.WRITE,
        "lensword_get_companion_session": AccessClass.READ,
        "lensword_resume_companion_session": AccessClass.WRITE,
        "lensword_pause_companion_session": AccessClass.WRITE,
        "lensword_finish_companion_session": AccessClass.WRITE,
    }
    for name, access in expected.items():
        assert name in by_name, f"{name} is missing from TOOL_CONTRACTS"
        assert by_name[name].access == access
    assert by_name["lensword_get_companion_session"].input_schema["required"] == ["session_id"]
    # "request_id" is appended for every write tool as of issue #196 TODO 4
    # (mandatory idempotency), on top of the tool's own required fields.
    assert by_name["lensword_start_companion_session"].input_schema["required"] == ["connection_id", "client_id", "request_id"]


def test_dispatcher_only_allows_registered_and_bound_use_case_handlers():
    dispatcher = MCPDispatcher({"lensword_search_words": lambda user_id, payload: {"user": user_id, "query": payload["query"]}})
    assert dispatcher.dispatch(7, "lensword_search_words", {"query": "hola"}) == {"user": 7, "query": "hola"}
    with pytest.raises(UnboundMCPToolError): dispatcher.dispatch(7, "lensword_add_word", {})
    with pytest.raises(UnknownMCPToolError): dispatcher.dispatch(7, "lensword.nope", {})


# --- Issue #188 TODO 3: learner-aware developer-workflow tools -------------

_DEV_WORKFLOW_TOOLS = (
    "lensword_get_language_profile",
    "lensword_check_known_term",
    "lensword_explain_for_user",
    "lensword_suggest_stretch_vocabulary",
    "lensword_record_context_occurrence",
)


def test_developer_workflow_tools_are_registered_and_read_mostly():
    by_name = {tool.name: tool for tool in TOOL_CONTRACTS}
    assert set(_DEV_WORKFLOW_TOOLS) <= set(by_name)
    for name in _DEV_WORKFLOW_TOOLS:
        contract = by_name[name]
        if name == "lensword_record_context_occurrence":
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
    contract = next(tool for tool in TOOL_CONTRACTS if tool.name == "lensword_record_context_occurrence")
    forbidden = {"strength", "repetitions", "mastered", "diagnosis", "ease_factor", "interval_days"}
    assert forbidden.isdisjoint(contract.input_schema["properties"])


# --- Tool presentation and behavioural hints -------------------------------
#
# `title`/`description` come from TOOL_DOCS and `annotations` is derived from
# the access class, so both are looked up rather than stored per contract —
# these guard the failure modes that indirection introduces.


def test_every_contract_has_documentation():
    """A contract added without a TOOL_DOCS entry would raise KeyError from
    `capabilities()` at request time, taking down tools/list entirely rather
    than shipping one under-documented tool."""
    from app.application.mcp.contracts import TOOL_DOCS

    missing = sorted({tool.name for tool in TOOL_CONTRACTS} - TOOL_DOCS.keys())
    assert not missing, f"TOOL_DOCS is missing an entry for: {missing}"
    for tool in TOOL_CONTRACTS:
        assert tool.title and not tool.title.lower().startswith("lensword")
        # The old placeholder was literally `f"LensWord {name}"`; a real
        # description is prose, not a restatement of the identifier.
        assert len(tool.description) > 40 and tool.name not in tool.description


def test_read_tools_are_annotated_read_only_so_hosts_need_not_confirm_them():
    """The whole point of the annotations block: without it every tool
    inherits the schema defaults (not read-only, possibly destructive, open
    world) and a host prompts for confirmation before even a search."""
    for tool in TOOL_CONTRACTS:
        if tool.access is AccessClass.READ:
            assert tool.annotations["readOnlyHint"] is True
            assert tool.annotations["openWorldHint"] is False
            # Defined as meaningful only when readOnlyHint is false.
            assert "destructiveHint" not in tool.annotations


def test_writes_are_idempotent_non_destructive_by_default_and_closed_world():
    from app.application.mcp.contracts import DESTRUCTIVE_TOOLS

    for tool in TOOL_CONTRACTS:
        if tool.access is AccessClass.READ:
            continue
        assert tool.annotations["readOnlyHint"] is False
        assert tool.annotations["openWorldHint"] is False
        # Every write schema mandates `request_id`, which is what makes the
        # idempotency claim true rather than aspirational.
        assert "request_id" in tool.input_schema["properties"]
        assert tool.annotations["idempotentHint"] is True
        assert tool.annotations["destructiveHint"] is (tool.name in DESTRUCTIVE_TOOLS)


def test_only_genuinely_irreversible_writes_are_marked_destructive():
    """Kept deliberately small: marking ordinary additive writes destructive
    trains users to click through the confirmations that do matter."""
    from app.application.mcp.contracts import DESTRUCTIVE_TOOLS

    assert DESTRUCTIVE_TOOLS == {
        "lensword_cancel_companion_task",
        "lensword_finish_companion_session",
    }
    assert DESTRUCTIVE_TOOLS <= {tool.name for tool in TOOL_CONTRACTS}


def test_capabilities_publishes_title_description_and_annotations():
    payload = capabilities()
    for descriptor in payload["tools"]:
        assert descriptor["title"] and descriptor["description"]
        assert "readOnlyHint" in descriptor["annotations"]


def test_tool_names_are_loadable_by_strict_clients():
    """The constraint that forced the `lensword.x` -> `lensword_x` rename.

    MCP's own spec permits dots in tool names (it lists `admin.tools.list`
    as valid), but the Anthropic API restricts them to
    `^[a-zA-Z0-9_-]{1,64}$`. Claude therefore refused to load every tool
    here and reported "26 tools with unsupported names", so the stricter
    client rule is the one that actually governs. A tool the client won't
    load is not a tool.
    """
    import re

    loadable = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
    offenders = [tool.name for tool in TOOL_CONTRACTS if not loadable.fullmatch(tool.name)]
    assert not offenders, f"tool names a strict client will refuse to load: {offenders}"
