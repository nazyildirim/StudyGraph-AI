"""Structured types for prompt building, LLM generation, and citation validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.rag.domain.types import RetrievedChunk


class AnswerMode(StrEnum):
    """Supported pedagogical response modes for the RAG assistant (Issue #8)."""

    EXPLAIN = "explain"
    PYTHON_EXAMPLE = "python_example"
    EXERCISE = "exercise"


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """Server-assigned source label (e.g. `S1`) bound to a DB-backed chunk."""

    source_id: str
    chunk: RetrievedChunk


@dataclass(frozen=True, slots=True)
class BuiltPrompt:
    """Output of `PromptBuilder`: separated system/user prompts and source map."""

    system_prompt: str
    user_prompt: str
    sources: tuple[SourceEntry, ...]
    mode: AnswerMode
    response_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Provider-independent structured generation request."""

    system_prompt: str
    user_prompt: str
    response_schema: Mapping[str, Any]
    sources: tuple[SourceEntry, ...] = ()
    mode: AnswerMode = AnswerMode.EXPLAIN
    max_output_tokens: int = 512
    temperature: float = 0.2
    context_window: int = 4096


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Structured response parsed from an LLMClient."""

    sufficient_context: bool
    answer: str
    cited_source_ids: tuple[str, ...]
    model_name: str
    is_fallback: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedSource:
    """Verified citation backed strictly by database chunk metadata."""

    source_id: str
    chunk_id: int
    material_id: int
    material_title: str
    page_start: int | None
    page_end: int | None
    relevance_score: float


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """Final structured answer returned by `RagAssistantService`."""

    query_id: int | None
    answer: str
    grounded: bool
    mode: AnswerMode
    sources: tuple[ValidatedSource, ...]
    model_name: str | None
    retrieval_method: str
    fallback_used: bool = False
    fallback_reason: str | None = None
