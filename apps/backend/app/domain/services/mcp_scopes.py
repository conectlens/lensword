"""Closed OAuth scope vocabulary for remote MCP companions (issue #196).

Scopes are a *consent-time* concept: a remote OAuth client requests some of
these, the resource owner approves a subset, and each approved scope expands
to concrete (tool, AccessClass) pairs that are provisioned as ordinary
`MCPGrantModel` rows and enforced by the existing deny-by-default
`MCPPolicyGate` in mcp_policy.py. Scopes never bypass that gate and never
grant an AccessClass wider than the tool's own contract in
app/application/mcp/contracts.py already declares — this module only decides
*which* tools a scope unlocks, not how strongly.

Deliberately a plain module-level mapping rather than a class: it is data,
not behaviour, and keeping it here (next to the enum) means adding a tool to
a scope is a one-line, reviewable diff.
"""
from __future__ import annotations

from enum import StrEnum


class MCPScope(StrEnum):
    """The eight scopes issue #196 asks for, verbatim."""

    PROFILE_READ = "profile-read"
    VOCABULARY_READ = "vocabulary-read"
    SESSION_READ = "session-read"
    PROGRESS_READ = "progress-read"
    CONVERSATION_WRITE = "conversation-write"
    REVIEW_WRITE = "review-write"
    CARD_WRITE = "card-write"
    CONTEXT_IMPORT = "context-import"


# Which MCP tools (app/application/mcp/contracts.py) each scope unlocks.
#
# profile-read and conversation-write map to no MCP *tool* today: profile is
# exposed as an MCP *resource* (lensword://me/profile, read via the honest
# resource endpoint added in mcp.py, not the stdio transport's REST-passthrough
# shortcut — see the PR description for why those are not the same thing for a
# remote token), and no MCP tool yet exists for writing a conversation turn.
# Listing them with an empty tuple is deliberate: the scope is real and
# selectable during consent, it just authorizes nothing on the /invoke
# surface yet, which is the honest state of this codebase today rather than a
# scope this module pretends is wired up.
SCOPE_TOOLS: dict[MCPScope, tuple[str, ...]] = {
    MCPScope.PROFILE_READ: (),
    MCPScope.VOCABULARY_READ: ("lensword_search_words",),
    MCPScope.SESSION_READ: ("lensword_get_due_reviews",),
    MCPScope.PROGRESS_READ: ("lensword_get_learning_progress",),
    MCPScope.CONVERSATION_WRITE: (),
    MCPScope.REVIEW_WRITE: ("lensword_create_study_session", "lensword_record_answer"),
    MCPScope.CARD_WRITE: ("lensword_add_word", "lensword_generate_exercises"),
    MCPScope.CONTEXT_IMPORT: ("lensword_extract_vocabulary",),
}

# Which MCP *resources* (server.py's _RESOURCE_DESCRIPTORS) each scope
# unlocks through the scoped resource endpoint. Deliberately a small subset
# of the full stdio resource list — see mcp.py's `read_resource` for why a
# remote OAuth token cannot use the same broad REST-passthrough the local
# stdio transport uses.
SCOPE_RESOURCES: dict[MCPScope, tuple[str, ...]] = {
    MCPScope.SESSION_READ: ("lensword://me/due",),
    MCPScope.VOCABULARY_READ: ("lensword://me/active-words",),
    MCPScope.PROGRESS_READ: ("lensword://me/progress",),
}


def parse_scope_string(raw: str) -> frozenset[MCPScope]:
    """Parse an OAuth space-delimited scope string, dropping unknown tokens.

    Dropping rather than raising mirrors RFC 6749 section 3.3: a server may
    grant a subset of what was requested. The token endpoint response always
    reports the actually-granted `scope`, so a client relying on strict
    RFC 6749 behaviour still sees the truth.
    """
    result: set[MCPScope] = set()
    for token in raw.split():
        try:
            result.add(MCPScope(token))
        except ValueError:
            continue
    return frozenset(result)


def tools_for_scopes(scopes: frozenset[MCPScope]) -> frozenset[str]:
    tools: set[str] = set()
    for scope in scopes:
        tools.update(SCOPE_TOOLS.get(scope, ()))
    return frozenset(tools)


def resources_for_scopes(scopes: frozenset[MCPScope]) -> frozenset[str]:
    resources: set[str] = set()
    for scope in scopes:
        resources.update(SCOPE_RESOURCES.get(scope, ()))
    return frozenset(resources)
