from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, UserRepo
from app.api.schemas.auth import AuthenticatedResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.application.use_cases.auth import AuthenticateUserUseCase, RegisterUserUseCase
from app.domain.exceptions import DuplicateEmailError, DuplicateUsernameError, InvalidCredentialsError
from app.infrastructure.security import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _to_user_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        streak_days=user.streak_days,
        longest_streak_days=user.longest_streak_days,
        last_activity_date=user.last_activity_date,
        total_words_learned=user.total_words_learned,
        total_study_seconds=user.total_study_seconds,
        is_active=user.is_active,
    )


@router.post("/register", response_model=AuthenticatedResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, user_repo: UserRepo) -> AuthenticatedResponse:
    try:
        user = RegisterUserUseCase(user_repo).execute(payload.username, payload.email, payload.password)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateUsernameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    token = create_access_token(subject=str(user.id))
    return AuthenticatedResponse(user=_to_user_response(user), token=TokenResponse(access_token=token))


@router.post("/login", response_model=AuthenticatedResponse)
def login(payload: LoginRequest, user_repo: UserRepo) -> AuthenticatedResponse:
    try:
        user = AuthenticateUserUseCase(user_repo).execute(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token = create_access_token(subject=str(user.id))
    return AuthenticatedResponse(user=_to_user_response(user), token=TokenResponse(access_token=token))


@router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUser) -> UserResponse:
    return _to_user_response(current_user)
