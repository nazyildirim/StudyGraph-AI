"""Pydantic schemas for the RAG assistant API endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rag.generation.types import AnswerMode, AssistantAnswer

ApiAnswerMode = Literal["topic_explanation", "code_example", "exercise"]

_API_TO_DOMAIN_MODE: dict[str, AnswerMode] = {
    "topic_explanation": AnswerMode.EXPLAIN,
    "code_example": AnswerMode.PYTHON_EXAMPLE,
    "exercise": AnswerMode.EXERCISE,
}

_DOMAIN_TO_API_MODE: dict[AnswerMode, ApiAnswerMode] = {
    AnswerMode.EXPLAIN: "topic_explanation",
    AnswerMode.PYTHON_EXAMPLE: "code_example",
    AnswerMode.EXERCISE: "exercise",
}


class AssistantRequest(BaseModel):
    """Request payload for asking the course RAG assistant."""

    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(min_length=1, max_length=2000)
    mode: ApiAnswerMode = Field(default="topic_explanation")
    outcome_id: str | None = Field(default=None, alias="outcomeId", max_length=100)

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be blank.")
        return stripped

    def to_domain_mode(self) -> AnswerMode:
        return _API_TO_DOMAIN_MODE[self.mode]


class AssistantSourceResponse(BaseModel):
    """Verified source metadata (frontend-compatible `title` & `page` + rich fields)."""

    source_id: str
    title: str
    page: int | None
    page_start: int | None
    page_end: int | None
    material_id: int
    chunk_id: int
    relevance_score: float


class AssistantResponse(BaseModel):
    """Structured RAG assistant response."""

    query_id: int | None
    answer: str
    sources: list[AssistantSourceResponse]
    grounded: bool
    model_name: str | None
    answer_mode: ApiAnswerMode
    retrieval_method: str
    fallback_used: bool
    fallback_reason: str | None = None

    @classmethod
    def from_domain(cls, result: AssistantAnswer) -> AssistantResponse:
        return cls(
            query_id=result.query_id,
            answer=result.answer,
            sources=[
                AssistantSourceResponse(
                    source_id=src.source_id,
                    title=src.material_title,
                    page=src.page_start,
                    page_start=src.page_start,
                    page_end=src.page_end,
                    material_id=src.material_id,
                    chunk_id=src.chunk_id,
                    relevance_score=src.relevance_score,
                )
                for src in result.sources
            ],
            grounded=result.grounded,
            model_name=result.model_name,
            answer_mode=_DOMAIN_TO_API_MODE[result.mode],
            retrieval_method=result.retrieval_method,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
        )
