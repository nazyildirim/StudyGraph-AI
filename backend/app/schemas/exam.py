"""Pydantic v2 request and response schemas for Student Exams (Issue #7).

Security guarantees:
- Request models use `extra="forbid"`, rejecting client-supplied `student_id`,
  `score`, `status`, `assessment_type`, or `course_id`.
- Student exam response models reuse `QuestionStudentOptionResponse` projection
  and strictly omit `is_correct`, `answer`, `correct_option_id`,
  `correct_answer`, and uncomputed mastery scores.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.question import DifficultyLevel, Question
from app.models.question_option import QuestionOption
from app.schemas.question import MAX_PG_INT32, QuestionStudentOptionResponse

MAX_SUBMIT_ANSWERS = 200


class InitialExamCreateRequest(BaseModel):
    """Strict optional payload for starting a diagnostic (initial) exam."""

    model_config = ConfigDict(extra="forbid")

    question_count: int | None = Field(default=None, ge=1, le=100)

    @field_validator("question_count", mode="before")
    @classmethod
    def _reject_bool_question_count(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("question_count must be an integer, not a boolean.")
        return value


class RetestExamCreateRequest(BaseModel):
    """Strict optional payload for starting a targeted or general review (retest) exam."""

    model_config = ConfigDict(extra="forbid")

    learning_outcome_id: int | None = Field(default=None, ge=1, le=MAX_PG_INT32)
    question_count: int | None = Field(default=None, ge=1, le=50)
    difficulty: DifficultyLevel | None = None

    @field_validator("learning_outcome_id", "question_count", mode="before")
    @classmethod
    def _reject_bool_ints(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Field must be an integer, not a boolean.")
        return value


class StudentExamOptionResponse(BaseModel):
    """Student-facing exam option — strictly omits `is_correct`."""

    option_id: int
    option_text: str
    order_index: int

    @classmethod
    def from_model(cls, option: QuestionOption) -> StudentExamOptionResponse:
        # Delegate through QuestionStudentOptionResponse to preserve a single
        # answer-stripping projection boundary.
        safe = QuestionStudentOptionResponse.from_model(option)
        return cls(
            option_id=safe.id,
            option_text=safe.option_text,
            order_index=safe.order_index,
        )


class StudentExamQuestionResponse(BaseModel):
    """Student-facing exam question ordered by `order_index`."""

    question_id: int
    learning_outcome_id: int
    question_text: str
    difficulty_level: str
    order_index: int
    options: list[StudentExamOptionResponse]

    @classmethod
    def from_models(
        cls,
        *,
        question: Question,
        order_index: int,
        options: Sequence[QuestionOption],
    ) -> StudentExamQuestionResponse:
        return cls(
            question_id=question.id,
            learning_outcome_id=question.learning_outcome_id,
            question_text=question.question_text,
            difficulty_level=question.difficulty_level,
            order_index=order_index,
            options=[StudentExamOptionResponse.from_model(opt) for opt in options],
        )


class StudentExamResponse(BaseModel):
    """Student-facing active or historical exam attempt payload (zero answer leakage)."""

    attempt_id: int
    assessment_id: int
    course_id: int
    assessment_type: str
    status: str
    requested_count: int
    actual_count: int
    unseen_question_count: int | None = None
    reused_question_count: int | None = None
    targeted_outcome_ids: list[int] = Field(default_factory=list)
    covered_outcome_ids: list[int] = Field(default_factory=list)
    uncovered_outcome_ids: list[int] = Field(default_factory=list)
    difficulty: str | None = None
    resumed: bool = False
    started_at: datetime
    questions: list[StudentExamQuestionResponse]


class StudentAnswerRequest(BaseModel):
    """Single student answer payload — strictly forbids grading/ownership fields."""

    model_config = ConfigDict(extra="forbid")

    question_id: int = Field(ge=1, le=MAX_PG_INT32)
    selected_option_id: int | None = Field(default=None, ge=1, le=MAX_PG_INT32)

    @field_validator("question_id", "selected_option_id", mode="before")
    @classmethod
    def _reject_bool_ids(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Identifier must be an integer, not a boolean.")
        return value


class ExamSubmitRequest(BaseModel):
    """Student exam submission payload — server computes all correctness & scores."""

    model_config = ConfigDict(extra="forbid")

    answers: list[StudentAnswerRequest] = Field(
        default_factory=list,
        max_length=MAX_SUBMIT_ANSWERS,
    )

    @model_validator(mode="after")
    def _reject_duplicate_questions(self) -> ExamSubmitRequest:
        seen: set[int] = set()
        for item in self.answers:
            if item.question_id in seen:
                raise ValueError(
                    f"Duplicate answer for question_id={item.question_id}."
                )
            seen.add(item.question_id)
        return self


class ExamQuestionResult(BaseModel):
    """Per-question grading summary for a completed attempt (omits answer key)."""

    question_id: int
    learning_outcome_id: int
    order_index: int
    selected_option_id: int | None
    is_correct: bool
    score_earned: float
    points_possible: float


class OutcomeMasteryScoreResponse(BaseModel):
    """Per-outcome mastery score produced by Issue #5 ScoringEngine."""

    learning_outcome_id: int
    correct_count: int
    question_count: int
    score_percent: float


class MasteryRecommendationResponse(BaseModel):
    """Per-outcome recommendation produced by Issue #5 RecommendationEngine."""

    learning_outcome_id: int
    status: str
    score_percent: float | None
    priority_order: int
    missing_prerequisites: list[int]
    reason: str


class ExamMasterySummaryResponse(BaseModel):
    """Learning analysis summary produced on exam submission (never faked)."""

    mastery_threshold: float
    learning_order: list[int]
    outcome_scores: list[OutcomeMasteryScoreResponse]
    weak_outcome_ids: list[int]
    unassessed_outcome_ids: list[int]
    blocked_outcome_ids: list[int]
    recommendations: list[MasteryRecommendationResponse]


class ExamResultResponse(BaseModel):
    """Server-graded result for a completed exam attempt."""

    attempt_id: int
    assessment_id: int
    course_id: int
    assessment_type: str
    status: str
    started_at: datetime
    completed_at: datetime
    total_questions: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    earned_points: float
    total_possible_points: float
    score: float
    results: list[ExamQuestionResult]
    mastery_summary: ExamMasterySummaryResponse | None = None


class ExamHistoryItemResponse(BaseModel):
    """Summary row for a student's course exam attempt history."""

    attempt_id: int
    assessment_id: int
    course_id: int
    assessment_type: str
    title: str
    status: str
    score: float | None
    started_at: datetime
    completed_at: datetime | None
