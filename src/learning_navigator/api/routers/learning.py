"""Learning plans, goals, routes, state and study-record endpoints."""

from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.api.schemas.requests import (
    GoalCreate,
    LearningSessionCreate,
    MasteryProfileEvidenceRequest,
    MasteryUpdateRequest,
    PathDraftGenerateRequest,
    PathOrderUpdate,
    PathRevisionCheckRequest,
    PathRevisionCloneRequest,
    PathStepCreate,
    PathStepUpdate,
    ProgressCheckInAIEvaluationRequest,
    ProgressCheckInClear,
    ProgressCheckInCreate,
    ProgressCheckInUpdate,
    ProjectPermanentDeleteRequest,
)

router = APIRouter(tags=["learning"])

_SAFE_INLINE_IMAGE_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@router.get("/learning-plans")
def list_learning_plans(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> list[dict[str, object]]:
    return application.list_learning_plans(user_id=user_id)


@router.get("/learning-plans/{plan_id}")
def get_learning_plan(
    plan_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.get_learning_plan(user_id=user_id, plan_id=plan_id)


@router.post("/learning-plans/{plan_id}/activate")
def activate_learning_plan(
    plan_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.activate_learning_plan(user_id=user_id, plan_id=plan_id)


@router.delete("/learning-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_learning_plan(
    plan_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.delete_learning_plan(user_id=user_id, plan_id=plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.create_goal(user_id=user_id, **payload.model_dump())


@router.get("/goals/archived")
def list_archived_projects(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> list[dict[str, object]]:
    return application.list_archived_projects(user_id=user_id)


@router.post("/goals/{goal_id}/archive")
def archive_project(
    goal_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.archive_project(user_id=user_id, goal_id=goal_id)


@router.post("/goals/{goal_id}/restore")
def restore_project(
    goal_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.restore_project(user_id=user_id, goal_id=goal_id)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def permanently_delete_project(
    goal_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    payload: ProjectPermanentDeleteRequest | None = None,
) -> Response:
    application.delete_project_permanently(
        user_id=user_id,
        goal_id=goal_id,
        confirm_title=payload.confirm_title if payload is not None else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/goals/{goal_id}/paths", deprecated=True)
def generate_path(
    goal_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.generate_path(user_id=user_id, goal_id=goal_id)


@router.get("/goals/{goal_id}/path-revisions")
def list_path_revisions(
    goal_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> list[dict[str, object]]:
    return application.list_path_revisions(user_id=user_id, goal_id=goal_id)


@router.post("/goals/{goal_id}/path-revisions", status_code=status.HTTP_201_CREATED)
def generate_path_draft(
    goal_id: str,
    payload: PathDraftGenerateRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.generate_path(
        user_id=user_id,
        goal_id=goal_id,
        activate=False,
        change_summary=payload.change_summary,
    )


@router.get("/path-revisions/{path_id}")
def get_path_revision(
    path_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.get_path_revision(user_id=user_id, path_id=path_id)


@router.post(
    "/path-revisions/{path_id}/clone",
    status_code=status.HTTP_201_CREATED,
)
def clone_path_revision(
    path_id: str,
    payload: PathRevisionCloneRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.clone_path_revision(
        user_id=user_id,
        path_id=path_id,
        expected_revision=payload.expected_revision,
        change_summary=payload.change_summary,
    )


@router.post("/path-revisions/{path_id}/validate")
def validate_path_revision(
    path_id: str,
    payload: PathRevisionCheckRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.validate_path_revision(
        user_id=user_id,
        path_id=path_id,
        expected_revision=payload.expected_revision,
        persist=True,
    )


@router.post("/path-revisions/{path_id}/activate")
def activate_path_revision(
    path_id: str,
    payload: PathRevisionCheckRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.activate_path_revision(
        user_id=user_id,
        path_id=path_id,
        expected_revision=payload.expected_revision,
    )


@router.post(
    "/path-revisions/{path_id}/steps",
    status_code=status.HTTP_201_CREATED,
)
def add_path_step(
    path_id: str,
    payload: PathStepCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.add_path_step(
        user_id=user_id,
        path_id=path_id,
        **payload.model_dump(),
    )


@router.patch("/path-revisions/{path_id}/steps/{step_id}")
def update_path_step(
    path_id: str,
    step_id: str,
    payload: PathStepUpdate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump(exclude_unset=True)
    expected_revision = int(values.pop("expected_revision"))
    return application.update_path_step(
        user_id=user_id,
        path_id=path_id,
        step_id=step_id,
        expected_revision=expected_revision,
        changes=values,
    )


@router.put("/path-revisions/{path_id}/order")
def update_path_order(
    path_id: str,
    payload: PathOrderUpdate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.update_path_order(
        user_id=user_id,
        path_id=path_id,
        expected_revision=payload.expected_revision,
        step_ids=payload.step_ids,
    )


@router.delete("/path-revisions/{path_id}/steps/{step_id}")
def remove_path_step(
    path_id: str,
    step_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    expected_revision: int = Query(ge=1),
) -> dict[str, object]:
    return application.remove_path_step(
        user_id=user_id,
        path_id=path_id,
        step_id=step_id,
        expected_revision=expected_revision,
    )


@router.get("/spaces/{space_id}/nodes/{node_id}/blockage")
def explain_blockage(
    space_id: str,
    node_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.explain_blockage(user_id=user_id, space_id=space_id, node_id=node_id)


@router.put("/nodes/{node_id}/mastery")
def update_mastery(
    node_id: str,
    payload: MasteryUpdateRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.update_mastery(user_id=user_id, node_id=node_id, **payload.model_dump())


@router.get("/nodes/{node_id}/mastery-profile")
def get_mastery_profile(
    node_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.get_mastery_profile(user_id=user_id, node_id=node_id)


@router.post("/nodes/{node_id}/mastery-profile/evidence", status_code=status.HTTP_201_CREATED)
def record_mastery_profile_evidence(
    node_id: str,
    payload: MasteryProfileEvidenceRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump(mode="python")
    values["measurements"] = [item.model_dump(mode="python") for item in payload.measurements]
    return application.record_mastery_profile_evidence(
        user_id=user_id,
        node_id=node_id,
        **values,
    )


@router.get("/nodes/{node_id}/learning-context")
def node_learning_context(
    node_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.node_learning_context(user_id=user_id, node_id=node_id)


@router.get("/goals/{goal_id}/nodes/{node_id}/check-ins")
def list_progress_check_ins(
    goal_id: str,
    node_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    limit: int = Query(default=100, ge=1, le=366),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return application.list_progress_check_ins(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        limit=limit,
        offset=offset,
    )


@router.get("/goals/{goal_id}/nodes/{node_id}/check-ins/{check_in_id}")
def get_progress_check_in(
    goal_id: str,
    node_id: str,
    check_in_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.get_progress_check_in(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        check_in_id=check_in_id,
    )


@router.post(
    "/goals/{goal_id}/nodes/{node_id}/check-ins",
    status_code=status.HTTP_201_CREATED,
)
def create_progress_check_in(
    goal_id: str,
    node_id: str,
    payload: ProgressCheckInCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.create_progress_check_in(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        **payload.model_dump(),
    )


@router.post("/goals/{goal_id}/nodes/{node_id}/check-ins/clear")
def clear_progress_check_ins(
    goal_id: str,
    node_id: str,
    payload: ProgressCheckInClear,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.clear_progress_check_ins(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        **payload.model_dump(),
    )


@router.post("/goals/{goal_id}/nodes/{node_id}/check-ins/clear-recovery/{batch_id}/restore")
def restore_cleared_progress_check_ins(
    goal_id: str,
    node_id: str,
    batch_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.restore_cleared_progress_check_ins(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        batch_id=batch_id,
    )


@router.delete(
    "/goals/{goal_id}/nodes/{node_id}/check-ins/clear-recovery/{batch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_cleared_progress_check_ins_permanently(
    goal_id: str,
    node_id: str,
    batch_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.delete_cleared_progress_check_ins_permanently(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        batch_id=batch_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/progress-check-ins/{check_in_id}")
def update_progress_check_in(
    check_in_id: str,
    payload: ProgressCheckInUpdate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump(exclude_unset=True)
    expected_revision = int(values.pop("expected_revision"))
    return application.update_progress_check_in(
        user_id=user_id,
        check_in_id=check_in_id,
        expected_revision=expected_revision,
        changes=values,
    )


@router.post("/progress-check-ins/{check_in_id}/ai-evaluation")
async def evaluate_progress_check_in(
    check_in_id: str,
    payload: ProgressCheckInAIEvaluationRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await application.evaluate_progress_check_in(
        user_id=user_id,
        check_in_id=check_in_id,
        **payload.model_dump(),
    )


@router.post(
    "/progress-check-ins/{check_in_id}/attachments",
    status_code=status.HTTP_201_CREATED,
)
async def add_progress_check_in_attachment(
    check_in_id: str,
    request: Request,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    encoded_name = request.headers.get("X-File-Name", "")
    original_name = unquote(encoded_name).strip()
    if not original_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "attachment_name_required", "message": "A file name is required"},
        )
    return await application.add_progress_check_in_attachment(
        user_id=user_id,
        check_in_id=check_in_id,
        original_name=original_name,
        media_type=request.headers.get("Content-Type"),
        chunks=request.stream(),
    )


@router.get("/progress-check-in-attachments/{attachment_id}/content")
def get_progress_check_in_attachment_content(
    attachment_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    download: bool = False,
) -> FileResponse:
    attachment, path = application.get_progress_check_in_attachment_content(
        user_id=user_id,
        attachment_id=attachment_id,
    )
    media_type = str(attachment.get("media_type") or "application/octet-stream")
    # SVG and unknown image formats are downloaded rather than served as
    # same-origin documents. Common raster formats remain previewable.
    inline = media_type.lower() in _SAFE_INLINE_IMAGE_TYPES and not download
    return FileResponse(
        path,
        media_type=media_type,
        filename=str(attachment["original_name"]),
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/progress-check-in-attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_progress_check_in_attachment(
    attachment_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.delete_progress_check_in_attachment(
        user_id=user_id,
        attachment_id=attachment_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/learning-sessions", status_code=status.HTTP_201_CREATED)
def record_session(
    payload: LearningSessionCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump()
    values["evidence"] = [item.model_dump() for item in payload.evidence]
    return application.record_learning_session(user_id=user_id, **values)


@router.get("/learning-sessions")
def list_learning_sessions(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return application.list_learning_sessions(
        user_id=user_id,
        limit=limit,
        offset=offset,
    )


@router.get("/growth")
def growth(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    days: int = Query(default=30, ge=7, le=365),
) -> dict[str, object]:
    return application.growth(user_id=user_id, days=days)


@router.get("/dashboard")
def dashboard(
    application: ApplicationDependency, user_id: CurrentUserDependency
) -> dict[str, object]:
    return application.dashboard(user_id=user_id)
