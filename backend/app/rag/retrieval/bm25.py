"""Pure-Python Okapi BM25 alternative retriever (zero external dependencies).

Important:
- BM25 is lexical/keyword retrieval, NOT semantic embedding retrieval.
- BM25 scores are unbounded non-negative floats (not cosine similarity) and
  must NEVER be directly compared to E5 cosine similarity scores.
- Candidate chunks are loaded strictly for the target `course_id` and
  `processing_status = 'processed'` at the SQL level.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.course_material import CourseMaterial
from app.models.material_chunk import MaterialChunk
from app.rag.domain.types import ProcessingStatus, RetrievalMethod, RetrievedChunk
from app.rag.retrieval.errors import InvalidQueryError

DEFAULT_BM25_TOP_K = 5
DEFAULT_BM25_MIN_SCORE = 0.25
DEFAULT_MAX_QUERY_LENGTH = 2000

_TOKEN_RE = re.compile(r"[a-zçğıöşü0-9_]+")

_STOPWORDS: frozenset[str] = frozenset(
    {
        # Minimal Turkish stopwords
        "ve",
        "veya",
        "ile",
        "bir",
        "bu",
        "şu",
        "da",
        "de",
        "mi",
        "mı",
        "mu",
        "mü",
        "için",
        "gibi",
        "olan",
        "olarak",
        "nedir",
        "nasıl",
        "ne",
        # Minimal English stopwords (code keywords like for/while/in/def/return kept!)
        "the",
        "and",
        "or",
        "of",
        "to",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "how",
        "does",
        "do",
    }
)


@dataclass(frozen=True, slots=True)
class Bm25Candidate:
    """A processed course chunk loaded for BM25 scoring."""

    chunk_id: int
    material_id: int
    material_title: str
    content: str
    page_start: int | None
    page_end: int | None


class Bm25CorpusRepository(Protocol):
    """Repository contract supplying processed chunks for a single course."""

    def list_processed_chunks(self, course_id: int) -> list[Bm25Candidate]: ...


class SqlAlchemyBm25CorpusRepository:
    """SQLAlchemy implementation filtering strictly by course_id and processed status."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_processed_chunks(self, course_id: int) -> list[Bm25Candidate]:
        rows = self._session.execute(
            select(
                MaterialChunk.id,
                MaterialChunk.material_id,
                CourseMaterial.title,
                MaterialChunk.content,
                MaterialChunk.page_start,
                MaterialChunk.page_end,
            )
            .join(CourseMaterial, CourseMaterial.id == MaterialChunk.material_id)
            .where(
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status == ProcessingStatus.PROCESSED.value,
            )
            .order_by(MaterialChunk.id)
        ).all()
        return [
            Bm25Candidate(
                chunk_id=row.id,
                material_id=row.material_id,
                material_title=row.title,
                content=row.content,
                page_start=row.page_start,
                page_end=row.page_end,
            )
            for row in rows
        ]


def tokenize_for_bm25(text: str) -> list[str]:
    """Turkish/English and C/Python code-aware tokenizer for BM25."""
    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    raw_tokens = [tok for tok in _TOKEN_RE.findall(lowered) if len(tok) >= 2]
    if not raw_tokens:
        return []
    filtered = [tok for tok in raw_tokens if tok not in _STOPWORDS]
    return filtered if filtered else raw_tokens


class Bm25Retriever:
    """Okapi BM25 lexical retriever implementing `ChunkRetriever`."""

    def __init__(
        self,
        *,
        corpus_repository: Bm25CorpusRepository,
        k1: float = 1.5,
        b: float = 0.75,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be > 0.")
        if not (0.0 <= b <= 1.0):
            raise ValueError("b must be in [0.0, 1.0].")
        if max_query_length <= 0:
            raise ValueError("max_query_length must be > 0.")
        self._corpus = corpus_repository
        self._k1 = k1
        self._b = b
        self._max_query_length = max_query_length

    @property
    def method(self) -> RetrievalMethod:
        return RetrievalMethod.BM25

    def retrieve(
        self,
        *,
        course_id: int,
        query: str,
        top_k: int = DEFAULT_BM25_TOP_K,
        min_score: float = DEFAULT_BM25_MIN_SCORE,
    ) -> list[RetrievedChunk]:
        if not isinstance(query, str) or not query.strip():
            raise InvalidQueryError("Query must not be blank.")
        cleaned = query.strip()
        if len(cleaned) > self._max_query_length:
            raise InvalidQueryError(
                f"Query length ({len(cleaned)}) exceeds maximum ({self._max_query_length})."
            )
        if course_id <= 0:
            raise ValueError("course_id must be > 0.")
        if top_k <= 0:
            raise ValueError("top_k must be > 0.")
        if not math.isfinite(min_score) or min_score < 0.0:
            raise ValueError("min_score for BM25 must be finite and >= 0.0.")

        query_tokens = tokenize_for_bm25(cleaned)
        if not query_tokens:
            return []

        candidates = self._corpus.list_processed_chunks(course_id)
        if not candidates:
            return []

        doc_tokens_list = [tokenize_for_bm25(c.content) for c in candidates]
        n_docs = len(candidates)
        avgdl = sum(len(t) for t in doc_tokens_list) / max(n_docs, 1)
        if avgdl == 0.0:
            return []

        # Document frequency per term
        df: Counter[str] = Counter()
        for doc_tokens in doc_tokens_list:
            for term in set(doc_tokens):
                df[term] += 1

        # Unique query terms (preserve frequency via Counter)
        q_counts = Counter(query_tokens)

        scored: list[RetrievedChunk] = []
        seen_ids: set[int] = set()
        for candidate, doc_tokens in zip(candidates, doc_tokens_list, strict=True):
            if candidate.chunk_id in seen_ids or not doc_tokens:
                continue
            tf_map = Counter(doc_tokens)
            dl = len(doc_tokens)
            score = 0.0
            for term, q_freq in q_counts.items():
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                # Robertson/Lucene non-negative IDF variant: ln(1 + (N - df + 0.5) / (df + 0.5))
                idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf + self._k1 * (1.0 - self._b + self._b * (dl / avgdl))
                score += q_freq * idf * ((tf * (self._k1 + 1.0)) / denom)

            if not math.isfinite(score):
                raise ValueError("BM25 produced a non-finite score.")
            if score < min_score:
                continue

            seen_ids.add(candidate.chunk_id)
            scored.append(
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    material_id=candidate.material_id,
                    material_title=candidate.material_title,
                    content=candidate.content,
                    page_start=candidate.page_start,
                    page_end=candidate.page_end,
                    score=float(score),
                    course_id=course_id,
                    retrieval_method=RetrievalMethod.BM25.value,
                )
            )

        scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return scored[:top_k]
