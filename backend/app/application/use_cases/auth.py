from app.domain.entities import User
from app.domain.exceptions import DuplicateEmailError, DuplicateUsernameError, InvalidCredentialsError
from app.domain.repositories import UserRepository
from app.domain.value_objects import UserRole
from app.infrastructure.security import hash_password, verify_password


class RegisterUserUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, username: str, email: str, password: str, role: UserRole = UserRole.USER) -> User:
        email = email.strip().lower()
        username = username.strip()

        if self.user_repo.get_by_email(email) is not None:
            raise DuplicateEmailError(email)
        if self.user_repo.get_by_username(username) is not None:
            raise DuplicateUsernameError(username)

        user = User(
            id=None,
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=role,
        )
        return self.user_repo.add(user)


class AuthenticateUserUseCase:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def execute(self, email: str, password: str) -> User:
        user = self.user_repo.get_by_email(email.strip().lower())
        if user is None or not user.is_active or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        return user
