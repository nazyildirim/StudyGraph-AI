"""PostgreSQL schema, migration-order and constraint tests (courses + RAG)."""

from __future__ import annotations

from collections.abc import Generator

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.integration.rag_pg_helpers import (
    TRUNCATE_ALL_SQL,
    insert_chunk,
    insert_course,
    insert_material,
    insert_user,
)

pytestmark = pytest.mark.postgres

COURSE_TABLES = {"courses", "course_enrollments"}
RAG_TABLES = {
    "course_materials",
    "material_chunks",
    "rag_queries",
    "rag_query_citations",
}


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(inspect(conn).get_table_names(schema="public"))


@pytest.fixture()
def clean_data(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_migrations_apply_and_revert_in_order(
    pg_engine: Engine, verified_alembic_config: Config
) -> None:
    cfg = verified_alembic_config
    try:
        command.downgrade(cfg, "base")
        assert not (COURSE_TABLES | RAG_TABLES | {"users"}) & _tables(pg_engine)

        command.upgrade(cfg, "0001_create_users")
        assert "users" in _tables(pg_engine)
        assert not (COURSE_TABLES | RAG_TABLES) & _tables(pg_engine)

        command.upgrade(cfg, "0002_create_courses_enrollments")
        tables = _tables(pg_engine)
        assert COURSE_TABLES <= tables
        assert not RAG_TABLES & tables  # RAG migration is separate

        command.upgrade(cfg, "0003_create_rag_tables")
        assert RAG_TABLES <= _tables(pg_engine)

        # RAG downgrade must leave courses/users untouched.
        command.downgrade(cfg, "0002_create_courses_enrollments")
        tables = _tables(pg_engine)
        assert COURSE_TABLES <= tables and not RAG_TABLES & tables

        command.downgrade(cfg, "0001_create_users")
        tables = _tables(pg_engine)
        assert "users" in tables and not COURSE_TABLES & tables
    finally:
        command.upgrade(cfg, "head")

    assert (COURSE_TABLES | RAG_TABLES | {"users"}) <= _tables(pg_engine)


def test_orm_metadata_has_no_drift_against_migrations(
    migrated_pg_engine: Engine, verified_alembic_config: Config
) -> None:
    command.check(verified_alembic_config)


def test_foreign_key_delete_rules_and_indexes(migrated_pg_engine: Engine) -> None:
    with migrated_pg_engine.connect() as conn:
        inspector = inspect(conn)
        expected = {
            "courses": {"instructor_id": "RESTRICT"},
            "course_enrollments": {"student_id": "CASCADE", "course_id": "CASCADE"},
            "course_materials": {"course_id": "CASCADE", "uploaded_by": "SET NULL"},
            "material_chunks": {"material_id": "CASCADE"},
            "rag_queries": {"student_id": "CASCADE", "course_id": "CASCADE"},
            "rag_query_citations": {"query_id": "CASCADE", "chunk_id": "CASCADE"},
        }
        for table, rules in expected.items():
            actual = {
                fk["constrained_columns"][0]: fk["options"].get("ondelete")
                for fk in inspector.get_foreign_keys(table)
            }
            assert actual == rules, table

        assert {i["name"] for i in inspector.get_indexes("course_materials")} >= {
            "ix_course_materials_course_id",
            "ix_course_materials_uploaded_by",
        }
        assert {c["name"] for c in inspector.get_check_constraints("material_chunks")} == {
            "ck_material_chunks_chunk_index_non_negative",
            "ck_material_chunks_page_start_positive",
            "ck_material_chunks_page_range_valid",
            "ck_material_chunks_embedding_fields_consistent",
            "ck_material_chunks_embedding_dim_positive",
            "ck_material_chunks_embedding_byte_length",
        }


def test_duplicate_course_code_and_enrollment_are_rejected(clean_data: Engine) -> None:
    with clean_data.begin() as conn:
        instructor = insert_user(conn, "i@example.edu", "instructor")
        student = insert_user(conn, "s@example.edu")
        course = insert_course(conn, "CENG101", instructor)
        conn.execute(
            text("INSERT INTO course_enrollments (student_id, course_id) VALUES (:s, :c)"),
            {"s": student, "c": course},
        )

    with pytest.raises(IntegrityError):
        with clean_data.begin() as conn:
            insert_course(conn, "CENG101", instructor)

    with pytest.raises(IntegrityError):
        with clean_data.begin() as conn:
            conn.execute(
                text("INSERT INTO course_enrollments (student_id, course_id) VALUES (:s, :c)"),
                {"s": student, "c": course},
            )


def test_invalid_status_and_check_values_are_rejected(clean_data: Engine) -> None:
    with clean_data.begin() as conn:
        instructor = insert_user(conn, "i@example.edu", "instructor")
        student = insert_user(conn, "s@example.edu")
        course = insert_course(conn, "CENG101", instructor)
        material = insert_material(conn, course, instructor)

    bad_statements = [
        (
            "INSERT INTO course_enrollments (student_id, course_id, status) "
            "VALUES (:student, :course, 'banned')"
        ),
        (
            "UPDATE course_materials SET processing_status = 'done' WHERE id = :material"
        ),
        "UPDATE course_materials SET file_size_bytes = -1 WHERE id = :material",
        (
            "INSERT INTO material_chunks (material_id, chunk_index, content) "
            "VALUES (:material, -1, 'x')"
        ),
        (
            "INSERT INTO material_chunks (material_id, chunk_index, content, page_start) "
            "VALUES (:material, 0, 'x', 0)"
        ),
        (
            "INSERT INTO material_chunks (material_id, chunk_index, content, page_end) "
            "VALUES (:material, 0, 'x', 2)"
        ),
        (
            "INSERT INTO material_chunks (material_id, chunk_index, content, page_start, page_end) "
            "VALUES (:material, 0, 'x', 3, 2)"
        ),
    ]
    for statement in bad_statements:
        with pytest.raises(IntegrityError):
            with clean_data.begin() as conn:
                conn.execute(
                    text(statement),
                    {"student": student, "course": course, "material": material},
                )


def test_citation_score_range_and_uniqueness(clean_data: Engine) -> None:
    with clean_data.begin() as conn:
        instructor = insert_user(conn, "i@example.edu", "instructor")
        student = insert_user(conn, "s@example.edu")
        course = insert_course(conn, "CENG101", instructor)
        material = insert_material(conn, course, instructor)
        chunk = insert_chunk(conn, material, 0)
        other_chunk = insert_chunk(conn, material, 1)
        query = conn.execute(
            text(
                "INSERT INTO rag_queries (student_id, course_id, question, answer) "
                "VALUES (:s, :c, 'q', 'a') RETURNING id"
            ),
            {"s": student, "c": course},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO rag_query_citations (query_id, chunk_id, relevance_score) "
                "VALUES (:q, :ch, 0.5)"
            ),
            {"q": query, "ch": chunk},
        )

    for statement in (
        "INSERT INTO rag_query_citations (query_id, chunk_id) VALUES (:q, :ch)",
        (
            "INSERT INTO rag_query_citations (query_id, chunk_id, relevance_score) "
            "VALUES (:q, :ch2, 1.5)"
        ),
    ):
        with pytest.raises(IntegrityError):
            with clean_data.begin() as conn:
                conn.execute(
                    text(statement),
                    {"q": query, "ch": chunk, "ch2": other_chunk},
                )


def test_delete_rules_cascade_restrict_and_set_null(clean_data: Engine) -> None:
    with clean_data.begin() as conn:
        instructor = insert_user(conn, "i@example.edu", "instructor")
        student = insert_user(conn, "s@example.edu")
        course = insert_course(conn, "CENG101", instructor)
        material = insert_material(conn, course, instructor)
        chunk = insert_chunk(conn, material)
        conn.execute(
            text("INSERT INTO course_enrollments (student_id, course_id) VALUES (:s, :c)"),
            {"s": student, "c": course},
        )
        query = conn.execute(
            text(
                "INSERT INTO rag_queries (student_id, course_id, question, answer) "
                "VALUES (:s, :c, 'q', 'a') RETURNING id"
            ),
            {"s": student, "c": course},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO rag_query_citations (query_id, chunk_id) VALUES (:q, :ch)"),
            {"q": query, "ch": chunk},
        )

    # RESTRICT: instructor owning a course cannot be deleted.
    with pytest.raises(IntegrityError):
        with clean_data.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": instructor})

    def count(conn, table: str) -> int:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    # Deleting a student removes enrollments and queries (and citations).
    with clean_data.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": student})
        assert count(conn, "course_enrollments") == 0
        assert count(conn, "rag_queries") == 0
        assert count(conn, "rag_query_citations") == 0
        assert count(conn, "material_chunks") == 1  # untouched

    # Deleting the course cascades to materials and chunks.
    with clean_data.begin() as conn:
        conn.execute(text("DELETE FROM courses WHERE id = :id"), {"id": course})
        assert count(conn, "course_materials") == 0
        assert count(conn, "material_chunks") == 0


def test_deleting_uploader_keeps_material_with_null_uploader(clean_data: Engine) -> None:
    with clean_data.begin() as conn:
        owner = insert_user(conn, "owner@example.edu", "instructor")
        uploader = insert_user(conn, "up@example.edu", "instructor")
        course = insert_course(conn, "CENG101", owner)
        material = insert_material(conn, course, uploader)
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uploader})
        value = conn.execute(
            text("SELECT uploaded_by FROM course_materials WHERE id = :id"),
            {"id": material},
        ).scalar_one()
        assert value is None
