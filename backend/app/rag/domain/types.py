"""Pure data types shared by RAG parsing, chunking, retrieval and persistence.

This module must not import SQLAlchemy, FastAPI or any provider SDK so the
domain stays independent of infrastructure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProcessingStatus(StrEnum):
    """Lifecycle of a course material in the RAG ingestion pipeline."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class RetrievalMethod(StrEnum):
    """Retrieval strategy that produced a set of candidate chunks."""

    SEMANTIC_E5 = "semantic_e5"
    BM25 = "bm25"


class RetrievalStatus(StrEnum):
    """Outcome of an authorized retrieval request (for Phase 5 consumption)."""

    OK = "ok"
    NO_SOURCES = "no_sources"


class BlockKind(StrEnum):
    """Structural block categories detected during document parsing."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE = "code"


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """A structural block (heading, paragraph, or code block) on a page."""

    kind: BlockKind
    text: str
    page_number: int
    language_hint: str | None = None

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1.")
        if not self.text or not self.text.strip():
            raise ValueError("block text must not be blank.")


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """Extracted content and diagnostics for a single document page."""

    page_number: int
    text: str
    blocks: tuple[DocumentBlock, ...] = ()
    image_count: int = 0
    is_empty: bool = False
    suspected_scanned: bool = False

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1.")
        if self.image_count < 0:
            raise ValueError("image_count must be >= 0.")


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Structured diagnostic summary produced during document parsing.

    Note: `suspected_scanned_pages` is a heuristic indicator based on image
    presence and low extracted text; it is NOT a definitive OCR result.
    """

    total_pages: int
    text_extracted_pages: tuple[int, ...] = ()
    empty_pages: tuple[int, ...] = ()
    image_pages: tuple[int, ...] = ()
    suspected_scanned_pages: tuple[int, ...] = ()
    code_block_count: int = 0
    unprocessed_items: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.total_pages < 0:
            raise ValueError("total_pages must be >= 0.")
        if self.code_block_count < 0:
            raise ValueError("code_block_count must be >= 0.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for persistence/logging."""
        return {
            "total_pages": self.total_pages,
            "text_extracted_pages": list(self.text_extracted_pages),
            "empty_pages": list(self.empty_pages),
            "image_pages": list(self.image_pages),
            "suspected_scanned_pages": list(self.suspected_scanned_pages),
            "code_block_count": self.code_block_count,
            "unprocessed_items": list(self.unprocessed_items),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Output of a DocumentParser: ordered pages plus an ExtractionReport."""

    source_name: str
    file_type: str
    pages: tuple[ParsedPage, ...]
    report: ExtractionReport

    @property
    def full_text(self) -> str:
        """Join extracted text from non-empty pages in reading order."""
        return "\n\n".join(
            page.text for page in self.pages if page.text and page.text.strip()
        )


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk produced by the chunker, not yet persisted.

    Pages are 1-based. `page_end` may only be set together with `page_start`.
    """

    chunk_index: int
    content: str
    page_start: int | None = None
    page_end: int | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be >= 0.")
        if not self.content or not self.content.strip():
            raise ValueError("content must not be blank.")
        if self.page_start is not None and self.page_start < 1:
            raise ValueError("page_start must be >= 1.")
        if self.page_end is not None:
            if self.page_start is None:
                raise ValueError("page_end requires page_start.")
            if self.page_end < self.page_start:
                raise ValueError("page_end must be >= page_start.")


@dataclass(frozen=True, slots=True)
class CitationDraft:
    """A source actually used for an answer; `relevance_score` is in [0, 1]."""

    chunk_id: int
    relevance_score: float | None = None

    def __post_init__(self) -> None:
        if self.relevance_score is not None and not (
            0.0 <= self.relevance_score <= 1.0
        ):
            raise ValueError("relevance_score must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by retrieval together with its source information."""

    chunk_id: int
    material_id: int
    material_title: str
    content: str
    page_start: int | None
    page_end: int | None
    score: float
    course_id: int | None = None
    retrieval_method: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Structured result of an authorized course retrieval call.

    Distinguishes `OK` vs `NO_SOURCES` cleanly; access denial and backend
    unavailability are signaled via dedicated exceptions.
    """

    status: RetrievalStatus
    course_id: int
    method: RetrievalMethod
    chunks: tuple[RetrievedChunk, ...]
    fallback_used: bool = False
    fallback_reason: str | None = None

    @property
    def has_sources(self) -> bool:
        return self.status is RetrievalStatus.OK and len(self.chunks) > 0
