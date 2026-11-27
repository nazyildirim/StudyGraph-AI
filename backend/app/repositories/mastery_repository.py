"""MasteryRecord and StudyRecommendation persistence (Issue #7).

Transaction convention (caller-owned Unit-of-Work):
- Mutating methods flush within SAVEPOINTs and NEVER call `session.commit()`.
- Lock ordering (Tier 2): `acquire_student_course_lock(student_id, course_id)`
  uses PostgreSQL's 1-argument `pg_advisory_xact_lock(bigint)` with key
  `(student_id << 32) | course_id` (disjoint from 2-argument course locks) to
  serialize concurrent exam submissions and mastery updates for the same
  student and course, preventing lost updates on `total_attempts` and
  `study_recommendations`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.learning_outcome_record import LearningOutcomeRecord
from app.models.mastery_record import MasteryRecord
from app.models.question import Question
from app.models.student_assessment import StudentAssessment, StudentAssessmentStatus
from app.models.student_response import StudentResponse
from app.models.study_recommendation import RecommendationStatus, StudyRecommendation
from app.repositories.errors import (
    CrossCourseReferenceError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
)

_ALLOWED_REC_STATUSES = frozenset(item.value for item in RecommendationStatus)


def build_student_course_lock_key(*, student_id: int, course_id: int) -> int:
    """Deterministic collision-free 64-bit advisory lock key for (student, course)."""
    if student_id <= 0 or course_id <= 0:
        raise ValueError("student_id and course_id must be positive integers.")
    return (student_id << 32) | course_id


@dataclass(frozen=True, slots=True)
class MasteryUpdateDraft:
    """Re-evaluated mastery score for one learning outcome."""

    learning_outcome_id: int
    mastery_score: float


@dataclass(frozen=True, slots=True)
class StudyRecommendationDraft:
    """Persisted recommendation entry preserving engine status (incl. `blocked`)."""

    learning_outcome_id: int
    priority_order: int
    reason: str
    status: str


@dataclass(frozen=True, slots=True)
class LatestOutcomeResponse:
    """A student's response from their most recently completed attempt for an outcome."""

    question_id: int
    learning_outcome_id: int
    is_correct: bool
    student_assessment_id: int
    completed_at: datetime


class MasteryRepository(Protocol):
    """Repository contract for mastery records, recommendations, and latest results."""

    def acquire_student_course_lock(
        self, *, student_id: int, course_id: int
    ) -> None: ...

    def get_mastery_record(
        self, *, student_id: int, learning_outcome_id: int
    ) -> MasteryRecord | None: ...

    def list_mastery_for_student_course(
        self, *, student_id: int, course_id: int
    ) -> list[MasteryRecord]: ...

    def list_weak_outcome_ids(
        self, *, student_id: int, course_id: int, mastery_threshold: float
    ) -> list[int]: ...

    def list_unassessed_outcome_ids(
        self, *, student_id: int, course_id: int
    ) -> list[int]: ...

    def upsert_mastery_records(
        self,
        *,
        student_id: int,
        course_id: int,
        updates: Sequence[MasteryUpdateDraft],
        assessed_at: datetime | None = None,
    ) -> list[MasteryRecord]: ...

    def replace_recommendations_for_course(
        self,
        *,
        student_id: int,
        course_id: int,
        recommendations: Sequence[StudyRecommendationDraft],
    ) -> list[StudyRecommendation]: ...

    def list_recommendations_for_student_course(
        self, *, student_id: int, course_id: int
    ) -> list[StudyRecommendation]: ...

    def list_latest_completed_responses_by_outcome(
        self, *, student_id: int, course_id: int
    ) -> list[LatestOutcomeResponse]: ...


class SqlAlchemyMasteryRepository:
    """SQLAlchemy 2.0 implementation of MasteryRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def acquire_student_course_lock(
        self, *, student_id: int, course_id: int
    ) -> None:
        """Tier 2 lock: serialize concurrent submissions for (student_id, course_id)."""
        lock_key = build_student_course_lock_key(
            student_id=student_id, course_id=course_id
        )
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    def get_mastery_record(
        self, *, student_id: int, learning_outcome_id: int
    ) -> MasteryRecord | None:
        return self._session.execute(
            select(MasteryRecord).where(
                MasteryRecord.student_id == student_id,
                MasteryRecord.learning_outcome_id == learning_outcome_id,
            )
        ).scalar_one_or_none()

    def list_mastery_for_student_course(
        self, *, student_id: int, course_id: int
    ) -> list[MasteryRecord]:
        return list(
            self._session.execute(
                select(MasteryRecord)
                .join(
                    LearningOutcomeRecord,
                    LearningOutcomeRecord.id == MasteryRecord.learning_outcome_id,
                )
                .where(
                    MasteryRecord.student_id == student_id,
                    LearningOutcomeRecord.course_id == course_id,
                )
                .order_by(
                    LearningOutcomeRecord.order_index.asc(),
                    LearningOutcomeRecord.id.asc(),
                )
            ).scalars()
        )

    def list_weak_outcome_ids(
        self, *, student_id: int, course_id: int, mastery_threshold: float
    ) -> list[int]:
        """Return ONLY assessed outcomes whose mastery_score is below threshold.

        Unassessed outcomes (no row in `mastery_records`) are intentionally
        excluded; call `list_unassessed_outcome_ids` to query them separately.
        """
        if isinstance(mastery_threshold, bool) or not 0.0 <= mastery_threshold <= 100.0:
            raise ValueError("mastery_threshold must be between 0 and 100.")
        return list(
            self._session.execute(
                select(MasteryRecord.learning_outcome_id)
                .join(
                    LearningOutcomeRecord,
                    LearningOutcomeRecord.id == MasteryRecord.learning_outcome_id,
                )
                .where(
                    MasteryRecord.student_id == student_id,
                    LearningOutcomeRecord.course_id == course_id,
                    MasteryRecord.mastery_score < mastery_threshold,
                )
                .order_by(
                    MasteryRecord.mastery_score.asc(),
                    LearningOutcomeRecord.order_index.asc(),
                    LearningOutcomeRecord.id.asc(),
                )
            ).scalars()
        )

    def list_unassessed_outcome_ids(
        self, *, student_id: int, course_id: int
    ) -> list[int]:
        """Return course outcomes that have never been assessed for this student."""
        assessed_subquery = select(MasteryRecord.learning_outcome_id).where(
            MasteryRecord.student_id == student_id
        )
        return list(
            self._session.execute(
                select(LearningOutcomeRecord.id)
                .where(
                    LearningOutcomeRecord.course_id == course_id,
                    ~LearningOutcomeRecord.id.in_(assessed_subquery),
                )
                .order_by(
                    LearningOutcomeRecord.order_index.asc(),
                    LearningOutcomeRecord.id.asc(),
                )
            ).scalars()
        )

    def _assert_outcomes_in_course(
        self, *, course_id: int, outcome_ids: set[int]
    ) -> None:
        if not outcome_ids:
            return
        matched = set(
            self._session.execute(
                select(LearningOutcomeRecord.id).where(
                    LearningOutcomeRecord.course_id == course_id,
                    LearningOutcomeRecord.id.in_(outcome_ids),
                )
            ).scalars()
        )
        if matched != outcome_ids:
            raise CrossCourseReferenceError(
                "One or more learning outcomes do not belong to the specified course."
            )

    def upsert_mastery_records(
        self,
        *,
        student_id: int,
        course_id: int,
        updates: Sequence[MasteryUpdateDraft],
        assessed_at: datetime | None = None,
    ) -> list[MasteryRecord]:
        """Atomically upsert mastery scores for re-evaluated outcomes only.

        Increments `total_attempts` in SQL (`mastery_records.total_attempts + 1`)
        under the Tier 2 `(student_id, course_id)` advisory lock so concurrent
        submissions never lose an attempt increment, and outcomes NOT present in
        `updates` retain their existing score and `total_attempts`.
        """
        if not updates:
            return []

        seen_ids: set[int] = set()
        for item in updates:
            if item.learning_outcome_id in seen_ids:
                raise ValueError(
                    f"Duplicate learning_outcome_id in mastery updates: {item.learning_outcome_id}."
                )
            if isinstance(item.mastery_score, bool) or not 0.0 <= item.mastery_score <= 100.0:
                raise ValueError("mastery_score must be between 0 and 100.")
            seen_ids.add(item.learning_outcome_id)

        self.acquire_student_course_lock(student_id=student_id, course_id=course_id)
        self._assert_outcomes_in_course(course_id=course_id, outcome_ids=seen_ids)

        timestamp = assessed_at or datetime.now(timezone.utc)
        ordered_updates = sorted(updates, key=lambda item: item.learning_outcome_id)
        table = MasteryRecord.__table__

        try:
            with self._session.begin_nested():
                for item in ordered_updates:
                    stmt = pg_insert(table).values(
                        student_id=student_id,
                        learning_outcome_id=item.learning_outcome_id,
                        mastery_score=item.mastery_score,
                        total_attempts=1,
                        last_assessed_at=timestamp,
                        updated_at=timestamp,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["student_id", "learning_outcome_id"],
                        set_={
                            "mastery_score": stmt.excluded.mastery_score,
                            "total_attempts": table.c.total_attempts + 1,
                            "last_assessed_at": stmt.excluded.last_assessed_at,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    self._session.execute(stmt)
                self._session.flush()
        except IntegrityError as error:
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("student or learning outcome") from error
            raise

        # Expire cached instances so callers see SQL-incremented `total_attempts`.
        self._session.expire_all()
        return list(
            self._session.execute(
                select(MasteryRecord)
                .where(
                    MasteryRecord.student_id == student_id,
                    MasteryRecord.learning_outcome_id.in_(seen_ids),
                )
                .order_by(MasteryRecord.learning_outcome_id.asc())
            ).scalars()
        )

    def replace_recommendations_for_course(
        self,
        *,
        student_id: int,
        course_id: int,
        recommendations: Sequence[StudyRecommendationDraft],
    ) -> list[StudyRecommendation]:
        """Atomically replace a student's recommendations for one course.

        Preserves all RecommendationEngine statuses (`blocked`, `study`,
        `review`, `completed`) without affecting other courses.
        """
        seen_ids: set[int] = set()
        for item in recommendations:
            if item.learning_outcome_id in seen_ids:
                raise ValueError(
                    f"Duplicate learning_outcome_id in recommendations: {item.learning_outcome_id}."
                )
            if item.priority_order < 1:
                raise ValueError("priority_order must be >= 1.")
            if item.status not in _ALLOWED_REC_STATUSES:
                raise ValueError(f"Unsupported recommendation status: {item.status!r}.")
            if not item.reason or not item.reason.strip():
                raise ValueError("Recommendation reason cannot be empty.")
            seen_ids.add(item.learning_outcome_id)

        self.acquire_student_course_lock(student_id=student_id, course_id=course_id)
        self._assert_outcomes_in_course(course_id=course_id, outcome_ids=seen_ids)

        course_outcome_ids = select(LearningOutcomeRecord.id).where(
            LearningOutcomeRecord.course_id == course_id
        )
        rows = [
            StudyRecommendation(
                student_id=student_id,
                learning_outcome_id=item.learning_outcome_id,
                priority_order=item.priority_order,
                reason=item.reason.strip(),
                status=item.status,
            )
            for item in sorted(recommendations, key=lambda r: r.priority_order)
        ]
        try:
            with self._session.begin_nested():
                self._session.execute(
                    delete(StudyRecommendation).where(
                        StudyRecommendation.student_id == student_id,
                        StudyRecommendation.learning_outcome_id.in_(course_outcome_ids),
                    )
                )
                self._session.flush()
                self._session.add_all(rows)
                self._session.flush()
        except IntegrityError as error:
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("student or learning outcome") from error
            raise
        return rows

    def list_recommendations_for_student_course(
        self, *, student_id: int, course_id: int
    ) -> list[StudyRecommendation]:
        return list(
            self._session.execute(
                select(StudyRecommendation)
                .join(
                    LearningOutcomeRecord,
                    LearningOutcomeRecord.id == StudyRecommendation.learning_outcome_id,
                )
                .where(
                    StudyRecommendation.student_id == student_id,
                    LearningOutcomeRecord.course_id == course_id,
                )
                .order_by(
                    StudyRecommendation.priority_order.asc(),
                    StudyRecommendation.id.asc(),
                )
            ).scalars()
        )

    def list_latest_completed_responses_by_outcome(
        self, *, student_id: int, course_id: int
    ) -> list[LatestOutcomeResponse]:
        """Return responses from the latest completed attempt per learning outcome.

        For each outcome in `course_id` that `student_id` has completed at least
        once, selects all `StudentResponse` rows belonging to the single most
        recently completed `StudentAssessment` (`completed_at DESC, id DESC`).
        Guarantees unique `question_id` values ready for `ScoringEngine`.
        """
        ranked = (
            select(
                StudentResponse.question_id.label("question_id"),
                Question.learning_outcome_id.label("learning_outcome_id"),
                StudentResponse.is_correct.label("is_correct"),
                StudentResponse.student_assessment_id.label("student_assessment_id"),
                StudentAssessment.completed_at.label("completed_at"),
                func.dense_rank()
                .over(
                    partition_by=Question.learning_outcome_id,
                    order_by=(
                        StudentAssessment.completed_at.desc(),
                        StudentAssessment.id.desc(),
                    ),
                )
                .label("attempt_rank"),
            )
            .select_from(StudentResponse)
            .join(
                StudentAssessment,
                StudentAssessment.id == StudentResponse.student_assessment_id,
            )
            .join(Assessment, Assessment.id == StudentAssessment.assessment_id)
            .join(Question, Question.id == StudentResponse.question_id)
            .where(
                StudentAssessment.student_id == student_id,
                Assessment.course_id == course_id,
                StudentAssessment.status == StudentAssessmentStatus.COMPLETED.value,
            )
            .subquery()
        )

        rows = self._session.execute(
            select(
                ranked.c.question_id,
                ranked.c.learning_outcome_id,
                ranked.c.is_correct,
                ranked.c.student_assessment_id,
                ranked.c.completed_at,
            )
            .where(ranked.c.attempt_rank == 1)
            .order_by(
                ranked.c.learning_outcome_id.asc(),
                ranked.c.question_id.asc(),
            )
        ).all()

        return [
            LatestOutcomeResponse(
                question_id=row.question_id,
                learning_outcome_id=row.learning_outcome_id,
                is_correct=row.is_correct,
                student_assessment_id=row.student_assessment_id,
                completed_at=row.completed_at,
            )
            for row in rows
        ]
