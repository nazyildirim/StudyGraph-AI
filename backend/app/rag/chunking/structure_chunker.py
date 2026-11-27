"""Structure-aware text chunker for RAG ingestion.

Preserves heading, paragraph, sentence, and code-block boundaries while
tracking `page_start`, `page_end`, `chunk_index`, and source metadata.

Token-limit note:
    `multilingual-e5-small` has a 512-token context window. Character-based
    limits (`chunk_size=800` by default) are a conservative heuristic for
    Turkish prose and C/Python code and do NOT guarantee exact token counts.
    Exact tokenizer-based verification is deferred to Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.rag.domain.types import (
    BlockKind,
    ChunkDraft,
    DocumentBlock,
    ParsedDocument,
)

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_MAX_CHUNK_SIZE = 4000

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9\"'\(\[`])")


@dataclass(frozen=True, slots=True)
class _Piece:
    """An atomic unit ready to be packed into a ChunkDraft."""

    text: str
    page_number: int
    kind: BlockKind
    heading: str | None
    language_hint: str | None = None


class StructureAwareChunker:
    """Splits a `ParsedDocument` into `ChunkDraft` objects respecting structure."""

    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
    ) -> None:
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be > 0.")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0.")
        if chunk_size > max_chunk_size:
            raise ValueError(
                f"chunk_size ({chunk_size}) cannot exceed max_chunk_size ({max_chunk_size})."
            )
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be >= 0.")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than "
                f"chunk_size ({chunk_size}) to guarantee forward progress."
            )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._max_chunk_size = max_chunk_size

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    def chunk(self, document: ParsedDocument) -> list[ChunkDraft]:
        pieces = self._collect_pieces(document)
        if not pieces:
            return []

        drafts: list[ChunkDraft] = []
        buffer: list[_Piece] = []
        buffer_len = 0
        previous_prose_tail = ""
        previous_prose_page: int | None = None

        def flush() -> None:
            nonlocal buffer, buffer_len, previous_prose_tail, previous_prose_page
            if not buffer:
                return
            content = "\n\n".join(p.text for p in buffer).strip("\n")
            if not content.strip():
                buffer = []
                buffer_len = 0
                return

            pages = [p.page_number for p in buffer]
            languages = sorted(
                {p.language_hint for p in buffer if p.language_hint}
            )
            has_code = any(p.kind is BlockKind.CODE for p in buffer)
            # Pick the most recent heading associated with the chunk.
            heading = next(
                (p.heading for p in reversed(buffer) if p.heading),
                None,
            )
            metadata = {
                "source_name": document.source_name,
                "file_type": document.file_type,
                "section_heading": heading,
                "has_code": has_code,
                "code_languages": languages,
                "char_count": len(content),
            }
            drafts.append(
                ChunkDraft(
                    chunk_index=len(drafts),
                    content=content,
                    page_start=min(pages),
                    page_end=max(pages),
                    metadata=metadata,
                )
            )

            # Prepare prose overlap tail only if the last piece was prose.
            last_piece = buffer[-1]
            if self._chunk_overlap > 0 and last_piece.kind is BlockKind.PARAGRAPH:
                previous_prose_tail = _extract_overlap_tail(
                    last_piece.text, self._chunk_overlap
                )
                previous_prose_page = last_piece.page_number
            else:
                previous_prose_tail = ""
                previous_prose_page = None

            buffer = []
            buffer_len = 0

        for piece in pieces:
            # Start a fresh chunk at a heading if buffer already has body content.
            if (
                piece.kind is BlockKind.HEADING
                and buffer
                and any(item.kind is not BlockKind.HEADING for item in buffer)
            ):
                flush()

            sep_len = 2 if buffer else 0
            if buffer and (buffer_len + sep_len + len(piece.text) > self._chunk_size):
                flush()

            # Prepend prose overlap when starting a new prose chunk.
            if (
                not buffer
                and previous_prose_tail
                and piece.kind is BlockKind.PARAGRAPH
                and len(previous_prose_tail) + 2 + len(piece.text) <= self._chunk_size
            ):
                overlap_piece = _Piece(
                    text=previous_prose_tail,
                    page_number=previous_prose_page or piece.page_number,
                    kind=BlockKind.PARAGRAPH,
                    heading=piece.heading,
                )
                buffer.append(overlap_piece)
                buffer_len = len(overlap_piece.text)
                previous_prose_tail = ""
                previous_prose_page = None

            sep_len = 2 if buffer else 0
            buffer.append(piece)
            buffer_len += sep_len + len(piece.text)

        flush()
        return drafts

    def _collect_pieces(self, document: ParsedDocument) -> list[_Piece]:
        pieces: list[_Piece] = []
        current_heading: str | None = None

        for page in document.pages:
            blocks: tuple[DocumentBlock, ...] = page.blocks
            if not blocks and page.text.strip():
                blocks = (
                    DocumentBlock(
                        kind=BlockKind.PARAGRAPH,
                        text=page.text.strip(),
                        page_number=page.page_number,
                    ),
                )

            for block in blocks:
                if block.kind is BlockKind.HEADING:
                    current_heading = block.text.strip()
                    for part in _split_text_units(block.text.strip(), self._chunk_size):
                        pieces.append(
                            _Piece(
                                text=part,
                                page_number=block.page_number,
                                kind=BlockKind.HEADING,
                                heading=current_heading,
                            )
                        )
                elif block.kind is BlockKind.CODE:
                    code_parts = _split_code_block(
                        block.text,
                        chunk_size=self._chunk_size,
                        chunk_overlap=self._chunk_overlap,
                    )
                    for part in code_parts:
                        pieces.append(
                            _Piece(
                                text=part,
                                page_number=block.page_number,
                                kind=BlockKind.CODE,
                                heading=current_heading,
                                language_hint=block.language_hint,
                            )
                        )
                else:
                    for part in _split_paragraph(block.text, self._chunk_size):
                        pieces.append(
                            _Piece(
                                text=part,
                                page_number=block.page_number,
                                kind=BlockKind.PARAGRAPH,
                                heading=current_heading,
                            )
                        )
        return pieces


def _split_code_block(
    code_text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Keep code whole when possible; otherwise split strictly on line boundaries."""
    cleaned = code_text.strip("\n")
    if not cleaned.strip():
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    raw_lines = cleaned.split("\n")
    # If any individual line exceeds chunk_size, slice only that line safely.
    lines: list[str] = []
    for line in raw_lines:
        if len(line) <= chunk_size:
            lines.append(line)
        else:
            for start in range(0, len(line), chunk_size):
                lines.append(line[start : start + chunk_size])

    chunks: list[str] = []
    start_idx = 0
    total_lines = len(lines)

    while start_idx < total_lines:
        end_idx = start_idx
        current_len = 0
        while end_idx < total_lines:
            line_len = len(lines[end_idx])
            extra = (1 if end_idx > start_idx else 0) + line_len
            if end_idx > start_idx and current_len + extra > chunk_size:
                break
            current_len += extra
            end_idx += 1

        chunk_text = "\n".join(lines[start_idx:end_idx]).strip("\n")
        if chunk_text.strip():
            chunks.append(chunk_text)

        if end_idx >= total_lines:
            break

        # Compute line-based overlap while strictly guaranteeing forward progress.
        if chunk_overlap > 0:
            overlap_len = 0
            next_start = end_idx
            while next_start - 1 > start_idx:
                candidate_len = overlap_len + len(lines[next_start - 1]) + 1
                if candidate_len > chunk_overlap:
                    break
                overlap_len = candidate_len
                next_start -= 1
            start_idx = next_start if next_start > start_idx else end_idx
        else:
            start_idx = end_idx

    return chunks


def _split_paragraph(text: str, chunk_size: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    sentences = [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(cleaned)
        if s and s.strip()
    ]
    if len(sentences) <= 1:
        return _split_text_units(cleaned, chunk_size)

    packed: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                packed.append(current)
                current = ""
            packed.extend(_split_text_units(sentence, chunk_size))
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= chunk_size:
            current = f"{current} {sentence}"
        else:
            packed.append(current)
            current = sentence
    if current:
        packed.append(current)
    return packed


def _split_text_units(text: str, chunk_size: int) -> list[str]:
    """Split text on whitespace boundaries, falling back to char slicing."""
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    words = cleaned.split()
    units: list[str] = []
    current = ""
    for word in words:
        if len(word) > chunk_size:
            if current:
                units.append(current)
                current = ""
            for i in range(0, len(word), chunk_size):
                units.append(word[i : i + chunk_size])
            continue
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= chunk_size:
            current = f"{current} {word}"
        else:
            units.append(current)
            current = word
    if current:
        units.append(current)
    return units


def _extract_overlap_tail(text: str, overlap_size: int) -> str:
    """Take up to `overlap_size` trailing chars aligned to a word boundary."""
    stripped = text.strip()
    if len(stripped) <= overlap_size:
        return stripped
    tail = stripped[-overlap_size:]
    space_idx = tail.find(" ")
    if 0 <= space_idx < len(tail) - 1:
        return tail[space_idx + 1 :].strip()
    return tail.strip()
