"""Fail-closed synchronization between knowledge nodes and editable paths."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.application.services import NavigatorApplication
from learning_navigator.domain.enums import GoalStatus, PathStatus, RecordStatus
from learning_navigator.domain.exceptions import NodeInActivePathError
from learning_navigator.infrastructure.database.models import (
    AuditLogModel,
    KnowledgeEdgeModel,
    KnowledgeNodeModel,
    KnowledgeNodeVersionModel,
    LearningGoalModel,
    LearningPathModel,
    LearningPathNodeModel,
    UserModel,
)
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)


def _project_with_active_and_draft_paths(
    client: TestClient,
    python_map: dict[str, object],
) -> dict[str, Any]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    target_node_id = list(nodes.values())[-1]
    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": target_node_id,
            "title": "Archive guard project",
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goal = goal_response.json()
    active_response = client.post(f"/api/goals/{goal['id']}/paths")
    assert active_response.status_code == 200, active_response.text
    active = active_response.json()
    draft_response = client.post(
        f"/api/goals/{goal['id']}/path-revisions",
        json={"change_summary": "Editable candidate"},
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    node_id = active["items"][0]["node_id"]
    assert node_id in {step["node_id"] for step in draft["steps"]}
    return {
        "space": space,
        "goal": goal,
        "active": active,
        "draft": draft,
        "node_id": node_id,
    }


@pytest.mark.integration
def test_repository_counts_only_current_user_live_project_references(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        owner = session.scalar(select(UserModel).order_by(UserModel.created_at).limit(1))
        assert owner is not None
        repository = SqlAlchemyKnowledgeRepository(session)
        assert repository.active_path_reference_counts_for_node(
            node_id=project["node_id"],
            user_id=owner.id,
        ) == (2, 1)

        owner_paths = list(
            session.scalars(
                select(LearningPathModel).where(LearningPathModel.goal_id == project["goal"]["id"])
            )
        )
        for path in owner_paths:
            path.status = PathStatus.SUPERSEDED.value
        session.flush()
        assert repository.active_path_reference_counts_for_node(
            node_id=project["node_id"],
            user_id=owner.id,
        ) == (0, 0)

        other_user = UserModel(display_name="Other learner")
        session.add(other_user)
        session.flush()
        other_goal = LearningGoalModel(
            user_id=other_user.id,
            space_id=project["space"]["id"],
            target_node_id=project["node_id"],
            title="Other user's project",
            status=GoalStatus.ACTIVE.value,
        )
        session.add(other_goal)
        session.flush()
        other_path = LearningPathModel(
            goal_id=other_goal.id,
            space_id=project["space"]["id"],
            map_version_id=project["active"]["path"]["map_version_id"],
            algorithm_version="isolation-test",
            status=PathStatus.ACTIVE.value,
        )
        session.add(other_path)
        session.flush()
        session.add(
            LearningPathNodeModel(
                path_id=other_path.id,
                node_id=project["node_id"],
                sequence_number=0,
                preferred_order=0,
                required_mastery_level=1,
                recommendation_reason="Other user's private route",
                satisfied_prerequisites=[],
                unmet_prerequisites=[],
                unlocks=[],
                computed_status="AVAILABLE",
            )
        )
        session.flush()

        assert repository.active_path_reference_counts_for_node(
            node_id=project["node_id"],
            user_id=owner.id,
        ) == (0, 0)
        assert repository.active_path_reference_counts_for_node(
            node_id=project["node_id"],
            user_id=other_user.id,
        ) == (1, 1)

        # A draft kept only by a trashed project is historical and must not block.
        owner_paths[0].status = PathStatus.DRAFT.value
        owner_goal = session.get(LearningGoalModel, project["goal"]["id"])
        assert owner_goal is not None
        owner_goal.status = GoalStatus.ARCHIVED.value
        session.flush()
        assert repository.active_path_reference_counts_for_node(
            node_id=project["node_id"],
            user_id=owner.id,
        ) == (0, 0)


@pytest.mark.integration
def test_application_guard_does_not_mutate_node_edges_or_audit(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        owner = session.scalar(select(UserModel).order_by(UserModel.created_at).limit(1))
        assert owner is not None
        repository = SqlAlchemyKnowledgeRepository(session)
        application = NavigatorApplication(
            repository,
            app.state.settings,
            app.state.ai_provider,
            app.state.credential_store,
            app.state.ai_http_client,
        )
        node_before = session.get(KnowledgeNodeModel, project["node_id"])
        assert node_before is not None
        node_status_before = node_before.status
        snapshot_before = session.scalar(
            select(KnowledgeNodeVersionModel).where(
                KnowledgeNodeVersionModel.node_id == project["node_id"],
                KnowledgeNodeVersionModel.map_version_id == project["space"]["draft_version_id"],
            )
        )
        assert snapshot_before is not None
        snapshot_status_before = snapshot_before.status
        edge_statuses_before = dict(
            session.execute(
                select(KnowledgeEdgeModel.id, KnowledgeEdgeModel.status).where(
                    (KnowledgeEdgeModel.source_node_id == project["node_id"])
                    | (KnowledgeEdgeModel.target_node_id == project["node_id"])
                )
            ).all()
        )

        with pytest.raises(NodeInActivePathError) as raised:
            application.archive_node(
                user_id=owner.id,
                space_id=project["space"]["id"],
                node_id=project["node_id"],
            )

        assert raised.value.active_path_count == 2
        assert raised.value.project_count == 1
        node = session.get(KnowledgeNodeModel, project["node_id"])
        assert node is not None
        assert node.status == node_status_before
        snapshot = session.scalar(
            select(KnowledgeNodeVersionModel).where(
                KnowledgeNodeVersionModel.node_id == project["node_id"],
                KnowledgeNodeVersionModel.map_version_id == project["space"]["draft_version_id"],
            )
        )
        assert snapshot is not None
        assert snapshot.status == snapshot_status_before
        assert (
            dict(
                session.execute(
                    select(KnowledgeEdgeModel.id, KnowledgeEdgeModel.status).where(
                        (KnowledgeEdgeModel.source_node_id == project["node_id"])
                        | (KnowledgeEdgeModel.target_node_id == project["node_id"])
                    )
                ).all()
            )
            == edge_statuses_before
        )
        assert (
            session.scalar(
                select(AuditLogModel.id).where(
                    AuditLogModel.action == "ARCHIVE_NODE",
                    AuditLogModel.entity_id == project["node_id"],
                )
            )
            is None
        )


@pytest.mark.integration
def test_archive_node_api_reports_live_references_then_allows_trashed_project(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    app = cast(FastAPI, client.app)
    path_statuses_before: dict[str, str]
    node_status_before: str
    with app.state.session_factory() as session:
        node = session.get(KnowledgeNodeModel, project["node_id"])
        assert node is not None
        node_status_before = node.status
        path_statuses_before = dict(
            session.execute(
                select(LearningPathModel.id, LearningPathModel.status).where(
                    LearningPathModel.goal_id == project["goal"]["id"]
                )
            ).all()
        )

    blocked = client.delete(f"/api/spaces/{project['space']['id']}/nodes/{project['node_id']}")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == {
        "code": "node_in_active_path",
        "message": (
            "This node is used by 2 active or draft learning path(s) across 1 "
            "non-archived project(s); edit those paths before archiving the node"
        ),
        "active_path_count": 2,
        "project_count": 1,
    }

    with app.state.session_factory() as session:
        node = session.get(KnowledgeNodeModel, project["node_id"])
        assert node is not None
        assert node.status == node_status_before
        assert (
            dict(
                session.execute(
                    select(LearningPathModel.id, LearningPathModel.status).where(
                        LearningPathModel.goal_id == project["goal"]["id"]
                    )
                ).all()
            )
            == path_statuses_before
        )

    archived = client.post(f"/api/goals/{project['goal']['id']}/archive")
    assert archived.status_code == 200, archived.text
    allowed = client.delete(f"/api/spaces/{project['space']['id']}/nodes/{project['node_id']}")
    assert allowed.status_code == 204, allowed.text

    with app.state.session_factory() as session:
        node = session.get(KnowledgeNodeModel, project["node_id"])
        assert node is not None
        assert node.status == RecordStatus.ARCHIVED.value
        assert (
            dict(
                session.execute(
                    select(LearningPathModel.id, LearningPathModel.status).where(
                        LearningPathModel.goal_id == project["goal"]["id"]
                    )
                ).all()
            )
            == path_statuses_before
        )
