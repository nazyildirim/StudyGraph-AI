"""PostgreSQL integration and concurrency tests for ExamGenerationService (Phase 4)."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
import random
import threading

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError
from app.core.config import Settings
from app.models import Assessment, AssessmentQuestion, StudentAssessment, User
from app.repositories import (
    QuestionOptionDraft,
    SqlAlchemyAssessmentRepository,
    SqlAlchemyLearningOutcomeRepository,
    SqlAlchemyMasteryRepository,
    SqlAlchemyQuestionRepository,
)
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.schemas.question import QuestionOptionCreate, QuestionUpdateRequest
from app.services.exam_generation_service import (
    DiagnosticExamAlreadyCompletedError,
    ExamGenerationService,
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


def _exam_service(session: Session) -> ExamGenerationService:
    policy = CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(session),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(session),
    )
    return ExamGenerationService(
        access_policy=policy,
        assessment_repository=SqlAlchemyAssessmentRepository(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        mastery_repository=SqlAlchemyMasteryRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
        settings=Settings(_env_file=None),
        rng_factory=lambda: random.Random(42),
    )


def _qb_service(session: Session) -> QuestionBankService:
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
def clean_exam_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_concurrent_initial_exam_starts_create_single_attempt_and_preserve_order(
    clean_exam_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_exam_db.begin() as conn:
        inst_id = insert_user(conn, "inst@example.edu", "instructor")
        stu_id = insert_user(conn, "stu@example.edu", "student")
        stu2_id = insert_user(conn, "stu2@example.edu", "student")
        c1_id = insert_course(conn, "CENG101", inst_id)
        for sid in (stu_id, stu2_id):
            conn.execute(
                text(
                    "INSERT INTO course_enrollments (student_id, course_id) "
                    "VALUES (:s, :c)"
                ),
                {"s": sid, "c": c1_id},
            )

    # Seed 5 outcomes x 4 active questions = 20 questions
    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            q_repo = SqlAlchemyQuestionRepository(session)
            for idx in range(5):
                lo = lo_repo.create_outcome(
                    course_id=c1_id, code=f"LO-{idx + 1}", title=f"Outcome {idx + 1}", order_index=idx
                )
                for qn in range(4):
                    q_repo.create_with_options(
                        course_id=c1_id,
                        learning_outcome_id=lo.id,
                        question_text=f"LO{idx + 1} Q{qn + 1}",
                        options=[
                            QuestionOptionDraft(f"Opt {o}", o == 0, o) for o in range(4)
                        ],
                        created_by=inst_id,
                    )

    # 2 concurrent start_initial_exam calls must serialize via Tier 2 lock and
    # return the exact same single attempt_id!
    barrier = threading.Barrier(2)

    def start_worker() -> tuple[int, list[int]]:
        with pg_session_factory() as session:
            user = session.get(User, stu_id)
            assert user is not None
            svc = _exam_service(session)
            barrier.wait()
            resp = svc.start_initial_exam(user=user, course_id=c1_id)
            return resp.attempt_id, [q.question_id for q in resp.questions]

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(start_worker)
        f2 = pool.submit(start_worker)
        r1 = f1.result()
        r2 = f2.result()

    assert r1[0] == r2[0]
    assert r1[1] == r2[1]
    assert len(r1[1]) == 15

    with pg_session_factory() as session:
        assert len(session.execute(select(Assessment)).all()) == 1
        assert len(session.execute(select(StudentAssessment)).all()) == 1
        assert len(session.execute(select(AssessmentQuestion)).all()) == 15

        # Student 1 can view own attempt; Student 2 is denied (404 anti-enumeration)
        stu1 = session.get(User, stu_id)
        stu2 = session.get(User, stu2_id)
        assert stu1 and stu2
        svc = _exam_service(session)
        fetched = svc.get_student_exam(user=stu1, course_id=c1_id, attempt_id=r1[0])
        assert fetched.attempt_id == r1[0]
        assert [q.question_id for q in fetched.questions] == r1[1]
        with pytest.raises(ResourceNotFoundError):
            svc.get_student_exam(user=stu2, course_id=c1_id, attempt_id=r1[0])

    # Mark completed -> subsequent start_initial_exam rejected
    with clean_exam_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE student_assessments SET status = 'completed', completed_at = now() "
                "WHERE id = :aid"
            ),
            {"aid": r1[0]},
        )
    with pg_session_factory() as session:
        stu1 = session.get(User, stu_id)
        assert stu1 is not None
        with pytest.raises(DiagnosticExamAlreadyCompletedError):
            _exam_service(session).start_initial_exam(user=stu1, course_id=c1_id)


def test_concurrent_question_edit_and_initial_exam_creation_preserves_integrity(
    clean_exam_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_exam_db.begin() as conn:
        inst_id = insert_user(conn, "inst@example.edu", "instructor")
        stu_id = insert_user(conn, "stu@example.edu", "student")
        c1_id = insert_course(conn, "CENG101", inst_id)
        conn.execute(
            text(
                "INSERT INTO course_enrollments (student_id, course_id) "
                "VALUES (:s, :c)"
            ),
            {"s": stu_id, "c": c1_id},
        )

    with pg_session_factory() as session:
        with session.begin():
            lo = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1_id, code="LO-1", title="Basics"
            )
            q1, _ = SqlAlchemyQuestionRepository(session).create_with_options(
                course_id=c1_id,
                learning_outcome_id=lo.id,
                question_text="Original Q1",
                options=[QuestionOptionDraft(f"Orig {i}", i == 0, i) for i in range(4)],
                created_by=inst_id,
            )
            lo_id, q1_id = lo.id, q1.id

    barrier = threading.Barrier(2)

    def exam_worker() -> int:
        with pg_session_factory() as session:
            stu = session.get(User, stu_id)
            assert stu is not None
            svc = _exam_service(session)
            barrier.wait()
            resp = svc.start_initial_exam(user=stu, course_id=c1_id)
            assert resp.actual_count == 1
            return resp.questions[0].question_id

    def edit_worker() -> bool:
        with pg_session_factory() as session:
            inst = session.get(User, inst_id)
            assert inst is not None
            qb = _qb_service(session)
            barrier.wait()
            res = qb.update_question(
                user=inst,
                course_id=c1_id,
                question_id=q1_id,
                payload=QuestionUpdateRequest(
                    learning_outcome_id=lo_id,
                    question_text="Edited Q1",
                    options=[
                        QuestionOptionCreate(
                            option_text=f"New {i}", is_correct=(i == 1), order_index=i
                        )
                        for i in range(4)
                    ],
                ),
            )
            return res.was_versioned

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_exam = pool.submit(exam_worker)
        f_edit = pool.submit(edit_worker)
        assigned_qid = f_exam.result()
        was_versioned = f_edit.result()

    # If exam won first, edit MUST have versioned leaving exam's q1 immutable ("Original Q1")
    with pg_session_factory() as session:
        q1_row = SqlAlchemyQuestionRepository(session).get_by_id(q1_id)
        assert q1_row is not None
        if was_versioned:
            assert assigned_qid == q1_id
            assert q1_row.question_text == "Original Q1"
            assert q1_row.is_active is False
        else:
            assert assigned_qid == q1_id
