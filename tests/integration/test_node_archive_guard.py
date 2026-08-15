"""Permanent framework deletion stays synchronized with paths and projections."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.infrastructure.database.models import (
    AISuggestionModel,
    AuditLogModel,
    KnowledgeEdgeModel,
    KnowledgeNodeModel,
    KnowledgeNodeVersionModel,
    LearningGoalModel,
    LearningPathModel,
    LearningPathNodeModel,
    UserModel,
)


def _project_with_active_and_draft_paths(
    client: TestClient,
    python_map: dict[str, object],
) -> dict[str, Any]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": list(nodes.values())[-1],
            "title": "Synchronized deletion project",
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goal = goal_response.json()
    active = client.post(f"/api/goals/{goal['id']}/paths").json()
    draft = client.post(
        f"/api/goals/{goal['id']}/path-revisions",
        json={"change_summary": "Editable candidate"},
    ).json()
    return {
        "space": space,
        "goal": goal,
        "active": active,
        "draft": draft,
        "node_id": active["items"][0]["node_id"],
    }


@pytest.mark.integration
def test_delete_impact_and_delete_remove_all_path_references(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    space_id = project["space"]["id"]
    node_id = project["node_id"]

    impact = client.get(f"/api/spaces/{space_id}/nodes/{node_id}/delete-impact")
    assert impact.status_code == 200, impact.text
    assert impact.json()["node_count"] == 1
    assert impact.json()["path_count"] == 2
    assert impact.json()["path_step_count"] == 2

    deleted = client.delete(f"/api/spaces/{space_id}/nodes/{node_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert deleted.json()["path_step_count"] == 2

    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    assert node_id not in {node["id"] for node in graph["nodes"]}
    assert all(
        edge["source_node_id"] != node_id and edge["target_node_id"] != node_id
        for edge in graph["edges"]
    )
    for path in (project["active"], project["draft"]):
        detail = client.get(f"/api/path-revisions/{path['path']['id']}")
        assert detail.status_code == 200, detail.text
        assert node_id not in {step["node_id"] for step in detail.json()["steps"]}
        assert [step["sequence_number"] for step in detail.json()["steps"]] == list(
            range(len(detail.json()["steps"]))
        )


@pytest.mark.integration
def test_module_delete_removes_children_and_current_relationships(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    assert isinstance(space, dict)
    module = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": "Test module", "node_type": "MODULE"},
    ).json()
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    children = {graph["nodes"][0]["id"], graph["nodes"][1]["id"]}
    for child_id in children:
        edge = client.post(
            f"/api/spaces/{space['id']}/edges",
            json={
                "source_node_id": module["id"],
                "target_node_id": child_id,
                "relation_type": "CONTAINS",
            },
        )
        assert edge.status_code == 201, edge.text
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert children

    impact = client.get(f"/api/spaces/{space['id']}/nodes/{module['id']}/delete-impact").json()
    assert impact["node_count"] == len(children) + 1
    response = client.delete(f"/api/spaces/{space['id']}/nodes/{module['id']}")
    assert response.status_code == 200, response.text

    refreshed = client.get(f"/api/spaces/{space['id']}/graph").json()
    removed_ids = {module["id"], *children}
    assert removed_ids.isdisjoint({node["id"] for node in refreshed["nodes"]})
    assert all(
        edge["source_node_id"] not in removed_ids and edge["target_node_id"] not in removed_ids
        for edge in refreshed["edges"]
    )


@pytest.mark.integration
def test_permanent_node_delete_removes_version_rows_and_redacts_audit(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    node_id = next(iter(nodes.values()))
    app = cast(FastAPI, client.app)

    response = client.delete(f"/api/spaces/{space['id']}/nodes/{node_id}")
    assert response.status_code == 200, response.text

    with app.state.session_factory() as session:
        assert session.get(KnowledgeNodeModel, node_id) is None
        assert (
            session.scalar(
                select(KnowledgeNodeVersionModel.id).where(
                    KnowledgeNodeVersionModel.node_id == node_id
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(KnowledgeEdgeModel.id).where(
                    (KnowledgeEdgeModel.source_node_id == node_id)
                    | (KnowledgeEdgeModel.target_node_id == node_id)
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(LearningPathNodeModel.id).where(LearningPathNodeModel.node_id == node_id)
            )
            is None
        )
        deletion_audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "DELETE_FRAMEWORK_NODE",
                AuditLogModel.entity_id == node_id,
            )
        )
        assert deletion_audit is not None
        assert deletion_audit.details["permanent"] is True


@pytest.mark.integration
def test_node_delete_does_not_change_path_status_or_other_nodes(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        status_before = dict(
            session.execute(
                select(LearningPathModel.id, LearningPathModel.status).where(
                    LearningPathModel.goal_id == project["goal"]["id"]
                )
            ).all()
        )
    deleted = client.delete(f"/api/spaces/{project['space']['id']}/nodes/{project['node_id']}")
    assert deleted.status_code == 200, deleted.text
    with app.state.session_factory() as session:
        assert (
            dict(
                session.execute(
                    select(LearningPathModel.id, LearningPathModel.status).where(
                        LearningPathModel.goal_id == project["goal"]["id"]
                    )
                ).all()
            )
            == status_before
        )


@pytest.mark.integration
def test_delete_scrubs_denormalized_path_relationships_and_ai_artifacts(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project = _project_with_active_and_draft_paths(client, python_map)
    node_id = project["node_id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        remaining = session.scalar(
            select(LearningPathNodeModel).where(
                LearningPathNodeModel.path_id == project["active"]["path"]["id"],
                LearningPathNodeModel.node_id != node_id,
            )
        )
        assert remaining is not None
        remaining.satisfied_prerequisites = [node_id]
        remaining.unmet_prerequisites = [node_id]
        remaining.unlocks = [node_id]
        suggestion = AISuggestionModel(
            user_id=project["goal"]["user_id"],
            space_id=project["space"]["id"],
            suggestion_type="PATH_ADJUSTMENT",
            target_type="KnowledgeNode",
            target_id=node_id,
            provider="mock",
            model="mock",
            prompt_version="test",
            raw_structured_output={"node_id": node_id},
            proposed_changes={"remove": node_id},
            reason="test",
            confidence=1.0,
            sources=[],
        )
        audit = AuditLogModel(
            actor_user_id=project["goal"]["user_id"],
            action="TEST_REFERENCE",
            entity_type="OtherEntity",
            entity_id="unrelated-entity",
            details={"node_id": node_id},
        )
        session.add_all([suggestion, audit])
        session.commit()
        suggestion_id = suggestion.id
        audit_id = audit.id

    response = client.delete(f"/api/spaces/{project['space']['id']}/nodes/{node_id}")
    assert response.status_code == 200, response.text
    assert response.json()["suggestion_count"] == 1
    with app.state.session_factory() as session:
        rows = list(
            session.scalars(
                select(LearningPathNodeModel).where(
                    LearningPathNodeModel.path_id == project["active"]["path"]["id"]
                )
            )
        )
        assert all(node_id not in (row.satisfied_prerequisites or []) for row in rows)
        assert all(node_id not in (row.unmet_prerequisites or []) for row in rows)
        assert all(node_id not in (row.unlocks or []) for row in rows)
        assert session.get(AISuggestionModel, suggestion_id) is None
        redacted = session.get(AuditLogModel, audit_id)
        assert redacted is not None
        assert redacted.details == {
            "redacted": True,
            "reason": "FRAMEWORK_ELEMENT_PERMANENTLY_DELETED",
        }


@pytest.mark.integration
def test_delete_fails_closed_if_another_user_has_a_node_reference(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = cast(dict[str, Any], python_map["space"])
    nodes = cast(dict[str, str], python_map["nodes"])
    node_id = next(iter(nodes.values()))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        other = UserModel(display_name="Other learner")
        session.add(other)
        session.flush()
        other_goal = LearningGoalModel(
            user_id=other.id,
            space_id=space["id"],
            target_node_id=node_id,
            title="Malformed shared reference",
            status="ACTIVE",
        )
        session.add(other_goal)
        session.commit()

    response = client.delete(f"/api/spaces/{space['id']}/nodes/{node_id}")
    assert response.status_code == 409, response.text
    assert client.get(f"/api/spaces/{space['id']}/graph").status_code == 200
    with app.state.session_factory() as session:
        assert session.get(KnowledgeNodeModel, node_id) is not None
