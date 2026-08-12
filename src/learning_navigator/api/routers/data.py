"""Portable JSON import and privacy export endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.api.schemas.requests import MapImportRequest

router = APIRouter(tags=["data portability"])


@router.get("/data/export")
def export_data(
    application: ApplicationDependency, user_id: CurrentUserDependency
) -> dict[str, object]:
    return application.export_user_data(user_id=user_id)


@router.post("/data/import", status_code=status.HTTP_201_CREATED)
def import_data(
    payload: MapImportRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    try:
        return application.import_map(user_id=user_id, payload=payload.payload)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        # Treat the import as one atomic request. The raised HTTPException makes
        # the session dependency roll back any rows created before validation failed.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_map_import",
                "message": "The imported map is malformed or internally inconsistent",
            },
        ) from exc
