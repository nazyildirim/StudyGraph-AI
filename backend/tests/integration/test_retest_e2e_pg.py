"""PostgreSQL end-to-end and concurrency tests for Retest Exams + Issue #5 Mastery (Phase 7)."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
import random
import threading

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.core.config import Settings
from app.models import Assessment, DifficultyLevel, StudentAssessment, User
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
from app.repositories.errors import CrossCourseReferenceError
from app.schemas.exam import (
    ExamSubmitRequest,
    InitialExamCreateRequest,
    RetestExamCreateRequest,
    StudentAnswerRequest,
)
from app.schemas.question import QuestionOptionCreate, QuestionUpdateRequest
from app.services.exam_generation_service import (
    ActiveRetestConflictError,
    DiagnosticExamRequiredError,
    ExamGenerationService,
    InsufficientQuestionsError,
    NoEligibleOutcomesForRetestError,
    OutcomeNotEligibleForRetestError,
)
from app.services.exam_submission_service import ExamSubmissionService
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter
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


def _gen(session: Session) -> ExamGenerationService:
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


def _sub(session: Session) -> ExamSubmissionService:
    m_repo = SqlAlchemyMasteryRepository(session)
    adapter = MasteryIntegrationAdapter(
        learning_analysis_service=LearningAnalysisService(),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        mastery_repository=m_repo,
        settings=Settings(_env_file=None),
    )
    return ExamSubmissionService(
        access_policy=_policy(session),
        assessment_repository=SqlAlchemyAssessmentRepository(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        mastery_repository=m_repo,
        transaction_manager=SqlAlchemyTransactionManager(session),
        mastery_integrator=adapter,
    )


def _qb(session: Session) -> QuestionBankService:
    return QuestionBankService(
        access_policy=_policy(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        transaction_manager=SqlAlchemyTransactionManager(session),
    )


@pytest.fixture()
def clean_retest_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_full_retest_lifecycle_prereqs_unseen_concurrency_conflict_and_unblocking(
    clean_retest_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_retest_db.begin() as conn:
        inst_id = insert_user(conn, "inst@example.edu", "instructor")
        stu_id = insert_user(conn, "stu@example.edu", "student")
        other_stu_id = insert_user(conn, "other@example.edu", "student")
        c1_id = insert_course(conn, "CENG101", inst_id)
        c2_id = insert_course(conn, "CENG201", inst_id)
        conn.execute(
            text(
                "INSERT INTO course_enrollments (student_id, course_id) "
                "VALUES (:s, :c)"
            ),
            {"s": stu_id, "c": c1_id},
        )

    # Graph: LO1 -> LO2 -> LO3, plus LO4 (no questions -> unassessed)
    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics", order_index=1)
            lo2 = lo_repo.create_outcome(course_id=c1_id, code="LO-2", title="Loops", order_index=2)
            lo3 = lo_repo.create_outcome(course_id=c1_id, code="LO-3", title="Sorting", order_index=3)
            lo4 = lo_repo.create_outcome(course_id=c1_id, code="LO-4", title="Unassessed", order_index=4)
            lo_other_course = lo_repo.create_outcome(course_id=c2_id, code="LO-X", title="Other")
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo1.id, dependent_outcome_id=lo2.id)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo2.id, dependent_outcome_id=lo3.id)

            q_repo = SqlAlchemyQuestionRepository(session)
            correct_opt_by_qid: dict[int, int] = {}
            wrong_opt_by_qid: dict[int, int] = {}
            lo2_qids: list[int] = []
            # LO1: 2 questions, LO2: 7 questions (5 medium + 2 hard), LO3: 2 questions
            for oid, specs in (
                (lo1.id, [("medium", 2)]),
                (lo2.id, [("medium", 5), ("hard", 2)]),
                (lo3.id, [("medium", 2)]),
            ):
                for diff, count in specs:
                    for idx in range(count):
                        q, opts = q_repo.create_with_options(
                            course_id=c1_id,
                            learning_outcome_id=oid,
                            question_text=f"LO{oid} {diff} #{idx}",
                            difficulty_level=diff,
                            options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
                            created_by=inst_id,
                        )
                        correct_opt_by_qid[q.id] = opts[0].id
                        wrong_opt_by_qid[q.id] = opts[1].id
                        if oid == lo2.id:
                            lo2_qids.append(q.id)

            lo1_id, lo2_id, lo3_id, lo4_id, lo_other_id = (
                lo1.id, lo2.id, lo3.id, lo4.id, lo_other_course.id
            )

    # 1) Retest before diagnostic is completed -> DiagnosticExamRequiredError
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        inst = session.get(User, inst_id)
        other_stu = session.get(User, other_stu_id)
        assert stu and inst and other_stu
        with pytest.raises(DiagnosticExamRequiredError):
            _gen(session).start_retest_exam(user=stu, course_id=c1_id)
        with pytest.raises(RoleAuthorizationError):
            _gen(session).start_retest_exam(user=inst, course_id=c1_id)
        with pytest.raises(ResourceNotFoundError):
            _gen(session).start_retest_exam(user=other_stu, course_id=c1_id)

        # Start & submit 6-question diagnostic (2 from LO1, 2 from LO2, 2 from LO3):
        # LO1 = 100% (completed), LO2 = 0% (review), LO3 = 0% (blocked by LO2), LO4 = unassessed (study)
        diag = _gen(session).start_initial_exam(
            user=stu, course_id=c1_id, payload=InitialExamCreateRequest(question_count=6)
        )
        diag_qids = {q.question_id for q in diag.questions}
        diag_lo2_qids = [q.question_id for q in diag.questions if q.learning_outcome_id == lo2_id]
        answers = [
            StudentAnswerRequest(
                question_id=q.question_id,
                selected_option_id=(
                    correct_opt_by_qid[q.question_id]
                    if q.learning_outcome_id == lo1_id
                    else wrong_opt_by_qid[q.question_id]
                ),
            )
            for q in diag.questions
        ]
        diag_res = _sub(session).submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=diag.attempt_id,
            payload=ExamSubmitRequest(answers=answers),
        )
        assert diag_res.mastery_summary is not None

        # Version one of the seen LO2 diagnostic questions -> v2 must STILL count as seen!
        v2_res = _qb(session).update_question(
            user=inst,
            course_id=c1_id,
            question_id=diag_lo2_qids[0],
            payload=QuestionUpdateRequest(
                learning_outcome_id=lo2_id,
                question_text="LO2 seen v2",
                options=[
                    QuestionOptionCreate(option_text=f"N{i}", is_correct=(i == 0), order_index=i)
                    for i in range(4)
                ],
            ),
        )
        assert v2_res.was_versioned is True
        v2_qid = v2_res.question.id

        # Cross-course outcome, mastered LO1, blocked LO3, and unassessed LO4 are all rejected
        with pytest.raises(CrossCourseReferenceError):
            _gen(session).start_retest_exam(
                user=stu,
                course_id=c1_id,
                payload=RetestExamCreateRequest(learning_outcome_id=lo_other_id),
            )
        for ineligible_id in (lo1_id, lo3_id, lo4_id):
            with pytest.raises(OutcomeNotEligibleForRetestError):
                _gen(session).start_retest_exam(
                    user=stu,
                    course_id=c1_id,
                    payload=RetestExamCreateRequest(learning_outcome_id=ineligible_id),
                )

    # 2) Concurrent general retest starts -> single attempt, 5 UNSEEN questions (v2_qid excluded!)
    barrier = threading.Barrier(2)

    def retest_worker() -> tuple[int, list[int], int | None, int | None]:
        with pg_session_factory() as session:
            stu = session.get(User, stu_id)
            assert stu is not None
            barrier.wait()
            resp = _gen(session).start_retest_exam(user=stu, course_id=c1_id)
            return (
                resp.attempt_id,
                [q.question_id for q in resp.questions],
                resp.unseen_question_count,
                resp.reused_question_count,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(retest_worker)
        f2 = pool.submit(retest_worker)
        r1, r2 = f1.result(), f2.result()

    assert r1 == r2
    retest_attempt_id, retest_qids, unseen_cnt, reused_cnt = r1
    assert len(retest_qids) == 5
    assert unseen_cnt == 5 and reused_cnt == 0
    assert not (set(retest_qids) & diag_qids)
    assert v2_qid not in retest_qids

    # 3) Different target/difficulty while review is in_progress -> ActiveRetestConflictError
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        with pytest.raises(ActiveRetestConflictError):
            _gen(session).start_retest_exam(
                user=stu,
                course_id=c1_id,
                payload=RetestExamCreateRequest(
                    learning_outcome_id=lo2_id, difficulty=DifficultyLevel.HARD
                ),
            )

        # Submit retest with all 5 correct -> LO2 becomes 100% (total_attempts=2) & unblocks LO3 -> review!
        retest_res = _sub(session).submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=retest_attempt_id,
            payload=ExamSubmitRequest(
                answers=[
                    StudentAnswerRequest(
                        question_id=qid, selected_option_id=correct_opt_by_qid[qid]
                    )
                    for qid in retest_qids
                ]
            ),
        )
        assert retest_res.score == 100.0
        assert retest_res.mastery_summary is not None
        rec_map = {
            r.learning_outcome_id: r.status
            for r in retest_res.mastery_summary.recommendations
        }
        assert rec_map == {
            lo1_id: "completed",
            lo2_id: "completed",
            lo3_id: "review",
            lo4_id: "study",
        }

        # Now LO3 is eligible! Targeted retest on LO3 with only 2 seen questions -> reuses 2 without repeating
        lo3_retest = _gen(session).start_retest_exam(
            user=stu,
            course_id=c1_id,
            payload=RetestExamCreateRequest(learning_outcome_id=lo3_id, question_count=5),
        )
        assert lo3_retest.requested_count == 5
        assert lo3_retest.actual_count == 2
        assert lo3_retest.unseen_question_count == 0
        assert lo3_retest.reused_question_count == 2

        # Complete LO3 retest (100%) -> now NO eligible outcomes left!
        _sub(session).submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=lo3_retest.attempt_id,
            payload=ExamSubmitRequest(
                answers=[
                    StudentAnswerRequest(
                        question_id=q.question_id,
                        selected_option_id=correct_opt_by_qid[q.question_id],
                    )
                    for q in lo3_retest.questions
                ]
            ),
        )
        with pytest.raises(NoEligibleOutcomesForRetestError):
            _gen(session).start_retest_exam(user=stu, course_id=c1_id)

        # Verify LO1 mastery record stayed untouched at total_attempts == 1
        m1 = SqlAlchemyMasteryRepository(session).get_mastery_record(
            student_id=stu_id, learning_outcome_id=lo1_id
        )
        m2 = SqlAlchemyMasteryRepository(session).get_mastery_record(
            student_id=stu_id, learning_outcome_id=lo2_id
        )
        assert m1 is not None and m1.total_attempts == 1
        assert m2 is not None and m2.total_attempts == 2
