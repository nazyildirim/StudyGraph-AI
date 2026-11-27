"""Document chunking package (TextChunker Protocol and StructureAwareChunker)."""

from app.rag.chunking.protocol import TextChunker
from app.rag.chunking.structure_chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_CHUNK_SIZE,
    StructureAwareChunker,
)

__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_CHUNK_SIZE",
    "StructureAwareChunker",
    "TextChunker",
]
