"""Project trash, restore and permanent deletion lifecycle contracts."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.infrastructure.database.models import (
    AIConversationModel,
    AISuggestionModel,
    AssessmentAttemptModel,
    AssessmentModel,
    AuditLogModel,
    KnowledgeMapVersionModel,
    KnowledgeNodeModel,
    KnowledgeNodeVersionModel,
    KnowledgeSpaceModel,
    LearnerNodeStateModel,
    LearningEvidenceModel,
    LearningGoalModel,
    LearningPathModel,
    LearningResourceModel,
    LearningSessionModel,
    NodeProgressCheckInModel,
    ProgressCheckInAttachmentModel,
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
    target_node_id = next(reversed(nodes.values()))
    created = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": target_node_id,
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
    space_response = client.post(
        "/api/spaces",
        json={"title": space_title, "description": "Project-owned framework"},
    )
    assert space_response.status_code == 201, space_response.text
    space = space_response.json()
    node_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": node_title, "node_type": "CONCEPT", "difficulty": 1},
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


def _create_project_conversation(
    client: TestClient,
    *,
    goal: dict[str, Any],
) -> str:
    response = client.post(
        "/api/ai/conversations",
        json={
            "title": "Project assistant",
            "space_id": goal["space_id"],
            "goal_id": goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": f"project:{goal['id']}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["conversation"]["id"])


def _archive_project(client: TestClient, goal: dict[str, Any]) -> Any:
    return client.post(f"/api/goals/{goal['id']}/archive")


def _permanently_delete_project(client: TestClient, goal: dict[str, Any]) -> Any:
    return client.request(
        "DELETE",
        f"/api/goals/{goal['id']}",
        json={"confirm_title": goal["title"]},
    )


@pytest.mark.integration
def test_archive_restore_is_idempotent_and_preserves_project_state(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, path = _create_project(client, python_map, title="Recoverable project")
    conversation_id = _create_project_conversation(client, goal=goal)
    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Keep this project history"},
    )
    assert turn.status_code == 200, turn.text
    conversation_revision = turn.json()["conversation"]["row_version"]
    check_in = client.post(
        f"/api/goals/{goal['id']}/nodes/{goal['target_node_id']}/check-ins",
        json={"score": 3, "note": "Keep this progress"},
    )
    assert check_in.status_code == 201, check_in.text

    archived = _archive_project(client, goal)
    assert archived.status_code == 200, archived.text
    assert archived.json()["goal"]["status"] == "ARCHIVED"
    assert archived.json()["archived_conversation_count"] == 1
    assert archived.json()["changed"] is True
    assert _archive_project(client, goal).json()["changed"] is False

    dashboard = client.get("/api/dashboard").json()
    assert goal["id"] not in {row["goal"]["id"] for row in dashboard["goal_overviews"]}
    trash = client.get("/api/goals/archived")
    assert trash.status_code == 200, trash.text
    archived_summary = next(item for item in trash.json() if item["goal"]["id"] == goal["id"])
    assert archived_summary["path_revision_count"] == 1
    assert archived_summary["conversation_count"] == 1
    assert client.get(f"/api/goals/{goal['id']}/path-revisions").status_code == 404
    assert client.get(f"/api/path-revisions/{path['path']['id']}").status_code == 404
    assert conversation_id not in {
        item["id"] for item in client.get("/api/ai/conversations").json()
    }

    archived_history = client.get(
        "/api/ai/conversations",
        params={"goal_id": goal["id"], "include_archived": True},
    )
    assert archived_history.status_code == 200, archived_history.text
    assert archived_history.json()[0]["id"] == conversation_id
    assert archived_history.json()[0]["row_version"] == conversation_revision + 1

    restored = client.post(f"/api/goals/{goal['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["goal"]["status"] == "ACTIVE"
    assert restored.json()["restored_conversation_count"] == 1
    assert restored.json()["changed"] is True
    assert client.post(f"/api/goals/{goal['id']}/restore").json()["changed"] is False
    assert client.get(f"/api/goals/{goal['id']}/path-revisions").status_code == 200
    assert conversation_id in {item["id"] for item in client.get("/api/ai/conversations").json()}
    check_ins = client.get(f"/api/goals/{goal['id']}/nodes/{goal['target_node_id']}/check-ins")
    assert check_ins.status_code == 200, check_ins.text
    assert check_ins.json()["items"][0]["note"] == "Keep this progress"

    with client.app.state.session_factory() as session:
        archive_audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ARCHIVE_PROJECT",
                    AuditLogModel.entity_id == goal["id"],
                )
            )
        )
        restore_audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "RESTORE_PROJECT",
                    AuditLogModel.entity_id == goal["id"],
                )
            )
        )
        assert len(archive_audits) == 1
        assert archive_audits[0].details["auto_archived_conversation_ids"] == [conversation_id]
        assert len(restore_audits) == 1


@pytest.mark.integration
def test_delete_removes_only_selected_project_from_a_shared_framework(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    deleted_goal, deleted_path = _create_project(client, python_map, title="First project")
    retained_goal, retained_path = _create_project(client, python_map, title="Second project")
    target_node_id = deleted_goal["target_node_id"]
    conversation_id = _create_project_conversation(client, goal=deleted_goal)
    check_in = client.post(
        f"/api/goals/{deleted_goal['id']}/nodes/{target_node_id}/check-ins",
        json={"score": 4, "note": "Sensitive note must not survive"},
    )
    assert check_in.status_code == 201, check_in.text
    check_in_id = check_in.json()["id"]
    attachment_response = client.post(
        f"/api/progress-check-ins/{check_in_id}/attachments",
        content=b"project-owned-attachment",
        headers={
            "Content-Type": "application/pdf",
            "X-File-Name": "project-evidence.pdf",
        },
    )
    assert attachment_response.status_code == 201, attachment_response.text
    attachment_id = attachment_response.json()["id"]
    with client.app.state.session_factory() as session:
        attachment_row = session.get(ProgressCheckInAttachmentModel, attachment_id)
        assert attachment_row is not None
        attachment_path = client.app.state.check_in_attachment_storage.path_for(
            attachment_row.storage_key
        )
        assert attachment_path.is_file()

    active_delete = _permanently_delete_project(client, deleted_goal)
    assert active_delete.status_code == 409, active_delete.text
    assert _archive_project(client, deleted_goal).status_code == 200
    response = _permanently_delete_project(client, deleted_goal)
    assert response.status_code == 204, response.text
    assert not attachment_path.exists()
    with client.app.state.session_factory() as session:
        assert session.get(ProgressCheckInAttachmentModel, attachment_id) is None

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert [row["goal"]["id"] for row in dashboard.json()["goal_overviews"]] == [
        retained_goal["id"]
    ]
    assert client.get(f"/api/goals/{deleted_goal['id']}/path-revisions").status_code == 404
    assert client.get(f"/api/path-revisions/{deleted_path['path']['id']}").status_code == 404
    assert (
        client.get(f"/api/goals/{deleted_goal['id']}/nodes/{target_node_id}/check-ins").status_code
        == 404
    )
    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404

    retained_revisions = client.get(f"/api/goals/{retained_goal['id']}/path-revisions")
    assert retained_revisions.status_code == 200, retained_revisions.text
    assert retained_revisions.json()[0]["path"]["id"] == retained_path["path"]["id"]

    space = python_map["space"]
    assert isinstance(space, dict)
    assert client.get(f"/api/spaces/{space['id']}/graph").status_code == 200
    with client.app.state.session_factory() as session:
        assert session.get(LearningGoalModel, deleted_goal["id"]) is None
        assert session.get(LearningPathModel, deleted_path["path"]["id"]) is None
        assert session.get(NodeProgressCheckInModel, check_in_id) is None
        assert session.get(AIConversationModel, conversation_id) is None
        assert session.get(LearningGoalModel, retained_goal["id"]) is not None
        audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.entity_id.in_([deleted_goal["id"], check_in_id])
                )
            )
        )
        deletion = next(row for row in audits if row.action == "DELETE_PROJECT")
        assert deletion.before_state is None
        assert deletion.after_state is None
        assert "Sensitive note" not in str(audits)
        assert deletion.details["permanent"] is True
        assert deletion.details["framework_deleted"] is False

    assert _permanently_delete_project(client, deleted_goal).status_code == 404


@pytest.mark.integration
def test_delete_reclaims_an_orphan_framework_and_all_its_history(client: TestClient) -> None:
    goal, node, path = _create_single_node_project(
        client,
        project_title="Disposable project",
        space_title="Disposable framework",
        node_title="Disposable node",
    )
    conversation_id = _create_project_conversation(client, goal=goal)
    check_in = client.post(
        f"/api/goals/{goal['id']}/nodes/{node['id']}/check-ins",
        json={"score": 3, "note": "delete me"},
    )
    assert check_in.status_code == 201, check_in.text

    created_ids: dict[str, str] = {}
    with client.app.state.session_factory.begin() as session:
        state = LearnerNodeStateModel(user_id=goal["user_id"], node_id=node["id"])
        learning_session = LearningSessionModel(
            user_id=goal["user_id"],
            node_id=node["id"],
            started_at=datetime.now(UTC),
            note="project session",
        )
        resource = LearningResourceModel(
            node_id=node["id"],
            title="project resource",
            resource_type="TEXT",
            created_by=goal["user_id"],
        )
        assessment = AssessmentModel(
            node_id=node["id"],
            title="project assessment",
            created_by=goal["user_id"],
        )
        suggestion = AISuggestionModel(
            user_id=goal["user_id"],
            space_id=goal["space_id"],
            suggestion_type="MAP_CHANGE",
            provider="mock",
            model="mock",
            prompt_version="test",
            raw_structured_output={},
            proposed_changes={},
            confidence=1.0,
        )
        session.add_all([state, learning_session, resource, assessment, suggestion])
        session.flush()
        evidence = LearningEvidenceModel(
            user_id=goal["user_id"],
            node_id=node["id"],
            session_id=learning_session.id,
            evidence_type="NOTE",
            title="project evidence",
        )
        attempt = AssessmentAttemptModel(
            assessment_id=assessment.id,
            user_id=goal["user_id"],
            response={"answer": "project answer"},
        )
        session.add_all([evidence, attempt])
        session.flush()
        created_ids = {
            "state": state.id,
            "session": learning_session.id,
            "resource": resource.id,
            "assessment": assessment.id,
            "suggestion": suggestion.id,
            "evidence": evidence.id,
            "attempt": attempt.id,
        }

    assert _archive_project(client, goal).status_code == 200
    response = _permanently_delete_project(client, goal)
    assert response.status_code == 204, response.text
    assert client.get(f"/api/spaces/{goal['space_id']}/graph").status_code == 404
    assert client.get(f"/api/path-revisions/{path['path']['id']}").status_code == 404
    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404

    export_response = client.get("/api/data/export")
    assert export_response.status_code == 200, export_response.text
    exported = export_response.json()
    non_audit_export = json.dumps(
        {key: value for key, value in exported.items() if key not in {"audit_logs", "audit"}},
        ensure_ascii=False,
    )
    for deleted_id in (
        goal["id"],
        goal["space_id"],
        path["path"]["id"],
        node["id"],
        *created_ids.values(),
    ):
        assert deleted_id not in non_audit_export

    # The internal audit trail keeps accountability, but portable exports must
    # not resurrect the identifier of a project that was permanently deleted.
    audit_export = json.dumps(
        exported.get("audit_logs", []) + exported.get("audit", []), ensure_ascii=False
    )
    assert goal["id"] not in audit_export
    deletion_audits = [
        item for item in exported.get("audit_logs", []) if item.get("action") == "DELETE_PROJECT"
    ]
    assert deletion_audits
    assert deletion_audits[-1]["entity_id"] is None
    assert deletion_audits[-1]["before_state"] is None
    assert deletion_audits[-1]["after_state"] is None

    models_and_ids = (
        (LearningGoalModel, goal["id"]),
        (LearningPathModel, path["path"]["id"]),
        (KnowledgeSpaceModel, goal["space_id"]),
        (KnowledgeNodeModel, node["id"]),
        (LearnerNodeStateModel, created_ids["state"]),
        (LearningSessionModel, created_ids["session"]),
        (LearningResourceModel, created_ids["resource"]),
        (AssessmentModel, created_ids["assessment"]),
        (AISuggestionModel, created_ids["suggestion"]),
        (LearningEvidenceModel, created_ids["evidence"]),
        (AssessmentAttemptModel, created_ids["attempt"]),
    )
    with client.app.state.session_factory() as session:
        for model, row_id in models_and_ids:
            assert session.get(model, row_id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeMapVersionModel)
                .where(KnowledgeMapVersionModel.space_id == goal["space_id"])
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeNodeVersionModel)
                .where(KnowledgeNodeVersionModel.space_id == goal["space_id"])
            )
            == 0
        )
        deletion = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "DELETE_PROJECT",
                AuditLogModel.entity_id == goal["id"],
            )
        )
        assert deletion is not None
        assert deletion.details["framework_deleted"] is True


@pytest.mark.integration
def test_delete_accepts_a_previously_archived_project(client: TestClient) -> None:
    goal, node, _ = _create_single_node_project(
        client,
        project_title="Previously archived",
        space_title="Archived framework",
        node_title="Archived node",
    )
    with client.app.state.session_factory.begin() as session:
        row = session.get(LearningGoalModel, goal["id"])
        assert row is not None
        row.status = "ARCHIVED"

    missing_confirmation = client.delete(f"/api/goals/{goal['id']}")
    assert missing_confirmation.status_code == 409, missing_confirmation.text
    wrong_confirmation = client.request(
        "DELETE",
        f"/api/goals/{goal['id']}",
        json={"confirm_title": "wrong title"},
    )
    assert wrong_confirmation.status_code == 409, wrong_confirmation.text
    response = _permanently_delete_project(client, goal)
    assert response.status_code == 204, response.text
    with client.app.state.session_factory() as session:
        assert session.get(LearningGoalModel, goal["id"]) is None
        assert session.get(KnowledgeNodeModel, node["id"]) is None


@pytest.mark.integration
def test_delete_is_id_scoped_for_same_title_projects(client: TestClient) -> None:
    deleted_goal, deleted_node, _ = _create_single_node_project(
        client,
        project_title="Same title",
        space_title="First framework",
        node_title="Same node title",
    )
    retained_goal, retained_node, retained_path = _create_single_node_project(
        client,
        project_title="Same title",
        space_title="Second framework",
        node_title="Same node title",
    )
    assert deleted_node["id"] != retained_node["id"]

    assert _archive_project(client, deleted_goal).status_code == 200
    response = _permanently_delete_project(client, deleted_goal)
    assert response.status_code == 204, response.text
    assert client.get(f"/api/goals/{retained_goal['id']}/path-revisions").status_code == 200
    assert client.get(f"/api/path-revisions/{retained_path['path']['id']}").status_code == 200
    assert client.get(f"/api/nodes/{retained_node['id']}/learning-context").status_code == 200
    with client.app.state.session_factory() as session:
        assert session.get(KnowledgeNodeModel, deleted_node["id"]) is None
        assert session.get(KnowledgeNodeModel, retained_node["id"]) is not None


@pytest.mark.integration
def test_delete_does_not_expose_or_mutate_another_users_project(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    project, _ = _create_project(client, python_map, title="Owner project")
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
        assert session.get(LearningGoalModel, project["id"]) is not None
