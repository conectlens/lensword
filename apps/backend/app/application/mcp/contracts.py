"""Versioned, transport-neutral LensWord MCP contract registry.

An MCP adapter may expose these descriptors over stdio/HTTP, but it must map
calls to application use cases only—repositories never cross this boundary.
"""
from __future__ import annotations
from dataclasses import dataclass
from app.domain.services.companion_activities import ActivityType
from app.domain.services.mcp_policy import AccessClass

CONTRACT_VERSION = "1.0.0"
MAX_PAGE_SIZE = 100

# Bounded, closed vocabulary of where a developer-context sighting came from
# (issue #188 TODOs 2/4). Kept here, beside the contract that names it in a
# tool schema, so the schema and the use case that enforces it again
# (app.application.use_cases.mcp_dev_workflow) can never quietly diverge.
CONTEXT_KINDS = (
    "commit_message",
    "pull_request",
    "readme",
    "documentation",
    "terminal_output",
    "prompt",
    "explanation",
    "stack_trace",
)

@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    schema_id: str
    access: AccessClass
    input_schema: dict
    errors: tuple[str, ...] = ("unauthorized", "validation_error", "not_found", "rate_limited")

def _schema(properties: dict, required: list[str] = [], *, write: bool = False) -> dict:
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "properties": properties, "required": list(required)}
    if write:
        # Mandatory idempotency for writes (issue #196 TODO 4): every write
        # tool's caller must supply a client-chosen `request_id`, so
        # mcp.py's IdempotencyStore can always dedupe a retried call instead
        # of that being an opt-in the caller could simply omit.
        base["properties"]["request_id"] = {"type": "string", "minLength": 1, "maxLength": 128}
        base["required"].append("request_id")
    return base

TOOL_CONTRACTS = tuple(ToolContract(name, f"https://lensword.app/mcp/{CONTRACT_VERSION}/{name}.schema.json", access, schema) for name, access, schema in (
    ("lensword.add_word", AccessClass.WRITE, _schema({"group_id": {"type":"integer", "minimum":1}, "term":{"type":"string","minLength":1,"maxLength":255}, "target_language":{"type":"string"}, "translations":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":255}}}, ["group_id","term","target_language"], write=True)),
    ("lensword.search_words", AccessClass.READ, _schema({"query":{"type":"string","maxLength":255}, "limit":{"type":"integer","minimum":1,"maximum":100}, "cursor":{"type":"string","maxLength":256}})),
    ("lensword.extract_vocabulary", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "text":{"type":"string","minLength":1,"maxLength":20000}, "target_language":{"type":"string"}, "max_items":{"type":"integer","minimum":1,"maximum":50}}, ["group_id","text","target_language"], write=True)),
    ("lensword.get_due_reviews", AccessClass.READ, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}, "cursor":{"type":"string","maxLength":256}})),
    ("lensword.create_study_session", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}}, write=True)),
    ("lensword.generate_exercises", AccessClass.WRITE, _schema({"word_id":{"type":"integer","minimum":1}, "kind":{"enum":["translation","definition","cloze"]}}, ["word_id"], write=True)),
    ("lensword.get_learning_progress", AccessClass.READ, _schema({"week":{"type":"string","maxLength":32}})),
    ("lensword.record_answer", AccessClass.WRITE, _schema({"session_id":{"type":"integer","minimum":1}, "word_id":{"type":"integer","minimum":1}, "outcome":{"enum":["correct","incorrect","skipped"]}}, ["session_id","word_id","outcome"], write=True)),
    # Companion task tools (#197 TODO 2): genuinely long-running work only.
    # `start_extraction_task` wraps the existing companion_tasks.py state
    # machine and the background executor in
    # app.infrastructure.jobs.companion_task_dispatch — it never does the
    # work synchronously itself, only creates the durable task record. The
    # MCP transport (apps/mcp/lensword_mcp/server.py) gates exposing it on
    # the client having declared task capability during initialize.
    # `get_companion_task`/`cancel_companion_task` are generic and cover any
    # task type, including `plan_generation` tasks created through
    # `app.api.routers.companion_tasks`'s own generate-plan/confirm-plan
    # flow (#194 TODO 4) — there is deliberately no `start_plan_generation_
    # task` tool here, since that flow already exists and this would only
    # duplicate it (see companion_task_dispatch.py's module docstring).
    ("lensword.start_extraction_task", AccessClass.WRITE, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "text":{"type":"string","minLength":1,"maxLength":8000}, "target_language":{"type":"string","minLength":1,"maxLength":64}, "max_terms":{"type":"integer","minimum":1,"maximum":50}}, ["companion_session_id","text","target_language"], write=True)),
    ("lensword.get_companion_task", AccessClass.READ, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "task_id":{"type":"string","minLength":1,"maxLength":64}}, ["companion_session_id","task_id"])),
    ("lensword.cancel_companion_task", AccessClass.WRITE, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "task_id":{"type":"string","minLength":1,"maxLength":64}}, ["companion_session_id","task_id"], write=True)),
    # Durable companion sessions (#193 TODO 1). `session_id` is the opaque
    # hex id `CompanionSession.id` — bounded to 64 chars to match
    # CompanionSessionModel.id (String(64)), same as every other resource
    # id in this registry.
    ("lensword.start_companion_session", AccessClass.WRITE, _schema({
        "connection_id": {"type":"string","minLength":1,"maxLength":128},
        "client_id": {"type":"string","minLength":1,"maxLength":128},
        "goal": {"type":"string","maxLength":500},
        "language": {"type":"string","maxLength":64},
        "group_id": {"type":"integer","minimum":1},
        "difficulty": {"type":"string","maxLength":32},
        "active_activity": {"type":"string","maxLength":128},
    }, ["connection_id","client_id"], write=True)),
    ("lensword.get_companion_session", AccessClass.READ, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"])),
    ("lensword.resume_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    ("lensword.pause_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    ("lensword.finish_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    # Learner-aware developer-workflow tools (issue #188 TODO 3). Every one
    # of these but the last is read-only by construction: none of them can
    # mark a word mastered or create a Diagnosis. record_context_occurrence
    # is the sole write, and it writes a single low-trust LearningObservation
    # (never a Word/ReviewState mutation) — see
    # app.application.use_cases.mcp_dev_workflow for why that boundary holds.
    ("lensword.get_language_profile", AccessClass.READ, _schema({})),
    ("lensword.check_known_term", AccessClass.READ, _schema({"term":{"type":"string","minLength":1,"maxLength":255}}, ["term"])),
    ("lensword.explain_for_user", AccessClass.READ, _schema({"word_id":{"type":"integer","minimum":1}}, ["word_id"])),
    ("lensword.suggest_stretch_vocabulary", AccessClass.READ, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":50}})),
    ("lensword.record_context_occurrence", AccessClass.WRITE, _schema({"word_id":{"type":"integer","minimum":1}, "context_kind":{"enum":list(CONTEXT_KINDS)}, "outcome":{"enum":["correct","incorrect"]}, "confirmed":{"type":"boolean"}}, ["word_id","context_kind","outcome","confirmed"], write=True)),
    # Measurable companion activities and companion action tools (issue
    # #194 TODO 1). `begin_learning_activity` fixes `expected_evaluation`
    # once, and nothing here — not even `submit_activity_response` — can
    # change it afterward (#194 TODO 5): the companion cannot submit an
    # expected answer after seeing the learner's response.
    ("lensword.begin_learning_activity", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_type": {"enum": [item.value for item in ActivityType]},
        "prompt": {"type":"string","minLength":1,"maxLength":4000},
        "expected_evaluation": {"type":"object"},
    }, ["session_id","activity_type","prompt"], write=True)),
    ("lensword.submit_activity_response", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
        "response": {"type":"string","minLength":1,"maxLength":10000},
    }, ["session_id","activity_id","response"], write=True)),
    ("lensword.get_activity_result", AccessClass.READ, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"])),
    ("lensword.finish_learning_activity", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"], write=True)),
    # A write, not a read: it increments the activity's bounded hint
    # counter (MAX_HINTS_PER_ACTIVITY) and persists that.
    ("lensword.request_hint", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"], write=True)),
    ("lensword.explain_evidence", AccessClass.READ, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"])),
))

def capabilities() -> dict:
    return {"version": CONTRACT_VERSION, "compatibility": "minor versions are additive; major versions require explicit client opt-in", "tools": [{"name": tool.name, "schema_id": tool.schema_id, "access": tool.access.value, "input_schema": tool.input_schema, "errors": tool.errors} for tool in TOOL_CONTRACTS]}


def validate_payload(contract: ToolContract, payload: dict) -> str | None:
    """Validate the bounded JSON-schema subset used by MCP contracts.

    Keeping this small validator beside the registry makes contract enforcement
    available without accepting arbitrary schema features or adding a second
    dynamic execution surface. It deliberately fails closed on every unknown
    property and malformed primitive.
    """
    schema = contract.input_schema
    if not isinstance(payload, dict):
        return "payload must be an object"
    properties = schema["properties"]
    unknown = set(payload) - set(properties)
    if unknown:
        return f"unsupported payload field: {sorted(unknown)[0]}"
    missing = [name for name in schema.get("required", []) if name not in payload]
    if missing:
        return f"missing required payload field: {missing[0]}"
    for name, value in payload.items():
        rules = properties[name]
        if "enum" in rules and value not in rules["enum"]:
            return f"invalid value for {name}"
        expected = rules.get("type")
        if expected == "string":
            if not isinstance(value, str): return f"{name} must be a string"
            if len(value) < rules.get("minLength", 0) or len(value) > rules.get("maxLength", float("inf")):
                return f"{name} has an invalid length"
        elif expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"{name} must be an integer"
        elif expected == "integer" and not rules.get("minimum", float("-inf")) <= value <= rules.get("maximum", float("inf")):
            return f"{name} is out of range"
        elif expected == "array":
            if not isinstance(value, list): return f"{name} must be an array"
            if len(value) > rules.get("maxItems", float("inf")): return f"{name} has too many items"
            item_rules = rules.get("items", {})
            if item_rules.get("type") == "string" and any(not isinstance(item, str) or len(item) > item_rules.get("maxLength", float("inf")) for item in value):
                return f"{name} contains an invalid item"
        elif expected == "boolean" and not isinstance(value, bool):
            return f"{name} must be a boolean"
    return None
