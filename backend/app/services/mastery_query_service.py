"""Read-only query service for Course Outcomes, Mastery Maps, and Recommendations.

SRP & Security:
- Contains zero FastAPI/HTTP dependencies and performs zero DB mutations.
- `list_course_outcomes` enforces `CourseAccessPolicy.check_read_access`
  (enrolled students, owning instructor, or admin).
- `get_student_mastery_map` and `get_student_recommendations` enforce active
  `Role.STUDENT` + active course enrollment and return ONLY the authenticated
  student's own records.
- Unassessed outcomes are explicitly returned with `is_assessed=False` and
  `mastery_score=None` (never synthesized as 0%).
"""

from __future__ import annotations

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
    RoleAuthorizationError,
    parse_user_role,
)
from app.authorization.roles import Role
from app.core.config import Settings, get_settings
from app.models.user import User
from app.repositories.learning_outcome_repository import LearningOutcomeRepository
from app.repositories.mastery_repository import MasteryRepository
from app.schemas.mastery import (
    CourseMasteryMapResponse,
    CourseOutcomeResponse,
    CourseRecommendationItemResponse,
    CourseRecommendationsResponse,
    MasteryOutcomeItemResponse,
)
from app.services.mastery_integration import compute_live_recommendations


class MasteryQueryService:
    """Read-only projection service for outcomes, mastery, and recommendations."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        learning_outcome_repository: LearningOutcomeRepository,
        mastery_repository: MasteryRepository,
        settings: Settings | None = None,
    ) -> None:
        self._access = access_policy
        self._outcomes = learning_outcome_repository
        self._mastery = mastery_repository
        self._settings = settings if settings is not None else get_settings()

    def _authorize_student_for_course(self, *, user: User, course_id: int) -> None:
        if user is None or not getattr(user, "is_active", False):
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        role = parse_user_role(user)
        if role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        if role is not Role.STUDENT:
            raise RoleAuthorizationError(
                "Only students may view personal mastery and study recommendations."
            )
        self._access.check_read_access(user, course_id)

    def list_course_outcomes(
        self, *, user: User, course_id: int
    ) -> list[CourseOutcomeResponse]:
        """List learning outcomes and prerequisite IDs for a course."""
        self._access.check_read_access(user, course_id)
        outcomes = self._outcomes.list_by_course(course_id)
        prereqs = self._outcomes.list_prerequisites_by_course(course_id)
        prereqs_by_dep: dict[int, list[int]] = {}
        for edge in prereqs:
            prereqs_by_dep.setdefault(edge.dependent_outcome_id, []).append(
                edge.prerequisite_outcome_id
            )
        return [
            CourseOutcomeResponse(
                id=lo.id,
                course_id=lo.course_id,
                code=lo.code,
                title=lo.title,
                description=lo.description,
                order_index=lo.order_index,
                prerequisite_ids=sorted(prereqs_by_dep.get(lo.id, [])),
            )
            for lo in outcomes
        ]

    def get_student_mastery_map(
        self, *, user: User, course_id: int
    ) -> CourseMasteryMapResponse:
        """Return the authenticated student's current mastery map (read-only)."""
        self._authorize_student_for_course(user=user, course_id=course_id)
        threshold = self._settings.exam_default_mastery_threshold
        outcomes = self._outcomes.list_by_course(course_id)
        mastery_by_oid = {
            rec.learning_outcome_id: rec
            for rec in self._mastery.list_mastery_for_student_course(
                student_id=user.id, course_id=course_id
            )
        }
        items = []
        for lo in outcomes:
            rec = mastery_by_oid.get(lo.id)
            if rec is None:
                items.append(
                    MasteryOutcomeItemResponse(
                        learning_outcome_id=lo.id,
                        code=lo.code,
                        title=lo.title,
                        is_assessed=False,
                        mastery_score=None,
                        total_attempts=0,
                        last_assessed_at=None,
                    )
                )
            else:
                items.append(
                    MasteryOutcomeItemResponse(
                        learning_outcome_id=lo.id,
                        code=lo.code,
                        title=lo.title,
                        is_assessed=True,
                        mastery_score=rec.mastery_score,
                        total_attempts=rec.total_attempts,
                        last_assessed_at=rec.last_assessed_at,
                    )
                )
        return CourseMasteryMapResponse(
            course_id=course_id,
            mastery_threshold=threshold,
            outcomes=items,
        )

    def get_student_recommendations(
        self, *, user: User, course_id: int
    ) -> CourseRecommendationsResponse:
        """Return live, graph-consistent recommendations (strictly read-only)."""
        self._authorize_student_for_course(user=user, course_id=course_id)
        threshold = self._settings.exam_default_mastery_threshold
        outcomes = self._outcomes.list_by_course(course_id)
        outcomes_by_id = {lo.id: lo for lo in outcomes}
        prerequisites = self._outcomes.list_prerequisites_by_course(course_id)

        live_recs = compute_live_recommendations(
            student_id=user.id,
            course_id=course_id,
            outcomes=outcomes,
            prerequisites=prerequisites,
            mastery_repository=self._mastery,
            mastery_threshold=threshold,
        )
        items = [
            CourseRecommendationItemResponse(
                learning_outcome_id=rec.learning_outcome_id,
                code=outcomes_by_id[rec.learning_outcome_id].code,
                title=outcomes_by_id[rec.learning_outcome_id].title,
                status=rec.status,
                priority_order=rec.priority_order,
                reason=rec.reason,
                missing_prerequisites=list(rec.missing_prerequisites),
                mastery_score=rec.score_percent,
            )
            for rec in live_recs
            if rec.learning_outcome_id in outcomes_by_id
        ]
        return CourseRecommendationsResponse(
            course_id=course_id,
            mastery_threshold=threshold,
            recommendations=items,
        )
