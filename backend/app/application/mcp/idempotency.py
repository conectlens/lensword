from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import MCPIdempotencyKeyModel


class IdempotencyStore:
    """Persist successful MCP write responses keyed by caller request IDs."""

    def __init__(self, db: Session):
        self.db = db

    def replay(self, requester: str, request_id: str) -> dict | None:
        item = self.db.query(MCPIdempotencyKeyModel).filter_by(requester=requester, request_id=request_id).one_or_none()
        return item.response if item else None

    def record(self, requester: str, request_id: str, tool: str, response: dict, now: datetime) -> dict:
        item = MCPIdempotencyKeyModel(
            requester=requester, request_id=request_id, tool=tool, response=response, created_at=now
        )
        self.db.add(item)
        try:
            self.db.flush()
            return response
        except IntegrityError:
            self.db.rollback()
            replay = self.replay(requester, request_id)
            if replay is None:
                raise
            return replay
