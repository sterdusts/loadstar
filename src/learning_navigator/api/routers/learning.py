"""Learning plans, goals, routes, state and study-record endpoints."""

from fastapi import APIRouter, Query, Response, status

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
    ProgressCheckInCreate,
    ProgressCheckInReset,
    ProgressCheckInUpdate,
    ProjectPermanentDeleteRequest,
)

router = APIRouter(tags=["learning"])


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


@router.post("/goals/{goal_id}/nodes/{node_id}/check-ins/reset")
def reset_progress_check_in(
    goal_id: str,
    node_id: str,
    payload: ProgressCheckInReset,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.reset_progress_check_in(
        user_id=user_id,
        goal_id=goal_id,
        node_id=node_id,
        **payload.model_dump(),
    )


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
