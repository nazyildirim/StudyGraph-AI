"""Token-limit enforcement helper using StructureAwareChunker.

Never silently truncates chunks that exceed the embedding model's token limit;
instead re-splits only oversized chunks with a progressively smaller character
budget while preserving page numbers, metadata, and sequential chunk indexes.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.rag.chunking.structure_chunker import StructureAwareChunker
from app.rag.domain.types import (
    BlockKind,
    ChunkDraft,
    DocumentBlock,
    ExtractionReport,
    ParsedDocument,
    ParsedPage,
)
from app.rag.embedding.errors import TokenLimitExceededError
from app.rag.embedding.protocol import EmbeddingProvider


def enforce_token_limit(
    drafts: Sequence[ChunkDraft],
    provider: EmbeddingProvider,
    *,
    max_split_attempts: int = 8,
) -> list[ChunkDraft]:
    """Ensure every chunk fits within `provider.max_tokens` without truncation."""
    result: list[ChunkDraft] = []
    max_tokens = provider.max_tokens

    for draft in drafts:
        token_count = provider.count_tokens(draft.content, is_query=False)
        if token_count <= max_tokens:
            result.append(_reindexed(draft, len(result)))
            continue

        sub_drafts = _resplit_oversized_chunk(
            draft,
            provider=provider,
            initial_tokens=token_count,
            max_attempts=max_split_attempts,
        )
        for sub in sub_drafts:
            result.append(_reindexed(sub, len(result)))

    return result


def _resplit_oversized_chunk(
    draft: ChunkDraft,
    *,
    provider: EmbeddingProvider,
    initial_tokens: int,
    max_attempts: int,
) -> list[ChunkDraft]:
    max_tokens = provider.max_tokens
    meta = dict(draft.metadata) if draft.metadata else {}
    has_code = bool(meta.get("has_code", False))
    code_langs = meta.get("code_languages") or []
    lang_hint = code_langs[0] if len(code_langs) == 1 else None
    source_name = str(meta.get("source_name", "resplit"))
    file_type = str(meta.get("file_type", "text/plain"))

    # Estimate a safe character budget from the observed chars-per-token ratio.
    ratio = len(draft.content) / max(initial_tokens, 1)
    char_budget = max(32, int(max_tokens * ratio * 0.8))

    last_max_seen = initial_tokens
    for _ in range(max_attempts):
        block = DocumentBlock(
            kind=BlockKind.CODE if has_code else BlockKind.PARAGRAPH,
            text=draft.content,
            page_number=draft.page_start or 1,
            language_hint=lang_hint,
        )
        mini_doc = ParsedDocument(
            source_name=source_name,
            file_type=file_type,
            pages=(
                ParsedPage(
                    page_number=draft.page_start or 1,
                    text=draft.content,
                    blocks=(block,),
                ),
            ),
            report=ExtractionReport(total_pages=1, text_extracted_pages=(1,)),
        )
        overlap = min(char_budget // 8, 40)
        candidates = StructureAwareChunker(
            chunk_size=char_budget,
            chunk_overlap=overlap,
            max_chunk_size=max(char_budget, 4000),
        ).chunk(mini_doc)

        counts = [
            provider.count_tokens(candidate.content, is_query=False)
            for candidate in candidates
        ]
        if candidates and all(count <= max_tokens for count in counts):
            preserved: list[ChunkDraft] = []
            for candidate in candidates:
                merged_meta = dict(meta)
                merged_meta["char_count"] = len(candidate.content)
                merged_meta["token_resplit"] = True
                preserved.append(
                    ChunkDraft(
                        chunk_index=candidate.chunk_index,
                        content=candidate.content,
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        metadata=merged_meta,
                    )
                )
            return preserved

        last_max_seen = max(counts) if counts else initial_tokens
        next_budget = max(16, int(char_budget * 0.65))
        if next_budget == char_budget:
            break
        char_budget = next_budget

    raise TokenLimitExceededError(last_max_seen, max_tokens)


def _reindexed(draft: ChunkDraft, new_index: int) -> ChunkDraft:
    return ChunkDraft(
        chunk_index=new_index,
        content=draft.content,
        page_start=draft.page_start,
        page_end=draft.page_end,
        metadata=draft.metadata,
    )
