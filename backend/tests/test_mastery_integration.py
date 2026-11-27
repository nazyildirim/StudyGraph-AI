"""Stateless unit tests for MasteryIntegrationAdapter using real LearningAnalysisService."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.repositories.mastery_repository import (
    LatestOutcomeResponse,
    MasteryUpdateDraft,
    StudyRecommendationDraft,
)
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter


class _FakeOutcomeRepo:
    def __init__(
        self,
        outcomes: list[SimpleNamespace],
        prerequisites: list[SimpleNamespace],
    ) -> None:
        self._outcomes = outcomes
        self._prerequisites = prerequisites

    def list_by_course(self, course_id: int) -> list[SimpleNamespace]:
        return [o for o in self._outcomes if o.course_id == course_id]

    def list_prerequisites_by_course(self, course_id: int) -> list[SimpleNamespace]:
        return [p for p in self._prerequisites if p.course_id == course_id]


class _FakeMasteryRepo:
    def __init__(self, responses: list[LatestOutcomeResponse]) -> None:
        self._responses = responses
        self.upserted: list[MasteryUpdateDraft] = []
        self.replaced_recs: list[StudyRecommendationDraft] = []

    def list_latest_completed_responses_by_outcome(
        self, *, student_id: int, course_id: int
    ) -> list[LatestOutcomeResponse]:
        return list(self._responses)

    def upsert_mastery_records(
        self,
        *,
        student_id: int,
        course_id: int,
        updates: Sequence[MasteryUpdateDraft],
        assessed_at: datetime | None = None,
    ) -> list[SimpleNamespace]:
        self.upserted = list(updates)
        return []

    def replace_recommendations_for_course(
        self,
        *,
        student_id: int,
        course_id: int,
        recommendations: Sequence[StudyRecommendationDraft],
    ) -> list[SimpleNamespace]:
        self.replaced_recs = list(recommendations)
        return []


def test_adapter_uses_real_learning_analysis_preserves_blocked_study_and_selective_upsert() -> None:
    now = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)
    # Graph: 10 -> 20 -> 30, and 10 -> 40
    outcomes = [
        SimpleNamespace(id=10, course_id=1, code="LO-1", title="Basics", description=""),
        SimpleNamespace(id=20, course_id=1, code="LO-2", title="Loops", description=""),
        SimpleNamespace(id=30, course_id=1, code="LO-3", title="Sorting", description=""),
        SimpleNamespace(id=40, course_id=1, code="LO-4", title="Arrays", description=""),
    ]
    prerequisites = [
        SimpleNamespace(course_id=1, prerequisite_outcome_id=10, dependent_outcome_id=20),
        SimpleNamespace(course_id=1, prerequisite_outcome_id=20, dependent_outcome_id=30),
        SimpleNamespace(course_id=1, prerequisite_outcome_id=10, dependent_outcome_id=40),
    ]
    # Latest completed responses: LO-1 = 100%, LO-2 = 50% (1/2), LO-3 = 0% (0/1), LO-4 unassessed
    responses = [
        LatestOutcomeResponse(101, 10, True, 1, now),
        LatestOutcomeResponse(201, 20, True, 2, now),
        LatestOutcomeResponse(202, 20, False, 2, now),
        LatestOutcomeResponse(301, 30, False, 1, now),
    ]
    mastery_repo = _FakeMasteryRepo(responses)
    adapter = MasteryIntegrationAdapter(
        learning_analysis_service=LearningAnalysisService(),
        learning_outcome_repository=_FakeOutcomeRepo(outcomes, prerequisites),  # type: ignore[arg-type]
        mastery_repository=mastery_repo,  # type: ignore[arg-type]
        settings=Settings(_env_file=None),
    )

    # Suppose ONLY LO-2 (20) was re-evaluated in this exam attempt
    summary = adapter.integrate_exam_submission(
        student_id=7,
        course_id=1,
        evaluated_outcome_ids={20},
        assessed_at=now,
    )

    assert summary.mastery_threshold == 70.0
    # Topological order: 10 before 20 and 40; 20 before 30
    assert summary.learning_order.index(10) < summary.learning_order.index(20)
    assert summary.learning_order.index(20) < summary.learning_order.index(30)
    assert summary.learning_order.index(10) < summary.learning_order.index(40)

    # Weak vs unassessed strictly separated (LO-4 is unassessed, NOT weak!)
    assert set(summary.weak_outcome_ids) == {20, 30}
    assert summary.unassessed_outcome_ids == [40]
    assert summary.blocked_outcome_ids == [30]

    # Exact statuses preserved: 10=completed, 20=review, 30=blocked (missing 20), 40=study
    rec_by_oid = {r.learning_outcome_id: r for r in summary.recommendations}
    assert rec_by_oid[10].status == "completed"
    assert rec_by_oid[20].status == "review"
    assert rec_by_oid[30].status == "blocked"
    assert rec_by_oid[30].missing_prerequisites == [20]
    assert rec_by_oid[40].status == "study"
    assert rec_by_oid[40].score_percent is None

    # Selective mastery upsert: ONLY evaluated outcome (20) updated!
    assert mastery_repo.upserted == [
        MasteryUpdateDraft(learning_outcome_id=20, mastery_score=50.0)
    ]
    # Persisted recommendations keep exact statuses including blocked & study
    persisted_by_oid = {r.learning_outcome_id: r.status for r in mastery_repo.replaced_recs}
    assert persisted_by_oid == {10: "completed", 20: "review", 30: "blocked", 40: "study"}


def test_adapter_rejects_empty_outcomes_or_empty_responses() -> None:
    now = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)
    adapter = MasteryIntegrationAdapter(
        learning_analysis_service=LearningAnalysisService(),
        learning_outcome_repository=_FakeOutcomeRepo([], []),  # type: ignore[arg-type]
        mastery_repository=_FakeMasteryRepo([]),  # type: ignore[arg-type]
        settings=Settings(_env_file=None),
    )
    with pytest.raises(ValueError):
        adapter.integrate_exam_submission(
            student_id=1, course_id=1, evaluated_outcome_ids={10}, assessed_at=now
        )
