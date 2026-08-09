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
# Every tool in the contract registry must appear under exactly one scope.
# When it did not, the consequence was silent and total: a tool absent from
# this mapping can never be granted to a remote OAuth caller, so it is
# permanently unreachable over /invoke and answers `no_grant` forever. Only
# eight tools were mapped here while the registry had grown past twenty,
# which is why an audit of the remote surface found the entire companion
# subsystem — `start_companion_session` and everything gated behind it —
# returning 403 with no indication that the cause was a missing line in this
# file rather than a revoked or expired consent.
#
# `test_mcp_scopes.py` asserts that coverage exhaustively, so a tool added to
# contracts.py without a scope now fails the suite instead of shipping dark.
#
# The eight scope *names* remain exactly the set issue #196 specifies: they
# are the vocabulary a resource owner sees on a consent screen, and adding a
# ninth would change what existing approvals mean. Tools are therefore sorted
# into the closest existing scope rather than given bespoke ones. The one
# consequence worth stating plainly: `card-write` now includes
# `lensword_delete_word`, so approving it authorizes removing vocabulary as
# well as adding it. That tool separately requires an explicit
# `confirmed: true` in its payload, so consent alone cannot destroy data
# without the caller also asserting intent per call.
SCOPE_TOOLS: dict[MCPScope, tuple[str, ...]] = {
    # Profile is also exposed as an MCP *resource* (lensword://me/profile);
    # the tool below is the /invoke equivalent of that same read.
    MCPScope.PROFILE_READ: ("lensword_get_language_profile",),
    MCPScope.VOCABULARY_READ: (
        "lensword_search_words",
        "lensword_list_groups",
        "lensword_list_group_words",
        "lensword_check_known_term",
        "lensword_explain_for_user",
        "lensword_suggest_stretch_vocabulary",
        "lensword_get_word_map",
        "lensword_get_mnemonics",
        "lensword_list_rooms",
    ),
    MCPScope.SESSION_READ: (
        "lensword_get_due_reviews",
        "lensword_get_companion_session",
        "lensword_get_companion_task",
        "lensword_get_activity_result",
        "lensword_explain_evidence",
    ),
    MCPScope.PROGRESS_READ: ("lensword_get_learning_progress",),
    # The companion loop: session lifecycle plus the measurable activities
    # conducted inside one. These are "conversation" writes in the sense the
    # scope name intends — they advance a coaching dialogue and record what
    # happened in it.
    MCPScope.CONVERSATION_WRITE: (
        "lensword_start_companion_session",
        "lensword_resume_companion_session",
        "lensword_pause_companion_session",
        "lensword_finish_companion_session",
        "lensword_begin_learning_activity",
        "lensword_submit_activity_response",
        "lensword_finish_learning_activity",
        "lensword_request_hint",
    ),
    MCPScope.REVIEW_WRITE: ("lensword_create_study_session", "lensword_record_answer"),
    MCPScope.CARD_WRITE: (
        "lensword_add_word",
        "lensword_generate_exercises",
        "lensword_create_group",
        "lensword_update_word",
        "lensword_delete_word",
        "lensword_create_room",
        "lensword_place_word_in_room",
        "lensword_generate_mnemonic",
        # Batched siblings (issue #348) sit in the same scope as the
        # single-item tool each one batches. A scope is what a resource owner
        # approves on a consent screen, and "place words in a room" is not a
        # different permission from "place a word in a room" — filing a batch
        # elsewhere would make consent depend on call shape rather than on
        # what the call can do.
        "lensword_place_words_in_room",
        "lensword_generate_exercises_for_words",
        "lensword_add_words",
        "lensword_update_words",
    ),
    MCPScope.CONTEXT_IMPORT: (
        "lensword_extract_vocabulary",
        "lensword_start_extraction_task",
        "lensword_cancel_companion_task",
        "lensword_record_context_occurrence",
        "lensword_record_context_occurrences",
    ),
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
