from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.entities import User
from app.domain.services.ai_provider import AIProvider
from app.domain.value_objects import UserRole
from app.infrastructure.ai import build_ai_provider
from app.infrastructure.db import get_db
from app.infrastructure.repositories import (
    SqlAlchemyGroupRepository,
    SqlAlchemyMnemonicRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyReviewSessionRepository,
    SqlAlchemyRoomRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)
from app.infrastructure.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_user_repository(db: DbSession) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(db)


def get_group_repository(db: DbSession) -> SqlAlchemyGroupRepository:
    return SqlAlchemyGroupRepository(db)


def get_word_repository(db: DbSession) -> SqlAlchemyWordRepository:
    return SqlAlchemyWordRepository(db)


def get_room_repository(db: DbSession) -> SqlAlchemyRoomRepository:
    return SqlAlchemyRoomRepository(db)


def get_review_session_repository(db: DbSession) -> SqlAlchemyReviewSessionRepository:
    return SqlAlchemyReviewSessionRepository(db)


def get_mnemonic_repository(db: DbSession) -> SqlAlchemyMnemonicRepository:
    return SqlAlchemyMnemonicRepository(db)


def get_recall_settings_repository(db: DbSession) -> SqlAlchemyRecallSettingsRepository:
    return SqlAlchemyRecallSettingsRepository(db)


@lru_cache
def _ai_provider() -> AIProvider | None:
    """Built once per process, not per request — the Ollama adapter owns a
    pooled HTTP client that would otherwise be recreated on every call."""
    return build_ai_provider(get_settings())


def get_ai_provider() -> AIProvider | None:
    return _ai_provider()


UserRepo = Annotated[SqlAlchemyUserRepository, Depends(get_user_repository)]
GroupRepo = Annotated[SqlAlchemyGroupRepository, Depends(get_group_repository)]
WordRepo = Annotated[SqlAlchemyWordRepository, Depends(get_word_repository)]
RoomRepo = Annotated[SqlAlchemyRoomRepository, Depends(get_room_repository)]
ReviewSessionRepo = Annotated[SqlAlchemyReviewSessionRepository, Depends(get_review_session_repository)]
MnemonicRepo = Annotated[SqlAlchemyMnemonicRepository, Depends(get_mnemonic_repository)]
RecallSettingsRepo = Annotated[SqlAlchemyRecallSettingsRepository, Depends(get_recall_settings_repository)]
OptionalAIProvider = Annotated[AIProvider | None, Depends(get_ai_provider)]


def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)], user_repo: UserRepo) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error
    subject = decode_access_token(token)
    if subject is None:
        raise credentials_error
    user = user_repo.get_by_id(int(subject))
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
