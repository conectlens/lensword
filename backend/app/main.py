from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import admin, auth, groups, mnemonics, review, rooms, settings, words
from app.application.use_cases.auth import RegisterUserUseCase
from app.config import get_settings
from app.domain.exceptions import DomainError
from app.domain.value_objects import UserRole
from app.infrastructure.db import SessionLocal, init_db
from app.infrastructure.repositories import SqlAlchemyUserRepository

settings_ = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _seed_first_admin()
    yield


app = FastAPI(title=settings_.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(words.router)
app.include_router(rooms.router)
app.include_router(review.router)
app.include_router(mnemonics.router)
app.include_router(settings.router)
app.include_router(admin.router)


@app.exception_handler(DomainError)
def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    """Fallback safety net: any DomainError not already translated to a
    specific HTTP status by a router still returns a clean 400 instead of
    leaking a 500."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}


def _seed_first_admin() -> None:
    if not (settings_.first_admin_email and settings_.first_admin_password):
        return
    db = SessionLocal()
    try:
        user_repo = SqlAlchemyUserRepository(db)
        if user_repo.get_by_email(settings_.first_admin_email) is None:
            RegisterUserUseCase(user_repo).execute(
                username="admin",
                email=settings_.first_admin_email,
                password=settings_.first_admin_password,
                role=UserRole.ADMIN,
            )
            db.commit()
    finally:
        db.close()
