"""PostgreSQL schema, constraint, isolation, and history tests for Issue #7."""

from __future__ import annotations

from collections.abc import Generator

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.integration.rag_pg_helpers import insert_course, insert_user

pytestmark = pytest.mark.postgres

ASSESSMENT_TABLES = {
    "learning_outcomes",
    "prerequisites",
    "questions",
    "question_options",
    "assessments",
    "assessment_questions",
    "student_assessments",
    "student_responses",
    "mastery_records",
    "study_recommendations",
}

TRUNCATE_ASSESSMENT_SQL = (
    "TRUNCATE TABLE study_recommendations, mastery_records, student_responses, "
    "student_assessments, assessment_questions, assessments, question_options, "
    "questions, prerequisites, learning_outcomes, rag_query_citations, rag_queries, "
    "material_chunks, course_materials, course_enrollments, courses, users "
    "RESTART IDENTITY CASCADE"
)


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(inspect(conn).get_table_names(schema="public"))


def _insert_outcome(
    conn: Connection, course_id: int, code: str, title: str = "Outcome"
) -> int:
    return conn.execute(
        text(
            "INSERT INTO learning_outcomes (course_id, code, title) "
            "VALUES (:course_id, :code, :title) RETURNING id"
        ),
        {"course_id": course_id, "code": code, "title": title},
    ).scalar_one()


def _insert_question(
    conn: Connection,
    course_id: int,
    outcome_id: int,
    created_by: int | None = None,
    question_text: str = "What is 2+2?",
) -> int:
    return conn.execute(
        text(
            "INSERT INTO questions (course_id, learning_outcome_id, question_text, created_by) "
            "VALUES (:course_id, :outcome_id, :question_text, :created_by) RETURNING id"
        ),
        {
            "course_id": course_id,
            "outcome_id": outcome_id,
            "question_text": question_text,
            "created_by": created_by,
        },
    ).scalar_one()


def _insert_option(
    conn: Connection,
    question_id: int,
    order_index: int,
    option_text: str = "4",
    is_correct: bool = False,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO question_options (question_id, option_text, is_correct, order_index) "
            "VALUES (:q, :text, :correct, :idx) RETURNING id"
        ),
        {
            "q": question_id,
            "text": option_text,
            "correct": is_correct,
            "idx": order_index,
        },
    ).scalar_one()


def _insert_assessment(
    conn: Connection,
    course_id: int,
    assessment_type: str = "diagnostic",
    created_by: int | None = None,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO assessments (course_id, title, assessment_type, created_by) "
            "VALUES (:c, 'Exam', :t, :by) RETURNING id"
        ),
        {"c": course_id, "t": assessment_type, "by": created_by},
    ).scalar_one()


@pytest.fixture()
def clean_assessment_db(migrated_pg_engine: Engine) -> Generator[Engine, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ASSESSMENT_SQL))
    try:
        yield migrated_pg_engine
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ASSESSMENT_SQL))


def test_0005_migration_upgrade_downgrade_and_drift(
    pg_engine: Engine, verified_alembic_config: Config
) -> None:
    cfg = verified_alembic_config
    try:
        command.upgrade(cfg, "head")
        assert ASSESSMENT_TABLES <= _tables(pg_engine)

        # Zero ORM vs migration drift
        command.check(cfg)

        # Downgrade to 0004 removes only Issue #7 tables and keeps RAG/Course/User tables.
        command.downgrade(cfg, "0004_add_chunk_embeddings")
        tables_at_0004 = _tables(pg_engine)
        assert not (ASSESSMENT_TABLES & tables_at_0004)
        assert {"users", "courses", "course_enrollments", "material_chunks"} <= tables_at_0004
    finally:
        command.upgrade(cfg, "head")

    assert ASSESSMENT_TABLES <= _tables(pg_engine)


def test_prerequisites_block_cross_course_and_self_reference(
    clean_assessment_db: Engine,
) -> None:
    with clean_assessment_db.begin() as conn:
        instructor = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", instructor)
        c2 = insert_course(conn, "CENG201", instructor)
        lo1 = _insert_outcome(conn, c1, "LO-1")
        lo2 = _insert_outcome(conn, c1, "LO-2")
        lo_other = _insert_outcome(conn, c2, "LO-1")

        # Valid same-course prerequisite succeeds
        conn.execute(
            text(
                "INSERT INTO prerequisites (course_id, prerequisite_outcome_id, dependent_outcome_id) "
                "VALUES (:c, :p, :d)"
            ),
            {"c": c1, "p": lo1, "d": lo2},
        )

    # Duplicate edge rejected
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO prerequisites (course_id, prerequisite_outcome_id, dependent_outcome_id) "
                    "VALUES (:c, :p, :d)"
                ),
                {"c": c1, "p": lo1, "d": lo2},
            )

    # Self-reference rejected
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO prerequisites (course_id, prerequisite_outcome_id, dependent_outcome_id) "
                    "VALUES (:c, :p, :p)"
                ),
                {"c": c1, "p": lo1},
            )

    # Cross-course prerequisite rejected by composite FK
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO prerequisites (course_id, prerequisite_outcome_id, dependent_outcome_id) "
                    "VALUES (:c, :p, :d)"
                ),
                {"c": c1, "p": lo1, "d": lo_other},
            )


def test_question_options_partial_unique_correct_and_unique_order(
    clean_assessment_db: Engine,
) -> None:
    with clean_assessment_db.begin() as conn:
        instructor = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", instructor)
        lo1 = _insert_outcome(conn, c1, "LO-1")
        q1 = _insert_question(conn, c1, lo1, instructor)
        _insert_option(conn, q1, 0, "A", is_correct=True)
        _insert_option(conn, q1, 1, "B", is_correct=False)

    # Second correct option for the same question rejected by partial unique index
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            _insert_option(conn, q1, 2, "C", is_correct=True)

    # Duplicate order_index for the same question rejected
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            _insert_option(conn, q1, 1, "B-dup", is_correct=False)


def test_course_isolation_for_questions_and_assessments(
    clean_assessment_db: Engine,
) -> None:
    with clean_assessment_db.begin() as conn:
        instructor = insert_user(conn, "inst@example.edu", "instructor")
        c1 = insert_course(conn, "CENG101", instructor)
        c2 = insert_course(conn, "CENG201", instructor)
        lo1 = _insert_outcome(conn, c1, "LO-1")
        lo2 = _insert_outcome(conn, c2, "LO-1")
        q2 = _insert_question(conn, c2, lo2, instructor)
        a1 = _insert_assessment(conn, c1, "diagnostic", instructor)

    # Question cannot link to an outcome in a different course
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            _insert_question(conn, c1, lo2, instructor)

    # Assessment in c1 cannot include a question from c2
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assessment_questions (assessment_id, question_id, course_id, order_index) "
                    "VALUES (:a, :q, :c, 0)"
                ),
                {"a": a1, "q": q2, "c": c1},
            )


def test_student_response_enforces_assignment_option_ownership_and_history_protection(
    clean_assessment_db: Engine,
) -> None:
    with clean_assessment_db.begin() as conn:
        instructor = insert_user(conn, "inst@example.edu", "instructor")
        student = insert_user(conn, "stu@example.edu", "student")
        c1 = insert_course(conn, "CENG101", instructor)
        lo1 = _insert_outcome(conn, c1, "LO-1")
        q_assigned = _insert_question(conn, c1, lo1, instructor, "Assigned Q")
        q_unassigned = _insert_question(conn, c1, lo1, instructor, "Unassigned Q")
        opt_assigned = _insert_option(conn, q_assigned, 0, "Right", is_correct=True)
        opt_other = _insert_option(conn, q_unassigned, 0, "Other", is_correct=True)

        a1 = _insert_assessment(conn, c1, "diagnostic", instructor)
        conn.execute(
            text(
                "INSERT INTO assessment_questions (assessment_id, question_id, course_id, order_index) "
                "VALUES (:a, :q, :c, 0)"
            ),
            {"a": a1, "q": q_assigned, "c": c1},
        )
        attempt_id = conn.execute(
            text(
                "INSERT INTO student_assessments (student_id, assessment_id) "
                "VALUES (:s, :a) RETURNING id"
            ),
            {"s": student, "a": a1},
        ).scalar_one()

        # Valid response succeeds
        conn.execute(
            text(
                "INSERT INTO student_responses "
                "(student_assessment_id, assessment_id, question_id, selected_option_id, is_correct, score_earned) "
                "VALUES (:att, :a, :q, :opt, true, 1.0)"
            ),
            {"att": attempt_id, "a": a1, "q": q_assigned, "opt": opt_assigned},
        )

    # Unassigned question cannot be answered in this attempt
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO student_responses "
                    "(student_assessment_id, assessment_id, question_id, selected_option_id, is_correct, score_earned) "
                    "VALUES (:att, :a, :q, :opt, true, 1.0)"
                ),
                {"att": attempt_id, "a": a1, "q": q_unassigned, "opt": opt_other},
            )

    # Option belonging to a different question is rejected by composite FK
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            attempt2 = conn.execute(
                text(
                    "INSERT INTO student_assessments (student_id, assessment_id) "
                    "VALUES (:s, :a) RETURNING id"
                ),
                {"s": student, "a": a1},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO student_responses "
                    "(student_assessment_id, assessment_id, question_id, selected_option_id, is_correct, score_earned) "
                    "VALUES (:att, :a, :q, :opt, false, 0.0)"
                ),
                {"att": attempt2, "a": a1, "q": q_assigned, "opt": opt_other},
            )

    # Historical protection: deleting a question included in assessment_questions is RESTRICTed
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text("DELETE FROM questions WHERE id = :q"),
                {"q": q_assigned},
            )

    # Historical protection: deleting an option referenced by student_responses is RESTRICTed
    with pytest.raises(IntegrityError):
        with clean_assessment_db.begin() as conn:
            conn.execute(
                text("DELETE FROM question_options WHERE id = :opt"),
                {"opt": opt_assigned},
            )

    # Archiving (soft-delete) + creating v2 with version lineage preserves history cleanly
    with clean_assessment_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE questions SET is_active = false, archived_at = now() WHERE id = :q"
            ),
            {"q": q_assigned},
        )
        v2_id = conn.execute(
            text(
                "INSERT INTO questions "
                "(course_id, learning_outcome_id, question_text, version_number, root_question_id, previous_version_id) "
                "VALUES (:c, :lo, 'Assigned Q v2', 2, :root, :prev) RETURNING id"
            ),
            {"c": c1, "lo": lo1, "root": q_assigned, "prev": q_assigned},
        ).scalar_one()
        assert v2_id > q_assigned


def test_check_constraints_reject_invalid_values(
    clean_assessment_db: Engine,
) -> None:
    with clean_assessment_db.begin() as conn:
        instructor = insert_user(conn, "inst@example.edu", "instructor")
        student = insert_user(conn, "stu@example.edu", "student")
        c1 = insert_course(conn, "CENG101", instructor)
        lo1 = _insert_outcome(conn, c1, "LO-1")
        q1 = _insert_question(conn, c1, lo1, instructor)
        a1 = _insert_assessment(conn, c1, "review", instructor)
        conn.execute(
            text(
                "INSERT INTO assessment_questions (assessment_id, question_id, course_id, order_index) "
                "VALUES (:a, :q, :c, 0)"
            ),
            {"a": a1, "q": q1, "c": c1},
        )
        attempt_id = conn.execute(
            text(
                "INSERT INTO student_assessments (student_id, assessment_id) "
                "VALUES (:s, :a) RETURNING id"
            ),
            {"s": student, "a": a1},
        ).scalar_one()

    bad_sqls = [
        # Non-positive points
        "INSERT INTO questions (course_id, learning_outcome_id, question_text, points) VALUES (:c, :lo, 'x', 0)",
        # Inconsistent active/archived_at
        "INSERT INTO questions (course_id, learning_outcome_id, question_text, is_active, archived_at) VALUES (:c, :lo, 'x', false, NULL)",
        # Inconsistent version lineage (v2 without root/prev)
        "INSERT INTO questions (course_id, learning_outcome_id, question_text, version_number) VALUES (:c, :lo, 'x', 2)",
        # Completed attempt without completed_at
        "INSERT INTO student_assessments (student_id, assessment_id, status, completed_at) VALUES (:s, :a, 'completed', NULL)",
        # Score > 100
        "INSERT INTO student_assessments (student_id, assessment_id, score) VALUES (:s, :a, 105.0)",
        # Unanswered response marked correct
        "INSERT INTO student_responses (student_assessment_id, assessment_id, question_id, selected_option_id, is_correct, score_earned) VALUES (:att, :a, :q, NULL, true, 1.0)",
        # Mastery score out of range
        "INSERT INTO mastery_records (student_id, learning_outcome_id, mastery_score) VALUES (:s, :lo, 101.0)",
        # Invalid recommendation status
        "INSERT INTO study_recommendations (student_id, learning_outcome_id, priority_order, reason, status) VALUES (:s, :lo, 1, 'r', 'unknown')",
    ]
    params = {"c": c1, "lo": lo1, "q": q1, "a": a1, "s": student, "att": attempt_id}
    for sql in bad_sqls:
        with pytest.raises(IntegrityError):
            with clean_assessment_db.begin() as conn:
                conn.execute(text(sql), params)

    # Blocked recommendation status is accepted and preserved
    with clean_assessment_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO study_recommendations (student_id, learning_outcome_id, priority_order, reason, status) "
                "VALUES (:s, :lo, 1, 'Missing prerequisite', 'blocked')"
            ),
            params,
        )
