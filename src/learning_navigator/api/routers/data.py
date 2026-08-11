"""Portable JSON import and privacy export endpoints."""

from fastapi import APIRouter, status

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
    return application.import_map(user_id=user_id, payload=payload.payload)
