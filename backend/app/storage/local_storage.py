"""Secure local file storage for uploaded course materials (Issue #8)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import BinaryIO, Protocol
import uuid

_PDF_MAGIC = b"%PDF-"
_CHUNK_READ_BYTES = 64 * 1024

_ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt"})
_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}
_ALLOWED_MIMES = frozenset({"application/pdf", "text/plain"})


class StorageError(Exception):
    """Base error for file storage operations."""


class FileTooLargeError(StorageError):
    """Raised when an upload exceeds the configured byte limit (HTTP 413)."""


class UnsupportedMediaTypeError(StorageError):
    """Raised when file extension, MIME type, or content signature is unsupported (HTTP 415)."""


class InvalidUploadError(StorageError):
    """Raised on path traversal attempts, empty files, or corrupt encoding (HTTP 422)."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Metadata for a file saved safely under the server upload root."""

    stored_path: str
    file_type: str
    file_size_bytes: int
    content_hash: str


class FileStorage(Protocol):
    """Contract for storing and deleting uploaded course materials."""

    def save_stream(
        self,
        *,
        stream: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> StoredFile: ...

    def save_text_bytes(self, content: bytes) -> StoredFile: ...

    def delete(self, stored_path: str) -> None: ...


class LocalFileStorage:
    """Stores validated uploads under a private directory using UUID filenames.

    Security controls (K56):
    - Never uses client filenames in storage paths (UUID-only filenames).
    - Rejects path traversal patterns (`..`, `/`, `\\`, NUL) in client filenames.
    - Enforces byte size limit while streaming (never reads unbounded uploads).
    - Validates extension, declared MIME, and actual magic bytes / UTF-8 encoding.
    - Cleans up temporary files automatically on any error.
    - `delete()` verifies the resolved path stays strictly inside `base_dir`.
    """

    def __init__(
        self,
        base_dir: Path | str,
        *,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be > 0.")
        self._base_dir = Path(base_dir).resolve()
        self._max_bytes = max_bytes

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def save_stream(
        self,
        *,
        stream: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> StoredFile:
        ext, canonical_mime = _validate_filename_and_mime(filename, content_type)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        target = (self._base_dir / f"{uuid.uuid4().hex}{ext}").resolve()
        _ensure_within(target, self._base_dir)

        hasher = hashlib.sha256()
        total_bytes = 0
        head_sample = bytearray()

        try:
            with target.open("wb") as out:
                while True:
                    chunk = stream.read(_CHUNK_READ_BYTES)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > self._max_bytes:
                        raise FileTooLargeError(
                            f"Uploaded file exceeds maximum allowed size of {self._max_bytes} bytes."
                        )
                    if len(head_sample) < 16:
                        head_sample.extend(chunk[: 16 - len(head_sample)])
                    hasher.update(chunk)
                    out.write(chunk)

            if total_bytes == 0:
                raise InvalidUploadError("Uploaded file is empty.")

            if canonical_mime == "application/pdf":
                if not bytes(head_sample).lstrip().startswith(_PDF_MAGIC):
                    raise UnsupportedMediaTypeError(
                        "File does not have a valid PDF signature."
                    )
            else:
                raw_text = target.read_bytes()
                if b"\x00" in raw_text:
                    raise UnsupportedMediaTypeError(
                        "Text upload contains binary NUL bytes."
                    )
                try:
                    decoded = raw_text.decode("utf-8-sig")
                except UnicodeDecodeError as error:
                    raise InvalidUploadError(
                        "Text upload must be valid UTF-8."
                    ) from error
                if not decoded.strip():
                    raise InvalidUploadError("Text upload contains only whitespace.")
        except Exception:
            self._safe_unlink(target)
            raise

        return StoredFile(
            stored_path=str(target),
            file_type=canonical_mime,
            file_size_bytes=total_bytes,
            content_hash=hasher.hexdigest(),
        )

    def save_text_bytes(self, content: bytes) -> StoredFile:
        if not content:
            raise InvalidUploadError("Material text must not be empty.")
        if len(content) > self._max_bytes:
            raise FileTooLargeError(
                f"Material text exceeds maximum allowed size of {self._max_bytes} bytes."
            )
        if b"\x00" in content:
            raise InvalidUploadError("Material text must not contain NUL bytes.")
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise InvalidUploadError("Material text must be valid UTF-8.") from error
        if not decoded.strip():
            raise InvalidUploadError("Material text must not be blank.")

        self._base_dir.mkdir(parents=True, exist_ok=True)
        target = (self._base_dir / f"{uuid.uuid4().hex}.txt").resolve()
        _ensure_within(target, self._base_dir)
        try:
            target.write_bytes(content)
        except Exception:
            self._safe_unlink(target)
            raise

        return StoredFile(
            stored_path=str(target),
            file_type="text/plain",
            file_size_bytes=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )

    def delete(self, stored_path: str) -> None:
        if not stored_path:
            return
        candidate = Path(stored_path).resolve()
        if not _is_within(candidate, self._base_dir):
            return
        self._safe_unlink(candidate)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_filename_and_mime(
    filename: str | None,
    content_type: str | None,
) -> tuple[str, str]:
    if not filename or not filename.strip():
        raise InvalidUploadError("Filename is required.")
    raw_name = filename.strip()
    if "\x00" in raw_name or "/" in raw_name or "\\" in raw_name or ".." in raw_name:
        raise InvalidUploadError("Invalid filename.")

    ext = Path(raw_name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise UnsupportedMediaTypeError(
            f"Unsupported file extension {ext!r}. Allowed: .pdf, .txt."
        )
    expected_mime = _EXT_TO_MIME[ext]

    if content_type:
        declared = content_type.split(";", 1)[0].strip().lower()
        if declared and declared not in ("application/octet-stream", expected_mime):
            if declared not in _ALLOWED_MIMES or declared != expected_mime:
                raise UnsupportedMediaTypeError(
                    f"Declared MIME type {declared!r} does not match extension {ext!r}."
                )
    return ext, expected_mime


def _is_within(target: Path, base_dir: Path) -> bool:
    try:
        target.relative_to(base_dir)
        return True
    except ValueError:
        return False


def _ensure_within(target: Path, base_dir: Path) -> None:
    if not _is_within(target, base_dir):
        raise InvalidUploadError("Resolved storage path escapes upload root.")
