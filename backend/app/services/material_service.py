"""Application service for course material CRUD, secure upload, and ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
)
from app.models.course_material import CourseMaterial
from app.models.user import User
from app.repositories.course_material_repository import CourseMaterialRepository
from app.services.material_ingestion_service import (
    MaterialIngestionError,
    MaterialIngestionService,
)
from app.storage.local_storage import FileStorage, InvalidUploadError


class MaterialService:
    """Coordinates authorization, secure storage, DB persistence, and ingestion.

    Shared by both canonical `/api/v1` and unprefixed frontend compatibility
    endpoints so no business logic or security check is duplicated.
    """

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        material_repository: CourseMaterialRepository,
        file_storage: FileStorage,
        ingestion_service: MaterialIngestionService,
    ) -> None:
        self._access = access_policy
        self._materials = material_repository
        self._storage = file_storage
        self._ingestion = ingestion_service

    def list_materials(self, *, user: User, course_id: int) -> list[CourseMaterial]:
        self._access.check_read_access(user, course_id)
        return self._materials.list_by_course(course_id)

    def get_material(
        self,
        *,
        user: User,
        course_id: int,
        material_id: int,
    ) -> CourseMaterial:
        self._access.check_read_access(user, course_id)
        material = self._materials.get_by_id(material_id)
        if material is None or material.course_id != course_id:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        return material

    def create_text_material(
        self,
        *,
        user: User,
        course_id: int,
        title: str,
        text: str,
        page: int | None = None,
        outcome_ref: str | None = None,
    ) -> CourseMaterial:
        # 1. Authorize BEFORE writing any file or running ingestion.
        self._access.check_manage_access(user, course_id)
        if page is not None and page < 1:
            raise InvalidUploadError("Page number must be >= 1.")

        raw_bytes = text.encode("utf-8")
        stored = self._storage.save_text_bytes(raw_bytes)
        try:
            material = self._materials.create(
                course_id=course_id,
                uploaded_by=user.id,
                title=title.strip(),
                file_path=stored.stored_path,
                file_type=stored.file_type,
                file_size_bytes=stored.file_size_bytes,
                content_hash=stored.content_hash,
                unverified_outcome_ref=outcome_ref,
            )
        except Exception:
            # Compensating cleanup: remove orphan file if DB insert fails (e.g. duplicate).
            self._storage.delete(stored.stored_path)
            raise

        try:
            self._ingestion.ingest(
                material.id,
                source=raw_bytes,
                user_reported_page=page,
            )
        except MaterialIngestionError:
            # Material row already marked `failed` with sanitized message; clean up file.
            self._storage.delete(stored.stored_path)
            refreshed = self._materials.get_by_id(material.id)
            if refreshed is not None:
                return refreshed
            raise

        refreshed = self._materials.get_by_id(material.id)
        return refreshed if refreshed is not None else material

    def upload_file_material(
        self,
        *,
        user: User,
        course_id: int,
        filename: str | None,
        content_type: str | None,
        stream: BinaryIO,
        title: str | None = None,
        outcome_ref: str | None = None,
    ) -> CourseMaterial:
        # 1. Authorize BEFORE reading or storing the upload stream.
        self._access.check_manage_access(user, course_id)

        stored = self._storage.save_stream(
            stream=stream,
            filename=filename,
            content_type=content_type,
        )
        resolved_title = (title or "").strip()
        if not resolved_title:
            resolved_title = Path(filename or "material").stem[:255] or "Untitled"
        if not resolved_title.strip():
            self._storage.delete(stored.stored_path)
            raise InvalidUploadError("Material title must not be blank.")

        try:
            material = self._materials.create(
                course_id=course_id,
                uploaded_by=user.id,
                title=resolved_title,
                file_path=stored.stored_path,
                file_type=stored.file_type,
                file_size_bytes=stored.file_size_bytes,
                content_hash=stored.content_hash,
                unverified_outcome_ref=outcome_ref,
            )
        except Exception:
            # Compensating cleanup: never leave orphan files on DB errors.
            self._storage.delete(stored.stored_path)
            raise

        try:
            self._ingestion.ingest(material.id, source=Path(stored.stored_path))
        except MaterialIngestionError:
            self._storage.delete(stored.stored_path)
            refreshed = self._materials.get_by_id(material.id)
            if refreshed is not None:
                return refreshed
            raise

        refreshed = self._materials.get_by_id(material.id)
        return refreshed if refreshed is not None else material

    def delete_material(
        self,
        *,
        user: User,
        course_id: int,
        material_id: int,
    ) -> None:
        self._access.check_manage_access(user, course_id)
        material = self._materials.get_by_id(material_id)
        if material is None or material.course_id != course_id:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        stored_path = material.file_path
        deleted = self._materials.delete(material_id)
        if not deleted:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        self._storage.delete(stored_path)
