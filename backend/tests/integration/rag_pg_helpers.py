"""Helpers for PostgreSQL integration tests of the course/RAG data layer."""

from __future__ import annotations

from sqlalchemy import Connection, text

TRUNCATE_ALL_SQL = (
    "TRUNCATE TABLE rag_query_citations, rag_queries, material_chunks, "
    "course_materials, course_enrollments, courses, users RESTART IDENTITY CASCADE"
)


def insert_user(conn: Connection, email: str, role: str = "student") -> int:
    return conn.execute(
        text(
            "INSERT INTO users (email, hashed_password, first_name, last_name, role) "
            "VALUES (:email, 'hash', 'A', 'B', :role) RETURNING id"
        ),
        {"email": email, "role": role},
    ).scalar_one()


def insert_course(conn: Connection, code: str, instructor_id: int) -> int:
    return conn.execute(
        text(
            "INSERT INTO courses (code, title, instructor_id) "
            "VALUES (:code, 'Title', :instructor_id) RETURNING id"
        ),
        {"code": code, "instructor_id": instructor_id},
    ).scalar_one()


def insert_material(
    conn: Connection,
    course_id: int,
    uploaded_by: int | None,
    content_hash: str = "a" * 64,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO course_materials "
            "(course_id, uploaded_by, title, file_path, file_type, content_hash) "
            "VALUES (:course_id, :uploaded_by, 'M', 'x/y.pdf', 'application/pdf', "
            ":content_hash) RETURNING id"
        ),
        {
            "course_id": course_id,
            "uploaded_by": uploaded_by,
            "content_hash": content_hash,
        },
    ).scalar_one()


def insert_chunk(conn: Connection, material_id: int, chunk_index: int = 0) -> int:
    return conn.execute(
        text(
            "INSERT INTO material_chunks (material_id, chunk_index, content) "
            "VALUES (:material_id, :chunk_index, 'text') RETURNING id"
        ),
        {"material_id": material_id, "chunk_index": chunk_index},
    ).scalar_one()
