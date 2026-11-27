"""Course materials API routers (canonical `/api/v1` + frontend compatibility).

Both routers delegate to the exact same `MaterialService`, authentication, and
authorization dependencies so zero business logic is duplicated.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Response,
    UploadFile,
    status,
)

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.authorization import require_roles
from app.api.dependencies.rag import acquire_model_slot, get_material_service
from app.api.routing import SanitizedValidationRoute
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.authorization.roles import Role
from app.core.config import Settings, get_settings
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.user import User
from app.rag.embedding.errors import ModelNotFoundError
from app.repositories.errors import (
    MaterialAlreadyExistsError,
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
)
from app.schemas.material import MaterialResponse, MaterialTextCreateRequest
from app.services.material_service import MaterialService
from app.storage import (
    FileTooLargeError,
    InvalidUploadError,
    UnsupportedMediaTypeError,
)

router = APIRouter(
    tags=["Course Materials"],
    route_class=SanitizedValidationRoute,
)

# Unprefixed compatibility router for the existing frontend (`BASE_URL + /courses/...`)
compat_router = APIRouter(
    tags=["Course Materials (Frontend Compat)"],
    route_class=SanitizedValidationRoute,
    include_in_schema=False,
)


def _translate_material_error(error: Exception) -> HTTPException:
    if isinstance(error, RoleAuthorizationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role permissions.",
        )
    if isinstance(error, ResourceNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found.",
        )
    if isinstance(
        error,
        (
            MaterialAlreadyExistsError,
            MaterialAlreadyProcessingError,
            MaterialAlreadyProcessedError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Material conflict: duplicate content or active processing.",
        )
    if isinstance(error, FileTooLargeError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Uploaded file exceeds the maximum allowed size.",
        )
    if isinstance(error, UnsupportedMediaTypeError):
        return HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported media type. Only PDF and UTF-8 TXT files are allowed.",
        )
    if isinstance(error, InvalidUploadError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid upload payload or filename.",
        )
    if isinstance(error, ModelNotFoundError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding model is currently unavailable.",
        )
    raise error


# ---------------------------------------------------------- Canonical /api/v1
@router.get(
    "/courses/{course_id}/materials",
    response_model=list[MaterialResponse],
    status_code=status.HTTP_200_OK,
)
def list_course_materials(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service),
) -> list[MaterialResponse]:
    try:
        materials = service.list_materials(user=current_user, course_id=course_id)
    except Exception as error:
        raise _translate_material_error(error) from error
    return [MaterialResponse.from_model(m) for m in materials]


@router.get(
    "/courses/{course_id}/materials/{material_id}",
    response_model=MaterialResponse,
    status_code=status.HTTP_200_OK,
)
def get_course_material(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    material_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service),
) -> MaterialResponse:
    try:
        material = service.get_material(
            user=current_user, course_id=course_id, material_id=material_id
        )
    except Exception as error:
        raise _translate_material_error(error) from error
    return MaterialResponse.from_model(material)


@router.post(
    "/courses/{course_id}/materials",
    response_model=MaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_text_course_material(
    payload: MaterialTextCreateRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    service: MaterialService = Depends(get_material_service),
    settings: Settings = Depends(get_settings),
) -> MaterialResponse:
    try:
        with acquire_model_slot(settings):
            material = service.create_text_material(
                user=current_user,
                course_id=course_id,
                title=payload.title,
                text=payload.text,
                page=payload.page,
                outcome_ref=payload.outcome_id,
            )
    except HTTPException:
        raise
    except Exception as error:
        raise _translate_material_error(error) from error
    return MaterialResponse.from_model(material)


@router.post(
    "/courses/{course_id}/materials/upload",
    response_model=MaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_course_material(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=255),
    outcome_id: str | None = Form(default=None, max_length=100),
    current_user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    service: MaterialService = Depends(get_material_service),
    settings: Settings = Depends(get_settings),
) -> MaterialResponse:
    try:
        with acquire_model_slot(settings):
            material = service.upload_file_material(
                user=current_user,
                course_id=course_id,
                filename=file.filename,
                content_type=file.content_type,
                stream=file.file,
                title=title,
                outcome_ref=(outcome_id.strip() or None) if outcome_id else None,
            )
    except HTTPException:
        raise
    except Exception as error:
        raise _translate_material_error(error) from error
    finally:
        file.file.close()
    return MaterialResponse.from_model(material)


@router.delete(
    "/courses/{course_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_course_material(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    material_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    service: MaterialService = Depends(get_material_service),
) -> Response:
    try:
        service.delete_material(
            user=current_user, course_id=course_id, material_id=material_id
        )
    except Exception as error:
        raise _translate_material_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------- Unprefixed Frontend Compatibility
@compat_router.get(
    "/courses/{course_id}/materials",
    response_model=list[MaterialResponse],
    status_code=status.HTTP_200_OK,
)
def compat_list_course_materials(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service),
) -> list[MaterialResponse]:
    return list_course_materials(
        course_id=course_id, current_user=current_user, service=service
    )


@compat_router.post(
    "/courses/{course_id}/materials",
    response_model=list[MaterialResponse],
    status_code=status.HTTP_201_CREATED,
)
def compat_create_text_course_material(
    payload: MaterialTextCreateRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    service: MaterialService = Depends(get_material_service),
    settings: Settings = Depends(get_settings),
) -> list[MaterialResponse]:
    """Frontend `MaterialManager.jsx` expects the updated material list array."""
    create_text_course_material(
        payload=payload,
        course_id=course_id,
        current_user=current_user,
        service=service,
        settings=settings,
    )
    return list_course_materials(
        course_id=course_id, current_user=current_user, service=service
    )


@compat_router.delete(
    "/courses/{course_id}/materials/{material_id}",
    response_model=list[MaterialResponse],
    status_code=status.HTTP_200_OK,
)
def compat_delete_course_material(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    material_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    service: MaterialService = Depends(get_material_service),
) -> list[MaterialResponse]:
    """Frontend `MaterialManager.jsx` expects the updated material list array."""
    delete_course_material(
        course_id=course_id,
        material_id=material_id,
        current_user=current_user,
        service=service,
    )
    return list_course_materials(
        course_id=course_id, current_user=current_user, service=service
    )
