"""RAG assistant API routers (canonical `/api/v1` + unprefixed frontend compat)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.rag import (
    acquire_model_slot,
    get_rag_assistant_service,
)
from app.api.routing import SanitizedValidationRoute
from app.authorization.ownership import ResourceNotFoundError
from app.core.config import Settings, get_settings
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.user import User
from app.rag.generation.errors import CitationValidationError, LLMError
from app.rag.retrieval.errors import (
    InvalidQueryError,
    RetrievalBackendUnavailableError,
)
from app.repositories.errors import InvalidCitationError
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.rag_assistant_service import RagAssistantService

router = APIRouter(
    tags=["RAG Assistant"],
    route_class=SanitizedValidationRoute,
)

compat_router = APIRouter(
    tags=["RAG Assistant (Frontend Compat)"],
    route_class=SanitizedValidationRoute,
    include_in_schema=False,
)


def _handle_ask(
    *,
    course_id: int,
    payload: AssistantRequest,
    current_user: User,
    service: RagAssistantService,
    settings: Settings,
) -> AssistantResponse:
    try:
        with acquire_model_slot(settings):
            result = service.ask(
                user=current_user,
                course_id=course_id,
                question=payload.question,
                mode=payload.to_domain_mode(),
            )
    except HTTPException:
        raise
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found.",
        ) from error
    except InvalidQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid question payload.",
        ) from error
    except InvalidCitationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Referenced course material changed during answer generation.",
        ) from error
    except (
        RetrievalBackendUnavailableError,
        LLMError,
        CitationValidationError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI assistant service is temporarily unavailable.",
        ) from error

    return AssistantResponse.from_domain(result)


@router.post(
    "/courses/{course_id}/assistant",
    response_model=AssistantResponse,
    status_code=status.HTTP_200_OK,
)
def ask_course_assistant(
    payload: AssistantRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: RagAssistantService = Depends(get_rag_assistant_service),
    settings: Settings = Depends(get_settings),
) -> AssistantResponse:
    return _handle_ask(
        course_id=course_id,
        payload=payload,
        current_user=current_user,
        service=service,
        settings=settings,
    )


@compat_router.post(
    "/courses/{course_id}/assistant",
    response_model=AssistantResponse,
    status_code=status.HTTP_200_OK,
)
def compat_ask_course_assistant(
    payload: AssistantRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: RagAssistantService = Depends(get_rag_assistant_service),
    settings: Settings = Depends(get_settings),
) -> AssistantResponse:
    return _handle_ask(
        course_id=course_id,
        payload=payload,
        current_user=current_user,
        service=service,
        settings=settings,
    )
