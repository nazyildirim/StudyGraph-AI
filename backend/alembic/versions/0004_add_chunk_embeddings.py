"""Add embedding columns and consistency constraints to material_chunks.

Revision ID: 0004_add_chunk_embeddings
Revises: 0003_create_rag_tables
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_add_chunk_embeddings"
down_revision: str | Sequence[str] | None = "0003_create_rag_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "material_chunks",
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "material_chunks",
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "material_chunks",
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_material_chunks_embedding_fields_consistent"),
        "material_chunks",
        "(embedding IS NULL AND embedding_model IS NULL AND embedding_dim IS NULL) "
        "OR (embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_dim IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_material_chunks_embedding_dim_positive"),
        "material_chunks",
        "embedding_dim IS NULL OR embedding_dim > 0",
    )
    op.create_check_constraint(
        op.f("ck_material_chunks_embedding_byte_length"),
        "material_chunks",
        "embedding IS NULL OR octet_length(embedding) = embedding_dim * 4",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_material_chunks_embedding_byte_length"),
        "material_chunks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_material_chunks_embedding_dim_positive"),
        "material_chunks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_material_chunks_embedding_fields_consistent"),
        "material_chunks",
        type_="check",
    )
    op.drop_column("material_chunks", "embedding_dim")
    op.drop_column("material_chunks", "embedding_model")
    op.drop_column("material_chunks", "embedding")
