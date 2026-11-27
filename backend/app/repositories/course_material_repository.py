"""CourseMaterial persistence abstraction and SQLAlchemy implementation."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course_material import CourseMaterial
from app.rag.domain.types import ProcessingStatus
from app.repositories.errors import (
    MaterialAlreadyExistsError,
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
    MaterialNotFoundError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
    is_unique_violation,
)

MATERIAL_HASH_UNIQUE_CONSTRAINT = "uq_course_materials_course_id_content_hash"


class CourseMaterialRepository(Protocol):
    """Repository contract for course material metadata."""

    def get_by_id(self, material_id: int) -> CourseMaterial | None: ...

    def list_by_course(self, course_id: int) -> list[CourseMaterial]: ...

    def create(
        self,
        *,
        course_id: int,
        uploaded_by: int | None,
        title: str,
        file_path: str,
        file_type: str,
        file_size_bytes: int | None,
        content_hash: str,
        unverified_outcome_ref: str | None = None,
    ) -> CourseMaterial: ...

    def update_processing_status(
        self,
        material_id: int,
        status: ProcessingStatus,
        *,
        error_message: str | None = None,
        extraction_report: str | None = None,
    ) -> CourseMaterial: ...

    def claim_for_processing(self, material_id: int) -> CourseMaterial: ...

    def delete(self, material_id: int) -> bool: ...


class SqlAlchemyCourseMaterialRepository:
    """SQLAlchemy 2.0 implementation of CourseMaterialRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, material_id: int) -> CourseMaterial | None:
        return self._session.get(CourseMaterial, material_id)

    def list_by_course(self, course_id: int) -> list[CourseMaterial]:
        return list(
            self._session.execute(
                select(CourseMaterial)
                .where(CourseMaterial.course_id == course_id)
                .order_by(CourseMaterial.created_at, CourseMaterial.id)
            ).scalars()
        )

    def create(
        self,
        *,
        course_id: int,
        uploaded_by: int | None,
        title: str,
        file_path: str,
        file_type: str,
        file_size_bytes: int | None,
        content_hash: str,
        unverified_outcome_ref: str | None = None,
    ) -> CourseMaterial:
        material = CourseMaterial(
            course_id=course_id,
            uploaded_by=uploaded_by,
            title=title,
            file_path=file_path,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            content_hash=content_hash,
            unverified_outcome_ref=unverified_outcome_ref,
        )
        self._session.add(material)
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if is_unique_violation(error, MATERIAL_HASH_UNIQUE_CONSTRAINT):
                raise MaterialAlreadyExistsError(content_hash) from error
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("course or uploader") from error
            raise
        return material

    def update_processing_status(
        self,
        material_id: int,
        status: ProcessingStatus,
        *,
        error_message: str | None = None,
        extraction_report: str | None = None,
    ) -> CourseMaterial:
        status = ProcessingStatus(status)
        material = self._session.get(
            CourseMaterial, material_id, with_for_update=True
        )
        if material is None:
            self._session.rollback()
            raise MaterialNotFoundError(str(material_id))
        material.processing_status = status.value
        # An error message is only meaningful for failed processing.
        material.error_message = (
            error_message if status is ProcessingStatus.FAILED else None
        )
        if extraction_report is not None:
            material.extraction_report = extraction_report
        self._session.commit()
        return material

    def claim_for_processing(self, material_id: int) -> CourseMaterial:
        """Atomically transition a material from pending/failed to processing.

        Holds a row lock only for this state transition so concurrent workers
        cannot ingest the same material simultaneously, and already-processed
        materials are not silently re-indexed (which would cascade-delete
        existing `rag_query_citations`).
        """
        material = self._session.get(
            CourseMaterial, material_id, with_for_update=True
        )
        if material is None:
            self._session.rollback()
            raise MaterialNotFoundError(str(material_id))
        if material.processing_status == ProcessingStatus.PROCESSING.value:
            self._session.rollback()
            raise MaterialAlreadyProcessingError(str(material_id))
        if material.processing_status == ProcessingStatus.PROCESSED.value:
            self._session.rollback()
            raise MaterialAlreadyProcessedError(str(material_id))
        material.processing_status = ProcessingStatus.PROCESSING.value
        material.error_message = None
        self._session.commit()
        return material

    def delete(self, material_id: int) -> bool:
        material = self._session.get(CourseMaterial, material_id)
        if material is None:
            return False
        self._session.delete(material)
        self._session.commit()
        return True
