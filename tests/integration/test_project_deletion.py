"""Project deletion is a recoverable, ownership-safe archive operation."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.infrastructure.database.models import (
    AIConversationMessageModel,
    AIConversationModel,
    AuditLogModel,
    KnowledgeSpaceModel,
    LearningGoalModel,
    LearningPathModel,
    UserModel,
)


def _create_project(
    client: TestClient,
    python_map: dict[str, object],
    *,
    title: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    created = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": title,
        },
    )
    assert created.status_code == 201, created.text
    project = created.json()
    generated = client.post(f"/api/goals/{project['id']}/paths")
    assert generated.status_code == 200, generated.text
    return project, generated.json()


def _create_single_node_project(
    client: TestClient,
    *,
    project_title: str,
    space_title: str,
    node_title: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create a project whose IDs are unique even when its display copy is not."""

    space_response = client.post(
        "/api/spaces",
        json={"title": space_title, "description": "删除同步契约测试"},
    )
    assert space_response.status_code == 201, space_response.text
    space = space_response.json()

    node_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={
            "title": node_title,
            "node_type": "CONCEPT",
            "difficulty": 1,
        },
    )
    assert node_response.status_code == 201, node_response.text
    node = node_response.json()

    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": node["id"],
            "title": project_title,
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goal = goal_response.json()

    path_response = client.post(f"/api/goals/{goal['id']}/paths")
    assert path_response.status_code == 200, path_response.text
    return goal, node, path_response.json()


@pytest.mark.integration
def test_project_delete_archives_only_the_selected_goal_and_its_conversations(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    first, first_path = _create_project(client, python_map, title="项目一")
    second, second_path = _create_project(client, python_map, title="项目二")
    space = python_map["space"]
    assert isinstance(space, dict)

    created_conversation = client.post(
        "/api/ai/conversations",
        json={
            "title": "项目一的长期对话",
            "space_id": space["id"],
            "goal_id": first["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": f"project:{first['id']}",
        },
    )
    assert created_conversation.status_code == 201, created_conversation.text
    conversation_id = created_conversation.json()["conversation"]["id"]
    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "请记住这条项目上下文"},
    )
    assert turn.status_code == 200, turn.text
    message_count = len(turn.json()["messages"])
    assert message_count >= 2

    deleted = client.delete(f"/api/goals/{first['id']}")
    assert deleted.status_code == 204, deleted.text

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert [item["goal"]["id"] for item in dashboard.json()["goal_overviews"]] == [second["id"]]

    graph = client.get(f"/api/spaces/{space['id']}/graph")
    assert graph.status_code == 200, graph.text
    retained_path = client.get(f"/api/goals/{second['id']}/path-revisions")
    assert retained_path.status_code == 200, retained_path.text
    assert any(item["path"]["id"] == second_path["path"]["id"] for item in retained_path.json())

    assert client.get(f"/api/goals/{first['id']}/path-revisions").status_code == 404
    assert client.get(f"/api/path-revisions/{first_path['path']['id']}").status_code == 404

    active_conversations = client.get("/api/ai/conversations")
    assert active_conversations.status_code == 200, active_conversations.text
    assert conversation_id not in {item["id"] for item in active_conversations.json()}
    archived_conversations = client.get(
        "/api/ai/conversations",
        params={
            "goal_id": first["id"],
            "include_archived": True,
        },
    )
    assert archived_conversations.status_code == 200, archived_conversations.text
    assert archived_conversations.json()[0]["id"] == conversation_id
    assert archived_conversations.json()[0]["status"] == "ARCHIVED"
    history = client.get(f"/api/ai/conversations/{conversation_id}")
    assert history.status_code == 200, history.text
    assert len(history.json()["messages"]) == message_count

    with client.app.state.session_factory() as session:
        archived_goal = session.get(LearningGoalModel, first["id"])
        retained_space = session.get(KnowledgeSpaceModel, space["id"])
        retained_path_row = session.get(LearningPathModel, first_path["path"]["id"])
        archived_conversation = session.get(AIConversationModel, conversation_id)
        assert archived_goal is not None and archived_goal.status == "ARCHIVED"
        assert retained_space is not None and retained_space.status != "ARCHIVED"
        assert retained_path_row is not None
        assert archived_conversation is not None and archived_conversation.status == "ARCHIVED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AIConversationMessageModel)
                .where(AIConversationMessageModel.conversation_id == conversation_id)
            )
            == message_count
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ARCHIVE_PROJECT",
                    AuditLogModel.entity_id == first["id"],
                )
            )
            == 1
        )

    repeated = client.delete(f"/api/goals/{first['id']}")
    assert repeated.status_code == 204, repeated.text
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ARCHIVE_PROJECT",
                    AuditLogModel.entity_id == first["id"],
                )
            )
            == 1
        )


@pytest.mark.integration
def test_project_delete_does_not_expose_another_users_project(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project, _ = _create_project(client, python_map, title="仅属于本地用户")
    with client.app.state.session_factory.begin() as session:
        other_user = UserModel(display_name="Other user")
        session.add(other_user)
        session.flush()
        other_user_id = other_user.id

    response = client.delete(
        f"/api/goals/{project['id']}",
        headers={"X-User-ID": other_user_id},
    )
    assert response.status_code == 404, response.text
    with client.app.state.session_factory() as session:
        retained = session.get(LearningGoalModel, project["id"])
        assert retained is not None and retained.status == "ACTIVE"


@pytest.mark.integration
def test_project_delete_is_goal_scoped_when_two_projects_have_the_same_node_title(
    client: TestClient,
) -> None:
    """A same-title node in another project must not keep the deleted goal alive."""

    deleted_goal, deleted_node, deleted_path = _create_single_node_project(
        client,
        project_title="已删除的代数项目",
        space_title="旧数学框架",
        node_title="实数与代数式",
    )
    retained_goal, retained_node, retained_path = _create_single_node_project(
        client,
        project_title="仍在进行的量化数学项目",
        space_title="量化数学框架",
        node_title="实数与代数式",
    )
    assert deleted_node["id"] != retained_node["id"]

    deleted = client.delete(f"/api/goals/{deleted_goal['id']}")
    assert deleted.status_code == 204, deleted.text

    dashboard_response = client.get("/api/dashboard")
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard = dashboard_response.json()
    assert dashboard["current_goal_id"] == retained_goal["id"]
    assert [item["goal"]["id"] for item in dashboard["goal_overviews"]] == [retained_goal["id"]]
    assert {
        item["node_id"]
        for overview in dashboard["goal_overviews"]
        for item in overview["route_overview"]
    } == {retained_node["id"]}
    assert dashboard["next_step"]["node_id"] == retained_node["id"]

    # Old project-scoped reading and writing entry points must no longer be usable.
    assert (
        client.get(
            f"/api/goals/{deleted_goal['id']}/nodes/{deleted_node['id']}/check-ins"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/goals/{deleted_goal['id']}/nodes/{deleted_node['id']}/check-ins",
            json={"score": 1, "note": "不应写入已删除项目"},
        ).status_code
        == 404
    )
    assert client.get(f"/api/path-revisions/{deleted_path['path']['id']}").status_code == 404

    # Generic map context may remain inspectable, but it must not advertise an
    # archived goal as an active learning route.
    deleted_context_response = client.get(f"/api/nodes/{deleted_node['id']}/learning-context")
    assert deleted_context_response.status_code == 200, deleted_context_response.text
    assert deleted_context_response.json()["route_reasons"] == []

    # A distinct project with the same visible title remains fully operational.
    retained_check_in = client.post(
        f"/api/goals/{retained_goal['id']}/nodes/{retained_node['id']}/check-ins",
        json={"score": 1, "note": "保留项目仍可继续"},
    )
    assert retained_check_in.status_code == 201, retained_check_in.text
    retained_revisions = client.get(f"/api/goals/{retained_goal['id']}/path-revisions")
    assert retained_revisions.status_code == 200, retained_revisions.text
    assert retained_revisions.json()[0]["path"]["id"] == retained_path["path"]["id"]

    # Recoverable history and the deletion audit survive even though navigation
    # access is gone.
    with client.app.state.session_factory() as session:
        archived_goal = session.get(LearningGoalModel, deleted_goal["id"])
        archived_path = session.get(LearningPathModel, deleted_path["path"]["id"])
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(
                AuditLogModel.action == "ARCHIVE_PROJECT",
                AuditLogModel.entity_id == deleted_goal["id"],
            )
        )
        assert archived_goal is not None and archived_goal.status == "ARCHIVED"
        assert archived_path is not None
        assert audit_count == 1
