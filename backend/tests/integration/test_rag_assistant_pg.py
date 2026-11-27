"""PostgreSQL integration tests for RagAssistantService atomic persistence and rollback."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError
from app.authorization.roles import Role
from app.models import EnrollmentStatus
from app.rag.domain import ChunkDraft
from app.rag.embedding import serialize_vector
from app.rag.generation import (
    AnswerMode,
    CitationValidator,
    ExtractiveLLMClient,
    LLMRequest,
    LLMResponse,
    PromptBuilder,
)
from app.rag.retrieval import CourseRetrievalService, SemanticRetriever
from app.rag.vectorstore import PostgresNumpyVectorStore
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_material_repository import (
    SqlAlchemyCourseMaterialRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.errors import InvalidCitationError
from app.repositories.material_chunk_repository import (
    SqlAlchemyMaterialChunkRepository,
)
from app.repositories.rag_query_repository import SqlAlchemyRagQueryRepository
from app.repositories.user_repository import SqlAlchemyUserRepository
from app.services.rag_assistant_service import RagAssistantService
from tests.integration.rag_pg_helpers import TRUNCATE_ALL_SQL
from tests.rag.fakes import FakeEmbeddingProvider

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session(
    migrated_pg_engine: Engine, pg_session_factory: sessionmaker[Session]
) -> Generator[Session, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    db = pg_session_factory()
    try:
        yield db
    finally:
        db.close()
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_rag_assistant_atomic_persistence_and_midflight_deletion_rollback(
    session: Session,
) -> None:
    users = SqlAlchemyUserRepository(session)
    inst = users.create(
        email="inst@example.edu", hashed_password="h", first_name="A", last_name="B", role=Role.INSTRUCTOR
    )
    student = users.create(
        email="st@example.edu", hashed_password="h", first_name="C", last_name="D", role=Role.STUDENT
    )
    courses = SqlAlchemyCourseRepository(session)
    course = courses.create(code="CENG301", title="Systems", instructor_id=inst.id)
    enrollments = SqlAlchemyCourseEnrollmentRepository(session)
    enrollments.create(student_id=student.id, course_id=course.id, status=EnrollmentStatus.ACTIVE)

    mats = SqlAlchemyCourseMaterialRepository(session)
    mat = mats.create(
        course_id=course.id, uploaded_by=inst.id, title="Pointers",
        file_path="p.pdf", file_type="application/pdf", file_size_bytes=50, content_hash="a" * 64,
    )
    emb = FakeEmbeddingProvider(dimension=8, max_tokens=64)
    q_vec = emb.embed_query("pointer nedir")
    chunks = SqlAlchemyMaterialChunkRepository(session)
    saved_chunks = chunks.save_embedded_chunks_and_mark_processed(
        material_id=mat.id,
        drafts=[ChunkDraft(0, "C pointer bellek adresi saklar.", page_start=3, page_end=3)],
        embeddings=[serialize_vector(q_vec, 8)],
        embedding_model=emb.model_name,
        embedding_dim=emb.dimension,
    )

    policy = CourseAccessPolicy(course_repository=courses, enrollment_repository=enrollments)
    retrieval = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=SemanticRetriever(
            embedding_provider=emb, vector_store=PostgresNumpyVectorStore(session)
        ),
        primary_min_score=0.81,
    )
    query_repo = SqlAlchemyRagQueryRepository(session)

    class _OkLLM:
        model_name = "test-llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(True, "Pointer bellek adresini saklar [S1].", ("S1",), "test-llm")

    service = RagAssistantService(
        access_policy=policy,
        retrieval_service=retrieval,
        prompt_builder=PromptBuilder(),
        llm_client=_OkLLM(),  # type: ignore[arg-type]
        citation_validator=CitationValidator(),
        query_repository=query_repo,
        extractive_fallback=ExtractiveLLMClient(),
    )

    # 1. Grounded answer persisted atomically with citation
    ans = service.ask(user=student, course_id=course.id, question="pointer nedir", mode=AnswerMode.EXPLAIN)
    assert ans.grounded is True and ans.query_id is not None
    assert len(ans.sources) == 1 and ans.sources[0].chunk_id == saved_chunks[0].id
    assert len(query_repo.list_citations(ans.query_id)) == 1

    # 2. Mid-flight material deletion while LLM is generating -> rollback, zero new query row
    class _DeletingLLM:
        model_name = "test-llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            mats.delete(mat.id)
            return LLMResponse(True, "Cevap [S1].", ("S1",), "test-llm")

    service_del = RagAssistantService(
        access_policy=policy,
        retrieval_service=retrieval,
        prompt_builder=PromptBuilder(),
        llm_client=_DeletingLLM(),  # type: ignore[arg-type]
        citation_validator=CitationValidator(),
        query_repository=query_repo,
    )
    with pytest.raises(InvalidCitationError):
        service_del.ask(user=student, course_id=course.id, question="pointer nedir")
    assert len(query_repo.list_for_student(student.id, course.id)) == 1  # unchanged

    # 3. Unauthorized user rejected cleanly
    outsider = users.create(
        email="out@example.edu", hashed_password="h", first_name="X", last_name="Y", role=Role.STUDENT
    )
    with pytest.raises(ResourceNotFoundError):
        service.ask(user=outsider, course_id=course.id, question="pointer nedir")
