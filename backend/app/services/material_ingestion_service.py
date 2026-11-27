"""Application service orchestrating course material ingestion (Issue #8).

Workflow:
1. Validate material & atomically claim it (`pending`/`failed` -> `processing`).
   - Already-processing materials raise `MaterialAlreadyProcessingError`.
   - Already-processed materials raise `MaterialAlreadyProcessedError` in MVP
     to prevent silent re-indexing from cascade-deleting `rag_query_citations`.
2. Outside any DB lock: parse -> ExtractionReport -> StructureAwareChunker ->
   token-limit verification/re-splitting -> EmbeddingProvider -> float32 bytes.
3. Atomically persist embedded chunks and mark material `processed` in a single
   transaction. On any error, mark material `failed` with a sanitized message
   (and extraction report if available) without leaving a partial index.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from app.rag.chunking.protocol import TextChunker
from app.rag.domain.types import ExtractionReport, ProcessingStatus
from app.rag.embedding.errors import EmbeddingError
from app.rag.embedding.protocol import EmbeddingProvider
from app.rag.embedding.token_splitter import enforce_token_limit
from app.rag.embedding.validation import serialize_vector
from app.rag.parsing.errors import DocumentParseError
from app.rag.parsing.protocol import DocumentParser
from app.rag.parsing.text_parser import PlainTextParser
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.errors import (
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
    MaterialNotFoundError,
)
from app.repositories.material_chunk_repository import MaterialChunkRepository


class UnsupportedFileTypeError(Exception):
    """Raised when no parser is registered for the material's MIME type."""


class MaterialIngestionError(Exception):
    """Raised when material ingestion fails after recording failed status."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Summary returned after successful material ingestion."""

    material_id: int
    chunk_count: int
    embedding_model: str
    embedding_dim: int
    report: ExtractionReport


class MaterialIngestionService:
    """Orchestrates parsing, chunking, embedding, and atomic persistence."""

    def __init__(
        self,
        *,
        material_repository: CourseMaterialRepository,
        chunk_repository: MaterialChunkRepository,
        parsers: Mapping[str, DocumentParser],
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        release_db_connection: Callable[[], None] | None = None,
    ) -> None:
        self._materials = material_repository
        self._chunks = chunk_repository
        self._parsers = dict(parsers)
        self._chunker = chunker
        self._embeddings = embedding_provider
        self._release_db = release_db_connection

    def ingest(
        self,
        material_id: int,
        *,
        source: Path | str | bytes | None = None,
        user_reported_page: int | None = None,
    ) -> IngestionResult:
        """Ingest a pending or failed material into embedded chunks."""
        # Step 1-2: Validate & claim atomically (short row lock, immediately committed).
        material = self._materials.claim_for_processing(material_id)
        # Copy scalar fields into local primitives before releasing the DB connection
        # so detached/expired ORM state can never cause lazy-load errors.
        material_file_type = material.file_type
        material_title = material.title
        material_file_path = material.file_path

        parser = self._parsers.get(material_file_type)
        if parser is None:
            self._mark_failed(
                material_id,
                error_message=f"Unsupported file type: {material_file_type}",
                extraction_report=None,
            )
            raise UnsupportedFileTypeError(material_file_type)

        # Release pooled DB connection before CPU/model-heavy parsing & ONNX embedding.
        if self._release_db is not None:
            self._release_db()

        report_json: str | None = None
        try:
            # Step 3-4: Parse outside any DB lock or checked-out pool connection.
            effective_source: Path | str | bytes = (
                source if source is not None else Path(material_file_path)
            )
            if isinstance(parser, PlainTextParser) and user_reported_page is not None:
                parsed = parser.parse(
                    effective_source,
                    source_name=material_title,
                    page_number=user_reported_page,
                )
            else:
                parsed = parser.parse(effective_source, source_name=material_title)

            report_dict = parsed.report.to_dict()
            if material_file_type == "text/plain" and user_reported_page is not None:
                report_dict["user_reported_page"] = user_reported_page
                report_dict["page_source"] = "user_reported"
            elif material_file_type == "application/pdf":
                report_dict["page_source"] = "pdf_extracted"
            report_json = json.dumps(report_dict, ensure_ascii=False)

            # Step 5-6: Chunk and enforce real token limits without silent truncation.
            raw_drafts = self._chunker.chunk(parsed)
            drafts = enforce_token_limit(raw_drafts, self._embeddings)
            if not drafts:
                raise MaterialIngestionError("Document produced zero chunks.")

            # Step 7: Embed all chunks outside any DB lock.
            vectors = self._embeddings.embed_documents(
                [draft.content for draft in drafts]
            )
            if len(vectors) != len(drafts):
                raise MaterialIngestionError(
                    "Embedding provider returned an unexpected vector count."
                )
            serialized = [
                serialize_vector(vec, self._embeddings.dimension)
                for vec in vectors
            ]

            # Step 8-9: Single atomic transaction for chunks + status='processed'.
            stored = self._chunks.save_embedded_chunks_and_mark_processed(
                material_id=material_id,
                drafts=drafts,
                embeddings=serialized,
                embedding_model=self._embeddings.model_name,
                embedding_dim=self._embeddings.dimension,
                extraction_report=report_json,
            )
            return IngestionResult(
                material_id=material_id,
                chunk_count=len(stored),
                embedding_model=self._embeddings.model_name,
                embedding_dim=self._embeddings.dimension,
                report=parsed.report,
            )

        except (
            MaterialNotFoundError,
            MaterialAlreadyProcessingError,
            MaterialAlreadyProcessedError,
            UnsupportedFileTypeError,
        ):
            raise
        except DocumentParseError as error:
            if error.report is not None:
                report_json = json.dumps(error.report.to_dict(), ensure_ascii=False)
            safe_msg = f"Document parsing failed ({type(error).__name__})."
            self._mark_failed(material_id, error_message=safe_msg, extraction_report=report_json)
            raise MaterialIngestionError(safe_msg) from error
        except EmbeddingError as error:
            safe_msg = f"Embedding generation failed ({type(error).__name__})."
            self._mark_failed(material_id, error_message=safe_msg, extraction_report=report_json)
            raise MaterialIngestionError(safe_msg) from error
        except MaterialIngestionError as error:
            safe_msg = str(error)
            self._mark_failed(material_id, error_message=safe_msg, extraction_report=report_json)
            raise
        except Exception as error:
            safe_msg = f"Material ingestion failed ({type(error).__name__})."
            self._mark_failed(material_id, error_message=safe_msg, extraction_report=report_json)
            raise MaterialIngestionError(safe_msg) from error

    def _mark_failed(
        self,
        material_id: int,
        *,
        error_message: str,
        extraction_report: str | None,
    ) -> None:
        self._materials.update_processing_status(
            material_id,
            ProcessingStatus.FAILED,
            error_message=error_message,
            extraction_report=extraction_report,
        )
