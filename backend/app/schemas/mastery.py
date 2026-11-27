"""Pydantic v2 read-only response schemas for Outcomes, Mastery, and Recommendations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CourseOutcomeResponse(BaseModel):
    """Persisted learning outcome and its direct prerequisite IDs within a course."""

    id: int
    course_id: int
    code: str
    title: str
    description: str | None = None
    order_index: int
    prerequisite_ids: list[int] = Field(default_factory=list)


class MasteryOutcomeItemResponse(BaseModel):
    """Per-outcome mastery status distinguishing assessed vs. unassessed outcomes."""

    learning_outcome_id: int
    code: str
    title: str
    is_assessed: bool
    mastery_score: float | None = None
    total_attempts: int = 0
    last_assessed_at: datetime | None = None


class CourseMasteryMapResponse(BaseModel):
    """Current mastery map for the authenticated student in a course."""

    course_id: int
    mastery_threshold: float
    outcomes: list[MasteryOutcomeItemResponse]


class CourseRecommendationItemResponse(BaseModel):
    """Personalized learning outcome recommendation with prerequisite context."""

    learning_outcome_id: int
    code: str
    title: str
    status: str
    priority_order: int
    reason: str
    missing_prerequisites: list[int] = Field(default_factory=list)
    mastery_score: float | None = None


class CourseRecommendationsResponse(BaseModel):
    """Ordered personalized study recommendations for the authenticated student."""

    course_id: int
    mastery_threshold: float
    recommendations: list[CourseRecommendationItemResponse]
