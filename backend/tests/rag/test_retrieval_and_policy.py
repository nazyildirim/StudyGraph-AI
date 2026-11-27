"""Unit tests for CourseAccessPolicy, SemanticRetriever, Bm25Retriever, and CourseRetrievalService."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import SimpleNamespace

import pytest

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError
from app.authorization.roles import Role
from app.rag.domain import RetrievalMethod, RetrievalStatus, RetrievedChunk
from app.rag.embedding.errors import ModelNotFoundError
from app.rag.retrieval import (
    Bm25Candidate,
    Bm25Retriever,
    CourseRetrievalService,
    InvalidQueryError,
    RetrievalBackendUnavailableError,
    SemanticRetriever,
)


# ------------------------------------------------------------------ test fakes
def _user(user_id: int, role: str, *, is_active: bool = True):
    return SimpleNamespace(id=user_id, role=role, is_active=is_active)


def _course(course_id: int, instructor_id: int, *, is_active: bool = True):
    return SimpleNamespace(
        id=course_id, instructor_id=instructor_id, is_active=is_active
    )


@dataclass
class _FakeCourseRepo:
    courses: dict[int, object]

    def get_by_id(self, course_id: int):
        return self.courses.get(course_id)


@dataclass
class _FakeEnrollmentRepo:
    active_pairs: set[tuple[int, int]]

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool:
        return (student_id, course_id) in self.active_pairs


class _SpyEmbeddingProvider:
    model_name = "spy-model"
    dimension = 4
    max_tokens = 64

    def __init__(self, *, raise_not_found: bool = False) -> None:
        self.calls: list[str] = []
        self._raise_not_found = raise_not_found

    def count_tokens(self, text: str, *, is_query: bool = False) -> int:
        return len(text.split()) + 2

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        if self._raise_not_found:
            raise ModelNotFoundError("model missing")
        return [1.0, 0.0, 0.0, 0.0]


class _SpyVectorStore:
    def __init__(self, hits: list[RetrievedChunk], *, error: Exception | None = None) -> None:
        self.calls: list[int] = []
        self._hits = hits
        self._error = error

    def search(self, *, course_id: int, query_vector, expected_model: str, expected_dim: int, top_k: int = 5):
        self.calls.append(course_id)
        if self._error is not None:
            raise self._error
        return list(self._hits)


@dataclass
class _FakeBm25Repo:
    by_course: dict[int, list[Bm25Candidate]]

    def list_processed_chunks(self, course_id: int) -> list[Bm25Candidate]:
        return list(self.by_course.get(course_id, []))


def _make_policy() -> CourseAccessPolicy:
    return CourseAccessPolicy(
        course_repository=_FakeCourseRepo(
            {
                10: _course(10, instructor_id=200, is_active=True),
                11: _course(11, instructor_id=201, is_active=True),
                12: _course(12, instructor_id=200, is_active=False),
            }
        ),  # type: ignore[arg-type]
        enrollment_repository=_FakeEnrollmentRepo({(100, 10)}),  # type: ignore[arg-type]
    )


# --------------------------------------------------------- CourseAccessPolicy
def test_access_policy_role_matrix() -> None:
    policy = _make_policy()

    # 1. Active enrolled student -> allowed
    assert policy.check_read_access(_user(100, Role.STUDENT.value), 10).id == 10
    # 2. Unenrolled student -> denied
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(101, Role.STUDENT.value), 10)
    # 3. Course owner instructor -> allowed
    assert policy.check_read_access(_user(200, Role.INSTRUCTOR.value), 10).id == 10
    # 4. Different instructor -> denied
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(200, Role.INSTRUCTOR.value), 11)
    # 5. Admin -> allowed on active course
    assert policy.check_read_access(_user(300, Role.ADMIN.value), 11).id == 11
    # 6. Inactive user -> denied (even if admin or enrolled)
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(300, Role.ADMIN.value, is_active=False), 10)
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(100, Role.STUDENT.value, is_active=False), 10)
    # 7. Unknown role -> deny by default
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(100, "superadmin"), 10)
    # 8. Missing course and inactive course -> ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(300, Role.ADMIN.value), 999)
    with pytest.raises(ResourceNotFoundError):
        policy.check_read_access(_user(300, Role.ADMIN.value), 12)


# ------------------------------------- access-first & no unauthorized calls
def test_unauthorized_query_never_calls_embedding_store_or_fallback() -> None:
    policy = _make_policy()
    spy_emb = _SpyEmbeddingProvider(raise_not_found=True)
    spy_store = _SpyVectorStore([])
    bm25_called = False

    class _SpyBm25:
        method = RetrievalMethod.BM25

        def retrieve(self, **kwargs):
            nonlocal bm25_called
            bm25_called = True
            return []

    service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=spy_emb, vector_store=spy_store  # type: ignore[arg-type]
        ),
        fallback_retriever=_SpyBm25(),  # type: ignore[arg-type]
    )

    with pytest.raises(ResourceNotFoundError):
        service.retrieve(
            user=_user(101, Role.STUDENT.value),  # unenrolled
            course_id=10,
            query="C pointer nedir?",
        )

    assert spy_emb.calls == []
    assert spy_store.calls == []
    assert bm25_called is False


# --------------------------------- threshold, dedup, tie-break, no-sources
def test_semantic_retriever_threshold_dedup_metadata_and_deterministic_order() -> None:
    hits = [
        RetrievedChunk(5, 1, "Ders Notu", "esit skor B", 2, 2, 0.88),
        RetrievedChunk(2, 1, "Ders Notu", "esit skor A", 1, 1, 0.88),
        RetrievedChunk(2, 1, "Ders Notu", "duplicate chunk 2", 1, 1, 0.88),
        RetrievedChunk(9, 1, "Ders Notu", "esik alti", 3, 3, 0.72),
    ]
    retriever = SemanticRetriever(
        embedding_provider=_SpyEmbeddingProvider(),  # type: ignore[arg-type]
        vector_store=_SpyVectorStore(hits),  # type: ignore[arg-type]
    )

    out = retriever.retrieve(course_id=10, query="pointer", top_k=5, min_score=0.81)
    assert [c.chunk_id for c in out] == [2, 5]  # deduplicated + ascending chunk_id tie-break
    assert all(c.course_id == 10 for c in out)
    assert all(c.retrieval_method == RetrievalMethod.SEMANTIC_E5.value for c in out)
    assert (out[0].material_title, out[0].page_start, out[0].page_end) == ("Ders Notu", 1, 1)


def test_semantic_retriever_rejects_nan_scores_and_invalid_inputs() -> None:
    bad_hits = [RetrievedChunk(1, 1, "M", "x", 1, 1, math.nan)]
    retriever = SemanticRetriever(
        embedding_provider=_SpyEmbeddingProvider(),  # type: ignore[arg-type]
        vector_store=_SpyVectorStore(bad_hits),  # type: ignore[arg-type]
        max_query_length=50,
    )
    with pytest.raises(ValueError):
        retriever.retrieve(course_id=10, query="pointer", top_k=3, min_score=0.8)
    with pytest.raises(InvalidQueryError):
        retriever.retrieve(course_id=10, query="   ", top_k=3, min_score=0.8)
    with pytest.raises(InvalidQueryError):
        retriever.retrieve(course_id=10, query="a" * 51, top_k=3, min_score=0.8)
    with pytest.raises(ValueError):
        retriever.retrieve(course_id=10, query="ok", top_k=0, min_score=0.8)
    with pytest.raises(ValueError):
        retriever.retrieve(course_id=10, query="ok", top_k=3, min_score=1.5)


def test_no_sources_does_not_trigger_bm25_fallback() -> None:
    policy = _make_policy()
    # Vector store returns a below-threshold hit -> E5 produces empty list
    low_hits = [RetrievedChunk(1, 1, "M", "ilgisiz", 1, 1, 0.70)]
    bm25_called = False

    class _SpyBm25:
        method = RetrievalMethod.BM25

        def retrieve(self, **kwargs):
            nonlocal bm25_called
            bm25_called = True
            return [RetrievedChunk(1, 1, "M", "should not happen", 1, 1, 2.0)]

    service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=_SpyEmbeddingProvider(),  # type: ignore[arg-type]
            vector_store=_SpyVectorStore(low_hits),  # type: ignore[arg-type]
        ),
        fallback_retriever=_SpyBm25(),  # type: ignore[arg-type]
        primary_min_score=0.81,
    )
    res = service.retrieve(
        user=_user(100, Role.STUDENT.value),
        course_id=10,
        query="mercimek corbasi tarifi",
    )
    assert res.status is RetrievalStatus.NO_SOURCES
    assert res.has_sources is False
    assert res.chunks == ()
    assert res.method is RetrievalMethod.SEMANTIC_E5
    assert res.fallback_used is False
    assert bm25_called is False


def test_safe_fallback_only_on_model_unavailable_not_db_errors() -> None:
    policy = _make_policy()
    bm25 = Bm25Retriever(
        corpus_repository=_FakeBm25Repo(
            {
                10: [
                    Bm25Candidate(1, 5, "C Notu", "C dilinde malloc ve printf kullanimi", 2, 2),
                    Bm25Candidate(2, 5, "Python Notu", "Python for dongusu ve range", 4, 4),
                ]
            }
        )
    )

    # 1. ModelNotFoundError WITH fallback -> BM25 used and clearly flagged
    service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=_SpyEmbeddingProvider(raise_not_found=True),  # type: ignore[arg-type]
            vector_store=_SpyVectorStore([]),  # type: ignore[arg-type]
        ),
        fallback_retriever=bm25,
    )
    res = service.retrieve(
        user=_user(100, Role.STUDENT.value),
        course_id=10,
        query="malloc printf",
    )
    assert res.status is RetrievalStatus.OK
    assert res.method is RetrievalMethod.BM25
    assert res.fallback_used is True
    assert res.fallback_reason == "embedding_model_unavailable"
    assert res.chunks[0].chunk_id == 1
    assert res.chunks[0].retrieval_method == RetrievalMethod.BM25.value

    # 2. ModelNotFoundError WITHOUT fallback -> RetrievalBackendUnavailableError
    no_fb = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=_SpyEmbeddingProvider(raise_not_found=True),  # type: ignore[arg-type]
            vector_store=_SpyVectorStore([]),  # type: ignore[arg-type]
        ),
        fallback_retriever=None,
    )
    with pytest.raises(RetrievalBackendUnavailableError):
        no_fb.retrieve(user=_user(100, Role.STUDENT.value), course_id=10, query="malloc")

    # 3. Database / unexpected runtime error -> MUST NOT fall back to BM25
    db_err_service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=_SpyEmbeddingProvider(),  # type: ignore[arg-type]
            vector_store=_SpyVectorStore([], error=RuntimeError("db down")),  # type: ignore[arg-type]
        ),
        fallback_retriever=bm25,
    )
    with pytest.raises(RuntimeError, match="db down"):
        db_err_service.retrieve(user=_user(100, Role.STUDENT.value), course_id=10, query="malloc")


# ----------------------------------------------------------- BM25 standalone
def test_bm25_technical_terms_turkish_english_and_threshold() -> None:
    repo = _FakeBm25Repo(
        {
            10: [
                Bm25Candidate(10, 1, "C", "int *p = &x; printf(\"%d\", *p); malloc ve free bellek", 1, 1),
                Bm25Candidate(11, 1, "Py", "def factorial(n): for i in range(n): return sonuc", 2, 2),
                Bm25Candidate(12, 1, "OS", "İşletim sistemlerinde süreç ve iş parçacığı yönetimi", 3, 3),
            ]
        }
    )
    bm25 = Bm25Retriever(corpus_repository=repo)

    c_hits = bm25.retrieve(course_id=10, query="printf malloc", top_k=3, min_score=0.25)
    assert c_hits and c_hits[0].chunk_id == 10
    assert c_hits[0].retrieval_method == RetrievalMethod.BM25.value

    tr_hits = bm25.retrieve(course_id=10, query="İşletim sistemlerinde süreç", top_k=3, min_score=0.25)
    assert tr_hits and tr_hits[0].chunk_id == 12

    # Unrelated query returns empty list
    assert bm25.retrieve(course_id=10, query="domates corbasi tarifi", top_k=3, min_score=0.25) == []
    # High threshold filters weak matches
    assert bm25.retrieve(course_id=10, query="bellek", top_k=3, min_score=50.0) == []
