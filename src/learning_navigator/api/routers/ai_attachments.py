"""Local file uploads used by the unified AI assistant."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.application.collaboration import AICollaborationService

router = APIRouter(prefix="/ai/attachments", tags=["AI collaboration"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_ai_attachment(
    request: Request,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    x_file_name: str = Header(alias="X-File-Name"),
) -> dict[str, object]:
    filename = unquote(x_file_name).strip()
    if not filename:
        raise HTTPException(status_code=422, detail="X-File-Name is required")
    return await AICollaborationService(application).add_attachment(
        user_id=user_id,
        original_name=filename,
        media_type=request.headers.get("content-type"),
        chunks=request.stream(),
    )


@router.get("/{attachment_id}/content")
def get_ai_attachment_content(
    attachment_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> FileResponse:
    path, media_type, filename = AICollaborationService(application).get_attachment_content(
        user_id=user_id,
        attachment_id=attachment_id,
    )
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment content is unavailable")
    disposition = "inline" if media_type.startswith("image/") else "attachment"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type=disposition,
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_attachment(
    attachment_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    AICollaborationService(application).delete_attachment(
        user_id=user_id,
        attachment_id=attachment_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
