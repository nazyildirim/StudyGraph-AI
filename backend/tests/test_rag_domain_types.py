"""Unit tests for RAG domain types (no database required)."""

from __future__ import annotations

import pytest

from app.rag.domain import ChunkDraft, CitationDraft, ProcessingStatus, RetrievedChunk


def test_processing_status_values_match_database_design() -> None:
    assert [status.value for status in ProcessingStatus] == [
        "pending",
        "processing",
        "processed",
        "failed",
    ]


def test_chunk_draft_accepts_valid_values_and_is_immutable() -> None:
    draft = ChunkDraft(chunk_index=0, content="int *p;", page_start=2, page_end=3)
    assert draft.page_end == 3
    with pytest.raises(AttributeError):
        draft.content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunk_index": -1, "content": "x"},
        {"chunk_index": 0, "content": "   "},
        {"chunk_index": 0, "content": ""},
        {"chunk_index": 0, "content": "x", "page_start": 0},
        {"chunk_index": 0, "content": "x", "page_end": 2},
        {"chunk_index": 0, "content": "x", "page_start": 3, "page_end": 2},
    ],
)
def test_chunk_draft_rejects_invalid_values(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ChunkDraft(**kwargs)


def test_chunk_draft_allows_missing_pages_for_plain_text() -> None:
    draft = ChunkDraft(chunk_index=4, content="Pointer nedir?")
    assert draft.page_start is None and draft.page_end is None


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_citation_draft_rejects_out_of_range_score(score: float) -> None:
    with pytest.raises(ValueError):
        CitationDraft(chunk_id=1, relevance_score=score)


def test_citation_draft_accepts_boundaries_and_none() -> None:
    assert CitationDraft(chunk_id=1, relevance_score=0.0).relevance_score == 0.0
    assert CitationDraft(chunk_id=1, relevance_score=1.0).relevance_score == 1.0
    assert CitationDraft(chunk_id=1).relevance_score is None


def test_retrieved_chunk_holds_source_information() -> None:
    chunk = RetrievedChunk(
        chunk_id=1,
        material_id=2,
        material_title="C Pointers",
        content="text",
        page_start=1,
        page_end=1,
        score=0.8,
    )
    assert (chunk.material_title, chunk.page_start, chunk.score) == (
        "C Pointers",
        1,
        0.8,
    )
