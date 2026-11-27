"""Create RAG tables for Issue #8 (materials, chunks, queries, citations).

Revision ID: 0003_create_rag_tables
Revises: 0002_create_courses_enrollments
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_create_rag_tables"
down_revision: str | Sequence[str] | None = "0002_create_courses_enrollments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "course_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("unverified_outcome_ref", sa.String(length=100), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extraction_report", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'processing', 'processed', 'failed')",
            name=op.f("ck_course_materials_processing_status"),
        ),
        sa.CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name=op.f("ck_course_materials_file_size_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_course_materials_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_course_materials_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_course_materials"),
        sa.UniqueConstraint(
            "course_id",
            "content_hash",
            name="uq_course_materials_course_id_content_hash",
        ),
    )
    op.create_index("ix_course_materials_course_id", "course_materials", ["course_id"])
    op.create_index(
        "ix_course_materials_uploaded_by", "course_materials", ["uploaded_by"]
    )

    op.create_table(
        "material_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=op.f("ck_material_chunks_chunk_index_non_negative"),
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_start >= 1",
            name=op.f("ck_material_chunks_page_start_positive"),
        ),
        sa.CheckConstraint(
            "page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start)",
            name=op.f("ck_material_chunks_page_range_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["course_materials.id"],
            name=op.f("fk_material_chunks_material_id_course_materials"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_chunks"),
        sa.UniqueConstraint(
            "material_id",
            "chunk_index",
            name="uq_material_chunks_material_id_chunk_index",
        ),
    )

    op.create_table(
        "rag_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "grounded",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_rag_queries_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_rag_queries_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_queries"),
    )
    op.create_index(
        "ix_rag_queries_student_id_course_id",
        "rag_queries",
        ["student_id", "course_id"],
    )
    op.create_index("ix_rag_queries_course_id", "rag_queries", ["course_id"])

    op.create_table(
        "rag_query_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)",
            name=op.f("ck_rag_query_citations_relevance_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["rag_queries.id"],
            name=op.f("fk_rag_query_citations_query_id_rag_queries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["material_chunks.id"],
            name=op.f("fk_rag_query_citations_chunk_id_material_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_query_citations"),
        sa.UniqueConstraint(
            "query_id",
            "chunk_id",
            name="uq_rag_query_citations_query_id_chunk_id",
        ),
    )
    op.create_index(
        "ix_rag_query_citations_chunk_id", "rag_query_citations", ["chunk_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_rag_query_citations_chunk_id", table_name="rag_query_citations")
    op.drop_table("rag_query_citations")
    op.drop_index("ix_rag_queries_course_id", table_name="rag_queries")
    op.drop_index("ix_rag_queries_student_id_course_id", table_name="rag_queries")
    op.drop_table("rag_queries")
    op.drop_table("material_chunks")
    op.drop_index("ix_course_materials_uploaded_by", table_name="course_materials")
    op.drop_index("ix_course_materials_course_id", table_name="course_materials")
    op.drop_table("course_materials")
