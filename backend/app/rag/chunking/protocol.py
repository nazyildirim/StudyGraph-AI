"""TextChunker Protocol for strategy-based document chunking."""

from __future__ import annotations

from typing import Protocol

from app.rag.domain.types import ChunkDraft, ParsedDocument


class TextChunker(Protocol):
    """Contract implemented by document chunking strategies."""

    def chunk(self, document: ParsedDocument) -> list[ChunkDraft]: ...
