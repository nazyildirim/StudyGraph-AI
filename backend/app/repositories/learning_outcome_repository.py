"""LearningOutcomeRecord and Prerequisite persistence (Issue #7 shared layer).

Transaction convention (caller-owned Unit-of-Work):
- Read methods never mutate or commit.
- Mutating methods flush within a SAVEPOINT (`begin_nested`) so domain errors
  never poison an outer transaction, and NEVER call `session.commit()`.
- Lock ordering (Tier 1): `add_prerequisite` acquires a course-scoped
  transaction advisory lock `pg_advisory_xact_lock(1001, course_id)` so
  concurrent prerequisite inserts in the same course cannot jointly create a
  cycle. Cycle detection delegates directly to `app.domain.graph_engine.GraphEngine`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.graph_engine import GraphEngine
from app.domain.learning_outcome import LearningOutcome as DomainLearningOutcome
from app.models.learning_outcome_record import LearningOutcomeRecord
from app.models.prerequisite import Prerequisite
from app.repositories.errors import (
    CrossCourseReferenceError,
    CyclicPrerequisiteError,
    LearningOutcomeCodeAlreadyExistsError,
    PrerequisiteAlreadyExistsError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
    is_unique_violation,
)

COURSE_GRAPH_LOCK_NAMESPACE = 1001
OUTCOME_CODE_UNIQUE_CONSTRAINT = "uq_learning_outcomes_course_id_code"
PREREQUISITE_EDGE_UNIQUE_CONSTRAINT = "uq_prerequisites_prerequisite_dependent"


class LearningOutcomeRepository(Protocol):
    """Repository contract for persisted learning outcomes and prerequisites."""

    def create_outcome(
        self,
        *,
        course_id: int,
        code: str,
        title: str,
        description: str | None = None,
        order_index: int = 0,
    ) -> LearningOutcomeRecord: ...

    def get_by_id(self, outcome_id: int) -> LearningOutcomeRecord | None: ...

    def get_by_id_for_course(
        self, outcome_id: int, course_id: int
    ) -> LearningOutcomeRecord | None: ...

    def list_by_course(self, course_id: int) -> list[LearningOutcomeRecord]: ...

    def verify_outcomes_belong_to_course(
        self, course_id: int, outcome_ids: Sequence[int]
    ) -> bool: ...

    def list_prerequisites_by_course(self, course_id: int) -> list[Prerequisite]: ...

    def add_prerequisite(
        self,
        *,
        course_id: int,
        prerequisite_outcome_id: int,
        dependent_outcome_id: int,
    ) -> Prerequisite: ...


class SqlAlchemyLearningOutcomeRepository:
    """SQLAlchemy 2.0 implementation of LearningOutcomeRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_outcome(
        self,
        *,
        course_id: int,
        code: str,
        title: str,
        description: str | None = None,
        order_index: int = 0,
    ) -> LearningOutcomeRecord:
        if order_index < 0:
            raise ValueError("order_index must be non-negative.")

        record = LearningOutcomeRecord(
            course_id=course_id,
            code=code.strip(),
            title=title.strip(),
            description=description,
            order_index=order_index,
        )
        try:
            with self._session.begin_nested():
                self._session.add(record)
                self._session.flush()
        except IntegrityError as error:
            if is_unique_violation(error, OUTCOME_CODE_UNIQUE_CONSTRAINT):
                raise LearningOutcomeCodeAlreadyExistsError(code) from error
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("course") from error
            raise
        return record

    def get_by_id(self, outcome_id: int) -> LearningOutcomeRecord | None:
        return self._session.get(LearningOutcomeRecord, outcome_id)

    def get_by_id_for_course(
        self, outcome_id: int, course_id: int
    ) -> LearningOutcomeRecord | None:
        return self._session.execute(
            select(LearningOutcomeRecord).where(
                LearningOutcomeRecord.id == outcome_id,
                LearningOutcomeRecord.course_id == course_id,
            )
        ).scalar_one_or_none()

    def list_by_course(self, course_id: int) -> list[LearningOutcomeRecord]:
        return list(
            self._session.execute(
                select(LearningOutcomeRecord)
                .where(LearningOutcomeRecord.course_id == course_id)
                .order_by(
                    LearningOutcomeRecord.order_index.asc(),
                    LearningOutcomeRecord.id.asc(),
                )
            ).scalars()
        )

    def verify_outcomes_belong_to_course(
        self, course_id: int, outcome_ids: Sequence[int]
    ) -> bool:
        unique_ids = set(outcome_ids)
        if not unique_ids:
            return True
        matched_ids = set(
            self._session.execute(
                select(LearningOutcomeRecord.id).where(
                    LearningOutcomeRecord.course_id == course_id,
                    LearningOutcomeRecord.id.in_(unique_ids),
                )
            ).scalars()
        )
        return matched_ids == unique_ids

    def list_prerequisites_by_course(self, course_id: int) -> list[Prerequisite]:
        return list(
            self._session.execute(
                select(Prerequisite)
                .where(Prerequisite.course_id == course_id)
                .order_by(Prerequisite.id.asc())
            ).scalars()
        )

    def _acquire_course_graph_lock(self, course_id: int) -> None:
        """Tier 1 lock: serialize prerequisite graph mutations per course."""
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :course_id)"),
            {"ns": COURSE_GRAPH_LOCK_NAMESPACE, "course_id": course_id},
        )

    def add_prerequisite(
        self,
        *,
        course_id: int,
        prerequisite_outcome_id: int,
        dependent_outcome_id: int,
    ) -> Prerequisite:
        if prerequisite_outcome_id == dependent_outcome_id:
            raise CyclicPrerequisiteError(
                "A learning outcome cannot be a prerequisite of itself."
            )

        self._acquire_course_graph_lock(course_id)

        outcomes = self.list_by_course(course_id)
        outcome_ids = {item.id for item in outcomes}
        if (
            prerequisite_outcome_id not in outcome_ids
            or dependent_outcome_id not in outcome_ids
        ):
            raise CrossCourseReferenceError(
                "Both outcomes must belong to the specified course."
            )

        existing_edges = self.list_prerequisites_by_course(course_id)
        for edge in existing_edges:
            if (
                edge.prerequisite_outcome_id == prerequisite_outcome_id
                and edge.dependent_outcome_id == dependent_outcome_id
            ):
                raise PrerequisiteAlreadyExistsError(
                    f"{prerequisite_outcome_id} -> {dependent_outcome_id}"
                )

        # Delegate DAG cycle detection directly to the existing GraphEngine.
        graph = GraphEngine()
        course_key = str(course_id)
        for outcome in outcomes:
            graph.add_outcome(
                DomainLearningOutcome(
                    id=str(outcome.id),
                    course_id=course_key,
                    title=outcome.title,
                    description=outcome.description or "",
                )
            )
        for edge in existing_edges:
            graph.add_prerequisite(
                str(edge.dependent_outcome_id),
                str(edge.prerequisite_outcome_id),
            )
        try:
            graph.add_prerequisite(
                str(dependent_outcome_id),
                str(prerequisite_outcome_id),
            )
        except ValueError as error:
            raise CyclicPrerequisiteError(str(error)) from error

        record = Prerequisite(
            course_id=course_id,
            prerequisite_outcome_id=prerequisite_outcome_id,
            dependent_outcome_id=dependent_outcome_id,
        )
        try:
            with self._session.begin_nested():
                self._session.add(record)
                self._session.flush()
        except IntegrityError as error:
            if is_unique_violation(error, PREREQUISITE_EDGE_UNIQUE_CONSTRAINT):
                raise PrerequisiteAlreadyExistsError(
                    f"{prerequisite_outcome_id} -> {dependent_outcome_id}"
                ) from error
            if is_foreign_key_violation(error):
                raise CrossCourseReferenceError(
                    "Outcomes must belong to the same course."
                ) from error
            raise
        return record
