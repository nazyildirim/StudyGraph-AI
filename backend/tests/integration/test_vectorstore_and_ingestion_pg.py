"""PostgreSQL integration tests for 0004 migration, VectorStore, and ingestion."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from alembic import command
from alembic.config import Config
import numpy as np
import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.roles import Role
from app.rag.chunking import StructureAwareChunker
from app.rag.domain import ChunkDraft, ProcessingStatus
from app.rag.embedding import (
    EmbeddingModelMismatchError,
    InvalidEmbeddingVectorError,
    serialize_vector,
)
from app.rag.parsing import PdfDocumentParser, PlainTextParser
from app.rag.vectorstore import PostgresNumpyVectorStore
from app.repositories.course_material_repository import (
    SqlAlchemyCourseMaterialRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.errors import (
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
)
from app.repositories.material_chunk_repository import (
    SqlAlchemyMaterialChunkRepository,
)
from app.repositories.user_repository import SqlAlchemyUserRepository
from app.services.material_ingestion_service import MaterialIngestionService
from tests.integration.rag_pg_helpers import (
    TRUNCATE_ALL_SQL,
    insert_chunk,
    insert_course,
    insert_material,
    insert_user,
)
from tests.rag.fakes import FakeEmbeddingProvider
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf

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


def test_migration_0004_preserves_existing_chunks_and_downgrades_cleanly(
    pg_engine: Engine, verified_alembic_config: Config
) -> None:
    cfg = verified_alembic_config
    try:
        command.downgrade(cfg, "0003_create_rag_tables")
        with pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
            inst = insert_user(conn, "i@example.edu", "instructor")
            course = insert_course(conn, "CENG101", inst)
            mat = insert_material(conn, course, inst)
            chunk_id = insert_chunk(conn, mat, 0)

        # Upgrading to 0004 must keep the pre-existing unembedded chunk intact.
        command.upgrade(cfg, "0004_add_chunk_embeddings")
        with pg_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("material_chunks")}
            assert {"embedding", "embedding_model", "embedding_dim"} <= cols
            row = conn.execute(
                text(
                    "SELECT content, embedding, embedding_model, embedding_dim "
                    "FROM material_chunks WHERE id = :id"
                ),
                {"id": chunk_id},
            ).one()
            assert row == ("text", None, None, None)

        command.check(cfg)

        # Downgrade to 0003 removes embedding columns cleanly.
        command.downgrade(cfg, "0003_create_rag_tables")
        with pg_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("material_chunks")}
            assert not ({"embedding", "embedding_model", "embedding_dim"} & cols)
    finally:
        command.upgrade(cfg, "head")
        with pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_db_check_constraints_enforce_embedding_consistency_and_byte_length(
    migrated_pg_engine: Engine,
) -> None:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
        inst = insert_user(conn, "i@example.edu", "instructor")
        course = insert_course(conn, "CENG101", inst)
        mat = insert_material(conn, course, inst)

    good_bytes = np.array([1.0, 0.0, 0.0, 0.0], dtype="<f4").tobytes()
    bad_statements = [
        # Partial embedding fields (missing model & dim)
        (
            "INSERT INTO material_chunks (material_id, chunk_index, content, embedding) "
            "VALUES (:m, 0, 'x', :emb)"
        ),
        # Wrong byte length (16 bytes for dim=8)
        (
            "INSERT INTO material_chunks "
            "(material_id, chunk_index, content, embedding, embedding_model, embedding_dim) "
            "VALUES (:m, 1, 'x', :emb, 'm', 8)"
        ),
        # Non-positive dim
        (
            "INSERT INTO material_chunks "
            "(material_id, chunk_index, content, embedding, embedding_model, embedding_dim) "
            "VALUES (:m, 2, 'x', :empty, 'm', 0)"
        ),
    ]
    for stmt in bad_statements:
        with pytest.raises(IntegrityError):
            with migrated_pg_engine.begin() as conn:
                conn.execute(
                    text(stmt),
                    {"m": mat, "emb": good_bytes, "empty": b""},
                )


def test_vector_store_cosine_similarity_isolation_and_deterministic_tie_breaking(
    session: Session,
) -> None:
    inst = SqlAlchemyUserRepository(session).create(
        email="inst@example.edu",
        hashed_password="h",
        first_name="A",
        last_name="B",
        role=Role.INSTRUCTOR,
    ).id
    courses = SqlAlchemyCourseRepository(session)
    c1 = courses.create(code="C1", title="Course 1", instructor_id=inst).id
    c2 = courses.create(code="C2", title="Course 2", instructor_id=inst).id

    mats = SqlAlchemyCourseMaterialRepository(session)
    m1 = mats.create(
        course_id=c1,
        uploaded_by=inst,
        title="Processed C1",
        file_path="m1.pdf",
        file_type="application/pdf",
        file_size_bytes=10,
        content_hash="1" * 64,
    ).id
    m1_pending = mats.create(
        course_id=c1,
        uploaded_by=inst,
        title="Pending C1",
        file_path="m1p.pdf",
        file_type="application/pdf",
        file_size_bytes=10,
        content_hash="2" * 64,
    ).id
    m2 = mats.create(
        course_id=c2,
        uploaded_by=inst,
        title="Processed C2",
        file_path="m2.pdf",
        file_type="application/pdf",
        file_size_bytes=10,
        content_hash="3" * 64,
    ).id

    chunks = SqlAlchemyMaterialChunkRepository(session)
    # Course 1 processed: two equal-score tie chunks + one orthogonal chunk
    c1_chunks = chunks.save_embedded_chunks_and_mark_processed(
        material_id=m1,
        drafts=[
            ChunkDraft(0, "tie-a", page_start=1, page_end=1),
            ChunkDraft(1, "tie-b", page_start=2, page_end=2),
            ChunkDraft(2, "orthogonal", page_start=3, page_end=3),
        ],
        embeddings=[
            serialize_vector([1.0, 0.0, 0.0, 0.0], 4),
            serialize_vector([1.0, 0.0, 0.0, 0.0], 4),
            serialize_vector([0.0, 1.0, 0.0, 0.0], 4),
        ],
        embedding_model="test-model",
        embedding_dim=4,
    )
    # Course 1 pending: must NOT appear in search results
    chunks.replace_chunks(m1_pending, [ChunkDraft(0, "pending chunk")])
    # Course 2 processed: identical vector to query, must NEVER leak into Course 1
    chunks.save_embedded_chunks_and_mark_processed(
        material_id=m2,
        drafts=[ChunkDraft(0, "foreign course secret")],
        embeddings=[serialize_vector([1.0, 0.0, 0.0, 0.0], 4)],
        embedding_model="test-model",
        embedding_dim=4,
    )

    store = PostgresNumpyVectorStore(session)
    hits = store.search(
        course_id=c1,
        query_vector=[1.0, 0.0, 0.0, 0.0],
        expected_model="test-model",
        expected_dim=4,
        top_k=2,
    )
    assert len(hits) == 2
    # Equal score tie-breaking must deterministically order by ascending chunk_id.
    assert [h.chunk_id for h in hits] == [c1_chunks[0].id, c1_chunks[1].id]
    assert all(h.material_id == m1 for h in hits)
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)

    # Model mismatch is rejected.
    with pytest.raises(EmbeddingModelMismatchError):
        store.search(
            course_id=c1,
            query_vector=[1.0, 0.0, 0.0, 0.0],
            expected_model="other-model",
            expected_dim=4,
            top_k=2,
        )

    # Invalid top_k and zero-norm query vector are rejected.
    with pytest.raises(ValueError):
        store.search(
            course_id=c1,
            query_vector=[1.0, 0.0, 0.0, 0.0],
            expected_model="test-model",
            expected_dim=4,
            top_k=0,
        )
    with pytest.raises(InvalidEmbeddingVectorError):
        store.search(
            course_id=c1,
            query_vector=[0.0, 0.0, 0.0, 0.0],
            expected_model="test-model",
            expected_dim=4,
            top_k=2,
        )


def test_end_to_end_ingestion_and_concurrent_claim_on_postgres(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
) -> None:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))

    setup = pg_session_factory()
    try:
        inst = SqlAlchemyUserRepository(setup).create(
            email="i@example.edu",
            hashed_password="h",
            first_name="A",
            last_name="B",
            role=Role.INSTRUCTOR,
        ).id
        course = SqlAlchemyCourseRepository(setup).create(
            code="CENG201", title="C Programming", instructor_id=inst
        ).id
        material_id = SqlAlchemyCourseMaterialRepository(setup).create(
            course_id=course,
            uploaded_by=inst,
            title="C Pointers Lecture",
            file_path="pointers.pdf",
            file_type="application/pdf",
            file_size_bytes=200,
            content_hash="a" * 64,
        ).id
    finally:
        setup.close()

    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("C Pointers", x=72, y=730, size=15, font="bold"),
                    TextItem("Pointer degiskeni bellek adresi saklar.", x=72, y=700),
                )
            )
        ]
    )
    provider = FakeEmbeddingProvider(dimension=8, max_tokens=64)

    def run_worker() -> str:
        db = pg_session_factory()
        try:
            service = MaterialIngestionService(
                material_repository=SqlAlchemyCourseMaterialRepository(db),
                chunk_repository=SqlAlchemyMaterialChunkRepository(db),
                parsers={
                    "application/pdf": PdfDocumentParser(),
                    "text/plain": PlainTextParser(),
                },
                chunker=StructureAwareChunker(chunk_size=300, chunk_overlap=30),
                embedding_provider=provider,
            )
            service.ingest(material_id, source=pdf_bytes)
            return "ok"
        except (MaterialAlreadyProcessingError, MaterialAlreadyProcessedError):
            return "rejected"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted([f.result() for f in [pool.submit(run_worker), pool.submit(run_worker)]])

    assert outcomes == ["ok", "rejected"]

    verify = pg_session_factory()
    try:
        mat = SqlAlchemyCourseMaterialRepository(verify).get_by_id(material_id)
        assert mat.processing_status == ProcessingStatus.PROCESSED.value
        store = PostgresNumpyVectorStore(verify)
        q_vec = provider.embed_query("bellek adresi")
        hits = store.search(
            course_id=course,
            query_vector=q_vec,
            expected_model=provider.model_name,
            expected_dim=provider.dimension,
            top_k=3,
        )
        assert len(hits) == 1
        assert "bellek adresi" in hits[0].content
    finally:
        verify.close()
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))
