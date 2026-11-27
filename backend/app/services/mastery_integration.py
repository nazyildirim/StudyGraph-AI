"""Adapter integrating Issue #7 exam submissions with Issue #5 LearningAnalysisService.

Architectural principles:
- Adapter Pattern & DIP: Translates persisted PostgreSQL models into the exact
  in-memory domain objects required by `LearningAnalysisService.analyze(...)`
  without modifying any Issue #4/#5 domain or service code and without HTTP
  loopback calls.
- Transaction participation: Executes inside the caller's active transaction
  (never commits independently) so any failure rolls back responses, attempt
  status, mastery records, and recommendations atomically.
- Selective mastery updates: Only outcomes actually evaluated in the just-
  submitted exam have their `MasteryRecord` upserted (`total_attempts + 1`);
  other outcomes retain their existing scores/attempts, and unassessed outcomes
  never receive synthetic 0% records.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.config import Settings, get_settings
from app.domain.graph_engine import GraphEngine
from app.domain.learning_outcome import LearningOutcome as DomainLearningOutcome
from app.domain.recommendation_engine import RecommendationEngine
from app.domain.scoring_engine import OutcomeScore, QuestionResult
from app.models.learning_outcome_record import LearningOutcomeRecord
from app.models.prerequisite import Prerequisite
from app.repositories.learning_outcome_repository import LearningOutcomeRepository
from app.repositories.mastery_repository import (
    MasteryRepository,
    MasteryUpdateDraft,
    StudyRecommendationDraft,
)
from app.schemas.exam import (
    ExamMasterySummaryResponse,
    MasteryRecommendationResponse,
    OutcomeMasteryScoreResponse,
)
from app.services.learning_analysis_service import LearningAnalysisService


@dataclass(frozen=True, slots=True)
class LiveRecommendationItem:
    """Read-only live recommendation projection derived from the current course graph."""

    learning_outcome_id: int
    status: str
    score_percent: float | None
    priority_order: int
    missing_prerequisites: tuple[int, ...]
    reason: str


def compute_live_recommendations(
    *,
    student_id: int,
    course_id: int,
    outcomes: Sequence[LearningOutcomeRecord],
    prerequisites: Sequence[Prerequisite],
    mastery_repository: MasteryRepository,
    mastery_threshold: float,
    learning_analysis_service: LearningAnalysisService | None = None,
) -> list[LiveRecommendationItem]:
    """Compute read-only recommendations against the CURRENT prerequisite graph.

    Never writes to `mastery_records` or `study_recommendations`. Shared by both
    `MasteryQueryService.get_student_recommendations` and
    `ExamGenerationService.start_retest_exam` so recommendation status,
    `missing_prerequisites`, and retest eligibility stay 100% consistent even
    after the course prerequisite graph is modified.
    """
    if not outcomes:
        return []

    course_key = str(course_id)
    domain_outcomes = [
        DomainLearningOutcome(
            id=str(lo.id),
            course_id=course_key,
            title=lo.title,
            description=lo.description or "",
        )
        for lo in outcomes
    ]
    prerequisite_edges = [
        (str(edge.dependent_outcome_id), str(edge.prerequisite_outcome_id))
        for edge in prerequisites
    ]
    outcome_code_by_id = {lo.id: lo.code for lo in outcomes}

    latest_responses = mastery_repository.list_latest_completed_responses_by_outcome(
        student_id=student_id,
        course_id=course_id,
    )
    if latest_responses:
        analysis_svc = learning_analysis_service or LearningAnalysisService()
        question_results = [
            QuestionResult(
                question_id=str(resp.question_id),
                outcome_id=str(resp.learning_outcome_id),
                is_correct=resp.is_correct,
            )
            for resp in latest_responses
        ]
        analysis = analysis_svc.analyze(
            course_id=course_key,
            outcomes=domain_outcomes,
            prerequisite_edges=prerequisite_edges,
            question_results=question_results,
            mastery_threshold=mastery_threshold,
        )
        raw_recs = analysis.recommendations
    else:
        mastery_records = mastery_repository.list_mastery_for_student_course(
            student_id=student_id,
            course_id=course_id,
        )
        if not mastery_records:
            return []
        graph = GraphEngine()
        for item in domain_outcomes:
            graph.add_outcome(item)
        for dep_id, prereq_id in prerequisite_edges:
            graph.add_prerequisite(dep_id, prereq_id)
        scores = [
            OutcomeScore(
                outcome_id=str(rec.learning_outcome_id),
                correct_count=0,
                question_count=1,
                score_percent=rec.mastery_score,
            )
            for rec in mastery_records
        ]
        raw_recs = tuple(
            RecommendationEngine(
                graph=graph, mastery_threshold=mastery_threshold
            ).generate(course_id=course_key, scores=scores)
        )

    items: list[LiveRecommendationItem] = []
    for priority, rec in enumerate(raw_recs, start=1):
        oid = int(rec.outcome_id)
        missing_ids = [int(pid) for pid in rec.missing_prerequisites]
        reason = _format_recommendation_reason(
            status=rec.status,
            missing_prerequisite_ids=missing_ids,
            outcome_code_by_id=outcome_code_by_id,
        )
        items.append(
            LiveRecommendationItem(
                learning_outcome_id=oid,
                status=rec.status,
                score_percent=rec.score_percent,
                priority_order=priority,
                missing_prerequisites=tuple(missing_ids),
                reason=reason,
            )
        )
    return items


class MasteryIntegrator(Protocol):
    """Contract for integrating graded exam submissions with mastery analytics."""

    def integrate_exam_submission(
        self,
        *,
        student_id: int,
        course_id: int,
        evaluated_outcome_ids: set[int],
        assessed_at: datetime,
    ) -> ExamMasterySummaryResponse: ...


def _format_recommendation_reason(
    *,
    status: str,
    missing_prerequisite_ids: list[int],
    outcome_code_by_id: dict[int, str],
) -> str:
    if status == "completed":
        return "Basari esigine ulasildi."
    if status == "review":
        return "Basari puani esigin altinda; tekrar calisilmasi onerilir."
    if status == "study":
        return "On kosullar tamamlandi; calismaya hazir."
    if status == "blocked":
        labels = [
            outcome_code_by_id.get(pid, str(pid)) for pid in missing_prerequisite_ids
        ]
        if labels:
            return f"Eksik on kosullar tamamlanmali: {', '.join(labels)}."
        return "Eksik on kosullar tamamlanmali."
    return f"Durum: {status}."


class MasteryIntegrationAdapter:
    """Bridges persisted exam responses to the real `LearningAnalysisService`."""

    def __init__(
        self,
        *,
        learning_analysis_service: LearningAnalysisService,
        learning_outcome_repository: LearningOutcomeRepository,
        mastery_repository: MasteryRepository,
        settings: Settings | None = None,
    ) -> None:
        self._analysis = learning_analysis_service
        self._outcomes = learning_outcome_repository
        self._mastery = mastery_repository
        self._settings = settings if settings is not None else get_settings()

    def integrate_exam_submission(
        self,
        *,
        student_id: int,
        course_id: int,
        evaluated_outcome_ids: set[int],
        assessed_at: datetime,
    ) -> ExamMasterySummaryResponse:
        """Run `LearningAnalysisService` on latest completed results and persist outputs.

        Must be called inside an active transaction that already holds the
        Tier 2 `(student_id, course_id)` lock and has flushed the newly
        completed `StudentAssessment` and `StudentResponse` rows.
        """
        course_outcomes: list[LearningOutcomeRecord] = self._outcomes.list_by_course(
            course_id
        )
        if not course_outcomes:
            raise ValueError(
                f"Course {course_id} has no learning outcomes for mastery analysis."
            )

        prerequisites = self._outcomes.list_prerequisites_by_course(course_id)
        latest_responses = (
            self._mastery.list_latest_completed_responses_by_outcome(
                student_id=student_id,
                course_id=course_id,
            )
        )
        if not latest_responses:
            raise ValueError(
                "No completed exam responses found for mastery analysis."
            )

        course_key = str(course_id)
        domain_outcomes = [
            DomainLearningOutcome(
                id=str(lo.id),
                course_id=course_key,
                title=lo.title,
                description=lo.description or "",
            )
            for lo in course_outcomes
        ]
        # GraphEngine.add_prerequisite expects (dependent_outcome_id, prerequisite_outcome_id).
        prerequisite_edges = [
            (str(edge.dependent_outcome_id), str(edge.prerequisite_outcome_id))
            for edge in prerequisites
        ]
        question_results = [
            QuestionResult(
                question_id=str(resp.question_id),
                outcome_id=str(resp.learning_outcome_id),
                is_correct=resp.is_correct,
            )
            for resp in latest_responses
        ]

        threshold = self._settings.exam_default_mastery_threshold
        analysis = self._analysis.analyze(
            course_id=course_key,
            outcomes=domain_outcomes,
            prerequisite_edges=prerequisite_edges,
            question_results=question_results,
            mastery_threshold=threshold,
        )

        # Upsert MasteryRecord ONLY for outcomes evaluated in this exam attempt.
        score_by_outcome_id = {
            int(item.outcome_id): item for item in analysis.scores
        }
        mastery_updates = [
            MasteryUpdateDraft(
                learning_outcome_id=outcome_id,
                mastery_score=score_by_outcome_id[outcome_id].score_percent,
            )
            for outcome_id in sorted(evaluated_outcome_ids)
            if outcome_id in score_by_outcome_id
        ]
        if mastery_updates:
            self._mastery.upsert_mastery_records(
                student_id=student_id,
                course_id=course_id,
                updates=mastery_updates,
                assessed_at=assessed_at,
            )

        outcome_code_by_id = {lo.id: lo.code for lo in course_outcomes}
        rec_drafts: list[StudyRecommendationDraft] = []
        rec_responses: list[MasteryRecommendationResponse] = []
        blocked_outcome_ids: list[int] = []

        for priority, rec in enumerate(analysis.recommendations, start=1):
            oid = int(rec.outcome_id)
            missing_ids = [int(pid) for pid in rec.missing_prerequisites]
            reason = _format_recommendation_reason(
                status=rec.status,
                missing_prerequisite_ids=missing_ids,
                outcome_code_by_id=outcome_code_by_id,
            )
            if rec.status == "blocked":
                blocked_outcome_ids.append(oid)
            rec_drafts.append(
                StudyRecommendationDraft(
                    learning_outcome_id=oid,
                    priority_order=priority,
                    reason=reason,
                    status=rec.status,
                )
            )
            rec_responses.append(
                MasteryRecommendationResponse(
                    learning_outcome_id=oid,
                    status=rec.status,
                    score_percent=rec.score_percent,
                    priority_order=priority,
                    missing_prerequisites=missing_ids,
                    reason=reason,
                )
            )

        self._mastery.replace_recommendations_for_course(
            student_id=student_id,
            course_id=course_id,
            recommendations=rec_drafts,
        )

        learning_order = [int(oid) for oid in analysis.learning_order]
        outcome_scores = [
            OutcomeMasteryScoreResponse(
                learning_outcome_id=int(s.outcome_id),
                correct_count=s.correct_count,
                question_count=s.question_count,
                score_percent=s.score_percent,
            )
            for s in analysis.scores
        ]
        weak_outcome_ids = [
            oid
            for oid in learning_order
            if oid in score_by_outcome_id
            and score_by_outcome_id[oid].score_percent < threshold
        ]
        unassessed_outcome_ids = [
            oid for oid in learning_order if oid not in score_by_outcome_id
        ]

        return ExamMasterySummaryResponse(
            mastery_threshold=threshold,
            learning_order=learning_order,
            outcome_scores=outcome_scores,
            weak_outcome_ids=weak_outcome_ids,
            unassessed_outcome_ids=unassessed_outcome_ids,
            blocked_outcome_ids=blocked_outcome_ids,
            recommendations=rec_responses,
        )
