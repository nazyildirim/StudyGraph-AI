"""Framework-independent RAG domain types."""

from app.rag.domain.types import (
    BlockKind,
    ChunkDraft,
    CitationDraft,
    DocumentBlock,
    ExtractionReport,
    ParsedDocument,
    ParsedPage,
    ProcessingStatus,
    RetrievalMethod,
    RetrievalResult,
    RetrievalStatus,
    RetrievedChunk,
)

__all__ = [
    "BlockKind",
    "ChunkDraft",
    "CitationDraft",
    "DocumentBlock",
    "ExtractionReport",
    "ParsedDocument",
    "ParsedPage",
    "ProcessingStatus",
    "RetrievalMethod",
    "RetrievalResult",
    "RetrievalStatus",
    "RetrievedChunk",
]
