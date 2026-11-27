"""FastAPI dependency providers for RAG materials and assistant endpoints.

Lazy initialization guarantee:
- Importing this module never connects to PostgreSQL, never loads the ONNX
  model, and never connects to Ollama.
- The ONNX embedding provider is cached process-wide so the model is loaded at
  most once across requests, while DB sessions remain per-request.
- A bounded semaphore limits concurrent heavy model operations on 8 GB RAM
  machines and rejects excess load cleanly with HTTP 503.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
import threading

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authorization.course_access_policy import CourseAccessPolicy
from app.core.config import Settings, get_settings
from app.database import get_db
from app.rag.chunking import StructureAwareChunker
from app.rag.embedding import EmbeddingProvider, OnnxE5EmbeddingProvider
from app.rag.generation import (
    CitationValidator,
    ExtractiveLLMClient,
    LLMClient,
    OllamaLLMClient,
    PromptBuilder,
)
from app.rag.parsing import PdfDocumentParser, PlainTextParser
from app.rag.retrieval import (
    Bm25Retriever,
    CourseRetrievalService,
    SemanticRetriever,
    SqlAlchemyBm25CorpusRepository,
)
from app.rag.vectorstore import PostgresNumpyVectorStore
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_material_repository import (
    SqlAlchemyCourseMaterialRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.material_chunk_repository import (
    SqlAlchemyMaterialChunkRepository,
)
from app.repositories.rag_query_repository import SqlAlchemyRagQueryRepository
from app.services.material_ingestion_service import MaterialIngestionService
from app.services.material_service import MaterialService
from app.services.rag_assistant_service import RagAssistantService
from app.storage import FileStorage, LocalFileStorage

_state_lock = threading.Lock()
_cached_embedding_dir: str | None = None
_cached_embedding_provider: OnnxE5EmbeddingProvider | None = None
_cached_semaphore_limit: int | None = None
_model_semaphore: threading.BoundedSemaphore | None = None


def reset_rag_runtime_state() -> None:
    """Clear cached RAG singletons (intended for isolated tests)."""
    global _cached_embedding_dir, _cached_embedding_provider
    global _cached_semaphore_limit, _model_semaphore
    with _state_lock:
        _cached_embedding_dir = None
        _cached_embedding_provider = None
        _cached_semaphore_limit = None
        _model_semaphore = None


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    # Resolve relative paths against repository root (parent of backend/).
    repo_root = Path(__file__).resolve().parents[4]
    return (repo_root / path).resolve()


def get_embedding_provider(
    settings: Settings = Depends(get_settings),
) -> EmbeddingProvider:
    """Return process-wide lazily loaded ONNX E5 embedding provider."""
    global _cached_embedding_dir, _cached_embedding_provider
    resolved = str(_resolve_path(settings.embedding_model_dir))
    with _state_lock:
        if (
            _cached_embedding_provider is None
            or _cached_embedding_dir != resolved
        ):
            _cached_embedding_provider = OnnxE5EmbeddingProvider(resolved)
            _cached_embedding_dir = resolved
        return _cached_embedding_provider


def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    """Return configured local LLMClient (Ollama or extractive backup)."""
    if settings.llm_provider == "extractive":
        return ExtractiveLLMClient()
    return OllamaLLMClient(
        base_url=settings.ollama_base_url,
        model_name=settings.ollama_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def get_file_storage(
    settings: Settings = Depends(get_settings),
) -> FileStorage:
    """Return configured local file storage rooted at UPLOAD_DIR."""
    return LocalFileStorage(
        base_dir=_resolve_path(settings.upload_dir),
        max_bytes=settings.upload_max_bytes,
    )


@contextmanager
def acquire_model_slot(
    settings: Settings,
    *,
    timeout_seconds: float = 0.5,
) -> Generator[None, None, None]:
    """Limit concurrent heavy model operations to protect 8 GB RAM hosts."""
    global _cached_semaphore_limit, _model_semaphore
    with _state_lock:
        if (
            _model_semaphore is None
            or _cached_semaphore_limit != settings.rag_max_concurrent_model_ops
        ):
            _model_semaphore = threading.BoundedSemaphore(
                settings.rag_max_concurrent_model_ops
            )
            _cached_semaphore_limit = settings.rag_max_concurrent_model_ops
        sem = _model_semaphore

    acquired = sem.acquire(timeout=timeout_seconds)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model service is currently at capacity. Please retry shortly.",
        )
    try:
        yield
    finally:
        sem.release()


def get_course_access_policy(
    db: Session = Depends(get_db),
) -> CourseAccessPolicy:
    return CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(db),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(db),
    )


def get_material_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    access_policy: CourseAccessPolicy = Depends(get_course_access_policy),
    file_storage: FileStorage = Depends(get_file_storage),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> MaterialService:
    material_repo = SqlAlchemyCourseMaterialRepository(db)
    chunk_repo = SqlAlchemyMaterialChunkRepository(db)
    ingestion_service = MaterialIngestionService(
        material_repository=material_repo,
        chunk_repository=chunk_repo,
        parsers={
            "application/pdf": PdfDocumentParser(
                max_pages=settings.pdf_max_pages,
                max_extracted_chars=settings.pdf_max_extracted_chars,
            ),
            "text/plain": PlainTextParser(),
        },
        chunker=StructureAwareChunker(),
        embedding_provider=embedding_provider,
        release_db_connection=db.close,
    )
    return MaterialService(
        access_policy=access_policy,
        material_repository=material_repo,
        file_storage=file_storage,
        ingestion_service=ingestion_service,
    )


def get_rag_assistant_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    access_policy: CourseAccessPolicy = Depends(get_course_access_policy),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    llm_client: LLMClient = Depends(get_llm_client),
) -> RagAssistantService:
    semantic = SemanticRetriever(
        embedding_provider=embedding_provider,
        vector_store=PostgresNumpyVectorStore(db),
    )
    bm25 = Bm25Retriever(
        corpus_repository=SqlAlchemyBm25CorpusRepository(db),
    )
    if settings.retrieval_strategy == "bm25":
        retrieval_service = CourseRetrievalService(
            access_policy=access_policy,
            primary_retriever=bm25,
            fallback_retriever=None,
            default_top_k=settings.retrieval_top_k,
        )
    else:
        retrieval_service = CourseRetrievalService(
            access_policy=access_policy,
            primary_retriever=semantic,
            fallback_retriever=bm25,
            default_top_k=settings.retrieval_top_k,
            primary_min_score=settings.retrieval_min_score,
        )

    extractive_fallback = (
        ExtractiveLLMClient() if settings.llm_extractive_fallback_enabled else None
    )
    return RagAssistantService(
        access_policy=access_policy,
        retrieval_service=retrieval_service,
        prompt_builder=PromptBuilder(),
        llm_client=llm_client,
        citation_validator=CitationValidator(),
        query_repository=SqlAlchemyRagQueryRepository(db),
        extractive_fallback=extractive_fallback,
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
        context_window=settings.llm_context_window,
        release_db_connection=db.close,
    )
