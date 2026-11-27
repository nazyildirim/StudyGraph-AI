"""PostgreSQL integration tests for Issue #7 Final Code Review remediation (M2, M3, M4)."""

from __future__ import annotations

from collections.abc import Generator
import random

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.course_access_policy import CourseAccessPolicy
from app.core.config import Settings
from app.models import DifficultyLevel, User
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
from app.schemas.exam import (
    ExamSubmitRequest,
    InitialExamCreateRequest,
    RetestExamCreateRequest,
    StudentAnswerRequest,
)
from app.services.exam_generation_service import (
    ExamGenerationService,
    OutcomeNotEligibleForRetestError,
)
from app.services.exam_submission_service import ExamSubmissionService
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter
from app.services.mastery_query_service import MasteryQueryService
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


@pytest.fixture()
def clean_rem_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_m2_sql_level_pagination_filtering_and_course_isolation(
    clean_rem_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_rem_db.begin() as conn:
        inst_id = insert_user(conn, "inst@example.edu", "instructor")
        c1_id = insert_course(conn, "CENG101", inst_id)
        c2_id = insert_course(conn, "CENG201", inst_id)

    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics")
            lo2 = lo_repo.create_outcome(course_id=c2_id, code="LO-1", title="Other")
            q_repo = SqlAlchemyQuestionRepository(session)
            for idx in range(5):
                q_repo.create_with_options(
                    course_id=c1_id,
                    learning_outcome_id=lo1.id,
                    question_text=f"C1 Hard {idx}",
                    difficulty_level=DifficultyLevel.HARD.value,
                    options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
                )
            q_repo.create_with_options(
                course_id=c1_id,
                learning_outcome_id=lo1.id,
                question_text="C1 Easy",
                difficulty_level=DifficultyLevel.EASY.value,
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )
            q_repo.create_with_options(
                course_id=c2_id,
                learning_outcome_id=lo2.id,
                question_text="C2 Hard",
                difficulty_level=DifficultyLevel.HARD.value,
                options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
            )

    executed_sql: list[str] = []

    def _capture_sql(conn, cursor, statement, parameters, context, executemany):
        executed_sql.append(statement)

    event.listen(clean_rem_db, "before_cursor_execute", _capture_sql)
    try:
        with pg_session_factory() as session:
            inst = session.get(User, inst_id)
            assert inst is not None
            qb = QuestionBankService(
                access_policy=_policy(session),
                question_repository=SqlAlchemyQuestionRepository(session),
                learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
                transaction_manager=SqlAlchemyTransactionManager(session),
            )
            executed_sql.clear()
            page = qb.list_questions(
                user=inst,
                course_id=c1_id,
                difficulty_level=DifficultyLevel.HARD.value,
                limit=2,
                offset=1,
            )
    finally:
        event.remove(clean_rem_db, "before_cursor_execute", _capture_sql)

    assert len(page) == 2
    assert all(q.course_id == c1_id and q.difficulty_level == "hard" for q in page)
    assert [q.question_text for q in page] == ["C1 Hard 1", "C1 Hard 2"]

    question_queries = [s for s in executed_sql if "FROM questions" in s]
    option_queries = [s for s in executed_sql if "FROM question_options" in s]
    assert len(question_queries) == 1
    assert "LIMIT" in question_queries[0] and "OFFSET" in question_queries[0]
    assert "difficulty_level" in question_queries[0]
    # Single batch query for options (no N+1)
    assert len(option_queries) == 1


def test_m3_diagnostic_metadata_persists_across_get_settings_and_outcome_changes(
    clean_rem_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_rem_db.begin() as conn:
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
            lo1 = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1_id, code="LO-1", title="Basics", order_index=1
            )
            q_repo = SqlAlchemyQuestionRepository(session)
            for idx in range(4):
                q_repo.create_with_options(
                    course_id=c1_id,
                    learning_outcome_id=lo1.id,
                    question_text=f"Q{idx}",
                    options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
                )
            lo1_id = lo1.id

    # Start diagnostic with custom requested_count=6 (only 4 active exist -> actual=4, requested=6)
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        gen = ExamGenerationService(
            access_policy=_policy(session),
            assessment_repository=SqlAlchemyAssessmentRepository(session),
            question_repository=SqlAlchemyQuestionRepository(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            transaction_manager=SqlAlchemyTransactionManager(session),
            settings=Settings(_env_file=None, exam_initial_question_count=15),
            rng_factory=lambda: random.Random(1),
        )
        started = gen.start_initial_exam(
            user=stu, course_id=c1_id, payload=InitialExamCreateRequest(question_count=6)
        )
        assert started.requested_count == 6
        assert started.actual_count == 4
        assert started.targeted_outcome_ids == [lo1_id]
        attempt_id = started.attempt_id

    # Add a NEW outcome later AND change settings default to 20 -> GET must preserve 6 and [lo1_id]!
    with pg_session_factory() as session:
        with session.begin():
            SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1_id, code="LO-2", title="Added Later", order_index=2
            )

    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        gen_later = ExamGenerationService(
            access_policy=_policy(session),
            assessment_repository=SqlAlchemyAssessmentRepository(session),
            question_repository=SqlAlchemyQuestionRepository(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            transaction_manager=SqlAlchemyTransactionManager(session),
            settings=Settings(_env_file=None, exam_initial_question_count=20),
            rng_factory=lambda: random.Random(1),
        )
        fetched = gen_later.get_student_exam(
            user=stu, course_id=c1_id, attempt_id=attempt_id
        )
        resumed = gen_later.start_initial_exam(user=stu, course_id=c1_id)
        assert fetched.requested_count == 6
        assert fetched.actual_count == 4
        assert fetched.targeted_outcome_ids == [lo1_id]
        assert resumed.requested_count == 6
        assert resumed.targeted_outcome_ids == [lo1_id]


def test_m4_graph_change_keeps_live_recommendations_and_retest_eligibility_consistent(
    clean_rem_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_rem_db.begin() as conn:
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

    # Initial graph: LO1 -> LO2. Both fail diagnostic -> LO1=review, LO2=blocked.
    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics", order_index=1)
            lo2 = lo_repo.create_outcome(course_id=c1_id, code="LO-2", title="Loops", order_index=2)
            lo_repo.add_prerequisite(
                course_id=c1_id, prerequisite_outcome_id=lo1.id, dependent_outcome_id=lo2.id
            )
            q_repo = SqlAlchemyQuestionRepository(session)
            wrong_opt: dict[int, int] = {}
            for oid in (lo1.id, lo2.id):
                q, opts = q_repo.create_with_options(
                    course_id=c1_id,
                    learning_outcome_id=oid,
                    question_text=f"Q for {oid}",
                    options=[QuestionOptionDraft(f"O{i}", i == 0, i) for i in range(4)],
                )
                wrong_opt[q.id] = opts[1].id
            lo1_id, lo2_id = lo1.id, lo2.id

    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        gen = ExamGenerationService(
            access_policy=_policy(session),
            assessment_repository=SqlAlchemyAssessmentRepository(session),
            question_repository=SqlAlchemyQuestionRepository(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            transaction_manager=SqlAlchemyTransactionManager(session),
            settings=Settings(_env_file=None),
            rng_factory=lambda: random.Random(1),
        )
        m_repo = SqlAlchemyMasteryRepository(session)
        sub = ExamSubmissionService(
            access_policy=_policy(session),
            assessment_repository=SqlAlchemyAssessmentRepository(session),
            question_repository=SqlAlchemyQuestionRepository(session),
            mastery_repository=m_repo,
            transaction_manager=SqlAlchemyTransactionManager(session),
            mastery_integrator=MasteryIntegrationAdapter(
                learning_analysis_service=LearningAnalysisService(),
                learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
                mastery_repository=m_repo,
                settings=Settings(_env_file=None),
            ),
        )
        diag = gen.start_initial_exam(user=stu, course_id=c1_id)
        sub.submit_exam(
            user=stu,
            course_id=c1_id,
            attempt_id=diag.attempt_id,
            payload=ExamSubmitRequest(
                answers=[
                    StudentAnswerRequest(
                        question_id=q.question_id,
                        selected_option_id=wrong_opt[q.question_id],
                    )
                    for q in diag.questions
                ]
            ),
        )

        # Before graph change: LO2 is blocked and cannot start retest
        query_svc = MasteryQueryService(
            access_policy=_policy(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            settings=Settings(_env_file=None),
        )
        recs_before = {
            r.learning_outcome_id: r
            for r in query_svc.get_student_recommendations(
                user=stu, course_id=c1_id
            ).recommendations
        }
        assert recs_before[lo2_id].status == "blocked"
        assert recs_before[lo2_id].missing_prerequisites == [lo1_id]
        with pytest.raises(OutcomeNotEligibleForRetestError):
            gen.start_retest_exam(
                user=stu,
                course_id=c1_id,
                payload=RetestExamCreateRequest(learning_outcome_id=lo2_id),
            )

    # Remove prerequisite edge LO1 -> LO2 directly in DB (graph edit after exam)
    with clean_rem_db.begin() as conn:
        conn.execute(text("DELETE FROM prerequisites WHERE course_id = :c"), {"c": c1_id})

    # After graph change: BOTH GET /recommendations (read-only) AND start_retest_exam
    # immediately agree that LO2 is now 'review' with missing_prerequisites=[]!
    with pg_session_factory() as session:
        stu = session.get(User, stu_id)
        assert stu is not None
        query_svc = MasteryQueryService(
            access_policy=_policy(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            settings=Settings(_env_file=None),
        )
        recs_after = {
            r.learning_outcome_id: r
            for r in query_svc.get_student_recommendations(
                user=stu, course_id=c1_id
            ).recommendations
        }
        assert recs_after[lo2_id].status == "review"
        assert recs_after[lo2_id].missing_prerequisites == []

        gen = ExamGenerationService(
            access_policy=_policy(session),
            assessment_repository=SqlAlchemyAssessmentRepository(session),
            question_repository=SqlAlchemyQuestionRepository(session),
            learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(session),
            mastery_repository=SqlAlchemyMasteryRepository(session),
            transaction_manager=SqlAlchemyTransactionManager(session),
            settings=Settings(_env_file=None),
            rng_factory=lambda: random.Random(1),
        )
        retest = gen.start_retest_exam(
            user=stu,
            course_id=c1_id,
            payload=RetestExamCreateRequest(learning_outcome_id=lo2_id),
        )
        assert retest.targeted_outcome_ids == [lo2_id]
        assert retest.actual_count == 1
