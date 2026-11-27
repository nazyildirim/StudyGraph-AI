"""RAG retrieval package (Semantic E5, pure-Python BM25, CourseRetrievalService)."""

from app.rag.retrieval.bm25 import (
    DEFAULT_BM25_MIN_SCORE,
    DEFAULT_BM25_TOP_K,
    Bm25Candidate,
    Bm25CorpusRepository,
    Bm25Retriever,
    SqlAlchemyBm25CorpusRepository,
    tokenize_for_bm25,
)
from app.rag.retrieval.errors import (
    InvalidQueryError,
    RetrievalBackendUnavailableError,
    RetrievalError,
)
from app.rag.retrieval.protocol import ChunkRetriever
from app.rag.retrieval.retrieval_service import CourseRetrievalService
from app.rag.retrieval.semantic_retriever import (
    DEFAULT_MAX_QUERY_LENGTH,
    DEFAULT_SEMANTIC_MIN_SCORE,
    DEFAULT_SEMANTIC_TOP_K,
    SemanticRetriever,
)

__all__ = [
    "Bm25Candidate",
    "Bm25CorpusRepository",
    "Bm25Retriever",
    "ChunkRetriever",
    "CourseRetrievalService",
    "DEFAULT_BM25_MIN_SCORE",
    "DEFAULT_BM25_TOP_K",
    "DEFAULT_MAX_QUERY_LENGTH",
    "DEFAULT_SEMANTIC_MIN_SCORE",
    "DEFAULT_SEMANTIC_TOP_K",
    "InvalidQueryError",
    "RetrievalBackendUnavailableError",
    "RetrievalError",
    "SemanticRetriever",
    "SqlAlchemyBm25CorpusRepository",
    "tokenize_for_bm25",
]
