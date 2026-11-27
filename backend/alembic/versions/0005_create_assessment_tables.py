"""Create learning outcome, question bank, assessment, and mastery tables (Issue #7).

Revision ID: 0005_create_assessment_tables
Revises: 0004_add_chunk_embeddings
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_create_assessment_tables"
down_revision: str | Sequence[str] | None = "0004_add_chunk_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "order_index",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("ck_learning_outcomes_order_index_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_learning_outcomes_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_outcomes"),
        sa.UniqueConstraint(
            "course_id",
            "code",
            name="uq_learning_outcomes_course_id_code",
        ),
        sa.UniqueConstraint(
            "id",
            "course_id",
            name="uq_learning_outcomes_id_course_id",
        ),
    )
    op.create_index(
        "ix_learning_outcomes_course_id_order_index",
        "learning_outcomes",
        ["course_id", "order_index"],
    )

    op.create_table(
        "prerequisites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("prerequisite_outcome_id", sa.Integer(), nullable=False),
        sa.Column("dependent_outcome_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prerequisite_outcome_id != dependent_outcome_id",
            name=op.f("ck_prerequisites_no_self_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_prerequisites_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_prerequisites_prereq_outcome_course",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dependent_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_prerequisites_dep_outcome_course",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prerequisites"),
        sa.UniqueConstraint(
            "prerequisite_outcome_id",
            "dependent_outcome_id",
            name="uq_prerequisites_prerequisite_dependent",
        ),
    )
    op.create_index("ix_prerequisites_course_id", "prerequisites", ["course_id"])
    op.create_index(
        "ix_prerequisites_dependent_outcome_id",
        "prerequisites",
        ["dependent_outcome_id"],
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("learning_outcome_id", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "question_type",
            sa.String(length=30),
            server_default=sa.text("'multiple_choice'"),
            nullable=False,
        ),
        sa.Column(
            "difficulty_level",
            sa.String(length=20),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column(
            "points",
            sa.Float(),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version_number",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("root_question_id", sa.Integer(), nullable=True),
        sa.Column("previous_version_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "question_type IN ('multiple_choice', 'true_false')",
            name=op.f("ck_questions_question_type"),
        ),
        sa.CheckConstraint(
            "difficulty_level IN ('easy', 'medium', 'hard')",
            name=op.f("ck_questions_difficulty_level"),
        ),
        sa.CheckConstraint(
            "points > 0",
            name=op.f("ck_questions_points_positive"),
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=op.f("ck_questions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND root_question_id IS NULL AND previous_version_id IS NULL) "
            "OR (version_number > 1 AND root_question_id IS NOT NULL AND previous_version_id IS NOT NULL)",
            name=op.f("ck_questions_version_lineage_consistent"),
        ),
        sa.CheckConstraint(
            "root_question_id IS NULL OR root_question_id != id",
            name=op.f("ck_questions_root_not_self"),
        ),
        sa.CheckConstraint(
            "previous_version_id IS NULL OR previous_version_id != id",
            name=op.f("ck_questions_previous_not_self"),
        ),
        sa.CheckConstraint(
            "(is_active = true AND archived_at IS NULL) "
            "OR (is_active = false AND archived_at IS NOT NULL)",
            name=op.f("ck_questions_active_archived_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_questions_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learning_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_questions_outcome_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["root_question_id"],
            ["questions.id"],
            name=op.f("fk_questions_root_question_id_questions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["questions.id"],
            name=op.f("fk_questions_previous_version_id_questions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_questions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_questions"),
        sa.UniqueConstraint(
            "id",
            "course_id",
            name="uq_questions_id_course_id",
        ),
        sa.UniqueConstraint(
            "root_question_id",
            "version_number",
            name="uq_questions_root_question_id_version_number",
        ),
        sa.UniqueConstraint(
            "previous_version_id",
            name="uq_questions_previous_version_id",
        ),
    )
    op.create_index(
        "ix_questions_course_id_is_active",
        "questions",
        ["course_id", "is_active"],
    )
    op.create_index(
        "ix_questions_learning_outcome_id",
        "questions",
        ["learning_outcome_id"],
    )
    op.create_index("ix_questions_created_by", "questions", ["created_by"])
    op.create_index(
        "ix_questions_root_question_id",
        "questions",
        ["root_question_id"],
    )

    op.create_table(
        "question_options",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column(
            "is_correct",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "order_index",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("ck_question_options_order_index_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_question_options_question_id_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_question_options"),
        sa.UniqueConstraint(
            "question_id",
            "order_index",
            name="uq_question_options_question_id_order_index",
        ),
        sa.UniqueConstraint(
            "id",
            "question_id",
            name="uq_question_options_id_question_id",
        ),
    )
    op.create_index(
        "uq_question_options_one_correct_per_question",
        "question_options",
        ["question_id"],
        unique=True,
        postgresql_where=sa.text("is_correct = true"),
    )

    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assessment_type", sa.String(length=30), nullable=False),
        sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assessment_type IN ('diagnostic', 'practice', 'review', 'final')",
            name=op.f("ck_assessments_assessment_type"),
        ),
        sa.CheckConstraint(
            "time_limit_minutes IS NULL OR time_limit_minutes > 0",
            name=op.f("ck_assessments_time_limit_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_assessments_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_assessments_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments"),
        sa.UniqueConstraint(
            "id",
            "course_id",
            name="uq_assessments_id_course_id",
        ),
    )
    op.create_index(
        "ix_assessments_course_id_type",
        "assessments",
        ["course_id", "assessment_type"],
    )
    op.create_index("ix_assessments_created_by", "assessments", ["created_by"])

    op.create_table(
        "assessment_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column(
            "order_index",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("ck_assessment_questions_order_index_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "course_id"],
            ["assessments.id", "assessments.course_id"],
            name="fk_assessment_questions_assessment_course",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "course_id"],
            ["questions.id", "questions.course_id"],
            name="fk_assessment_questions_question_course",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_questions"),
        sa.UniqueConstraint(
            "assessment_id",
            "question_id",
            name="uq_assessment_questions_assessment_id_question_id",
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "order_index",
            name="uq_assessment_questions_assessment_id_order_index",
        ),
    )
    op.create_index(
        "ix_assessment_questions_question_id",
        "assessment_questions",
        ["question_id"],
    )
    op.create_index(
        "ix_assessment_questions_course_id",
        "assessment_questions",
        ["course_id"],
    )

    op.create_table(
        "student_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned')",
            name=op.f("ck_student_assessments_status"),
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name=op.f("ck_student_assessments_score_range"),
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) "
            "OR (status != 'completed' AND completed_at IS NULL)",
            name=op.f("ck_student_assessments_completed_at_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_student_assessments_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            name=op.f("fk_student_assessments_assessment_id_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_assessments"),
        sa.UniqueConstraint(
            "id",
            "assessment_id",
            name="uq_student_assessments_id_assessment_id",
        ),
    )
    op.create_index(
        "ix_student_assessments_student_id_status",
        "student_assessments",
        ["student_id", "status"],
    )
    op.create_index(
        "ix_student_assessments_assessment_id",
        "student_assessments",
        ["assessment_id"],
    )

    op.create_table(
        "student_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_assessment_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("selected_option_id", sa.Integer(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column(
            "score_earned",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "score_earned >= 0",
            name=op.f("ck_student_responses_score_earned_non_negative"),
        ),
        sa.CheckConstraint(
            "(selected_option_id IS NOT NULL) OR (is_correct = false AND score_earned = 0)",
            name=op.f("ck_student_responses_unanswered_cannot_be_correct"),
        ),
        sa.ForeignKeyConstraint(
            ["student_assessment_id", "assessment_id"],
            ["student_assessments.id", "student_assessments.assessment_id"],
            name="fk_student_responses_attempt_assessment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "question_id"],
            ["assessment_questions.assessment_id", "assessment_questions.question_id"],
            name="fk_student_responses_assessment_question",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_option_id", "question_id"],
            ["question_options.id", "question_options.question_id"],
            name="fk_student_responses_option_question",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_responses"),
        sa.UniqueConstraint(
            "student_assessment_id",
            "question_id",
            name="uq_student_responses_attempt_question",
        ),
    )
    op.create_index(
        "ix_student_responses_question_id",
        "student_responses",
        ["question_id"],
    )
    op.create_index(
        "ix_student_responses_assessment_id_question_id",
        "student_responses",
        ["assessment_id", "question_id"],
    )
    op.create_index(
        "ix_student_responses_selected_option_id",
        "student_responses",
        ["selected_option_id"],
    )

    op.create_table(
        "mastery_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("learning_outcome_id", sa.Integer(), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=False),
        sa.Column(
            "total_attempts",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "last_assessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mastery_score >= 0 AND mastery_score <= 100",
            name=op.f("ck_mastery_records_mastery_score_range"),
        ),
        sa.CheckConstraint(
            "total_attempts >= 1",
            name=op.f("ck_mastery_records_total_attempts_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_mastery_records_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learning_outcome_id"],
            ["learning_outcomes.id"],
            name=op.f("fk_mastery_records_learning_outcome_id_learning_outcomes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mastery_records"),
        sa.UniqueConstraint(
            "student_id",
            "learning_outcome_id",
            name="uq_mastery_records_student_id_learning_outcome_id",
        ),
    )
    op.create_index(
        "ix_mastery_records_learning_outcome_id",
        "mastery_records",
        ["learning_outcome_id"],
    )

    op.create_table(
        "study_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("learning_outcome_id", sa.Integer(), nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority_order >= 1",
            name=op.f("ck_study_recommendations_priority_order_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'review', 'study', 'blocked')",
            name=op.f("ck_study_recommendations_status"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_study_recommendations_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learning_outcome_id"],
            ["learning_outcomes.id"],
            name=op.f("fk_study_recommendations_learning_outcome_id_learning_outcomes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study_recommendations"),
        sa.UniqueConstraint(
            "student_id",
            "learning_outcome_id",
            name="uq_study_recommendations_student_outcome",
        ),
    )
    op.create_index(
        "ix_study_recommendations_student_id_priority",
        "study_recommendations",
        ["student_id", "priority_order"],
    )
    op.create_index(
        "ix_study_recommendations_learning_outcome_id",
        "study_recommendations",
        ["learning_outcome_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_study_recommendations_learning_outcome_id",
        table_name="study_recommendations",
    )
    op.drop_index(
        "ix_study_recommendations_student_id_priority",
        table_name="study_recommendations",
    )
    op.drop_table("study_recommendations")

    op.drop_index(
        "ix_mastery_records_learning_outcome_id",
        table_name="mastery_records",
    )
    op.drop_table("mastery_records")

    op.drop_index(
        "ix_student_responses_selected_option_id",
        table_name="student_responses",
    )
    op.drop_index(
        "ix_student_responses_assessment_id_question_id",
        table_name="student_responses",
    )
    op.drop_index(
        "ix_student_responses_question_id",
        table_name="student_responses",
    )
    op.drop_table("student_responses")

    op.drop_index(
        "ix_student_assessments_assessment_id",
        table_name="student_assessments",
    )
    op.drop_index(
        "ix_student_assessments_student_id_status",
        table_name="student_assessments",
    )
    op.drop_table("student_assessments")

    op.drop_index(
        "ix_assessment_questions_course_id",
        table_name="assessment_questions",
    )
    op.drop_index(
        "ix_assessment_questions_question_id",
        table_name="assessment_questions",
    )
    op.drop_table("assessment_questions")

    op.drop_index("ix_assessments_created_by", table_name="assessments")
    op.drop_index("ix_assessments_course_id_type", table_name="assessments")
    op.drop_table("assessments")

    op.drop_index(
        "uq_question_options_one_correct_per_question",
        table_name="question_options",
    )
    op.drop_table("question_options")

    op.drop_index("ix_questions_root_question_id", table_name="questions")
    op.drop_index("ix_questions_created_by", table_name="questions")
    op.drop_index("ix_questions_learning_outcome_id", table_name="questions")
    op.drop_index("ix_questions_course_id_is_active", table_name="questions")
    op.drop_table("questions")

    op.drop_index(
        "ix_prerequisites_dependent_outcome_id",
        table_name="prerequisites",
    )
    op.drop_index("ix_prerequisites_course_id", table_name="prerequisites")
    op.drop_table("prerequisites")

    op.drop_index(
        "ix_learning_outcomes_course_id_order_index",
        table_name="learning_outcomes",
    )
    op.drop_table("learning_outcomes")
