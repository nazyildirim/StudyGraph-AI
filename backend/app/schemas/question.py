"""Pydantic v2 request and response schemas for the Question Bank (Issue #7).

Security separation:
- Instructor schemas (`QuestionInstructorResponse`, `QuestionOptionResponse`)
  include `is_correct` and version lineage metadata, and are returned ONLY
  after `CourseAccessPolicy.check_manage_access`.
- Student schemas (`QuestionStudentResponse`, `QuestionStudentOptionResponse`)
  strictly omit `is_correct`, `answer`, and `correct_option_id` so correct
  answers can never leak before exam completion.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import math

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.models.question import DifficultyLevel, Question
from app.models.question_option import QuestionOption

MAX_QUESTION_TEXT_LENGTH = 4000
MAX_OPTION_TEXT_LENGTH = 1000
MULTIPLE_CHOICE_OPTION_COUNT = 4
MAX_QUESTION_POINTS = 1000.0
MAX_PG_INT32 = 2_147_483_647


class QuestionOptionCreate(BaseModel):
    """Request model for one multiple-choice option."""

    model_config = ConfigDict(extra="forbid")

    option_text: str = Field(min_length=1, max_length=MAX_OPTION_TEXT_LENGTH)
    is_correct: StrictBool
    order_index: int = Field(ge=0, le=100)

    @field_validator("order_index", mode="before")
    @classmethod
    def _reject_bool_order_index(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("order_index must be an integer, not a boolean.")
        return value

    @field_validator("option_text")
    @classmethod
    def _strip_and_require_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("option_text must not be blank.")
        return stripped


class _BaseQuestionWriteRequest(BaseModel):
    """Shared strict validation for creating or updating a multiple-choice question."""

    model_config = ConfigDict(extra="forbid")

    learning_outcome_id: int = Field(ge=1, le=MAX_PG_INT32)
    question_text: str = Field(min_length=1, max_length=MAX_QUESTION_TEXT_LENGTH)
    difficulty_level: DifficultyLevel = Field(default=DifficultyLevel.MEDIUM)
    points: float = Field(
        default=1.0,
        gt=0.0,
        le=MAX_QUESTION_POINTS,
        allow_inf_nan=False,
    )
    options: list[QuestionOptionCreate] = Field(
        min_length=MULTIPLE_CHOICE_OPTION_COUNT,
        max_length=MULTIPLE_CHOICE_OPTION_COUNT,
    )

    @field_validator("learning_outcome_id", mode="before")
    @classmethod
    def _reject_bool_outcome_id(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("learning_outcome_id must be an integer.")
        return value

    @field_validator("points", mode="before")
    @classmethod
    def _reject_bool_and_non_finite_points(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("points must be a positive finite number.")
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError("points must be finite.")
        return value

    @field_validator("question_text")
    @classmethod
    def _strip_and_require_non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question_text must not be blank.")
        return stripped

    @model_validator(mode="after")
    def _validate_options_integrity(self) -> _BaseQuestionWriteRequest:
        indices = [opt.order_index for opt in self.options]
        if len(indices) != len(set(indices)):
            raise ValueError("Option order_index values must be unique.")

        correct_count = sum(1 for opt in self.options if opt.is_correct)
        if correct_count != 1:
            raise ValueError("A question must have exactly one correct option.")
        return self


class QuestionCreateRequest(_BaseQuestionWriteRequest):
    """Strict payload for creating a new multiple-choice question."""


class QuestionUpdateRequest(_BaseQuestionWriteRequest):
    """Strict payload for updating (or versioning) a multiple-choice question."""


class QuestionOptionResponse(BaseModel):
    """Instructor-facing option schema (includes `is_correct`)."""

    id: int
    option_text: str
    is_correct: bool
    order_index: int

    @classmethod
    def from_model(cls, option: QuestionOption) -> QuestionOptionResponse:
        return cls(
            id=option.id,
            option_text=option.option_text,
            is_correct=option.is_correct,
            order_index=option.order_index,
        )


class QuestionInstructorResponse(BaseModel):
    """Instructor/admin-facing question schema including correct answer and lineage."""

    id: int
    course_id: int
    learning_outcome_id: int
    question_text: str
    question_type: str
    difficulty_level: str
    points: float
    is_active: bool
    archived_at: datetime | None
    version_number: int
    root_question_id: int | None
    previous_version_id: int | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    options: list[QuestionOptionResponse]

    @classmethod
    def from_models(
        cls,
        question: Question,
        options: Sequence[QuestionOption],
    ) -> QuestionInstructorResponse:
        return cls(
            id=question.id,
            course_id=question.course_id,
            learning_outcome_id=question.learning_outcome_id,
            question_text=question.question_text,
            question_type=question.question_type,
            difficulty_level=question.difficulty_level,
            points=question.points,
            is_active=question.is_active,
            archived_at=question.archived_at,
            version_number=question.version_number,
            root_question_id=question.root_question_id,
            previous_version_id=question.previous_version_id,
            created_by=question.created_by,
            created_at=question.created_at,
            updated_at=question.updated_at,
            options=[QuestionOptionResponse.from_model(opt) for opt in options],
        )


class QuestionUpdateResponse(BaseModel):
    """Result of updating a question, explicitly indicating immutable versioning."""

    question: QuestionInstructorResponse
    was_versioned: bool
    previous_question_id: int | None = None


class QuestionDeleteResponse(BaseModel):
    """Result of deleting or archiving a question."""

    question_id: int
    archived: bool


class QuestionStudentOptionResponse(BaseModel):
    """Student-facing option schema — strictly omits `is_correct`."""

    id: int
    option_text: str
    order_index: int

    @classmethod
    def from_model(cls, option: QuestionOption) -> QuestionStudentOptionResponse:
        return cls(
            id=option.id,
            option_text=option.option_text,
            order_index=option.order_index,
        )


class QuestionStudentResponse(BaseModel):
    """Student-facing question schema — never exposes correct answer fields."""

    id: int
    learning_outcome_id: int
    question_text: str
    question_type: str
    difficulty_level: str
    points: float
    options: list[QuestionStudentOptionResponse]

    @classmethod
    def from_models(
        cls,
        question: Question,
        options: Sequence[QuestionOption],
    ) -> QuestionStudentResponse:
        return cls(
            id=question.id,
            learning_outcome_id=question.learning_outcome_id,
            question_text=question.question_text,
            question_type=question.question_type,
            difficulty_level=question.difficulty_level,
            points=question.points,
            options=[
                QuestionStudentOptionResponse.from_model(opt) for opt in options
            ],
        )
