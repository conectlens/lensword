"""Versioned, transport-neutral LensWord MCP contract registry.

An MCP adapter may expose these descriptors over stdio/HTTP, but it must map
calls to application use cases only—repositories never cross this boundary.
"""
from __future__ import annotations
from dataclasses import dataclass
from app.domain.services.mcp_policy import AccessClass

CONTRACT_VERSION = "1.0.0"
MAX_PAGE_SIZE = 100

@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    schema_id: str
    access: AccessClass
    input_schema: dict
    errors: tuple[str, ...] = ("unauthorized", "validation_error", "not_found", "rate_limited")

def _schema(properties: dict, required: list[str] = [], *, write: bool = False) -> dict:
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "properties": properties, "required": required}
    if write: base["properties"]["request_id"] = {"type": "string", "minLength": 1, "maxLength": 128}
    return base

TOOL_CONTRACTS = tuple(ToolContract(name, f"https://lensword.app/mcp/{CONTRACT_VERSION}/{name}.schema.json", access, schema) for name, access, schema in (
    ("lensword.add_word", AccessClass.WRITE, _schema({"group_id": {"type":"integer", "minimum":1}, "term":{"type":"string","minLength":1,"maxLength":255}, "target_language":{"type":"string"}, "translations":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":255}}}, ["group_id","term","target_language"], write=True)),
    ("lensword.search_words", AccessClass.READ, _schema({"query":{"type":"string","maxLength":255}, "limit":{"type":"integer","minimum":1,"maximum":100}, "cursor":{"type":"string","maxLength":256}})),
    ("lensword.extract_vocabulary", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "text":{"type":"string","minLength":1,"maxLength":20000}, "target_language":{"type":"string"}, "max_items":{"type":"integer","minimum":1,"maximum":50}}, ["group_id","text","target_language"], write=True)),
    ("lensword.get_due_reviews", AccessClass.READ, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}})),
    ("lensword.create_study_session", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}}, write=True)),
    ("lensword.generate_exercises", AccessClass.WRITE, _schema({"word_id":{"type":"integer","minimum":1}, "kind":{"enum":["translation","definition","cloze"]}}, ["word_id"], write=True)),
    ("lensword.get_learning_progress", AccessClass.READ, _schema({"week":{"type":"string","maxLength":32}})),
    ("lensword.record_answer", AccessClass.WRITE, _schema({"session_id":{"type":"integer","minimum":1}, "word_id":{"type":"integer","minimum":1}, "outcome":{"enum":["correct","incorrect","skipped"]}}, ["session_id","word_id","outcome"], write=True)),
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
    return None
