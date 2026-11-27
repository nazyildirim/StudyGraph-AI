"""MaterialChunk persistence abstraction and SQLAlchemy implementation."""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.course_material import CourseMaterial
from app.models.material_chunk import MaterialChunk
from app.rag.domain.types import ChunkDraft, ProcessingStatus
from app.repositories.errors import MaterialNotFoundError


class MaterialChunkRepository(Protocol):
    """Repository contract for material chunks."""

    def replace_chunks(
        self, material_id: int, drafts: Sequence[ChunkDraft]
    ) -> list[MaterialChunk]: ...

    def save_embedded_chunks_and_mark_processed(
        self,
        *,
        material_id: int,
        drafts: Sequence[ChunkDraft],
        embeddings: Sequence[bytes],
        embedding_model: str,
        embedding_dim: int,
        extraction_report: str | None = None,
    ) -> list[MaterialChunk]: ...

    def list_by_material(self, material_id: int) -> list[MaterialChunk]: ...

    def get_many(self, chunk_ids: Sequence[int]) -> list[MaterialChunk]: ...

    def count_by_material(self, material_id: int) -> int: ...


class SqlAlchemyMaterialChunkRepository:
    """SQLAlchemy 2.0 implementation of MaterialChunkRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_chunks(
        self, material_id: int, drafts: Sequence[ChunkDraft]
    ) -> list[MaterialChunk]:
        """Atomically replace all chunks of a material without embeddings.

        The material row is locked so concurrent writes are serialized.
        Existing chunks (and, through ON DELETE CASCADE, their citations) are
        removed, so callers must treat this as a deliberate re-index.
        """
        indexes = [draft.chunk_index for draft in drafts]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Duplicate chunk_index values in drafts.")

        locked = self._session.execute(
            select(CourseMaterial.id)
            .where(CourseMaterial.id == material_id)
            .with_for_update()
        ).first()
        if locked is None:
            self._session.rollback()
            raise MaterialNotFoundError(str(material_id))

        try:
            self._session.execute(
                delete(MaterialChunk).where(MaterialChunk.material_id == material_id)
            )
            chunks = [
                MaterialChunk(
                    material_id=material_id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    metadata_json=(
                        json.dumps(dict(draft.metadata), ensure_ascii=False)
                        if draft.metadata is not None
                        else None
                    ),
                )
                for draft in sorted(drafts, key=lambda d: d.chunk_index)
            ]
            self._session.add_all(chunks)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return chunks

    def save_embedded_chunks_and_mark_processed(
        self,
        *,
        material_id: int,
        drafts: Sequence[ChunkDraft],
        embeddings: Sequence[bytes],
        embedding_model: str,
        embedding_dim: int,
        extraction_report: str | None = None,
    ) -> list[MaterialChunk]:
        """Atomically store embedded chunks and mark the material as processed.

        Executes inside a single database transaction so a failure can never
        leave a half-indexed material or mismatched status.
        """
        if len(drafts) != len(embeddings):
            raise ValueError("drafts and embeddings must have the same length.")
        if not drafts:
            raise ValueError("drafts must not be empty.")
        indexes = [draft.chunk_index for draft in drafts]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Duplicate chunk_index values in drafts.")
        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be > 0.")
        expected_bytes = embedding_dim * 4
        for raw in embeddings:
            if len(raw) != expected_bytes:
                raise ValueError(
                    f"Embedding byte length {len(raw)} does not match "
                    f"embedding_dim * 4 ({expected_bytes})."
                )

        material = self._session.get(
            CourseMaterial, material_id, with_for_update=True
        )
        if material is None:
            self._session.rollback()
            raise MaterialNotFoundError(str(material_id))

        paired = sorted(
            zip(drafts, embeddings, strict=True),
            key=lambda pair: pair[0].chunk_index,
        )
        try:
            self._session.execute(
                delete(MaterialChunk).where(MaterialChunk.material_id == material_id)
            )
            chunks = [
                MaterialChunk(
                    material_id=material_id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    metadata_json=(
                        json.dumps(dict(draft.metadata), ensure_ascii=False)
                        if draft.metadata is not None
                        else None
                    ),
                    embedding=emb_bytes,
                    embedding_model=embedding_model,
                    embedding_dim=embedding_dim,
                )
                for draft, emb_bytes in paired
            ]
            self._session.add_all(chunks)
            material.processing_status = ProcessingStatus.PROCESSED.value
            material.error_message = None
            if extraction_report is not None:
                material.extraction_report = extraction_report
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return chunks

    def list_by_material(self, material_id: int) -> list[MaterialChunk]:
        return list(
            self._session.execute(
                select(MaterialChunk)
                .where(MaterialChunk.material_id == material_id)
                .order_by(MaterialChunk.chunk_index)
            ).scalars()
        )

    def get_many(self, chunk_ids: Sequence[int]) -> list[MaterialChunk]:
        if not chunk_ids:
            return []
        return list(
            self._session.execute(
                select(MaterialChunk)
                .where(MaterialChunk.id.in_(list(chunk_ids)))
                .order_by(MaterialChunk.id)
            ).scalars()
        )

    def count_by_material(self, material_id: int) -> int:
        return self._session.execute(
            select(func.count())
            .select_from(MaterialChunk)
            .where(MaterialChunk.material_id == material_id)
        ).scalar_one()
