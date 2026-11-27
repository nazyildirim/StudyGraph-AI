"""PostgreSQL integration tests for QuestionBankService (Issue #7 Phase 3)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.models import AssessmentType, Question, QuestionOption, User
from app.repositories import (
    SqlAlchemyAssessmentRepository,
    SqlAlchemyLearningOutcomeRepository,
    SqlAlchemyQuestionRepository,
)
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.errors import CrossCourseReferenceError
from app.schemas.question import (
    QuestionCreateRequest,
    QuestionOptionCreate,
    QuestionUpdateRequest,
)
from app.services.question_bank_service import (
    QuestionBankService,
    SqlAlchemyTransactionManager,
)
from tests.integration.rag_pg_helpers import insert_course, insert_user

pytestmark = pytest.mark.postgres

TRUNCATE_ALL_SQL = (
    "TRUNCATE TABLE study_recommendations, mastery_records, student_responses, "
    "student_assessments, assessment_questions, assessments, question_options, "
    "questions, prerequisites, learning_outcomes, rag_query_citations, rag_queries, "
    "material_chunks, course_materials, course_enrollments, courses, users "
    "RESTART IDENTITY CASCADE"
)


def _make_options(correct_idx: int = 0, label: str = "Option") -> list[QuestionOptionCreate]:
    return [
        QuestionOptionCreate(
            option_text=f"{label} {i}",
            is_correct=(i == correct_idx),
            order_index=i,
        )
        for i in range(4)
    ]


def _service_for(session: Session) -> QuestionBankService:
    policy = CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(session),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(session),
    )
    return QuestionBankService(
        access_policy=policy,
        question_repository=SqlAlchemyQuestionRepository(session),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
    )


@pytest.fixture()
def clean_service_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_question_bank_service_e2e_auth_versioning_and_exam_history_preservation(
    clean_service_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_service_db.begin() as conn:
        inst1_id = insert_user(conn, "inst1@example.edu", "instructor")
        inst2_id = insert_user(conn, "inst2@example.edu", "instructor")
        stu_id = insert_user(conn, "stu@example.edu", "student")
        admin_id = insert_user(conn, "admin@example.edu", "admin")
        c1_id = insert_course(conn, "CENG101", inst1_id)
        c2_id = insert_course(conn, "CENG201", inst2_id)
        conn.execute(
            text(
                "INSERT INTO course_enrollments (student_id, course_id) "
                "VALUES (:s, :c)"
            ),
            {"s": stu_id, "c": c1_id},
        )

    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics")
            lo2 = lo_repo.create_outcome(course_id=c2_id, code="LO-1", title="Other")
            lo1_id, lo2_id = lo1.id, lo2.id

    with pg_session_factory() as session:
        inst1 = session.get(User, inst1_id)
        inst2 = session.get(User, inst2_id)
        stu = session.get(User, stu_id)
        admin = session.get(User, admin_id)
        assert inst1 and inst2 and stu and admin
        svc = _service_for(session)

        # Student & other instructor rejected with zero DB writes
        create_req = QuestionCreateRequest(
            learning_outcome_id=lo1_id,
            question_text="What is a variable?",
            options=_make_options(0, "Init"),
        )
        with pytest.raises(RoleAuthorizationError):
            svc.create_question(user=stu, course_id=c1_id, payload=create_req)
        with pytest.raises(ResourceNotFoundError):
            svc.create_question(user=inst2, course_id=c1_id, payload=create_req)
        with pytest.raises(CrossCourseReferenceError):
            svc.create_question(
                user=inst1,
                course_id=c1_id,
                payload=QuestionCreateRequest(
                    learning_outcome_id=lo2_id,
                    question_text="Wrong course LO",
                    options=_make_options(0),
                ),
            )

    with pg_session_factory() as session:
        assert session.execute(select(Question)).all() == []
        assert session.execute(select(QuestionOption)).all() == []

    # Instructor creates question; unused update mutates in-place
    with pg_session_factory() as session:
        inst1 = session.get(User, inst1_id)
        admin = session.get(User, admin_id)
        assert inst1 and admin
        svc = _service_for(session)

        created = svc.create_question(user=inst1, course_id=c1_id, payload=create_req)
        assert created.version_number == 1
        assert len(created.options) == 4

        inplace = svc.update_question(
            user=inst1,
            course_id=c1_id,
            question_id=created.id,
            payload=QuestionUpdateRequest(
                learning_outcome_id=lo1_id,
                question_text="What is a variable (revised)?",
                points=2.0,
                options=_make_options(1, "Rev"),
            ),
        )
        assert inplace.was_versioned is False
        assert inplace.question.id == created.id
        assert inplace.question.points == 2.0

        # Assign to an assessment & start an ongoing attempt
        with session.begin():
            a_repo = SqlAlchemyAssessmentRepository(session)
            assessment, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id,
                title="Diagnostic",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[created.id],
                created_by=inst1_id,
            )
            a_repo.create_attempt(
                student_id=stu_id, assessment_id=assessment.id, course_id=c1_id
            )

        # Now admin edits -> must archive v1 and create immutable v2!
        versioned = svc.update_question(
            user=admin,
            course_id=c1_id,
            question_id=created.id,
            payload=QuestionUpdateRequest(
                learning_outcome_id=lo1_id,
                question_text="What is a variable (v2)?",
                points=5.0,
                options=_make_options(2, "V2"),
            ),
        )
        assert versioned.was_versioned is True
        assert versioned.previous_question_id == created.id
        assert versioned.question.id != created.id
        assert versioned.question.version_number == 2
        assert versioned.question.root_question_id == created.id
        assert versioned.question.previous_version_id == created.id

        # Active list excludes archived v1 and returns only v2
        active_list = svc.list_questions(user=inst1, course_id=c1_id)
        assert [q.id for q in active_list] == [versioned.question.id]

        # Ongoing exam's v1 still has original text, points, and options intact
        v1 = svc.get_question(user=inst1, course_id=c1_id, question_id=created.id)
        assert v1.is_active is False
        assert v1.question_text == "What is a variable (revised)?"
        assert v1.points == 2.0
        assert [o.option_text for o in v1.options] == [
            "Rev 0",
            "Rev 1",
            "Rev 2",
            "Rev 3",
        ]

        # Deleting used v1 archives (keeps row); deleting unused v2 hard-deletes
        assert svc.delete_question(
            user=inst1, course_id=c1_id, question_id=created.id
        ).archived is True
        assert svc.delete_question(
            user=inst1, course_id=c1_id, question_id=versioned.question.id
        ).archived is False
        assert svc.list_questions(user=inst1, course_id=c1_id) == []
