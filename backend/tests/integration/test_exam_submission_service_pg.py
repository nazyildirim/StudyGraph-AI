"""PostgreSQL integration and concurrency tests for ExamSubmissionService (Phase 5)."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
import random
import threading

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.core.config import Settings
from app.models import StudentAssessment, StudentResponse, User
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
from app.repositories.errors import AttemptAlreadyFinalizedError, InvalidResponseError
from app.schemas.exam import ExamSubmitRequest, StudentAnswerRequest
from app.schemas.question import QuestionOptionCreate, QuestionUpdateRequest
from app.services.exam_generation_service import ExamGenerationService
from app.services.exam_submission_service import (
    AttemptNotCompletedError,
    ExamSubmissionService,
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


def _policy(session: Session) -> CourseAccessPolicy:
    return CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(session),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(session),
    )


def _exam_gen(session: Session) -> ExamGenerationService:
    return ExamGenerationService(
        access_policy=_policy(session),
        assessment_repository=SqlAlchemyAssessmentRepository(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        mastery_repository=SqlAlchemyMasteryRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
        settings=Settings(_env_file=None),
        rng_factory=lambda: random.Random(42),
    )


def _exam_sub(session: Session) -> ExamSubmissionService:
    return ExamSubmissionService(
        access_policy=_policy(session),
        assessment_repository=SqlAlchemyAssessmentRepository(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        mastery_repository=SqlAlchemyMasteryRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
        allow_skip_mastery_integration=True,
    )


def _qb(session: Session) -> QuestionBankService:
    return QuestionBankService(
        access_policy=_policy(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
    )


@pytest.fixture()
def clean_sub_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_versioned_question_grades_against_original_v1_concurrent_submit_and_history(
    clean_sub_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_sub_db.begin() as conn:
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

    with pg_session_factory() as session:
        with session.begin():
            lo = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1_id, code="LO-1", title="Basics"
            )
            q_repo = SqlAlchemyQuestionRepository(session)
            # Q1: option 0 is correct, points = 2.0
            q1, q1_opts = q_repo.create_with_options(
                course_id=c1_id,
                learning_outcome_id=lo.id,
                question_text="Q1 v1",
                options=[QuestionOptionDraft(f"Opt {i}", i == 0, i) for i in range(4)],
                points=2.0,
                created_by=inst_id,
            )
            # Q2: option 1 is correct, points = 3.0
            q2, _ = q_repo.create_with_options(
                course_id=c1_id,
                learning_outcome_id=lo.id,
                question_text="Q2 v1",
                options=[QuestionOptionDraft(f"Opt {i}", i == 1, i) for i in range(4)],
                points=3.0,
                created_by=inst_id,
            )
            lo_id, q1_id, q1_v1_correct_opt = lo.id, q1.id, q1_opts[0].id

    # Student starts initial exam (gets Q1 v1 and Q2 v1)
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        started = _exam_gen(session).start_initial_exam(user=stu, course_id=c1_id)
        attempt_id = started.attempt_id

        # In-progress attempt result must NOT be accessible
        with pytest.raises(AttemptNotCompletedError):
            _exam_sub(session).get_exam_result(
                user=stu, course_id=c1_id, attempt_id=attempt_id
            )

    # Instructor edits Q1 AFTER exam started (flips correct answer to idx 3 & points to 10.0)
    with pg_session_factory() as session:
        inst = session.get(User, inst_id)
        assert inst is not None
        upd = _qb(session).update_question(
            user=inst,
            course_id=c1_id,
            question_id=q1_id,
            payload=QuestionUpdateRequest(
                learning_outcome_id=lo_id,
                question_text="Q1 v2",
                points=10.0,
                options=[
                    QuestionOptionCreate(
                        option_text=f"New {i}", is_correct=(i == 3), order_index=i
                    )
                    for i in range(4)
                ],
            ),
        )
        assert upd.was_versioned is True

    # Invalid submission (bad option ID) rolls back cleanly -> 0 responses persisted
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        with pytest.raises(InvalidResponseError):
            _exam_sub(session).submit_exam(
                user=stu,
                course_id=c1_id,
                attempt_id=attempt_id,
                payload=ExamSubmitRequest(
                    answers=[
                        StudentAnswerRequest(question_id=q1_id, selected_option_id=999999)
                    ]
                ),
            )
    with pg_session_factory() as session:
        assert session.execute(select(StudentResponse)).all() == []
        att = session.get(StudentAssessment, attempt_id)
        assert att is not None and att.status == "in_progress"

    # Concurrent double-submit: Q1 answered with v1's correct option (2.0 pts), Q2 omitted (0/3.0)
    # Expected score against original v1: 2.0 / 5.0 * 100 = 40.0%
    barrier = threading.Barrier(2)

    def submit_worker() -> tuple[str, float | None]:
        with pg_session_factory() as session:
            stu = session.get(User, stu_id)
            assert stu is not None
            svc = _exam_sub(session)
            barrier.wait()
            try:
                res = svc.submit_exam(
                    user=stu,
                    course_id=c1_id,
                    attempt_id=attempt_id,
                    payload=ExamSubmitRequest(
                        answers=[
                            StudentAnswerRequest(
                                question_id=q1_id,
                                selected_option_id=q1_v1_correct_opt,
                            )
                        ]
                    ),
                )
                return ("ok", res.score)
            except AttemptAlreadyFinalizedError:
                return ("finalized", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(submit_worker)
        f2 = pool.submit(submit_worker)
        outcomes = sorted([f1.result(), f2.result()], key=lambda x: x[0])

    assert outcomes == [("finalized", None), ("ok", 40.0)]

    # Verify DB persistence, get_exam_result, and student-isolated history
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        stu2 = session.get(User, stu2_id)
        assert stu and stu2
        sub = _exam_sub(session)
        fetched = sub.get_exam_result(user=stu, course_id=c1_id, attempt_id=attempt_id)
        assert fetched.score == 40.0
        assert fetched.earned_points == 2.0
        assert fetched.total_possible_points == 5.0
        assert fetched.correct_count == 1
        assert fetched.incorrect_count == 0
        assert fetched.unanswered_count == 1

        history_stu1 = sub.list_exam_history(user=stu, course_id=c1_id)
        history_stu2 = sub.list_exam_history(user=stu2, course_id=c1_id)
        assert len(history_stu1) == 1
        assert history_stu1[0].attempt_id == attempt_id
        assert history_stu1[0].score == 40.0
        assert history_stu2 == []
