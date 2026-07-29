from datetime import datetime, timedelta
from app.domain.services.mcp_policy import AccessClass, GrantMode, MCPGrant, MCPPolicyGate, redact_and_chain

def test_policy_is_deny_by_default_and_honors_revocation_rate_and_payload_limits():
    now = datetime(2026, 1, 1)
    grant = MCPGrant("agent", "server", "read_words", AccessClass.READ, "workspace", GrantMode.ONCE)
    gate = MCPPolicyGate([grant], max_calls=1, max_payload_bytes=10)
    assert gate.authorize("agent", "server", "missing", AccessClass.READ, "workspace", 1, now).reason == "no_grant"
    assert gate.authorize("agent", "server", "read_words", AccessClass.READ, "workspace", 11, now).reason == "payload_too_large"
    assert gate.authorize("agent", "server", "read_words", AccessClass.READ, "workspace", 1, now).allowed
    assert gate.authorize("agent", "server", "read_words", AccessClass.READ, "workspace", 1, now).allowed is False

def test_high_impact_requires_confirmation_and_audit_redacts_secrets():
    now = datetime(2026, 1, 1)
    grant = MCPGrant("agent", "server", "delete_word", AccessClass.DESTRUCTIVE, "workspace", GrantMode.ALWAYS)
    decision = MCPPolicyGate([grant]).authorize("agent", "server", "delete_word", AccessClass.DESTRUCTIVE, "workspace", 1, now)
    assert decision.requires_confirmation and not decision.allowed
    event, digest = redact_and_chain("0", {"tool": "x", "token": "secret", "clipboard": "private"})
    assert event["token"] == event["clipboard"] == "[REDACTED]" and len(digest) == 64
