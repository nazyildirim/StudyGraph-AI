
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
)

from app.domain.learning_outcome import LearningOutcome
from app.domain.scoring_engine import QuestionResult
from app.services.learning_analysis_service import (
    LearningAnalysisService,
)


router = APIRouter(tags=["Learning Analysis"])


class APIInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class OutcomeInput(APIInput):
    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""


class PrerequisiteInput(APIInput):
    outcome_id: str = Field(min_length=1)
    prerequisite_id: str = Field(min_length=1)


class QuestionResultInput(APIInput):
    question_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    is_correct: StrictBool


class LearningAnalysisRequest(APIInput):
    course_id: str = Field(min_length=1)
    outcomes: list[OutcomeInput] = Field(min_length=1)
    prerequisite_edges: list[PrerequisiteInput] = Field(
        default_factory=list
    )
    question_results: list[QuestionResultInput] = Field(
        min_length=1
    )
    mastery_threshold: float = Field(
        default=70.0,
        ge=0,
        le=100,
        allow_inf_nan=False,
    )


class OutcomeScoreResponse(BaseModel):
    outcome_id: str
    correct_count: int
    question_count: int
    score_percent: float


class RecommendationResponse(BaseModel):
    outcome_id: str
    status: Literal[
        "completed", "review", "blocked", "study"
    ]
    score_percent: float | None
    missing_prerequisites: tuple[str, ...]


class LearningAnalysisResponse(BaseModel):
    course_id: str
    learning_order: tuple[str, ...]
    scores: tuple[OutcomeScoreResponse, ...]
    recommendations: tuple[RecommendationResponse, ...]


@router.post(
    "/learning-analyses",
    response_model=LearningAnalysisResponse,
    status_code=200,
)
def analyze_learning(
    request: LearningAnalysisRequest,
) -> LearningAnalysisResponse:
    """Sinav sonuclarindan ogrenme analizi olusturur."""

    service = LearningAnalysisService()

    try:
        result = service.analyze(
            course_id=request.course_id,
            outcomes=[
                LearningOutcome(
                    id=item.id,
                    course_id=item.course_id,
                    title=item.title,
                    description=item.description,
                )
                for item in request.outcomes
            ],
            prerequisite_edges=[
                (item.outcome_id, item.prerequisite_id)
                for item in request.prerequisite_edges
            ],
            question_results=[
                QuestionResult(
                    question_id=item.question_id,
                    outcome_id=item.outcome_id,
                    is_correct=item.is_correct,
                )
                for item in request.question_results
            ],
            mastery_threshold=request.mastery_threshold,
        )

    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    return LearningAnalysisResponse.model_validate(
        asdict(result)
    )
