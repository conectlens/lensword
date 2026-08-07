"""Companion deep links for the existing notification outbox (#197 TODO 0).

The success metric this exists to satisfy: "no unsolicited companion message
is represented as an MCP capability". LensWord decides a notification is
owed exactly as it always has (a reminder firing, an acquisition rung coming
due) and the delivery channels/quiet-hours/pause/cap policy in
RecallDeliveryPolicy is untouched. This module only ever adds *where a
notification goes if the user opens it* — a `lensword://` URI the desktop
shell can hand to a host, matching #193's `lensword://session/{id}` resume
template or one of the bounded prompt names `apps/mcp`'s server advertises.
Nothing here can cause a push; it is read only when a human already decided
to act on a notification that fired for an ordinary, existing reason.
"""
from __future__ import annotations

_KNOWN_PROMPTS = frozenset(
    {
        "daily_check_in",
        "practice_conversation",
        "review_weakness",
        "explain_word",
        "prepare_for_topic",
        "reflect_on_session",
        "developer_vocabulary_session",
    }
)


def companion_notification_deep_link(
    companion_enabled: bool,
    *,
    prompt: str = "daily_check_in",
    session_id: str | None = None,
) -> str | None:
    """A deep link for a notification, or None if the account opted out.

    `session_id` wins when present: resuming an existing companion session
    (#193's `resume_companion_session`) is always preferable to opening a
    fresh prompt. Otherwise the link points at one of the bounded prompts
    `apps/mcp`'s server already exposes, so a client that does not recognise
    it can still treat it as "start a chat" and fall through safely.
    """
    if not companion_enabled:
        return None
    if session_id:
        if not session_id.strip() or len(session_id) > 64:
            raise ValueError("session_id must contain 1-64 characters")
        return f"lensword://session/{session_id}"
    if prompt not in _KNOWN_PROMPTS:
        raise ValueError(f"unknown companion prompt: {prompt}")
    return f"lensword://prompt/{prompt}"
