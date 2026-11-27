"""PostgreSQL integration and concurrency tests for Issue #7 repositories."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    AssessmentType,
    MasteryRecord,
    Question,
    QuestionOption,
    RecommendationStatus,
    StudentAssessmentStatus,
)
from app.repositories import (
    MasteryUpdateDraft,
    QuestionOptionDraft,
    SqlAlchemyAssessmentRepository,
    SqlAlchemyLearningOutcomeRepository,
    SqlAlchemyMasteryRepository,
    SqlAlchemyQuestionRepository,
    StudentResponseDraft,
    StudyRecommendationDraft,
)
from app.repositories.errors import (
    AttemptAlreadyFinalizedError,
    AttemptNotFoundError,
    CrossCourseReferenceError,
    CyclicPrerequisiteError,
    InvalidQuestionOptionsError,
    InvalidResponseError,
    PrerequisiteAlreadyExistsError,
    QuestionArchivedError,
)
from tests.integration.rag_pg_helpers import insert_course, insert_user

pytestmark = pytest.mark.postgres

TRUNCATE_ALL_ASSESSMENT_SQL = (
    "TRUNCATE TABLE study_recommendations, mastery_records, student_responses, "
    "student_assessments, assessment_questions, assessments, question_options, "
    "questions, prerequisites, learning_outcomes, rag_query_citations, rag_queries, "
    "material_chunks, course_materials, course_enrollments, courses, users "
    "RESTART IDENTITY CASCADE"
)


def _sample_options(correct_idx: int = 0, prefix: str = "Opt") -> list[QuestionOptionDraft]:
    return [
        QuestionOptionDraft(
            option_text=f"{prefix} {i}",
            is_correct=(i == correct_idx),
            order_index=i,
        )
        for i in range(4)
    ]


@pytest.fixture()
def clean_repo_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_ASSESSMENT_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_ASSESSMENT_SQL))


def test_learning_outcome_prerequisites_block_cycles_and_cross_course(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", inst)
        c2 = insert_course(conn, "CENG201", inst)

    with pg_session_factory() as session:
        with session.begin():
            repo = SqlAlchemyLearningOutcomeRepository(session)
            lo_a = repo.create_outcome(course_id=c1, code="LO-1", title="A", order_index=1)
            lo_b = repo.create_outcome(course_id=c1, code="LO-2", title="B", order_index=2)
            lo_c = repo.create_outcome(course_id=c1, code="LO-3", title="C", order_index=3)
            lo_other = repo.create_outcome(course_id=c2, code="LO-1", title="Other")

            repo.add_prerequisite(
                course_id=c1,
                prerequisite_outcome_id=lo_a.id,
                dependent_outcome_id=lo_b.id,
            )
            repo.add_prerequisite(
                course_id=c1,
                prerequisite_outcome_id=lo_b.id,
                dependent_outcome_id=lo_c.id,
            )

            # Duplicate edge rejected
            with pytest.raises(PrerequisiteAlreadyExistsError):
                repo.add_prerequisite(
                    course_id=c1,
                    prerequisite_outcome_id=lo_a.id,
                    dependent_outcome_id=lo_b.id,
                )

            # Self-reference rejected
            with pytest.raises(CyclicPrerequisiteError):
                repo.add_prerequisite(
                    course_id=c1,
                    prerequisite_outcome_id=lo_a.id,
                    dependent_outcome_id=lo_a.id,
                )

            # 3-node cycle C -> A rejected via GraphEngine
            with pytest.raises(CyclicPrerequisiteError):
                repo.add_prerequisite(
                    course_id=c1,
                    prerequisite_outcome_id=lo_c.id,
                    dependent_outcome_id=lo_a.id,
                )

            # Cross-course prerequisite rejected
            with pytest.raises(CrossCourseReferenceError):
                repo.add_prerequisite(
                    course_id=c1,
                    prerequisite_outcome_id=lo_a.id,
                    dependent_outcome_id=lo_other.id,
                )

            assert repo.verify_outcomes_belong_to_course(c1, [lo_a.id, lo_b.id]) is True
            assert repo.verify_outcomes_belong_to_course(c1, [lo_a.id, lo_other.id]) is False


def test_concurrent_prerequisite_inserts_cannot_form_cycle(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", inst)

    with pg_session_factory() as session:
        with session.begin():
            repo = SqlAlchemyLearningOutcomeRepository(session)
            lo_a = repo.create_outcome(course_id=c1, code="LO-1", title="A")
            lo_b = repo.create_outcome(course_id=c1, code="LO-2", title="B")

    barrier = threading.Barrier(2)

    def worker(prereq_id: int, dep_id: int) -> str:
        with pg_session_factory() as session:
            barrier.wait()
            try:
                with session.begin():
                    SqlAlchemyLearningOutcomeRepository(session).add_prerequisite(
                        course_id=c1,
                        prerequisite_outcome_id=prereq_id,
                        dependent_outcome_id=dep_id,
                    )
                return "ok"
            except CyclicPrerequisiteError:
                return "cycle"

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, lo_a.id, lo_b.id)
        f2 = pool.submit(worker, lo_b.id, lo_a.id)
        results = sorted([f1.result(), f2.result()])

    assert results == ["cycle", "ok"]


def test_question_creation_rollback_and_option_validation(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", inst)
        c2 = insert_course(conn, "CENG201", inst)

    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1, code="LO-1", title="LO 1")
            lo2 = lo_repo.create_outcome(course_id=c2, code="LO-1", title="LO 2")

    # Outer transaction rollback leaves zero questions or options (no independent repo commits)
    with pg_session_factory() as session:
        try:
            with session.begin():
                q_repo = SqlAlchemyQuestionRepository(session)
                q_repo.create_with_options(
                    course_id=c1,
                    learning_outcome_id=lo1.id,
                    question_text="Should rollback",
                    options=_sample_options(0),
                    created_by=inst,
                )
                raise RuntimeError("Simulated service failure")
        except RuntimeError:
            pass

    with pg_session_factory() as session:
        assert session.execute(select(Question)).all() == []
        assert session.execute(select(QuestionOption)).all() == []

    with pg_session_factory() as session:
        with session.begin():
            q_repo = SqlAlchemyQuestionRepository(session)
            # Zero correct options rejected
            with pytest.raises(InvalidQuestionOptionsError):
                q_repo.create_with_options(
                    course_id=c1,
                    learning_outcome_id=lo1.id,
                    question_text="Bad",
                    options=[
                        QuestionOptionDraft("A", False, 0),
                        QuestionOptionDraft("B", False, 1),
                    ],
                )
            # Cross-course outcome rejected
            with pytest.raises(CrossCourseReferenceError):
                q_repo.create_with_options(
                    course_id=c1,
                    learning_outcome_id=lo2.id,
                    question_text="Cross course",
                    options=_sample_options(0),
                )


def test_unused_vs_used_question_editing_versioning_and_ongoing_exam_protection(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        student = insert_user(conn, "stu@example.edu", "student")
        c1 = insert_course(conn, "CENG101", inst)

    with pg_session_factory() as session:
        with session.begin():
            lo1 = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1, code="LO-1", title="LO 1"
            )
            q_repo = SqlAlchemyQuestionRepository(session)
            q_unused, _ = q_repo.create_with_options(
                course_id=c1,
                learning_outcome_id=lo1.id,
                question_text="Original unused",
                options=_sample_options(0, "V0"),
                created_by=inst,
            )
            # Editing an unused question mutates in-place (was_versioned=False)
            updated, updated_opts, was_versioned = q_repo.update_or_version(
                course_id=c1,
                question_id=q_unused.id,
                learning_outcome_id=lo1.id,
                question_text="Edited in-place",
                options=_sample_options(1, "V1"),
                updated_by=inst,
            )
            assert was_versioned is False
            assert updated.id == q_unused.id
            assert updated.question_text == "Edited in-place"
            assert [o.option_text for o in updated_opts] == ["V1 0", "V1 1", "V1 2", "V1 3"]

            # Assign to an assessment & start an ongoing attempt (NO student_responses yet!)
            a_repo = SqlAlchemyAssessmentRepository(session)
            assessment, _ = a_repo.create_assessment_with_questions(
                course_id=c1,
                title="Diagnostic",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[updated.id],
                created_by=inst,
            )
            a_repo.create_attempt(
                student_id=student,
                assessment_id=assessment.id,
                course_id=c1,
            )

            # Now editing MUST archive v1 and create immutable v2!
            v2, v2_opts, was_versioned_2 = q_repo.update_or_version(
                course_id=c1,
                question_id=updated.id,
                learning_outcome_id=lo1.id,
                question_text="Edited v2",
                options=_sample_options(2, "V2"),
                points=2.0,
                updated_by=inst,
            )
            assert was_versioned_2 is True
            assert v2.id != updated.id
            assert v2.version_number == 2
            assert v2.root_question_id == updated.id
            assert v2.previous_version_id == updated.id
            assert v2.is_active is True

            # Ongoing exam's v1 remains completely unchanged and archived
            v1_reloaded = q_repo.get_by_id(updated.id)
            assert v1_reloaded is not None
            assert v1_reloaded.is_active is False
            assert v1_reloaded.archived_at is not None
            assert v1_reloaded.question_text == "Edited in-place"
            assert [o.option_text for o in q_repo.list_options(updated.id)] == [
                "V1 0",
                "V1 1",
                "V1 2",
                "V1 3",
            ]

            # Editing archived v1 is rejected (prevents multiple active versions)
            with pytest.raises(QuestionArchivedError):
                q_repo.update_or_version(
                    course_id=c1,
                    question_id=updated.id,
                    learning_outcome_id=lo1.id,
                    question_text="Illegal fork",
                    options=_sample_options(0),
                )

            # Deleting used v1 archives (never deletes); deleting unused v2 hard-deletes
            assert q_repo.delete_or_archive(course_id=c1, question_id=updated.id) is True
            assert q_repo.get_by_id(updated.id) is not None
            assert q_repo.delete_or_archive(course_id=c1, question_id=v2.id) is False
            assert q_repo.get_by_id(v2.id) is None


def test_concurrent_question_edit_and_assessment_assignment(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", inst)

    with pg_session_factory() as session:
        with session.begin():
            lo1 = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1, code="LO-1", title="LO 1"
            )
            q1, _ = SqlAlchemyQuestionRepository(session).create_with_options(
                course_id=c1,
                learning_outcome_id=lo1.id,
                question_text="Original",
                options=_sample_options(0),
                created_by=inst,
            )

    barrier = threading.Barrier(2)

    def assign_worker() -> str:
        with pg_session_factory() as session:
            barrier.wait()
            try:
                with session.begin():
                    SqlAlchemyAssessmentRepository(session).create_assessment_with_questions(
                        course_id=c1,
                        title="Concurrent Exam",
                        assessment_type=AssessmentType.DIAGNOSTIC.value,
                        question_ids=[q1.id],
                        created_by=inst,
                    )
                return "assigned"
            except QuestionArchivedError:
                return "archived_reject"

    def edit_worker() -> tuple[str, bool]:
        with pg_session_factory() as session:
            barrier.wait()
            with session.begin():
                _, _, versioned = SqlAlchemyQuestionRepository(session).update_or_version(
                    course_id=c1,
                    question_id=q1.id,
                    learning_outcome_id=lo1.id,
                    question_text="Mutated",
                    options=_sample_options(1),
                    updated_by=inst,
                )
            return ("edited", versioned)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_assign = pool.submit(assign_worker)
        f_edit = pool.submit(edit_worker)
        assign_res = f_assign.result()
        edit_res, was_versioned = f_edit.result()

    assert edit_res == "edited"
    assert assign_res in {"assigned", "archived_reject"}
    # If assignment won first, edit MUST have versioned so exam's q1 stayed "Original"
    with pg_session_factory() as session:
        reloaded = SqlAlchemyQuestionRepository(session).get_by_id(q1.id)
        assert reloaded is not None
        if was_versioned:
            assert assign_res == "assigned"
            assert reloaded.question_text == "Original"
            assert reloaded.is_active is False


def test_seen_lineages_cross_student_isolation_and_concurrent_attempt_submit(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        stu1 = insert_user(conn, "s1@example.edu", "student")
        stu2 = insert_user(conn, "s2@example.edu", "student")
        c1 = insert_course(conn, "CENG101", inst)

    with pg_session_factory() as session:
        with session.begin():
            lo1 = SqlAlchemyLearningOutcomeRepository(session).create_outcome(
                course_id=c1, code="LO-1", title="LO 1"
            )
            q_repo = SqlAlchemyQuestionRepository(session)
            q1, q1_opts = q_repo.create_with_options(
                course_id=c1,
                learning_outcome_id=lo1.id,
                question_text="Q1",
                options=_sample_options(0),
            )
            q2, q2_opts = q_repo.create_with_options(
                course_id=c1,
                learning_outcome_id=lo1.id,
                question_text="Q2",
                options=_sample_options(1),
            )
            a_repo = SqlAlchemyAssessmentRepository(session)
            assessment, _ = a_repo.create_assessment_with_questions(
                course_id=c1,
                title="Diag",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[q1.id],
            )
            attempt = a_repo.create_attempt(
                student_id=stu1, assessment_id=assessment.id, course_id=c1
            )
            attempt_id = attempt.id
            q1_id = q1.id
            q1_opt0_id = q1_opts[0].id

            # Even BEFORE any student_responses exist, q1's lineage is marked seen for stu1
            assert a_repo.get_seen_question_lineage_ids(student_id=stu1, course_id=c1) == {
                q1.id
            }
            assert a_repo.get_seen_question_lineage_ids(student_id=stu2, course_id=c1) == set()

            # Versioning q1 -> v2 keeps the same canonical lineage root (q1.id)
            v2, _, was_versioned = q_repo.update_or_version(
                course_id=c1,
                question_id=q1.id,
                learning_outcome_id=lo1.id,
                question_text="Q1 v2",
                options=_sample_options(0),
            )
            assert was_versioned is True
            v2_lineage = v2.root_question_id if v2.root_question_id is not None else v2.id
            assert v2_lineage in a_repo.get_seen_question_lineage_ids(
                student_id=stu1, course_id=c1
            )

            # Cross-student isolation: stu2 cannot read or submit stu1's attempt
            assert (
                a_repo.get_attempt_for_student(attempt_id=attempt.id, student_id=stu2)
                is None
            )
            with pytest.raises(AttemptNotFoundError):
                a_repo.save_responses_and_complete_attempt(
                    attempt_id=attempt.id,
                    student_id=stu2,
                    course_id=c1,
                    responses=[
                        StudentResponseDraft(q1.id, q1_opts[0].id, True, 1.0)
                    ],
                    score=100.0,
                )

            # Mismatched option (q2's option on q1) rejected as InvalidResponseError
            with pytest.raises(InvalidResponseError):
                a_repo.save_responses_and_complete_attempt(
                    attempt_id=attempt.id,
                    student_id=stu1,
                    course_id=c1,
                    responses=[
                        StudentResponseDraft(q1.id, q2_opts[0].id, False, 0.0)
                    ],
                    score=0.0,
                )

    # Concurrent double-submit on the same attempt: exactly one succeeds
    barrier = threading.Barrier(2)

    def submit_worker() -> str:
        with pg_session_factory() as session:
            barrier.wait()
            try:
                with session.begin():
                    SqlAlchemyAssessmentRepository(session).save_responses_and_complete_attempt(
                        attempt_id=attempt_id,
                        student_id=stu1,
                        course_id=c1,
                        responses=[
                            StudentResponseDraft(q1_id, q1_opt0_id, True, 1.0)
                        ],
                        score=100.0,
                    )
                return "submitted"
            except AttemptAlreadyFinalizedError:
                return "already_finalized"

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(submit_worker)
        f2 = pool.submit(submit_worker)
        outcomes = sorted([f1.result(), f2.result()])

    assert outcomes == ["already_finalized", "submitted"]


def test_mastery_concurrent_upsert_no_lost_updates_and_latest_responses(
    clean_repo_db: Engine, pg_session_factory: sessionmaker[Session]
) -> None:
    with clean_repo_db.begin() as conn:
        inst = insert_user(conn, "inst@example.edu", "instructor")
        stu = insert_user(conn, "stu@example.edu", "student")
        c1 = insert_course(conn, "CENG101", inst)

    with pg_session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1, code="LO-1", title="LO 1", order_index=1)
            lo2 = lo_repo.create_outcome(course_id=c1, code="LO-2", title="LO 2", order_index=2)
            lo3 = lo_repo.create_outcome(course_id=c1, code="LO-3", title="LO 3", order_index=3)

            m_repo = SqlAlchemyMasteryRepository(session)
            # Initial mastery for lo1 (50%, weak) and lo2 (90%, sufficient); lo3 stays unassessed
            m_repo.upsert_mastery_records(
                student_id=stu,
                course_id=c1,
                updates=[
                    MasteryUpdateDraft(lo1.id, 50.0),
                    MasteryUpdateDraft(lo2.id, 90.0),
                ],
            )
            assert m_repo.list_weak_outcome_ids(
                student_id=stu, course_id=c1, mastery_threshold=70.0
            ) == [lo1.id]
            assert m_repo.list_unassessed_outcome_ids(
                student_id=stu, course_id=c1
            ) == [lo3.id]

            # Recommendations preserve blocked, review, study, completed
            m_repo.replace_recommendations_for_course(
                student_id=stu,
                course_id=c1,
                recommendations=[
                    StudyRecommendationDraft(lo1.id, 1, "Below threshold", RecommendationStatus.REVIEW.value),
                    StudyRecommendationDraft(lo2.id, 2, "Mastered", RecommendationStatus.COMPLETED.value),
                    StudyRecommendationDraft(lo3.id, 3, "Missing prerequisite LO-1", RecommendationStatus.BLOCKED.value),
                ],
            )
            recs = m_repo.list_recommendations_for_student_course(student_id=stu, course_id=c1)
            assert [(r.learning_outcome_id, r.status) for r in recs] == [
                (lo1.id, "review"),
                (lo2.id, "completed"),
                (lo3.id, "blocked"),
            ]

    # 8 concurrent updates on lo1 must produce total_attempts = 1 + 8 = 9 (zero lost updates),
    # while untouched lo2 remains at total_attempts = 1!
    workers = 8
    barrier = threading.Barrier(workers)

    def upsert_worker(idx: int) -> None:
        with pg_session_factory() as session:
            barrier.wait()
            with session.begin():
                SqlAlchemyMasteryRepository(session).upsert_mastery_records(
                    student_id=stu,
                    course_id=c1,
                    updates=[MasteryUpdateDraft(lo1.id, 60.0 + idx)],
                )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(upsert_worker, i) for i in range(workers)]
        for f in futures:
            f.result()

    with pg_session_factory() as session:
        m_repo = SqlAlchemyMasteryRepository(session)
        rec1 = m_repo.get_mastery_record(student_id=stu, learning_outcome_id=lo1.id)
        rec2 = m_repo.get_mastery_record(student_id=stu, learning_outcome_id=lo2.id)
        assert rec1 is not None and rec1.total_attempts == 1 + workers
        assert rec2 is not None and rec2.total_attempts == 1

    # Verify list_latest_completed_responses_by_outcome picks latest per outcome
    t1 = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=10)
    with pg_session_factory() as session:
        with session.begin():
            q_repo = SqlAlchemyQuestionRepository(session)
            q_lo1_a, opts_1a = q_repo.create_with_options(
                course_id=c1, learning_outcome_id=lo1.id, question_text="1A", options=_sample_options(0)
            )
            q_lo2_a, opts_2a = q_repo.create_with_options(
                course_id=c1, learning_outcome_id=lo2.id, question_text="2A", options=_sample_options(0)
            )
            q_lo1_b, opts_1b = q_repo.create_with_options(
                course_id=c1, learning_outcome_id=lo1.id, question_text="1B", options=_sample_options(0)
            )
            a_repo = SqlAlchemyAssessmentRepository(session)
            diag, _ = a_repo.create_assessment_with_questions(
                course_id=c1,
                title="Diag",
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                question_ids=[q_lo1_a.id, q_lo2_a.id],
            )
            att1 = a_repo.create_attempt(student_id=stu, assessment_id=diag.id, course_id=c1)
            a_repo.save_responses_and_complete_attempt(
                attempt_id=att1.id,
                student_id=stu,
                course_id=c1,
                responses=[
                    StudentResponseDraft(q_lo1_a.id, opts_1a[1].id, False, 0.0),
                    StudentResponseDraft(q_lo2_a.id, opts_2a[0].id, True, 1.0),
                ],
                score=50.0,
                completed_at=t1,
            )

            retest, _ = a_repo.create_assessment_with_questions(
                course_id=c1,
                title="Retest LO1",
                assessment_type=AssessmentType.REVIEW.value,
                question_ids=[q_lo1_b.id],
            )
            att2 = a_repo.create_attempt(student_id=stu, assessment_id=retest.id, course_id=c1)
            a_repo.save_responses_and_complete_attempt(
                attempt_id=att2.id,
                student_id=stu,
                course_id=c1,
                responses=[
                    StudentResponseDraft(q_lo1_b.id, opts_1b[0].id, True, 1.0),
                ],
                score=100.0,
                completed_at=t2,
            )

            latest = SqlAlchemyMasteryRepository(session).list_latest_completed_responses_by_outcome(
                student_id=stu, course_id=c1
            )
            assert [(r.learning_outcome_id, r.question_id, r.is_correct) for r in latest] == [
                (lo1.id, q_lo1_b.id, True),
                (lo2.id, q_lo2_a.id, True),
            ]
