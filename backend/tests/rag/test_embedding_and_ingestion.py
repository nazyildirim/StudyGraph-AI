"""Unit tests for embedding validation, token splitting, ONNX lazy loading, and ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path

import numpy as np
import pytest

from app.rag.chunking import StructureAwareChunker
from app.rag.domain import ChunkDraft, ProcessingStatus
from app.rag.embedding import (
    InvalidEmbeddingInputError,
    InvalidEmbeddingVectorError,
    ModelNotFoundError,
    OnnxE5EmbeddingProvider,
    TokenLimitExceededError,
    deserialize_vector,
    enforce_token_limit,
    l2_normalize_matrix,
    serialize_vector,
    validate_vector,
)
from app.rag.embedding.onnx_e5_provider import _mean_pool
from app.rag.parsing import PdfDocumentParser, PlainTextParser
from app.repositories.errors import (
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
    MaterialNotFoundError,
)
from app.services.material_ingestion_service import (
    MaterialIngestionError,
    MaterialIngestionService,
    UnsupportedFileTypeError,
)
from tests.rag.fakes import FakeEmbeddingProvider
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf


# ----------------------------------------------------------- vector validation
def test_vector_serialize_deserialize_roundtrip() -> None:
    vec = [0.6, 0.8, 0.0, 0.0]
    raw = serialize_vector(vec, expected_dim=4)
    assert len(raw) == 16
    restored = deserialize_vector(raw, expected_dim=4)
    assert np.allclose(restored, np.array(vec, dtype=np.float32))


@pytest.mark.parametrize(
    "bad_vec",
    [
        [1.0, 2.0],  # wrong dim
        [0.0, 0.0, 0.0, 0.0],  # zero norm
        [float("nan"), 1.0, 0.0, 0.0],
        [float("inf"), 1.0, 0.0, 0.0],
        [float("-inf"), 1.0, 0.0, 0.0],
    ],
)
def test_validate_vector_rejects_invalid_vectors(bad_vec: list[float]) -> None:
    with pytest.raises(InvalidEmbeddingVectorError):
        validate_vector(bad_vec, expected_dim=4)


def test_deserialize_rejects_wrong_byte_length_and_nan() -> None:
    with pytest.raises(InvalidEmbeddingVectorError):
        deserialize_vector(b"\x00" * 12, expected_dim=4)
    nan_bytes = np.array([math.nan, 1.0, 0.0, 0.0], dtype="<f4").tobytes()
    with pytest.raises(InvalidEmbeddingVectorError):
        deserialize_vector(nan_bytes, expected_dim=4)


def test_mean_pooling_respects_attention_mask_and_l2_normalizes() -> None:
    # Batch of 2, seq_len 3, dim 2; padded tokens have huge junk values that must be ignored.
    token_emb = np.array(
        [
            [[2.0, 0.0], [4.0, 0.0], [999.0, 999.0]],
            [[0.0, 3.0], [999.0, 999.0], [999.0, 999.0]],
        ],
        dtype=np.float32,
    )
    mask = np.array([[1, 1, 0], [1, 0, 0]], dtype=np.int64)
    pooled = _mean_pool(token_emb, mask)
    assert np.allclose(pooled, np.array([[3.0, 0.0], [0.0, 3.0]], dtype=np.float32))

    normed = l2_normalize_matrix(pooled)
    assert np.allclose(normed, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))


# ----------------------------------------------------------- provider contract
def test_fake_embedding_provider_is_deterministic_and_distinguishes_prefixes() -> None:
    provider = FakeEmbeddingProvider(dimension=8, max_tokens=32)
    v1 = provider.embed_documents(["pointer bellek adresi"])[0]
    v2 = provider.embed_documents(["pointer bellek adresi"])[0]
    q1 = provider.embed_query("pointer bellek adresi")
    assert v1 == v2
    assert len(v1) == 8
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-5)
    assert v1 != q1  # passage: vs query: prefix


def test_onnx_provider_is_lazy_and_reports_missing_model_cleanly(tmp_path: Path) -> None:
    # Construction must NOT touch disk or fail even when model_dir does not exist.
    provider = OnnxE5EmbeddingProvider(tmp_path / "nonexistent")
    assert provider.is_loaded is False
    assert provider.dimension == 384
    assert provider.max_tokens == 512

    with pytest.raises(ModelNotFoundError):
        provider.embed_query("test")
    with pytest.raises(InvalidEmbeddingInputError):
        provider.embed_documents([])
    with pytest.raises(InvalidEmbeddingInputError):
        provider.embed_query("   ")


def test_enforce_token_limit_resplits_oversized_chunk_without_truncation() -> None:
    provider = FakeEmbeddingProvider(dimension=8, max_tokens=15)
    long_text = " ".join(f"kelime{i}" for i in range(40))
    oversized = ChunkDraft(
        chunk_index=0,
        content=long_text,
        page_start=2,
        page_end=3,
        metadata={"source_name": "ders.pdf", "file_type": "application/pdf", "has_code": False},
    )
    adjusted = enforce_token_limit([oversized], provider)
    assert len(adjusted) >= 3
    assert [c.chunk_index for c in adjusted] == list(range(len(adjusted)))
    for chunk in adjusted:
        assert provider.count_tokens(chunk.content, is_query=False) <= provider.max_tokens
        assert (chunk.page_start, chunk.page_end) == (2, 3)
        assert chunk.metadata["token_resplit"] is True
    # Every original word must still appear somewhere (no silent truncation).
    combined = " ".join(c.content for c in adjusted)
    assert "kelime0" in combined and "kelime39" in combined


# ---------------------------------------------- MaterialIngestionService units
@dataclass
class _FakeMaterial:
    id: int
    course_id: int
    title: str
    file_path: str
    file_type: str
    processing_status: str = ProcessingStatus.PENDING.value
    error_message: str | None = None
    extraction_report: str | None = None


@dataclass
class _FakeMaterialRepo:
    store: dict[int, _FakeMaterial] = field(default_factory=dict)

    def get_by_id(self, material_id: int) -> _FakeMaterial | None:
        return self.store.get(material_id)

    def claim_for_processing(self, material_id: int) -> _FakeMaterial:
        mat = self.store.get(material_id)
        if mat is None:
            raise MaterialNotFoundError(str(material_id))
        if mat.processing_status == ProcessingStatus.PROCESSING.value:
            raise MaterialAlreadyProcessingError(str(material_id))
        if mat.processing_status == ProcessingStatus.PROCESSED.value:
            raise MaterialAlreadyProcessedError(str(material_id))
        mat.processing_status = ProcessingStatus.PROCESSING.value
        mat.error_message = None
        return mat

    def update_processing_status(
        self,
        material_id: int,
        status: ProcessingStatus,
        *,
        error_message: str | None = None,
        extraction_report: str | None = None,
    ) -> _FakeMaterial:
        mat = self.store[material_id]
        mat.processing_status = status.value
        mat.error_message = error_message if status is ProcessingStatus.FAILED else None
        if extraction_report is not None:
            mat.extraction_report = extraction_report
        return mat


@dataclass
class _FakeChunkRepo:
    materials: _FakeMaterialRepo
    chunks: dict[int, list[tuple[ChunkDraft, bytes, str, int]]] = field(default_factory=dict)

    def save_embedded_chunks_and_mark_processed(
        self,
        *,
        material_id: int,
        drafts: list[ChunkDraft],
        embeddings: list[bytes],
        embedding_model: str,
        embedding_dim: int,
        extraction_report: str | None = None,
    ) -> list[ChunkDraft]:
        self.chunks[material_id] = [
            (d, e, embedding_model, embedding_dim)
            for d, e in zip(drafts, embeddings, strict=True)
        ]
        self.materials.update_processing_status(
            material_id,
            ProcessingStatus.PROCESSED,
            extraction_report=extraction_report,
        )
        return list(drafts)


def _make_service(
    mat_repo: _FakeMaterialRepo,
    chunk_repo: _FakeChunkRepo,
    embedding_provider=None,
) -> MaterialIngestionService:
    return MaterialIngestionService(
        material_repository=mat_repo,  # type: ignore[arg-type]
        chunk_repository=chunk_repo,  # type: ignore[arg-type]
        parsers={
            "application/pdf": PdfDocumentParser(),
            "text/plain": PlainTextParser(),
        },
        chunker=StructureAwareChunker(chunk_size=300, chunk_overlap=30),
        embedding_provider=embedding_provider or FakeEmbeddingProvider(dimension=8, max_tokens=64),
    )


def test_ingestion_service_success_and_blocks_silent_reindexing() -> None:
    mat_repo = _FakeMaterialRepo(
        {1: _FakeMaterial(1, 10, "Pointers", "p.pdf", "application/pdf")}
    )
    chunk_repo = _FakeChunkRepo(mat_repo)
    service = _make_service(mat_repo, chunk_repo)

    pdf = build_pdf([PageSpec(items=(TextItem("C pointer bellek adresi.", x=72, y=700),))])
    result = service.ingest(1, source=pdf)

    assert result.chunk_count == 1
    assert mat_repo.store[1].processing_status == ProcessingStatus.PROCESSED.value
    assert mat_repo.store[1].extraction_report is not None
    assert len(chunk_repo.chunks[1]) == 1

    # Re-ingesting an already processed material must be refused (protects citations).
    with pytest.raises(MaterialAlreadyProcessedError):
        service.ingest(1, source=pdf)


def test_ingestion_service_marks_failed_on_parse_or_embedding_error_without_partial_index() -> None:
    mat_repo = _FakeMaterialRepo(
        {
            1: _FakeMaterial(1, 10, "Secret", "bad.pdf", "application/pdf"),
            2: _FakeMaterial(2, 10, "Good", "ok.txt", "text/plain"),
        }
    )
    chunk_repo = _FakeChunkRepo(mat_repo)

    # 1. Corrupt PDF -> failed, sanitized error, zero chunks saved
    service = _make_service(mat_repo, chunk_repo)
    with pytest.raises(MaterialIngestionError):
        service.ingest(1, source=b"not a pdf with SECRET_TOKEN_123")
    assert mat_repo.store[1].processing_status == ProcessingStatus.FAILED.value
    assert "SECRET_TOKEN_123" not in (mat_repo.store[1].error_message or "")
    assert 1 not in chunk_repo.chunks

    # 2. Embedding provider error -> failed, zero chunks saved
    class _BrokenEmbedding(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            raise InvalidEmbeddingVectorError("simulated NaN")

    broken_service = _make_service(mat_repo, chunk_repo, embedding_provider=_BrokenEmbedding())
    with pytest.raises(MaterialIngestionError):
        broken_service.ingest(2, source=b"Normal ders metni.")
    assert mat_repo.store[2].processing_status == ProcessingStatus.FAILED.value
    assert 2 not in chunk_repo.chunks

    # 3. Retry on failed material with working provider succeeds cleanly
    res = service.ingest(2, source=b"Normal ders metni.")
    assert res.chunk_count == 1
    assert mat_repo.store[2].processing_status == ProcessingStatus.PROCESSED.value


def test_ingestion_service_rejects_concurrent_processing_and_unsupported_mime() -> None:
    mat_repo = _FakeMaterialRepo(
        {
            1: _FakeMaterial(1, 10, "Busy", "a.pdf", "application/pdf", ProcessingStatus.PROCESSING.value),
            2: _FakeMaterial(2, 10, "Docx", "a.docx", "application/vnd.openxmlformats"),
        }
    )
    chunk_repo = _FakeChunkRepo(mat_repo)
    service = _make_service(mat_repo, chunk_repo)

    with pytest.raises(MaterialAlreadyProcessingError):
        service.ingest(1, source=b"%PDF-1.4")

    with pytest.raises(UnsupportedFileTypeError):
        service.ingest(2, source=b"data")
    assert mat_repo.store[2].processing_status == ProcessingStatus.FAILED.value
