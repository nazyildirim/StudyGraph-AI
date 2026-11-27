"""Repository-level errors shared by course and RAG repositories.

Services translate these into domain/HTTP errors; repositories never raise
raw SQLAlchemy `IntegrityError` for expected business conflicts.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

_PG_UNIQUE_VIOLATION = "23505"
_PG_FOREIGN_KEY_VIOLATION = "23503"


class CourseCodeAlreadyExistsError(Exception):
    """A course with the same code already exists."""


class EnrollmentAlreadyExistsError(Exception):
    """The student is already enrolled in the course."""


class MaterialAlreadyExistsError(Exception):
    """The same content was already uploaded to the course."""


class MaterialNotFoundError(Exception):
    """The target course material does not exist."""


class MaterialAlreadyProcessingError(Exception):
    """Another ingestion worker is already processing this material."""


class MaterialAlreadyProcessedError(Exception):
    """The material is already processed; silent re-indexing is disabled in MVP."""


class RelatedRecordNotFoundError(Exception):
    """A referenced record (user, course, material) does not exist."""


class InvalidCitationError(Exception):
    """A citation does not point to a chunk of the query's own course."""


class LearningOutcomeCodeAlreadyExistsError(Exception):
    """A learning outcome with the same code already exists in the course."""


class PrerequisiteAlreadyExistsError(Exception):
    """The directed prerequisite edge already exists."""


class CyclicPrerequisiteError(Exception):
    """Adding the prerequisite edge would create a self-loop or cycle."""


class CrossCourseReferenceError(Exception):
    """A referenced outcome, question, or option belongs to another course."""


class QuestionNotFoundError(Exception):
    """The target question does not exist in the specified course."""


class QuestionArchivedError(Exception):
    """The target question is archived and cannot be modified or assigned."""


class InvalidQuestionOptionsError(Exception):
    """Question options violate count, uniqueness, or single-correct-answer rules."""


class AssessmentNotFoundError(Exception):
    """The target assessment does not exist in the specified course."""


class AttemptNotFoundError(Exception):
    """The target student assessment attempt does not exist for this student."""


class AttemptAlreadyFinalizedError(Exception):
    """The student assessment attempt is already completed or abandoned."""


class InvalidResponseError(Exception):
    """A student response references an unassigned question or mismatched option."""


class DuplicateResponseError(Exception):
    """A response for the same question already exists in this attempt."""


class PaginationValidationError(Exception):
    """Pagination parameters (`limit` or `offset`) are out of valid bounds."""


def integrity_sqlstate(error: IntegrityError) -> str | None:
    """Return the PostgreSQL SQLSTATE of an IntegrityError, if available."""
    return getattr(getattr(error, "orig", None), "sqlstate", None)


def constraint_name(error: IntegrityError) -> str | None:
    """Return the violated constraint name reported by PostgreSQL."""
    diag = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def is_unique_violation(error: IntegrityError, name: str) -> bool:
    return integrity_sqlstate(error) == _PG_UNIQUE_VIOLATION and (
        constraint_name(error) == name
    )


def is_foreign_key_violation(error: IntegrityError) -> bool:
    return integrity_sqlstate(error) == _PG_FOREIGN_KEY_VIOLATION
