"""PostgreSQL end-to-end, rollback, and concurrency tests for Issue #5 integration."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.core.config import Settings
from app.models import (
    AssessmentType,
    MasteryRecord,
    StudentAssessment,
    StudentResponse,
    StudyRecommendation,
    User,
)
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
from app.repositories.errors import AttemptAlreadyFinalizedError
from app.schemas.exam import ExamSubmitRequest, StudentAnswerRequest
from app.services.exam_submission_service import ExamSubmissionService
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter
from app.services.question_bank_service import SqlAlchemyTransactionManager
from tests.integration.rag_pg_helpers import insert_course, insert_user

pytestmark = pytest.mark.postgres

TRUNCATE_ALL_SQL = (
    "TRUNCATE TABLE study_recommendations, mastery_records, student_responses, "
    "student_assessments, assessment_questions, assessments, question_options, "
    "questions, prerequisites, learning_outcomes, rag_query_citations, rag_queries, "
    "material_chunks, course_materials, course_enrollments, courses, users "
    "RESTART IDENTITY CASCADE"
)


def _make_submission_service(
    session: Session,
    *,
    analysis_service: LearningAnalysisService | None = None,
    mastery_repo: SqlAlchemyMasteryRepository | None = None,
) -> ExamSubmissionService:
    policy = CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(session),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(session),
    )
    m_repo = mastery_repo or SqlAlchemyMasteryRepository(session)
    adapter = MasteryIntegrationAdapter(
        learning_analysis_service=analysis_service or LearningAnalysisService(),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
        mastery_repository=m_repo,
        settings=Settings(_env_file=None),
    )
    return ExamSubmissionService(
        access_policy=policy,
        assessment_repository=SqlAlchemyAssessmentRepository(session),
        question_repository=SqlAlchemyQuestionRepository(session),
        mastery_repository=m_repo,
        transaction_manager=SqlAlchemyTransactionManager(session),
        mastery_integrator=adapter,
    )


@pytest.fixture()
def clean_mastery_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_e2e_diagnostic_then_partial_retest_preserves_other_outcomes_and_unblocks_prereqs(
    clean_mastery_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_mastery_db.begin() as conn:
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

    # Graph: LO1 -> LO2 -> LO3, and LO1 -> LO4 (unassessed)
    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics", order_index=1)
            lo2 = lo_repo.create_outcome(course_id=c1_id, code="LO-2", title="Loops", order_index=2)
            lo3 = lo_repo.create_outcome(course_id=c1_id, code="LO-3", title="Sorting", order_index=3)
            lo4 = lo_repo.create_outcome(course_id=c1_id, code="LO-4", title="Arrays", order_index=4)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo1.id, dependent_outcome_id=lo2.id)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo2.id, dependent_outcome_id=lo3.id)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo1.id, dependent_outcome_id=lo4.id)

            q_repo = SqlAlchemyQuestionRepository(session)
            q1, o1 = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo1.id, question_text="Q1",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q2a, o2a = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo2.id, question_text="Q2A",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q2b, o2b = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo2.id, question_text="Q2B",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q3, o3 = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo3.id, question_text="Q3",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q2_retest, o2_retest = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo2.id, question_text="Q2 Retest",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )

            a_repo = SqlAlchemyAssessmentRepository(session)
            diag, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id,
                title="Diag",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[q1.id, q2a.id, q2b.id, q3.id],
            )
            diag_attempt = a_repo.create_attempt(
                student_id=stu_id, assessment_id=diag.id, course_id=c1_id
            )
            retest, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id,
                title="Retest LO2",
                assessment_type=AssessmentType.REVIEW.value,
                question_ids=[q2_retest.id],
            )
            retest_attempt = a_repo.create_attempt(
                student_id=stu_id, assessment_id=retest.id, course_id=c1_id
            )

            lo1_id, lo2_id, lo3_id, lo4_id = lo1.id, lo2.id, lo3.id, lo4.id
            diag_attempt_id, retest_attempt_id = diag_attempt.id, retest_attempt.id
            q1_id, o1_ok = q1.id, o1[0].id
            q2a_id, o2a_ok = q2a.id, o2a[0].id
            q2b_id, o2b_bad = q2b.id, o2b[1].id
            q3_id, o3_bad = q3.id, o3[1].id
            q2r_id, o2r_ok = q2_retest.id, o2_retest[0].id

    # 1) Submit diagnostic: LO1=100%, LO2=50%, LO3=0%, LO4=unassessed
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        diag_res = _make_submission_service(session).submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=diag_attempt_id,
            payload=ExamSubmitRequest(
                answers=[
                    StudentAnswerRequest(question_id=q1_id, selected_option_id=o1_ok),
                    StudentAnswerRequest(question_id=q2a_id, selected_option_id=o2a_ok),
                    StudentAnswerRequest(question_id=q2b_id, selected_option_id=o2b_bad),
                    StudentAnswerRequest(question_id=q3_id, selected_option_id=o3_bad),
                ]
            ),
        )
        assert diag_res.score == 50.0
        assert diag_res.mastery_summary is not None
        recs1 = {r.learning_outcome_id: r.status for r in diag_res.mastery_summary.recommendations}
        assert recs1 == {
            lo1_id: "completed",
            lo2_id: "review",
            lo3_id: "blocked",
            lo4_id: "study",
        }
        assert diag_res.mastery_summary.unassessed_outcome_ids == [lo4_id]

    # Verify LO4 has NO fake 0% MasteryRecord
    with pg_session_factory() as session:
        m_repo = SqlAlchemyMasteryRepository(session)
        assert m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo4_id) is None
        m2 = m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo2_id)
        assert m2 is not None and m2.mastery_score == 50.0 and m2.total_attempts == 1

    # 2) Submit LO2 retest (100%): LO1 & LO3 keep total_attempts=1 & original scores;
    # LO2 becomes 100% (total_attempts=2) and unblocks LO3 -> review!
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        svc = _make_submission_service(session)
        retest_res = svc.submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=retest_attempt_id,
            payload=ExamSubmitRequest(
                answers=[
                    StudentAnswerRequest(question_id=q2r_id, selected_option_id=o2r_ok)
                ]
            ),
        )
        assert retest_res.mastery_summary is not None
        recs2 = {r.learning_outcome_id: r.status for r in retest_res.mastery_summary.recommendations}
        assert recs2 == {
            lo1_id: "completed",
            lo2_id: "completed",
            lo3_id: "review",
            lo4_id: "study",
        }

        # Historical diagnostic result remains unchanged (50.0) and does NOT attach current mastery
        hist_diag = svc.get_exam_result(
            user=stu, course_id=c1_id, attempt_id=diag_attempt_id
        )
        assert hist_diag.score == 50.0
        assert hist_diag.mastery_summary is None

    with pg_session_factory() as session:
        m_repo = SqlAlchemyMasteryRepository(session)
        m1 = m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo1_id)
        m2 = m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo2_id)
        m3 = m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo3_id)
        m4 = m_repo.get_mastery_record(student_id=stu_id, learning_outcome_id=lo4_id)
        assert m1 is not None and m1.mastery_score == 100.0 and m1.total_attempts == 1
        assert m2 is not None and m2.mastery_score == 100.0 and m2.total_attempts == 2
        assert m3 is not None and m3.mastery_score == 0.0 and m3.total_attempts == 1
        assert m4 is None


def test_atomic_rollback_on_analysis_or_recommendation_failure_allows_retry(
    clean_mastery_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_mastery_db.begin() as conn:
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
            q1, opts1 = SqlAlchemyQuestionRepository(session).create_with_options(
                course_id=c1_id,
                learning_outcome_id=lo.id,
                question_text="Q1",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            a_repo = SqlAlchemyAssessmentRepository(session)
            a1, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id,
                title="Diag",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[q1.id],
            )
            att = a_repo.create_attempt(
                student_id=stu_id, assessment_id=a1.id, course_id=c1_id
            )
            attempt_id, q1_id, opt_ok = att.id, q1.id, opts1[0].id

    class _BoomAnalysis(LearningAnalysisService):
        def analyze(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("Simulated LearningAnalysisService failure")

    # 1) Analysis failure rolls back responses, attempt status, mastery, and recommendations
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        with pytest.raises(RuntimeError):
            _make_submission_service(session, analysis_service=_BoomAnalysis()).submit_exam(
                user=stu,
                course_id=c1_id,
                attempt_id=attempt_id,
                payload=ExamSubmitRequest(
                    answers=[StudentAnswerRequest(question_id=q1_id, selected_option_id=opt_ok)]
                ),
            )

    with pg_session_factory() as session:
        assert session.execute(select(StudentResponse)).all() == []
        assert session.execute(select(MasteryRecord)).all() == []
        assert session.execute(select(StudyRecommendation)).all() == []
        att_row = session.get(StudentAssessment, attempt_id)
        assert att_row is not None and att_row.status == "in_progress"

    # 2) Recommendation persistence failure also rolls back everything (including MasteryRecord)
    class _BoomRecRepo(SqlAlchemyMasteryRepository):
        def replace_recommendations_for_course(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("Simulated recommendation write failure")

    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        with pytest.raises(RuntimeError):
            _make_submission_service(
                session, mastery_repo=_BoomRecRepo(session)
            ).submit_exam(
                user=stu,
                course_id=c1_id,
                attempt_id=attempt_id,
                payload=ExamSubmitRequest(
                    answers=[StudentAnswerRequest(question_id=q1_id, selected_option_id=opt_ok)]
                ),
            )

    with pg_session_factory() as session:
        assert session.execute(select(StudentResponse)).all() == []
        assert session.execute(select(MasteryRecord)).all() == []
        assert session.execute(select(StudyRecommendation)).all() == []

    # 3) Student can now safely re-submit and succeed cleanly
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        ok_res = _make_submission_service(session).submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=attempt_id,
            payload=ExamSubmitRequest(
                answers=[StudentAnswerRequest(question_id=q1_id, selected_option_id=opt_ok)]
            ),
        )
        assert ok_res.score == 100.0
        assert ok_res.mastery_summary is not None


def test_concurrent_same_attempt_and_different_attempts_prevent_lost_updates(
    clean_mastery_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_mastery_db.begin() as conn:
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
            q_repo = SqlAlchemyQuestionRepository(session)
            q1, o1 = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo.id, question_text="Q1",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q2, o2 = q_repo.create_with_options(
                course_id=c1_id, learning_outcome_id=lo.id, question_text="Q2",
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            a_repo = SqlAlchemyAssessmentRepository(session)
            a1, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id, title="A1", assessment_type=AssessmentType.DIAGNOSTIC.value, question_ids=[q1.id]
            )
            a2, _ = a_repo.create_assessment_with_questions(
                course_id=c1_id, title="A2", assessment_type=AssessmentType.REVIEW.value, question_ids=[q2.id]
            )
            att1 = a_repo.create_attempt(student_id=stu_id, assessment_id=a1.id, course_id=c1_id)
            att2 = a_repo.create_attempt(student_id=stu_id, assessment_id=a2.id, course_id=c1_id)
            lo_id = lo.id
            att1_id, att2_id = att1.id, att2.id
            q1_id, o1_ok, q2_id, o2_ok = q1.id, o1[0].id, q2.id, o2[0].id

    # A) Concurrent double-submit of att1 -> exactly 1 succeeds, total_attempts == 1
    b1 = threading.Barrier(2)

    def dup_worker() -> str:
        with pg_session_factory() as session:
            stu = session.get(User, stu_id)
            assert stu is not None
            b1.wait()
            try:
                _make_submission_service(session).submit_exam(
                    user=stu,
                    course_id=c1_id,
                    attempt_id=att1_id,
                    payload=ExamSubmitRequest(
                        answers=[StudentAnswerRequest(question_id=q1_id, selected_option_id=o1_ok)]
                    ),
                )
                return "ok"
            except AttemptAlreadyFinalizedError:
                return "finalized"

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(dup_worker)
        f2 = pool.submit(dup_worker)
        res_a = sorted([f1.result(), f2.result()])
    assert res_a == ["finalized", "ok"]

    with pg_session_factory() as session:
        rec = SqlAlchemyMasteryRepository(session).get_mastery_record(
            student_id=stu_id, learning_outcome_id=lo_id
        )
        assert rec is not None and rec.total_attempts == 1

    # B) Concurrent submission of att2 alongside a third attempt att3 -> zero lost updates (1 + 2 = 3)
    with pg_session_factory() as session:
        with session.begin():
            att3 = SqlAlchemyAssessmentRepository(session).create_attempt(
                student_id=stu_id, assessment_id=a2.id, course_id=c1_id
            )
            att3_id = att3.id

    b2 = threading.Barrier(2)

    def submit_attempt(target_att_id: int) -> None:
        with pg_session_factory() as session:
            stu = session.get(User, stu_id)
            assert stu is not None
            b2.wait()
            _make_submission_service(session).submit_exam(
                user=stu,
                course_id=c1_id,
                attempt_id=target_att_id,
                payload=ExamSubmitRequest(
                    answers=[StudentAnswerRequest(question_id=q2_id, selected_option_id=o2_ok)]
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        f2 = pool.submit(submit_attempt, att2_id)
        f3 = pool.submit(submit_attempt, att3_id)
        f2.result()
        f3.result()

    with pg_session_factory() as session:
        rec = SqlAlchemyMasteryRepository(session).get_mastery_record(
            student_id=stu_id, learning_outcome_id=lo_id
        )
        assert rec is not None and rec.total_attempts == 3
