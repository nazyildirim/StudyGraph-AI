"""Unit tests for course/RAG ORM metadata and the Alembic revision chain."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _fk_ondelete(table: Table) -> dict[str, str | None]:
    return {
        fk.parent.name: fk.ondelete for fk in table.foreign_keys
    }


def _names(table: Table, kind: type) -> set[str]:
    return {c.name for c in table.constraints if isinstance(c, kind)}


def test_all_phase1_tables_are_registered_in_metadata() -> None:
    assert {
        "users",
        "courses",
        "course_enrollments",
        "course_materials",
        "material_chunks",
        "rag_queries",
        "rag_query_citations",
    } <= set(Base.metadata.tables)


def test_course_instructor_fk_is_restrict_and_code_is_unique() -> None:
    table = _table("courses")
    assert _fk_ondelete(table) == {"instructor_id": "RESTRICT"}
    assert table.c.instructor_id.nullable is False
    assert "uq_courses_code" in _names(table, UniqueConstraint)
    assert table.c.code.type.length == 50
    assert table.c.title.type.length == 200


def test_enrollment_prevents_duplicates_and_cascades() -> None:
    table = _table("course_enrollments")
    assert _fk_ondelete(table) == {"student_id": "CASCADE", "course_id": "CASCADE"}
    assert "uq_course_enrollments_student_id_course_id" in _names(
        table, UniqueConstraint
    )
    assert "ck_course_enrollments_status" in _names(table, CheckConstraint)
    assert {i.name for i in table.indexes} == {"ix_course_enrollments_course_id"}


def test_material_foreign_keys_and_constraints() -> None:
    table = _table("course_materials")
    assert _fk_ondelete(table) == {"course_id": "CASCADE", "uploaded_by": "SET NULL"}
    assert table.c.uploaded_by.nullable is True
    assert table.c.content_hash.nullable is False
    assert {
        "ck_course_materials_processing_status",
        "ck_course_materials_file_size_non_negative",
    } <= _names(table, CheckConstraint)
    assert "uq_course_materials_course_id_content_hash" in _names(
        table, UniqueConstraint
    )


def test_unverified_outcome_reference_is_not_a_foreign_key() -> None:
    material = _table("course_materials")
    chunk = _table("material_chunks")
    assert "unverified_outcome_ref" in material.c
    assert not material.c.unverified_outcome_ref.foreign_keys
    assert "learning_outcome_id" not in chunk.c
    assert "learning_outcomes" not in Base.metadata.tables


def test_chunk_constraints_and_page_columns() -> None:
    table = _table("material_chunks")
    assert _fk_ondelete(table) == {"material_id": "CASCADE"}
    assert {
        "page_start",
        "page_end",
        "metadata_json",
        "embedding",
        "embedding_model",
        "embedding_dim",
    } <= set(table.c.keys())
    assert "page_number" not in table.c
    assert "uq_material_chunks_material_id_chunk_index" in _names(
        table, UniqueConstraint
    )
    assert {
        "ck_material_chunks_chunk_index_non_negative",
        "ck_material_chunks_page_start_positive",
        "ck_material_chunks_page_range_valid",
        "ck_material_chunks_embedding_fields_consistent",
        "ck_material_chunks_embedding_dim_positive",
        "ck_material_chunks_embedding_byte_length",
    } <= _names(table, CheckConstraint)


def test_rag_query_and_citation_constraints() -> None:
    queries = _table("rag_queries")
    citations = _table("rag_query_citations")
    assert _fk_ondelete(queries) == {"student_id": "CASCADE", "course_id": "CASCADE"}
    assert queries.c.grounded.nullable is False
    assert _fk_ondelete(citations) == {"query_id": "CASCADE", "chunk_id": "CASCADE"}
    assert "uq_rag_query_citations_query_id_chunk_id" in _names(
        citations, UniqueConstraint
    )
    assert "ck_rag_query_citations_relevance_score_range" in _names(
        citations, CheckConstraint
    )


def test_all_foreign_key_columns_are_indexed_or_unique_prefixed() -> None:
    """Every FK column must lead an index or a unique constraint."""
    for name in (
        "courses",
        "course_enrollments",
        "course_materials",
        "material_chunks",
        "rag_queries",
        "rag_query_citations",
    ):
        table = _table(name)
        leading = {
            list(i.columns)[0].name for i in table.indexes if len(i.columns) > 0
        } | {
            list(c.columns)[0].name
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }
        for fk in table.foreign_keys:
            assert fk.parent.name in leading, f"{name}.{fk.parent.name} not indexed"


def test_alembic_revision_chain_is_linear_and_ordered() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    assert script.get_heads() == ["0004_add_chunk_embeddings"]
    chain = [rev.revision for rev in script.walk_revisions()]
    assert chain == [
        "0004_add_chunk_embeddings",
        "0003_create_rag_tables",
        "0002_create_courses_enrollments",
        "0001_create_users",
    ]
    assert all(len(rev) <= 32 for rev in chain)  # alembic_version.version_num
