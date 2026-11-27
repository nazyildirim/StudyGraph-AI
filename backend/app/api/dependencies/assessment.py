"""FastAPI dependency providers and HTTP error translation for Issue #7.

Production guarantees:
- Lazy initialization: importing this module never connects to PostgreSQL or
  loads environment secrets.
- Shared request-scoped Session: all repositories and `SqlAlchemyTransactionManager`
  created for a request share the exact same `Session` from `get_db`.
- Real Issue #5 wiring: `get_exam_submission_service` ALWAYS injects a real
  `MasteryIntegrationAdapter` backed by `LearningAnalysisService` (never None,
  never `allow_skip_mastery_integration=True`, never mocked).
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
    RoleAuthorizationError,
)
from app.core.config import Settings, get_settings
from app.database import get_db
from app.repositories.assessment_repository import SqlAlchemyAssessmentRepository
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.errors import (
    AssessmentNotFoundError,
    AttemptAlreadyFinalizedError,
    AttemptNotFoundError,
    CrossCourseReferenceError,
    DuplicateResponseError,
    InvalidQuestionOptionsError,
    InvalidResponseError,
    PaginationValidationError,
    QuestionArchivedError,
    QuestionNotFoundError,
)
from app.repositories.learning_outcome_repository import (
    SqlAlchemyLearningOutcomeRepository,
)
from app.repositories.mastery_repository import SqlAlchemyMasteryRepository
from app.repositories.question_repository import SqlAlchemyQuestionRepository
from app.services.exam_generation_service import (
    ActiveRetestConflictError,
    DiagnosticExamAlreadyCompletedError,
    DiagnosticExamRequiredError,
    ExamGenerationService,
    InsufficientQuestionsError,
    NoEligibleOutcomesForRetestError,
    OutcomeNotEligibleForRetestError,
)
from app.services.exam_submission_service import (
    AttemptNotCompletedError,
    ExamSubmissionService,
)
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter
from app.services.mastery_query_service import MasteryQueryService
from app.services.question_bank_service import (
    QuestionBankService,
    SqlAlchemyTransactionManager,
)


def _build_course_access_policy(db: Session) -> CourseAccessPolicy:
    return CourseAccessPolicy(
        course_repository=SqlAlchemyCourseRepository(db),
        enrollment_repository=SqlAlchemyCourseEnrollmentRepository(db),
    )


def get_question_bank_service(
    db: Session = Depends(get_db),
) -> QuestionBankService:
    """Provide request-scoped QuestionBankService sharing one Session."""
    return QuestionBankService(
        access_policy=_build_course_access_policy(db),
        question_repository=SqlAlchemyQuestionRepository(db),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(db),
        transaction_manager=SqlAlchemyTransactionManager(db),
    )


def get_exam_generation_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExamGenerationService:
    """Provide request-scoped ExamGenerationService sharing one Session."""
    return ExamGenerationService(
        access_policy=_build_course_access_policy(db),
        assessment_repository=SqlAlchemyAssessmentRepository(db),
        question_repository=SqlAlchemyQuestionRepository(db),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(db),
        mastery_repository=SqlAlchemyMasteryRepository(db),
        transaction_manager=SqlAlchemyTransactionManager(db),
        settings=settings,
    )


def get_exam_submission_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExamSubmissionService:
    """Provide request-scoped ExamSubmissionService with real Issue #5 MasteryIntegrator."""
    mastery_repo = SqlAlchemyMasteryRepository(db)
    mastery_adapter = MasteryIntegrationAdapter(
        learning_analysis_service=LearningAnalysisService(),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(db),
        mastery_repository=mastery_repo,
        settings=settings,
    )
    return ExamSubmissionService(
        access_policy=_build_course_access_policy(db),
        assessment_repository=SqlAlchemyAssessmentRepository(db),
        question_repository=SqlAlchemyQuestionRepository(db),
        mastery_repository=mastery_repo,
        transaction_manager=SqlAlchemyTransactionManager(db),
        mastery_integrator=mastery_adapter,
    )


def get_mastery_query_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MasteryQueryService:
    """Provide request-scoped read-only MasteryQueryService."""
    return MasteryQueryService(
        access_policy=_build_course_access_policy(db),
        learning_outcome_repository=SqlAlchemyLearningOutcomeRepository(db),
        mastery_repository=SqlAlchemyMasteryRepository(db),
        settings=settings,
    )


def translate_assessment_error(
    error: Exception, *, operation: str = "assessment_api"
) -> HTTPException:
    """Map Issue #7 domain exceptions to safe, non-disclosing HTTP errors.

    Only explicitly defined domain validation errors map to HTTP 422.
    Unexpected `ValueError` or internal exceptions are logged safely (operation
    + exception type only — never raw payloads, JWTs, or DB connection strings)
    and returned as generic HTTP 500.
    """
    if isinstance(error, RoleAuthorizationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role permissions.",
        )
    if isinstance(
        error,
        (
            ResourceNotFoundError,
            QuestionNotFoundError,
            AssessmentNotFoundError,
            AttemptNotFoundError,
            CrossCourseReferenceError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RESOURCE_NOT_FOUND_MESSAGE,
        )
    if isinstance(
        error,
        (
            InsufficientQuestionsError,
            DiagnosticExamAlreadyCompletedError,
            DiagnosticExamRequiredError,
            NoEligibleOutcomesForRetestError,
            OutcomeNotEligibleForRetestError,
            ActiveRetestConflictError,
            AttemptAlreadyFinalizedError,
            AttemptNotCompletedError,
            QuestionArchivedError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
    if isinstance(
        error,
        (
            InvalidResponseError,
            DuplicateResponseError,
            InvalidQuestionOptionsError,
            PaginationValidationError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )
    logger.error(
        "Unexpected internal error during %s: exception_type=%s",
        operation,
        type(error).__name__,
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error.",
    )
