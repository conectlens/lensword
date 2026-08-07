"""Provider-neutral companion session state (issue #193).

The companion owns conversation style; LensWord owns this normalized state.
Only bounded turns and structured metadata are accepted here. Provider
memory, chain-of-thought, credentials, and opaque tool state have no field in
the model and therefore cannot be persisted accidentally.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CompanionSessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"
    REVOKED = "revoked"


class CompanionTurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class CompanionSession:
    id: str
    user_id: int
    connection_id: str
    client_id: str
    goal: str | None
    language: str | None
    group_id: int | None
    difficulty: str | None
    active_activity: str | None
    consent_snapshot: dict
    summary: str | None
    status: CompanionSessionStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    def _transition(self, status: CompanionSessionStatus) -> None:
        if self.status is CompanionSessionStatus.REVOKED:
            raise ValueError("A revoked companion session cannot be resumed")
        if self.status is CompanionSessionStatus.FINISHED and status is not CompanionSessionStatus.REVOKED:
            raise ValueError("A finished companion session cannot be reopened")
        self.status = status
        self.revision += 1

    def resume(self) -> None:
        self._transition(CompanionSessionStatus.ACTIVE)

    def pause(self) -> None:
        self._transition(CompanionSessionStatus.PAUSED)

    def finish(self) -> None:
        self._transition(CompanionSessionStatus.FINISHED)

    def revoke(self) -> None:
        self.status = CompanionSessionStatus.REVOKED
        self.revision += 1

    def update_summary(self, summary: str | None) -> None:
        if summary is not None and len(summary) > 4000:
            raise ValueError("Companion summaries are limited to 4000 characters")
        self.summary = summary
        self.revision += 1

    def transfer(self, connection_id: str, client_id: str) -> None:
        """Reassign which companion connection currently controls this
        session (#193 TODO 3), e.g. handing an active session from a desktop
        client to a mobile one. Distinct from `resume`: the session's status
        is untouched, only who may act on it next changes."""
        if self.status in (CompanionSessionStatus.FINISHED, CompanionSessionStatus.REVOKED):
            raise ValueError(f"Control of a {self.status.value} companion session cannot be transferred")
        if not (1 <= len(connection_id) <= 128):
            raise ValueError("A transferred companion session requires a bounded connection id")
        if not (1 <= len(client_id) <= 128):
            raise ValueError("A transferred companion session requires a bounded client id")
        self.connection_id = connection_id
        self.client_id = client_id
        self.revision += 1


@dataclass(frozen=True, slots=True)
class CompanionTurn:
    id: int | None
    session_id: str
    role: CompanionTurnRole
    content: str
    activity_id: str | None
    operation_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.content.strip() or len(self.content) > 10000:
            raise ValueError("Companion turn content must contain 1-10000 characters")
        if self.operation_id is not None and len(self.operation_id) > 128:
            raise ValueError("Companion operation_id is too long")


# --- Summarization (#193 TODO 2) --------------------------------------------
#
# `update_summary` above only stores whatever text a caller hands it — no
# generation, no grounding. What follows is the deterministic half of real
# summarization: pure functions, zero I/O, safe to run unconditionally as the
# always-available fallback. The optional AI-assisted half (calling an
# AIProvider and validating its output against these same facts before
# trusting it) is orchestration with I/O and belongs one layer up, in
# app.application.use_cases.companion_sessions — this module only produces
# and validates against the facts, it never talks to a provider.

# Only tokens shaped like the concrete, fabricable facts a summary can lie
# about are held to strict grounding: a bare number (a count that could be
# invented) or a hyphen/underscore-joined id (an activity id, a slug). Plain
# prose words are not checked, so a provider may freely paraphrase
# "turn_count: 4" as "four exchanges" — but it may not state a *different*
# count, id, or fact that was never supplied.
_NUMBER_TOKEN = re.compile(r"\d+")
_ID_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:[\-_][a-z0-9]+)+")


def extract_session_facts(session: CompanionSession, turns: Sequence[CompanionTurn]) -> tuple[str, ...]:
    """Bounded, literal facts about a session — the only material a summary,
    AI-generated or not, is permitted to describe."""
    facts: list[str] = [f"status: {session.status.value}"]
    if session.goal:
        facts.append(f"goal: {session.goal}")
    if session.language:
        facts.append(f"language: {session.language}")
    if session.difficulty:
        facts.append(f"difficulty: {session.difficulty}")
    if session.group_id is not None:
        facts.append(f"group_id: {session.group_id}")
    user_turns = sum(1 for turn in turns if turn.role is CompanionTurnRole.USER)
    assistant_turns = len(turns) - user_turns
    facts.append(f"turn_count: {len(turns)}")
    facts.append(f"user_turns: {user_turns}")
    facts.append(f"assistant_turns: {assistant_turns}")
    activities = sorted({turn.activity_id for turn in turns if turn.activity_id})
    if activities:
        facts.append(f"activities_touched: {', '.join(activities)}")
    return tuple(facts)


def deterministic_session_summary(facts: Sequence[str]) -> str:
    """Always-available fallback: a factual recap built only from
    `extract_session_facts`, with no generation and nothing to validate."""
    if not facts:
        return "No recorded activity in this companion session yet."
    text = "Session facts recorded by LensWord — " + "; ".join(facts) + "."
    return text[:4000]


def summary_is_grounded(text: str, facts: Sequence[str]) -> bool:
    """True if every checkable claim in `text` traces back to `facts`.

    Deliberately conservative in one direction only: numbers, activity ids,
    and other id-shaped tokens in the candidate summary must appear
    somewhere in the source facts, or the whole summary is rejected as
    having invented a detail. Ordinary prose words are not required to
    appear verbatim — a provider is allowed to paraphrase "turn_count: 4" as
    "four exchanges", but not allowed to state a count, id, or fact that
    was never supplied.
    """
    if not text or not text.strip():
        return False
    fact_corpus = " ".join(facts).casefold()
    fact_numbers = set(_NUMBER_TOKEN.findall(fact_corpus))
    fact_ids = set(_ID_TOKEN.findall(fact_corpus))
    candidate = text.casefold()
    if any(number not in fact_numbers for number in _NUMBER_TOKEN.findall(candidate)):
        return False
    if any(token not in fact_ids for token in _ID_TOKEN.findall(candidate)):
        return False
    return True
