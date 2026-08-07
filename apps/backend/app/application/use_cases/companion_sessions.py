"""Companion session use cases (#193): start/get/transition and
summarization, shared by the REST router (app.api.routers.companion) and the
MCP tool bindings (app.application.mcp.bindings) so the two surfaces cannot
drift into different behaviour for the same session — a resume over MCP and
a resume over REST must mean the same thing for cross-client continuity to
hold at all.
"""
from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.domain.exceptions import AIProviderUnavailableError, EntityNotFoundError
from app.domain.repositories import CompanionSessionRepository
from app.domain.services.ai_provider import AIProvider
from app.domain.services.companion_sessions import (
    CompanionSession,
    CompanionSessionStatus,
    deterministic_session_summary,
    extract_session_facts,
    summary_is_grounded,
)
from app.domain.value_objects import utcnow


class SummarizeCompanionSessionUseCase:
    """`CompanionSession.update_summary` is a pure setter — it stores
    whatever text it is given. Generating that text is orchestration with
    I/O (it may call an AIProvider) and so lives here, one layer above the
    domain, not inside `app.domain.services.companion_sessions`.

    The deterministic path is always available and always correct by
    construction: it is built only from `extract_session_facts`, which reads
    straight off the stored session and turns. The AI path is optional, and
    its output is trusted only after `summary_is_grounded` confirms it did
    not introduce a number, activity id, or other checkable detail absent
    from those same facts — an ungrounded or unavailable provider falls back
    to the deterministic summary rather than failing the request.
    """

    def __init__(self, session_repo: CompanionSessionRepository, provider: AIProvider | None):
        self.session_repo = session_repo
        self.provider = provider

    async def build_summary(self, session: CompanionSession) -> tuple[str, str]:
        """Return (summary_text, source) without persisting anything.

        `source` is "deterministic" or "ai", so callers (and tests) can tell
        which path actually produced the text rather than inferring it from
        the string contents.
        """
        turns = self.session_repo.list_turns(session.user_id, session.id)
        facts = extract_session_facts(session, turns)
        summary = deterministic_session_summary(facts)
        source = "deterministic"
        if self.provider is not None:
            try:
                candidate = await self.provider.generate_field(
                    "companion_session_summary",
                    session.id,
                    None,
                    session.language or "English",
                    "; ".join(facts),
                )
            except AIProviderUnavailableError:
                candidate = None
            if candidate and summary_is_grounded(candidate, facts):
                summary = candidate.strip()[:4000]
                source = "ai"
        return summary, source


class StartCompanionSessionUseCase:
    def __init__(self, session_repo: CompanionSessionRepository):
        self.session_repo = session_repo

    def execute(
        self,
        user_id: int,
        *,
        connection_id: str,
        client_id: str,
        goal: str | None = None,
        language: str | None = None,
        group_id: int | None = None,
        difficulty: str | None = None,
        active_activity: str | None = None,
        consent_snapshot: dict | None = None,
    ) -> CompanionSession:
        now = utcnow()
        return self.session_repo.add(
            CompanionSession(
                id=uuid4().hex,
                user_id=user_id,
                connection_id=connection_id,
                client_id=client_id,
                goal=goal,
                language=language,
                group_id=group_id,
                difficulty=difficulty,
                active_activity=active_activity,
                consent_snapshot=consent_snapshot or {},
                summary=None,
                status=CompanionSessionStatus.ACTIVE,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )


class GetCompanionSessionUseCase:
    def __init__(self, session_repo: CompanionSessionRepository):
        self.session_repo = session_repo

    def execute(self, user_id: int, session_id: str) -> CompanionSession:
        session = self.session_repo.get(user_id, session_id)
        if session is None:
            raise EntityNotFoundError("Companion session", session_id)
        return session


class TransitionCompanionSessionUseCase:
    """A single domain mutation (resume/pause/revoke/transfer/...) with a
    real optimistic-locking write-back (#193 TODO 3): the revision seen on
    read is the revision the repository's WHERE clause must still see when
    the write lands, or `ConcurrentModificationError` is raised rather than
    silently overwriting a concurrent change.
    """

    def __init__(self, session_repo: CompanionSessionRepository):
        self.session_repo = session_repo

    def execute(
        self, user_id: int, session_id: str, mutate: Callable[[CompanionSession], None]
    ) -> CompanionSession:
        session = self.session_repo.get(user_id, session_id)
        if session is None:
            raise EntityNotFoundError("Companion session", session_id)
        expected_revision = session.revision
        mutate(session)
        session.updated_at = utcnow()
        return self.session_repo.update(session, expected_revision=expected_revision)


class FinishCompanionSessionUseCase:
    """Finishing is the natural point to summarize (#193 TODO 2): the
    conversation is over, so the recap is generated once from the final set
    of turns and stored atomically with the status change, rather than left
    for a client to request separately."""

    def __init__(self, session_repo: CompanionSessionRepository, provider: AIProvider | None):
        self.session_repo = session_repo
        self.provider = provider

    async def execute(self, user_id: int, session_id: str) -> CompanionSession:
        session = self.session_repo.get(user_id, session_id)
        if session is None:
            raise EntityNotFoundError("Companion session", session_id)
        summary, _source = await SummarizeCompanionSessionUseCase(self.session_repo, self.provider).build_summary(
            session
        )
        expected_revision = session.revision
        session.update_summary(summary)
        session.finish()
        session.updated_at = utcnow()
        return self.session_repo.update(session, expected_revision=expected_revision)
