
"""StudyGraph AI Backend - FastAPI entry point."""

from fastapi import FastAPI

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.learning import router as learning_router
from app.api.users import router as users_router


app = FastAPI(
    title="StudyGraph AI API",
    description="Backend and learning algorithms for StudyGraph AI.",
    version="0.1.0",
)

app.include_router(
    health_router,
    prefix="/api/v1",
)

app.include_router(
    learning_router,
    prefix="/api/v1",
)

app.include_router(
    auth_router,
    prefix="/api/v1",
)

app.include_router(
    users_router,
    prefix="/api/v1",
)

app.include_router(
    admin_users_router,
    prefix="/api/v1",
)
