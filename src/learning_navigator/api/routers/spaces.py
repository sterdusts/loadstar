"""Knowledge-space, node and edge transport endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.api.schemas.requests import (
    EdgeCreate,
    NodeCreate,
    NodeUpdate,
    SpaceCreate,
    VersionPublishRequest,
    VersionRestoreRequest,
)

router = APIRouter(tags=["knowledge maps"])


@router.get("/spaces")
def list_spaces(
    application: ApplicationDependency, user_id: CurrentUserDependency
) -> list[dict[str, object]]:
    return application.list_spaces(user_id)


@router.post("/spaces", status_code=status.HTTP_201_CREATED)
def create_space(
    payload: SpaceCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.create_space(user_id=user_id, **payload.model_dump())


@router.get("/spaces/{space_id}/versions")
def list_versions(
    space_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> list[dict[str, object]]:
    return application.list_map_versions(user_id=user_id, space_id=space_id)


@router.post("/spaces/{space_id}/versions/publish")
def publish_version(
    space_id: str,
    payload: VersionPublishRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.publish_map_version(
        user_id=user_id, space_id=space_id, **payload.model_dump()
    )


@router.post("/spaces/{space_id}/versions/{version_id}/restore")
def restore_version(
    space_id: str,
    version_id: str,
    payload: VersionRestoreRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.restore_map_version(
        user_id=user_id,
        space_id=space_id,
        version_id=version_id,
        **payload.model_dump(),
    )


@router.get("/spaces/{space_id}/versions/compare")
def compare_versions(
    space_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    base_version_id: Annotated[str, Query()],
    head_version_id: Annotated[str, Query()],
) -> dict[str, object]:
    return application.compare_map_versions(
        user_id=user_id,
        space_id=space_id,
        base_version_id=base_version_id,
        head_version_id=head_version_id,
    )


@router.get("/spaces/{space_id}/graph")
def graph_view(
    space_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    target_node_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    return application.graph_view(space_id=space_id, user_id=user_id, target_node_id=target_node_id)


@router.post("/spaces/{space_id}/nodes", status_code=status.HTTP_201_CREATED)
def create_node(
    space_id: str,
    payload: NodeCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.create_node(user_id=user_id, space_id=space_id, **payload.model_dump())


@router.patch("/spaces/{space_id}/nodes/{node_id}")
def update_node(
    space_id: str,
    node_id: str,
    payload: NodeUpdate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    changes = payload.model_dump(exclude_unset=True)
    return application.update_node(
        user_id=user_id, space_id=space_id, node_id=node_id, changes=changes
    )


@router.delete("/spaces/{space_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_node(
    space_id: str,
    node_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.archive_node(user_id=user_id, space_id=space_id, node_id=node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/spaces/{space_id}/edges", status_code=status.HTTP_201_CREATED)
def create_edge(
    space_id: str,
    payload: EdgeCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.create_edge(user_id=user_id, space_id=space_id, **payload.model_dump())


@router.delete("/spaces/{space_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_edge(
    space_id: str,
    edge_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.remove_edge(user_id=user_id, space_id=space_id, edge_id=edge_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
