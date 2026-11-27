"""Unit tests for StructureAwareChunker."""

from __future__ import annotations

import pytest

from app.rag.chunking import StructureAwareChunker
from app.rag.domain import (
    BlockKind,
    DocumentBlock,
    ExtractionReport,
    ParsedDocument,
    ParsedPage,
)
from app.rag.parsing import PdfDocumentParser, PlainTextParser
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunk_size": 0, "chunk_overlap": 0},
        {"chunk_size": -10, "chunk_overlap": 0},
        {"chunk_size": 5000, "chunk_overlap": 0, "max_chunk_size": 4000},
        {"chunk_size": 100, "chunk_overlap": -1},
        {"chunk_size": 100, "chunk_overlap": 100},
        {"chunk_size": 100, "chunk_overlap": 150},
    ],
)
def test_invalid_chunk_parameters_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        StructureAwareChunker(**kwargs)


def test_heading_and_paragraph_boundaries_and_metadata() -> None:
    raw = (
        "# 1. Bellek Yönetimi\n\n"
        "C dilinde dinamik bellek malloc ile ayrılır. İş bitince free çağrılmalıdır.\n\n"
        "# 2. İşaretçiler\n\n"
        "Bir işaretçi başka bir değişkenin bellek adresini saklar.\n"
    ).encode("utf-8")
    doc = PlainTextParser().parse(raw, source_name="bellek.txt")
    chunks = StructureAwareChunker(chunk_size=140, chunk_overlap=20).chunk(doc)

    assert len(chunks) >= 2
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.content.strip() for c in chunks)
    assert chunks[0].metadata["source_name"] == "bellek.txt"
    assert chunks[0].metadata["file_type"] == "text/plain"
    assert chunks[0].metadata["section_heading"] == "1. Bellek Yönetimi"
    assert any(
        c.metadata["section_heading"] == "2. İşaretçiler" for c in chunks
    )


def test_chunk_overlap_carries_context_between_prose_chunks() -> None:
    sentences = " ".join(
        f"Cumle numarasi {i} ogrenme grafigi ve on kosul iliskilerini aciklar."
        for i in range(1, 10)
    )
    doc = PlainTextParser().parse(sentences.encode("utf-8"), source_name="overlap.txt")
    chunks = StructureAwareChunker(chunk_size=160, chunk_overlap=40).chunk(doc)

    assert len(chunks) >= 3
    # Adjacent prose chunks must share trailing/leading words from overlap.
    prev_words = set(chunks[0].content.split()[-5:])
    next_words = set(chunks[1].content.split()[:8])
    assert prev_words & next_words


def test_short_code_block_is_kept_intact() -> None:
    code = (
        "def binary_search(arr, target):\n"
        "    lo, hi = 0, len(arr) - 1\n"
        "    while lo <= hi:\n"
        "        mid = (lo + hi) // 2\n"
        "        if arr[mid] == target:\n"
        "            return mid\n"
        "        lo = mid + 1 if arr[mid] < target else lo\n"
        "    return -1"
    )
    raw = (f"# Arama\n\nKısa açıklama metni.\n\n```python\n{code}\n```\n").encode("utf-8")
    doc = PlainTextParser().parse(raw, source_name="search.txt")
    chunks = StructureAwareChunker(chunk_size=260, chunk_overlap=30).chunk(doc)

    code_chunks = [c for c in chunks if c.metadata["has_code"]]
    assert len(code_chunks) == 1
    assert code in code_chunks[0].content
    assert code_chunks[0].metadata["code_languages"] == ["python"]


def test_long_code_block_splits_only_on_line_boundaries() -> None:
    code_lines = [f"    value_{i} = value_{i - 1} + {i}" for i in range(1, 25)]
    code = "def compute():\n    value_0 = 0\n" + "\n".join(code_lines) + "\n    return value_24"
    doc = ParsedDocument(
        source_name="long_code.py.txt",
        file_type="text/plain",
        pages=(
            ParsedPage(
                page_number=1,
                text=code,
                blocks=(
                    DocumentBlock(
                        kind=BlockKind.CODE,
                        text=code,
                        page_number=1,
                        language_hint="python",
                    ),
                ),
            ),
        ),
        report=ExtractionReport(total_pages=1, text_extracted_pages=(1,), code_block_count=1),
    )

    chunks = StructureAwareChunker(chunk_size=180, chunk_overlap=40).chunk(doc)
    assert len(chunks) >= 3
    original_line_set = set(code.splitlines())
    for chunk in chunks:
        assert len(chunk.content) <= 180
        assert chunk.metadata["has_code"] is True
        # Every line in each chunk must be a complete original line (no mid-line break).
        for ln in chunk.content.splitlines():
            assert ln in original_line_set


def test_multipage_pdf_chunking_tracks_page_start_and_page_end() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(items=(TextItem("Sayfa bir kisa metin.", x=72, y=700),)),
            PageSpec(items=(TextItem("Sayfa iki kisa metin.", x=72, y=700),)),
            PageSpec(items=(TextItem("Sayfa uc kisa metin.", x=72, y=700),)),
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="pages.pdf")

    # Large chunk merges all 3 pages -> page_start=1, page_end=3
    merged = StructureAwareChunker(chunk_size=500, chunk_overlap=0).chunk(doc)
    assert len(merged) == 1
    assert (merged[0].page_start, merged[0].page_end) == (1, 3)

    # Small chunk keeps pages separate -> accurate per-chunk page numbers
    separate = StructureAwareChunker(chunk_size=30, chunk_overlap=0).chunk(doc)
    assert [(c.page_start, c.page_end) for c in separate] == [(1, 1), (2, 2), (3, 3)]
