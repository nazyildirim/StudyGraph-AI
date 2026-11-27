"""Pydantic schemas for course material API endpoints (canonical + frontend compat)."""

from __future__ import annotations

from datetime import datetime
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.course_material import CourseMaterial


class MaterialTextCreateRequest(BaseModel):
    """JSON request body for creating a text-based course material."""

    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=500_000)
    page: int | None = Field(default=None, ge=1, le=10000)
    outcome_id: str | None = Field(
        default=None,
        alias="outcomeId",
        max_length=100,
    )

    @field_validator("title", "text")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be blank.")
        return stripped

    @field_validator("outcome_id")
    @classmethod
    def _normalize_outcome(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MaterialResponse(BaseModel):
    """Safe material metadata response (never exposes local file paths)."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    course_id: int
    title: str
    file_type: str
    file_size: int | None
    processing_status: str
    page_count: int | None = None
    page: int = 1
    outcomeId: str | None = None
    error_message: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, material: CourseMaterial) -> MaterialResponse:
        page_count: int | None = None
        display_page = 1
        if material.extraction_report:
            try:
                parsed = json.loads(material.extraction_report)
                total = parsed.get("total_pages")
                if isinstance(total, int) and total >= 1:
                    page_count = total
                    display_page = total
                user_page = parsed.get("user_reported_page")
                if isinstance(user_page, int) and user_page >= 1:
                    display_page = user_page
            except (ValueError, TypeError, AttributeError):
                page_count = None

        return cls(
            id=material.id,
            course_id=material.course_id,
            title=material.title,
            file_type=material.file_type,
            file_size=material.file_size_bytes,
            processing_status=material.processing_status,
            page_count=page_count,
            page=display_page,
            outcomeId=material.unverified_outcome_ref,
            error_message=material.error_message,
            created_at=material.created_at,
        )
