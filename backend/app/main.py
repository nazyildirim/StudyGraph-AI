"""StudyGraph AI Backend - FastAPI entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_users import router as admin_users_router
from app.api.assistant import (
    compat_router as assistant_compat_router,
    router as assistant_router,
)
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.learning import router as learning_router
from app.api.materials import (
    compat_router as materials_compat_router,
    router as materials_router,
)
from app.api.middleware import UploadBodyLimitMiddleware
from app.api.users import router as users_router
from app.core.config import get_cors_origins_for_app


app = FastAPI(
    title="StudyGraph AI API",
    description="Backend and learning algorithms for StudyGraph AI.",
    version="0.1.0",
)

app.add_middleware(UploadBodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins_for_app(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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

app.include_router(
    materials_router,
    prefix="/api/v1",
)

app.include_router(
    assistant_router,
    prefix="/api/v1",
)

# Unprefixed compatibility routes for the existing frontend (`BASE_URL + /courses/...`)
app.include_router(materials_compat_router)
app.include_router(assistant_compat_router)
