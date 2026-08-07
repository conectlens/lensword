"""Issue #199 TODO 1: "no advertised-but-fake capability" audit.

The single most valuable, purely-achievable deliverable this issue names:
walk `capabilities()`'s declared tool surface (app/application/mcp/contracts.py)
and cross-check it against the *real* dispatcher composition root used by the
production `/api/v1/mcp/invoke` boundary (`app.api.routers.mcp._handlers`) —
not a hand-rolled duplicate of the tool list, and not merely the contract
registry, which is a separate module that could drift from what is actually
wired up.

Before this file, a tool present in `TOOL_CONTRACTS` but missing from
`_handlers()` would only ever surface as a `501 "MCP tool is not bound"` the
first time some caller actually invoked it (`UnboundMCPToolError`, exercised
generically but never exhaustively in test_mcp_contracts.py's dispatcher
test). This file makes that check exhaustive and runs at test-collection
time for every one of the 27 declared tools, so a future PR that adds a
`ToolContract` without wiring a handler fails CI immediately instead of
shipping a dead tool.
"""
from __future__ import annotations

from app.api.routers.mcp import _handlers
from app.application.mcp.contracts import TOOL_CONTRACTS, capabilities
from app.application.mcp.dispatcher import MCPDispatcher
from app.infrastructure.repositories import (
    SqlAlchemyCompanionActivityRepository,
    SqlAlchemyCompanionSessionRepository,
    SqlAlchemyCompanionTaskRepository,
    SqlAlchemyDiagnosisRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyLearningObservationRepository,
    SqlAlchemyPracticeExerciseRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyReviewSessionRepository,
    SqlAlchemyWordRepository,
)


def _real_handlers(db_session) -> dict:
    """Build the exact same handler dict `invoke()`/`read_resource()` build
    per-request in app/api/routers/mcp.py, using real SQLAlchemy repository
    adapters bound to the test database rather than fakes — the point is to
    audit the actual transport composition root, not a stand-in for it."""
    return _handlers(
        SqlAlchemyGroupRepository(db_session),
        SqlAlchemyWordRepository(db_session),
        SqlAlchemyReviewSessionRepository(db_session),
        SqlAlchemyPracticeExerciseRepository(db_session),
        None,  # provider: OptionalAIProvider — unused by handler *presence* checks below
        SqlAlchemyCompanionSessionRepository(db_session),
        SqlAlchemyCompanionTaskRepository(db_session),
        SqlAlchemyRecallSettingsRepository(db_session),
        SqlAlchemyDiagnosisRepository(db_session),
        SqlAlchemyLearningObservationRepository(db_session),
        SqlAlchemyCompanionActivityRepository(db_session),
    )


def test_every_declared_tool_contract_has_a_real_bound_handler(db_session):
    handlers = _real_handlers(db_session)
    missing = [contract.name for contract in TOOL_CONTRACTS if contract.name not in handlers]
    assert not missing, (
        f"advertised in TOOL_CONTRACTS but not bound in mcp.py's _handlers(): {missing} "
        "— these tools would 501 the first time a caller invoked them."
    )
    assert all(callable(handlers[contract.name]) for contract in TOOL_CONTRACTS)


def test_capabilities_endpoint_advertises_exactly_the_bound_tool_set(db_session):
    """Not "at least" and not "roughly" — exactly. Fewer would mean a real,
    working handler is silently unreachable; more would mean a capability is
    ceremonial (advertised, but nothing dispatches it)."""
    handlers = _real_handlers(db_session)
    advertised = {tool["name"] for tool in capabilities()["tools"]}
    assert advertised == set(handlers.keys())


def test_dispatcher_built_from_the_real_handlers_resolves_every_contract(db_session):
    """A second, independent check through `MCPDispatcher` itself (the same
    class `/invoke` and `/resource` construct per-request) rather than
    inspecting the handlers dict directly — proves `contract_for` and
    `handlers.get` agree for the whole registry, not just that the dict has
    the right keys."""
    dispatcher = MCPDispatcher(_real_handlers(db_session))
    for contract in TOOL_CONTRACTS:
        resolved = dispatcher.contract_for(contract.name)
        assert resolved.name == contract.name
        assert dispatcher.handlers.get(contract.name) is not None


def test_every_tool_input_schema_is_well_formed_json_schema():
    """TODO 1's "enumerate every declared tool ... and assert its schema is
    well-formed" — a bounded, closed-vocabulary structural check matching
    what `validate_payload` itself is able to interpret (this codebase does
    not accept arbitrary JSON Schema, only the small subset `validate_payload`
    implements), so "well-formed" here means "actually enforceable by this
    server's own validator," not merely "parses as JSON."""
    for contract in TOOL_CONTRACTS:
        schema = contract.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema.get("required", []), list)
        for name in schema.get("required", []):
            assert name in schema["properties"], f"{contract.name}: required field {name!r} has no property definition"
        for prop_name, rules in schema["properties"].items():
            assert isinstance(prop_name, str) and prop_name
            has_type_or_enum = "type" in rules or "enum" in rules
            assert has_type_or_enum, f"{contract.name}.{prop_name} declares neither type nor enum"


def test_every_write_tool_requires_the_idempotency_key_and_every_read_tool_does_not():
    """Cross-checks the access classification against the schema shape it is
    supposed to imply — a write tool that forgot `request_id` would silently
    lose replay protection; a read tool that demanded one would be a needless
    caller-facing inconsistency."""
    from app.domain.services.mcp_policy import AccessClass

    for contract in TOOL_CONTRACTS:
        requires_request_id = "request_id" in contract.input_schema.get("required", [])
        if contract.access == AccessClass.READ:
            assert not requires_request_id, f"{contract.name} is READ but requires request_id"
        else:
            assert requires_request_id, f"{contract.name} is {contract.access} but does not require request_id"
