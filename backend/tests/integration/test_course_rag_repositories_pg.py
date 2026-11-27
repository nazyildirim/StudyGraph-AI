"""PostgreSQL integration tests for course and RAG repositories."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.roles import Role
from app.models import EnrollmentStatus
from app.rag.domain import ChunkDraft, CitationDraft, ProcessingStatus
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_material_repository import (
    SqlAlchemyCourseMaterialRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.errors import (
    CourseCodeAlreadyExistsError,
    EnrollmentAlreadyExistsError,
    InvalidCitationError,
    MaterialAlreadyExistsError,
    MaterialNotFoundError,
    RelatedRecordNotFoundError,
)
from app.repositories.material_chunk_repository import (
    SqlAlchemyMaterialChunkRepository,
)
from app.repositories.rag_query_repository import SqlAlchemyRagQueryRepository
from app.repositories.user_repository import SqlAlchemyUserRepository
from tests.integration.rag_pg_helpers import TRUNCATE_ALL_SQL

pytestmark = pytest.mark.postgres

HASH_A = "a" * 64
HASH_B = "b" * 64


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


def _user(session: Session, email: str, role: Role = Role.STUDENT) -> int:
    return SqlAlchemyUserRepository(session).create(
        email=email,
        hashed_password="hash",
        first_name="A",
        last_name="B",
        role=role,
    ).id


def _course(session: Session, code: str, instructor_id: int) -> int:
    return SqlAlchemyCourseRepository(session).create(
        code=code, title="Title", instructor_id=instructor_id
    ).id


def _material(
    session: Session, course_id: int, uploader: int, content_hash: str = HASH_A
) -> int:
    return SqlAlchemyCourseMaterialRepository(session).create(
        course_id=course_id,
        uploaded_by=uploader,
        title="C Pointers",
        file_path="uploads/uuid.pdf",
        file_type="application/pdf",
        file_size_bytes=1234,
        content_hash=content_hash,
        unverified_outcome_ref="k1",
    ).id


# ---------------------------------------------------------------- courses
def test_course_create_get_and_duplicate_code(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    repo = SqlAlchemyCourseRepository(session)
    course = repo.create(code="CENG101", title="Intro", instructor_id=instructor)

    assert repo.get_by_id(course.id).code == "CENG101"
    assert repo.get_by_code("CENG101").id == course.id
    assert repo.get_by_id(9999) is None and repo.get_by_code("NOPE") is None
    assert course.is_active is True and course.created_at is not None

    with pytest.raises(CourseCodeAlreadyExistsError):
        repo.create(code="CENG101", title="Other", instructor_id=instructor)
    # Session stays usable after the rolled-back failure.
    assert repo.get_by_code("CENG101") is not None


def test_course_with_missing_instructor_is_rejected(session: Session) -> None:
    with pytest.raises(RelatedRecordNotFoundError):
        SqlAlchemyCourseRepository(session).create(
            code="X1", title="T", instructor_id=424242
        )


# ------------------------------------------------------------ enrollments
def test_enrollment_lifecycle_and_duplicates(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    student = _user(session, "s@example.edu")
    course = _course(session, "CENG101", instructor)
    repo = SqlAlchemyCourseEnrollmentRepository(session)

    assert repo.has_active_enrollment(student, course) is False
    enrollment = repo.create(student_id=student, course_id=course)
    assert enrollment.status == "active"
    assert repo.get(student, course).id == enrollment.id
    assert repo.has_active_enrollment(student, course) is True

    with pytest.raises(EnrollmentAlreadyExistsError):
        repo.create(student_id=student, course_id=course)


def test_only_active_enrollment_grants_access(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    student = _user(session, "s@example.edu")
    course = _course(session, "CENG101", instructor)
    repo = SqlAlchemyCourseEnrollmentRepository(session)
    repo.create(student_id=student, course_id=course, status=EnrollmentStatus.DROPPED)
    assert repo.has_active_enrollment(student, course) is False


def test_enrollment_with_missing_student_or_course(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    course = _course(session, "CENG101", instructor)
    repo = SqlAlchemyCourseEnrollmentRepository(session)
    with pytest.raises(RelatedRecordNotFoundError):
        repo.create(student_id=999, course_id=course)
    with pytest.raises(RelatedRecordNotFoundError):
        repo.create(student_id=instructor, course_id=999)


# -------------------------------------------------------------- materials
def test_material_create_list_status_and_delete(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    course = _course(session, "CENG101", instructor)
    other_course = _course(session, "CENG102", instructor)
    repo = SqlAlchemyCourseMaterialRepository(session)

    first = _material(session, course, instructor, HASH_A)
    second = _material(session, course, instructor, HASH_B)
    _material(session, other_course, instructor, HASH_A)  # same hash, other course ok

    listed = repo.list_by_course(course)
    assert [m.id for m in listed] == [first, second]
    assert listed[0].processing_status == "pending"
    assert listed[0].unverified_outcome_ref == "k1"

    failed = repo.update_processing_status(
        first, ProcessingStatus.FAILED, error_message="bad pdf"
    )
    assert (failed.processing_status, failed.error_message) == ("failed", "bad pdf")
    done = repo.update_processing_status(
        first, ProcessingStatus.PROCESSED, extraction_report='{"empty_pages": []}'
    )
    assert done.error_message is None
    assert done.extraction_report == '{"empty_pages": []}'

    assert repo.delete(first) is True
    assert repo.delete(first) is False
    assert [m.id for m in repo.list_by_course(course)] == [second]


def test_material_duplicate_hash_and_missing_references(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    course = _course(session, "CENG101", instructor)
    repo = SqlAlchemyCourseMaterialRepository(session)
    _material(session, course, instructor)

    with pytest.raises(MaterialAlreadyExistsError):
        _material(session, course, instructor)
    with pytest.raises(RelatedRecordNotFoundError):
        _material(session, 9999, instructor, HASH_B)
    with pytest.raises(MaterialNotFoundError):
        repo.update_processing_status(9999, ProcessingStatus.PROCESSED)


# ----------------------------------------------------------------- chunks
def test_replace_chunks_is_atomic_ordered_and_idempotent(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    material = _material(session, _course(session, "CENG101", instructor), instructor)
    repo = SqlAlchemyMaterialChunkRepository(session)

    drafts = [
        ChunkDraft(1, "second", page_start=2, page_end=3, metadata={"başlık": "Pointer"}),
        ChunkDraft(0, "first", page_start=1, page_end=1),
    ]
    created = repo.replace_chunks(material, drafts)
    assert [c.chunk_index for c in created] == [0, 1]
    assert repo.count_by_material(material) == 2

    stored = repo.list_by_material(material)
    assert [c.content for c in stored] == ["first", "second"]
    assert (stored[1].page_start, stored[1].page_end) == (2, 3)
    assert "başlık" in stored[1].metadata_json  # ensure_ascii=False

    # Re-indexing replaces rather than duplicates.
    repo.replace_chunks(material, [ChunkDraft(0, "only")])
    assert [c.content for c in repo.list_by_material(material)] == ["only"]
    assert [c.id for c in repo.get_many([stored[0].id])] == []  # old row is gone
    assert repo.get_many([]) == []


def test_replace_chunks_validation_and_missing_material(session: Session) -> None:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    material = _material(session, _course(session, "CENG101", instructor), instructor)
    repo = SqlAlchemyMaterialChunkRepository(session)
    repo.replace_chunks(material, [ChunkDraft(0, "keep me")])

    with pytest.raises(ValueError):
        repo.replace_chunks(material, [ChunkDraft(0, "a"), ChunkDraft(0, "b")])
    with pytest.raises(MaterialNotFoundError):
        repo.replace_chunks(9999, [ChunkDraft(0, "a")])
    # Failed attempts must not have destroyed existing data.
    assert [c.content for c in repo.list_by_material(material)] == ["keep me"]


# ------------------------------------------------------------ rag queries
def _seed_chunks(session: Session) -> tuple[int, int, int, list[int], int]:
    instructor = _user(session, "i@example.edu", Role.INSTRUCTOR)
    student = _user(session, "s@example.edu")
    course = _course(session, "CENG101", instructor)
    other_course = _course(session, "CENG102", instructor)
    chunks = SqlAlchemyMaterialChunkRepository(session)
    chunks.replace_chunks(
        _material(session, course, instructor),
        [ChunkDraft(0, "a", page_start=1), ChunkDraft(1, "b", page_start=2)],
    )
    chunks.replace_chunks(
        _material(session, other_course, instructor, HASH_B),
        [ChunkDraft(0, "foreign")],
    )
    own_ids = [
        c.id
        for m in SqlAlchemyCourseMaterialRepository(session).list_by_course(course)
        for c in chunks.list_by_material(m.id)
    ]
    foreign_id = chunks.list_by_material(
        SqlAlchemyCourseMaterialRepository(session).list_by_course(other_course)[0].id
    )[0].id
    return student, course, other_course, own_ids, foreign_id


def test_query_with_citations_roundtrip(session: Session) -> None:
    student, course, _, own_ids, _ = _seed_chunks(session)
    repo = SqlAlchemyRagQueryRepository(session)

    query = repo.create_with_citations(
        student_id=student,
        course_id=course,
        question="Pointer nedir?",
        answer="Bir adres tutar [S1].",
        grounded=True,
        model_name="qwen3:4b",
        citations=[
            CitationDraft(own_ids[0], 0.9),
            CitationDraft(own_ids[1], None),
        ],
    )
    assert repo.get_by_id(query.id).grounded is True
    citations = repo.list_citations(query.id)
    assert [(c.chunk_id, c.relevance_score) for c in citations] == [
        (own_ids[0], 0.9),
        (own_ids[1], None),
    ]


def test_ungrounded_query_without_citations_is_allowed(session: Session) -> None:
    student, course, *_ = _seed_chunks(session)
    repo = SqlAlchemyRagQueryRepository(session)
    query = repo.create_with_citations(
        student_id=student,
        course_id=course,
        question="Dersle ilgisiz?",
        answer="Ders materyallerinde bu konuda kaynak bulunamadı.",
        grounded=False,
        model_name=None,
        citations=[],
    )
    assert repo.get_by_id(query.id).grounded is False
    assert repo.list_citations(query.id) == []


def test_citation_from_another_course_is_rejected_and_nothing_written(
    session: Session,
) -> None:
    student, course, _, own_ids, foreign_id = _seed_chunks(session)
    repo = SqlAlchemyRagQueryRepository(session)

    with pytest.raises(InvalidCitationError):
        repo.create_with_citations(
            student_id=student,
            course_id=course,
            question="q",
            answer="a",
            grounded=True,
            model_name=None,
            citations=[CitationDraft(own_ids[0]), CitationDraft(foreign_id)],
        )
    assert repo.list_for_student(student, course) == []


def test_invalid_citation_combinations_are_rejected(session: Session) -> None:
    student, course, _, own_ids, _ = _seed_chunks(session)
    repo = SqlAlchemyRagQueryRepository(session)
    common = dict(
        student_id=student, course_id=course, question="q", answer="a", model_name=None
    )

    with pytest.raises(InvalidCitationError):  # duplicate chunk
        repo.create_with_citations(
            grounded=True,
            citations=[CitationDraft(own_ids[0]), CitationDraft(own_ids[0])],
            **common,
        )
    with pytest.raises(InvalidCitationError):  # unknown chunk
        repo.create_with_citations(
            grounded=True, citations=[CitationDraft(999999)], **common
        )
    with pytest.raises(InvalidCitationError):  # ungrounded + citation
        repo.create_with_citations(
            grounded=False, citations=[CitationDraft(own_ids[0])], **common
        )
    assert repo.list_for_student(student, course) == []


def test_query_with_missing_student_is_rejected(session: Session) -> None:
    _, course, *_ = _seed_chunks(session)
    with pytest.raises(RelatedRecordNotFoundError):
        SqlAlchemyRagQueryRepository(session).create_with_citations(
            student_id=424242,
            course_id=course,
            question="q",
            answer="a",
            grounded=False,
            model_name=None,
            citations=[],
        )


def test_list_for_student_is_scoped_newest_first_and_paginated(
    session: Session,
) -> None:
    student, course, other_course, *_ = _seed_chunks(session)
    other_student = _user(session, "s2@example.edu")
    repo = SqlAlchemyRagQueryRepository(session)

    def ask(student_id: int, course_id: int, question: str) -> int:
        return repo.create_with_citations(
            student_id=student_id,
            course_id=course_id,
            question=question,
            answer="a",
            grounded=False,
            model_name=None,
            citations=[],
        ).id

    first = ask(student, course, "1")
    second = ask(student, course, "2")
    ask(student, other_course, "other course")
    ask(other_student, course, "other student")

    assert [q.id for q in repo.list_for_student(student, course)] == [second, first]
    assert [q.id for q in repo.list_for_student(student, course, limit=1)] == [second]
    assert [q.id for q in repo.list_for_student(student, course, limit=1, offset=1)] == [first]
