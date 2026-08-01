from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import MCPIdempotencyKeyModel


class IdempotencyStore:
    """Persist successful MCP write responses keyed by caller request IDs."""

    def __init__(self, db: Session):
        self.db = db

    def replay(self, requester: str, request_id: str, tool: str) -> dict | None:
        item = self.db.query(MCPIdempotencyKeyModel).filter_by(requester=requester, request_id=request_id).one_or_none()
        if item is not None and item.tool != tool:
            raise ValueError("request_id was already used for another MCP tool")
        return item.response if item else None

    def record(self, requester: str, request_id: str, tool: str, response: dict, now: datetime) -> dict:
        item = MCPIdempotencyKeyModel(
            requester=requester, request_id=request_id, tool=tool, response=response, created_at=now
        )
        try:
            # A duplicate request must not roll back the caller's surrounding
            # audit/grant transaction. Restrict its race recovery to a savepoint.
            with self.db.begin_nested():
                self.db.add(item)
                self.db.flush()
            return response
        except IntegrityError:
            replay = self.replay(requester, request_id, tool)
            if replay is None:
                raise
            return replay
