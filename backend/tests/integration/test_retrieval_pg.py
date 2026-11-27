"""PostgreSQL integration tests for CourseAccessPolicy, SemanticRetriever, and Bm25Retriever."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError
from app.authorization.roles import Role
from app.models import EnrollmentStatus
from app.rag.domain import ChunkDraft, RetrievalMethod, RetrievalStatus
from app.rag.embedding import serialize_vector
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
from app.repositories.user_repository import SqlAlchemyUserRepository
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


def test_postgres_retrieval_enforces_access_isolation_and_processed_only(
    session: Session,
) -> None:
    users = SqlAlchemyUserRepository(session)
    inst1 = users.create(
        email="inst1@example.edu", hashed_password="h", first_name="A", last_name="B", role=Role.INSTRUCTOR
    )
    inst2 = users.create(
        email="inst2@example.edu", hashed_password="h", first_name="C", last_name="D", role=Role.INSTRUCTOR
    )
    active_student = users.create(
        email="s1@example.edu", hashed_password="h", first_name="E", last_name="F", role=Role.STUDENT
    )
    dropped_student = users.create(
        email="s2@example.edu", hashed_password="h", first_name="G", last_name="H", role=Role.STUDENT
    )
    admin = users.create(
        email="admin@example.edu", hashed_password="h", first_name="I", last_name="J", role=Role.ADMIN
    )

    courses = SqlAlchemyCourseRepository(session)
    c1 = courses.create(code="CENG101", title="C Programming", instructor_id=inst1.id)
    c2 = courses.create(code="CENG202", title="Other Course", instructor_id=inst2.id)

    enrollments = SqlAlchemyCourseEnrollmentRepository(session)
    enrollments.create(student_id=active_student.id, course_id=c1.id, status=EnrollmentStatus.ACTIVE)
    enrollments.create(student_id=dropped_student.id, course_id=c1.id, status=EnrollmentStatus.DROPPED)

    mats = SqlAlchemyCourseMaterialRepository(session)
    m1_proc = mats.create(
        course_id=c1.id, uploaded_by=inst1.id, title="Pointers PDF",
        file_path="p.pdf", file_type="application/pdf", file_size_bytes=100, content_hash="1" * 64,
    )
    m1_pending = mats.create(
        course_id=c1.id, uploaded_by=inst1.id, title="Unprocessed PDF",
        file_path="u.pdf", file_type="application/pdf", file_size_bytes=100, content_hash="2" * 64,
    )
    m2_proc = mats.create(
        course_id=c2.id, uploaded_by=inst2.id, title="Course 2 Secret",
        file_path="s.pdf", file_type="application/pdf", file_size_bytes=100, content_hash="3" * 64,
    )

    provider = FakeEmbeddingProvider(dimension=8, max_tokens=64)
    q_vec = provider.embed_query("pointer printf")
    chunks = SqlAlchemyMaterialChunkRepository(session)
    chunks.save_embedded_chunks_and_mark_processed(
        material_id=m1_proc.id,
        drafts=[ChunkDraft(0, "C pointer printf bellek adresi", page_start=2, page_end=2)],
        embeddings=[serialize_vector(q_vec, 8)],
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
    )
    # Pending material in C1 must be excluded from both semantic & BM25
    chunks.replace_chunks(
        m1_pending.id,
        [ChunkDraft(0, "pointer printf pending unprocessed secret")],
    )
    # Processed material in C2 must never leak into C1
    chunks.save_embedded_chunks_and_mark_processed(
        material_id=m2_proc.id,
        drafts=[ChunkDraft(0, "pointer printf foreign course 2 secret", page_start=1, page_end=1)],
        embeddings=[serialize_vector(q_vec, 8)],
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
    )

    policy = CourseAccessPolicy(
        course_repository=courses, enrollment_repository=enrollments
    )
    semantic = SemanticRetriever(
        embedding_provider=provider,
        vector_store=PostgresNumpyVectorStore(session),
    )
    bm25 = Bm25Retriever(
        corpus_repository=SqlAlchemyBm25CorpusRepository(session)
    )
    service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=semantic,
        fallback_retriever=bm25,
        primary_min_score=0.81,
    )

    # Enrolled student, owning instructor, and admin all get ONLY C1 processed chunk
    for allowed_user in (active_student, inst1, admin):
        res = service.retrieve(user=allowed_user, course_id=c1.id, query="pointer printf")
        assert res.status is RetrievalStatus.OK
        assert len(res.chunks) == 1
        assert res.chunks[0].material_id == m1_proc.id
        assert res.chunks[0].course_id == c1.id
        assert res.chunks[0].page_start == 2

    # Dropped student and other instructor are rejected with ResourceNotFoundError
    for denied_user in (dropped_student, inst2):
        with pytest.raises(ResourceNotFoundError):
            service.retrieve(user=denied_user, course_id=c1.id, query="pointer printf")

    # BM25 standalone against PostgreSQL also enforces course_id + processed-only
    bm25_service = CourseRetrievalService(
        access_policy=policy,
        primary_retriever=bm25,
        primary_min_score=0.25,
    )
    bm25_res = bm25_service.retrieve(
        user=active_student, course_id=c1.id, query="pointer printf"
    )
    assert bm25_res.status is RetrievalStatus.OK
    assert bm25_res.method is RetrievalMethod.BM25
    assert [c.material_id for c in bm25_res.chunks] == [m1_proc.id]
