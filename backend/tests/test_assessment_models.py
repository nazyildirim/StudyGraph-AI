"""Unit tests for Issue #7 ORM metadata, config defaults, and Alembic chain."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from app.core.config import Settings
from app.models import (
    Assessment,
    AssessmentQuestion,
    AssessmentType,
    Base,
    DifficultyLevel,
    LearningOutcomeRecord,
    MasteryRecord,
    Prerequisite,
    Question,
    QuestionOption,
    QuestionType,
    RecommendationStatus,
    StudentAssessment,
    StudentAssessmentStatus,
    StudentResponse,
    StudyRecommendation,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent

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


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _names(table: Table, kind: type) -> set[str]:
    return {c.name for c in table.constraints if isinstance(c, kind)}


def _fk_constraints(table: Table) -> dict[str, ForeignKeyConstraint]:
    return {
        c.name: c
        for c in table.constraints
        if isinstance(c, ForeignKeyConstraint) and c.name is not None
    }


def test_all_issue7_tables_and_models_are_registered() -> None:
    assert ASSESSMENT_TABLES <= set(Base.metadata.tables)
    assert LearningOutcomeRecord.__tablename__ == "learning_outcomes"
    assert Prerequisite.__tablename__ == "prerequisites"
    assert Question.__tablename__ == "questions"
    assert QuestionOption.__tablename__ == "question_options"
    assert Assessment.__tablename__ == "assessments"
    assert AssessmentQuestion.__tablename__ == "assessment_questions"
    assert StudentAssessment.__tablename__ == "student_assessments"
    assert StudentResponse.__tablename__ == "student_responses"
    assert MasteryRecord.__tablename__ == "mastery_records"
    assert StudyRecommendation.__tablename__ == "study_recommendations"


def test_enum_values_match_database_design_and_recommendation_engine() -> None:
    assert {item.value for item in QuestionType} == {"multiple_choice", "true_false"}
    assert {item.value for item in DifficultyLevel} == {"easy", "medium", "hard"}
    assert {item.value for item in AssessmentType} == {
        "diagnostic",
        "practice",
        "review",
        "final",
    }
    assert {item.value for item in StudentAssessmentStatus} == {
        "in_progress",
        "completed",
        "abandoned",
    }
    assert {"completed", "review", "study", "blocked", "pending", "in_progress"} == {
        item.value for item in RecommendationStatus
    }


def test_learning_outcomes_and_prerequisites_enforce_course_isolation() -> None:
    lo = _table("learning_outcomes")
    assert {
        "uq_learning_outcomes_course_id_code",
        "uq_learning_outcomes_id_course_id",
    } <= _names(lo, UniqueConstraint)
    assert "ck_learning_outcomes_order_index_non_negative" in _names(
        lo, CheckConstraint
    )

    prereq = _table("prerequisites")
    fks = _fk_constraints(prereq)
    assert set(fks["fk_prerequisites_prereq_outcome_course"].column_keys) == {
        "prerequisite_outcome_id",
        "course_id",
    }
    assert set(fks["fk_prerequisites_dep_outcome_course"].column_keys) == {
        "dependent_outcome_id",
        "course_id",
    }
    assert "uq_prerequisites_prerequisite_dependent" in _names(
        prereq, UniqueConstraint
    )
    assert "ck_prerequisites_no_self_reference" in _names(prereq, CheckConstraint)


def test_question_versioning_and_option_constraints() -> None:
    q = _table("questions")
    assert {
        "uq_questions_id_course_id",
        "uq_questions_root_question_id_version_number",
        "uq_questions_previous_version_id",
    } <= _names(q, UniqueConstraint)
    assert {
        "ck_questions_question_type",
        "ck_questions_difficulty_level",
        "ck_questions_points_positive",
        "ck_questions_version_number_positive",
        "ck_questions_version_lineage_consistent",
        "ck_questions_root_not_self",
        "ck_questions_previous_not_self",
        "ck_questions_active_archived_consistent",
    } <= _names(q, CheckConstraint)
    fks = _fk_constraints(q)
    assert fks["fk_questions_outcome_course"].ondelete == "RESTRICT"

    opts = _table("question_options")
    assert {
        "uq_question_options_question_id_order_index",
        "uq_question_options_id_question_id",
    } <= _names(opts, UniqueConstraint)
    partial_indexes = {
        idx.name: idx for idx in opts.indexes if idx.unique
    }
    assert "uq_question_options_one_correct_per_question" in partial_indexes


def test_assessment_and_response_composite_fks_protect_history() -> None:
    aq = _table("assessment_questions")
    aq_fks = _fk_constraints(aq)
    assert aq_fks["fk_assessment_questions_assessment_course"].ondelete == "CASCADE"
    assert aq_fks["fk_assessment_questions_question_course"].ondelete == "RESTRICT"
    assert {
        "uq_assessment_questions_assessment_id_question_id",
        "uq_assessment_questions_assessment_id_order_index",
    } <= _names(aq, UniqueConstraint)

    sa_tbl = _table("student_assessments")
    assert "uq_student_assessments_id_assessment_id" in _names(
        sa_tbl, UniqueConstraint
    )
    assert {
        "ck_student_assessments_status",
        "ck_student_assessments_score_range",
        "ck_student_assessments_completed_at_consistent",
    } <= _names(sa_tbl, CheckConstraint)

    sr = _table("student_responses")
    sr_fks = _fk_constraints(sr)
    assert sr_fks["fk_student_responses_attempt_assessment"].ondelete == "CASCADE"
    assert sr_fks["fk_student_responses_assessment_question"].ondelete == "RESTRICT"
    assert sr_fks["fk_student_responses_option_question"].ondelete == "RESTRICT"
    assert "uq_student_responses_attempt_question" in _names(sr, UniqueConstraint)
    assert {
        "ck_student_responses_score_earned_non_negative",
        "ck_student_responses_unanswered_cannot_be_correct",
    } <= _names(sr, CheckConstraint)


def test_mastery_and_recommendation_constraints() -> None:
    mastery = _table("mastery_records")
    assert "uq_mastery_records_student_id_learning_outcome_id" in _names(
        mastery, UniqueConstraint
    )
    assert {
        "ck_mastery_records_mastery_score_range",
        "ck_mastery_records_total_attempts_positive",
    } <= _names(mastery, CheckConstraint)

    rec = _table("study_recommendations")
    assert "uq_study_recommendations_student_outcome" in _names(
        rec, UniqueConstraint
    )
    assert {
        "ck_study_recommendations_priority_order_positive",
        "ck_study_recommendations_status",
    } <= _names(rec, CheckConstraint)


def test_alembic_revision_chain_includes_0005() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    assert script.get_heads() == ["0005_create_assessment_tables"]
    chain = [rev.revision for rev in script.walk_revisions()]
    assert chain == [
        "0005_create_assessment_tables",
        "0004_add_chunk_embeddings",
        "0003_create_rag_tables",
        "0002_create_courses_enrollments",
        "0001_create_users",
    ]
    assert all(len(rev) <= 32 for rev in chain)


def test_exam_config_defaults_load_without_env() -> None:
    settings = Settings(_env_file=None)
    assert settings.exam_initial_question_count == 15
    assert settings.exam_retest_question_count == 5
    assert settings.exam_default_mastery_threshold == 70.0
