"""Backward-compatible wrapper for the legacy text splitter prototype.

Delegates all text splitting to `PlainTextParser` and `StructureAwareChunker`
so no chunking logic is duplicated.
"""

from __future__ import annotations

from app.rag.chunking.structure_chunker import StructureAwareChunker
from app.rag.parsing.text_parser import PlainTextParser


def split_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int = 0,
) -> list[str]:
    """Split text into structure-aware chunks and return their contents."""
    if chunk_size <= 0:
        raise ValueError("chunk_size sifirdan buyuk olmalidir")
    if not text or not text.strip():
        return []
    chunker = StructureAwareChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        max_chunk_size=max(chunk_size, 4000),
    )
    document = PlainTextParser().parse(text.encode("utf-8"), source_name="inline.txt")
    return [draft.content for draft in chunker.chunk(document)]
