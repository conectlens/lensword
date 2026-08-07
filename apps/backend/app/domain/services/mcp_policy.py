"""Deny-by-default authorization primitives for the future MCP boundary.

MCP handlers must call :meth:`MCPPolicyGate.authorize` before invoking any
application use case, and append its decision through the audit repository.
The module intentionally has no MCP/FastAPI imports so both inbound and
outbound adapters enforce the identical policy.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps


class AccessClass(StrEnum):
    READ = "read"
    WRITE = "write"
    HIGH_IMPACT = "high_impact"
    DESTRUCTIVE = "destructive"


class GrantMode(StrEnum):
    ONCE = "once"
    ALWAYS = "always"
    DENY = "deny"


@dataclass(slots=True)
class MCPGrant:
    requester: str
    server: str
    tool: str
    access: AccessClass
    workspace: str
    mode: GrantMode
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    consumed_at: datetime | None = None

    def permits(self, now: datetime) -> bool:
        return self.mode != GrantMode.DENY and self.revoked_at is None and (self.expires_at is None or now < self.expires_at) and (self.mode != GrantMode.ONCE or self.consumed_at is None)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    requires_confirmation: bool = False


class MCPPolicyGate:
    """Pure deny-by-default policy evaluation with deterministic rate limits."""
    def __init__(self, grants: list[MCPGrant], *, max_payload_bytes: int = 65_536, max_calls: int = 30, window: timedelta = timedelta(minutes=1), calls: dict[tuple[str, str], list[datetime]] | None = None):
        self.grants, self.max_payload_bytes, self.max_calls, self.window = grants, max_payload_bytes, max_calls, window
        self._calls = calls if calls is not None else {}

    def authorize(self, requester: str, server: str, tool: str, access: AccessClass, workspace: str, payload_bytes: int, now: datetime) -> PolicyDecision:
        if payload_bytes > self.max_payload_bytes: return PolicyDecision(False, "payload_too_large")
        key = (requester, tool); calls = [at for at in self._calls.get(key, []) if at > now - self.window]
        if len(calls) >= self.max_calls: return PolicyDecision(False, "rate_limited")
        grant = next((item for item in self.grants if (item.requester, item.server, item.tool, item.access, item.workspace) == (requester, server, tool, access, workspace)), None)
        if grant is None: return PolicyDecision(False, "no_grant")
        if not grant.permits(now): return PolicyDecision(False, "grant_revoked_or_expired")
        if access in (AccessClass.HIGH_IMPACT, AccessClass.DESTRUCTIVE): return PolicyDecision(False, "confirmation_required", True)
        calls.append(now); self._calls[key] = calls
        if grant.mode == GrantMode.ONCE: grant.consumed_at = now
        return PolicyDecision(True, "granted")


def redact_and_chain(previous_hash: str, event: dict) -> tuple[dict, str]:
    """Redact secret-bearing keys and return a tamper-evident hash-chain link."""
    sensitive = ("token", "authorization", "clipboard", "screenshot", "password", "secret", "api_key", "credential")

    def redact(value):
        if isinstance(value, dict):
            return {key: "[REDACTED]" if any(word in key.lower() for word in sensitive) else redact(item) for key, item in value.items()}
        if isinstance(value, list): return [redact(item) for item in value]
        return value

    redacted = redact(event)
    encoded = dumps({"previous_hash": previous_hash, "event": redacted}, sort_keys=True, separators=(",", ":"))
    return redacted, sha256(encoded.encode()).hexdigest()


def verify_chain(links: Iterable[tuple[str, dict, str]]) -> int | None:
    """Recompute an MCP audit hash chain and report the first broken link.

    `links` is the persisted `(previous_hash, event, event_hash)` triple for
    each `MCPAuditEventModel` row, oldest first. Each link's `event_hash` is
    recomputed from its own `previous_hash`/`event` (via `redact_and_chain`,
    which is idempotent on an already-redacted event) and compared against
    the stored value; each link's `previous_hash` is also compared against
    the prior link's stored `event_hash`. Either mismatch means the stored
    row was mutated after the fact (an attacker with direct database access
    editing an audit event, or corruption) rather than genuinely produced by
    this chain.

    Returns the zero-based index of the first link that fails to verify, or
    `None` if the whole chain is intact. issue #199 TODO 2: this is the
    verification half of `redact_and_chain`'s tamper-evidence claim — a hash
    chain nothing ever recomputes and compares is not actually tamper
    *evident*, only tamper-shaped.
    """
    prior_event_hash: str | None = None
    for index, (previous_hash, event, event_hash) in enumerate(links):
        if prior_event_hash is not None and previous_hash != prior_event_hash:
            return index
        _, recomputed_hash = redact_and_chain(previous_hash, event)
        if recomputed_hash != event_hash:
            return index
        prior_event_hash = event_hash
    return None
