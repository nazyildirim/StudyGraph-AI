"""CitationValidator: server-side verification of LLM citation IDs.

Important limitation (documented per K45):
    Validating citation IDs guarantees STRUCTURAL integrity — every cited ID
    maps to a real, authorized, same-course chunk whose title and page numbers
    come from the database. It does NOT mathematically prove semantic factual
    entailment of every claim in the generated prose.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

from app.rag.generation.errors import CitationValidationError
from app.rag.generation.types import LLMResponse, SourceEntry, ValidatedSource

_INLINE_TAG_RE = re.compile(r"\[(S\d+)\]")
_ID_ONLY_RE = re.compile(r"^\[?(S\d+)\]?$")


class CitationValidator:
    """Validates LLM citations strictly against server-issued `SourceEntry` items."""

    def validate(
        self,
        *,
        response: LLMResponse,
        sources: Sequence[SourceEntry],
        expected_course_id: int,
    ) -> tuple[bool, tuple[ValidatedSource, ...]]:
        """Return `(grounded, validated_sources)` or raise `CitationValidationError`."""
        source_map = {entry.source_id: entry for entry in sources}

        # Ungrounded refusal: never keep citations.
        if not response.sufficient_context:
            return False, ()

        # Check inline [S#] references inside the answer text for invented IDs.
        inline_ids = _INLINE_TAG_RE.findall(response.answer)
        for inline_id in inline_ids:
            if inline_id not in source_map:
                raise CitationValidationError(
                    f"Answer text references unknown source ID [{inline_id}]."
                )

        if not response.cited_source_ids:
            raise CitationValidationError(
                "Grounded response must cite at least one valid source ID."
            )

        validated: list[ValidatedSource] = []
        seen_chunk_ids: set[int] = set()

        for raw_id in response.cited_source_ids:
            match = _ID_ONLY_RE.match(raw_id.strip())
            if not match:
                raise CitationValidationError(
                    f"Invalid citation identifier format: {raw_id!r}."
                )
            norm_id = match.group(1)
            entry = source_map.get(norm_id)
            if entry is None:
                raise CitationValidationError(
                    f"Unknown citation source ID: {norm_id!r}."
                )

            chunk = entry.chunk
            if chunk.course_id is not None and chunk.course_id != expected_course_id:
                raise CitationValidationError(
                    f"Source {norm_id} belongs to course {chunk.course_id}, "
                    f"expected {expected_course_id}."
                )

            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)

            # All titles and page numbers come strictly from DB-backed metadata.
            validated.append(
                ValidatedSource(
                    source_id=entry.source_id,
                    chunk_id=chunk.chunk_id,
                    material_id=chunk.material_id,
                    material_title=chunk.material_title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    relevance_score=float(chunk.score),
                )
            )

        if not validated:
            raise CitationValidationError("No valid citations remained after validation.")

        return True, tuple(validated)
