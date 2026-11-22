
"""StudyGraph AI Backend - FastAPI entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.learning import router as learning_router


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
