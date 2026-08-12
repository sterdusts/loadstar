"""Privacy and lifecycle coverage for irreversible AI conversation deletion."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.infrastructure.database.models import (
    AIConversationMessageModel,
    AIConversationModel,
    AuditLogModel,
    LearningGoalModel,
    UserModel,
)


def _delete(
    client: TestClient,
    conversation_id: str,
    *,
    expected_revision: int,
    confirm_title: str,
    headers: dict[str, str] | None = None,
) -> Any:
    return client.request(
        "DELETE",
        f"/api/ai/conversations/{conversation_id}",
        json={
            "expected_revision": expected_revision,
            "confirm_title": confirm_title,
        },
        headers=headers,
    )


def _create_project_conversation(
    client: TestClient,
    python_map: dict[str, object],
    *,
    title: str,
    marker: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": next(iter(nodes.values())),
            "title": "Project retained after conversation deletion",
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goal = goal_response.json()
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": title,
            "space_id": space["id"],
            "goal_id": goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": f"project:{goal['id']}",
            "context_snapshot": {
                "page_key": "project-overview",
                "page_kind": "project",
                "page_title": marker,
                "space_id": space["id"],
                "goal_id": goal["id"],
            },
        },
    )
    assert created.status_code == 201, created.text
    return goal, created.json()["conversation"]


@pytest.mark.integration
def test_permanent_delete_is_archived_only_user_scoped_and_privacy_complete(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    app = cast(FastAPI, client.app)
    marker = "PRIVATE-CONVERSATION-CONTENT-9137"
    title = f"Conversation {marker}"
    goal, conversation = _create_project_conversation(
        client,
        python_map,
        title=title,
        marker=marker,
    )
    conversation_id = str(conversation["id"])
    owner_id = str(conversation["user_id"])

    with app.state.session_factory() as session:
        stored = session.get(AIConversationModel, conversation_id)
        assert stored is not None
        stored.summary = marker
        stored.working_plan = {"private_draft": marker}
        stored.final_plan = {"private_final_plan": marker}
        user_message = AIConversationMessageModel(
            conversation_id=conversation_id,
            sequence_number=1,
            role="USER",
            content=marker,
            structured_content={"private_input": marker},
            message_metadata={"page_context": marker},
        )
        tool_message = AIConversationMessageModel(
            conversation_id=conversation_id,
            sequence_number=2,
            role="TOOL",
            content="add_node pending review",
            structured_content={
                "status": "PENDING",
                "tool_call_id": "proposal-private",
                "proposal": {"arguments": {"description": marker}},
            },
            tool_call_id="proposal-private",
            tool_name="add_node",
            message_metadata={"requires_human_review": True, "private": marker},
        )
        session.add_all([user_message, tool_message])
        session.flush()
        message_ids = [user_message.id, tool_message.id]
        session.add(
            AuditLogModel(
                actor_user_id=owner_id,
                action="AI_CONTEXT_TRACE",
                entity_type="LearningGoal",
                entity_id=goal["id"],
                details={"conversation_id": conversation_id, "private": marker},
            )
        )
        session.commit()

    current = client.get(f"/api/ai/conversations/{conversation_id}")
    assert current.status_code == 200, current.text
    active_revision = current.json()["conversation"]["row_version"]

    active_delete = _delete(
        client,
        conversation_id,
        expected_revision=active_revision,
        confirm_title=title,
    )
    assert active_delete.status_code == 409, active_delete.text
    assert active_delete.json()["detail"]["code"] == "invalid_state_transition"

    archived = client.post(
        f"/api/ai/conversations/{conversation_id}/archive",
        json={"expected_revision": active_revision},
    )
    assert archived.status_code == 200, archived.text
    archived_revision = archived.json()["conversation"]["row_version"]

    stale = _delete(
        client,
        conversation_id,
        expected_revision=active_revision,
        confirm_title=title,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "revision_conflict"
    wrong_title = _delete(
        client,
        conversation_id,
        expected_revision=archived_revision,
        confirm_title="wrong title",
    )
    assert wrong_title.status_code == 409, wrong_title.text

    with app.state.session_factory() as session:
        other_user = UserModel(display_name="Other learner")
        session.add(other_user)
        session.commit()
        other_user_id = other_user.id
    foreign_delete = _delete(
        client,
        conversation_id,
        expected_revision=archived_revision,
        confirm_title=title,
        headers={"X-User-ID": other_user_id},
    )
    assert foreign_delete.status_code == 404, foreign_delete.text

    deleted = _delete(
        client,
        conversation_id,
        expected_revision=archived_revision,
        confirm_title=title,
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404

    exported = client.get("/api/data/export")
    assert exported.status_code == 200, exported.text
    export_payload = exported.json()
    assert conversation_id not in {item["id"] for item in export_payload["ai_conversations"]}
    assert not set(message_ids) & {
        item["id"] for item in export_payload["ai_conversation_messages"]
    }
    assert marker not in json.dumps(export_payload, ensure_ascii=False)

    with app.state.session_factory() as session:
        assert session.get(AIConversationModel, conversation_id) is None
        assert session.get(LearningGoalModel, goal["id"]) is not None
        assert not list(
            session.scalars(
                select(AIConversationMessageModel).where(
                    AIConversationMessageModel.id.in_(message_ids)
                )
            )
        )
        audits = list(
            session.scalars(select(AuditLogModel).where(AuditLogModel.actor_user_id == owner_id))
        )
        deletion = next(
            row
            for row in audits
            if row.action == "DELETE_AI_CONVERSATION" and row.entity_id == conversation_id
        )
        assert deletion.before_state is None
        assert deletion.after_state is None
        assert deletion.details == {
            "permanent": True,
            "content_redacted": True,
            "deleted_message_count": 2,
        }
        related = [
            row
            for row in audits
            if row.entity_id == conversation_id or row.action == "AI_CONTEXT_TRACE"
        ]
        assert all(row.before_state is None and row.after_state is None for row in related)
        assert all(
            row is deletion
            or row.details
            == {
                "redacted": True,
                "reason": "AI_CONVERSATION_PERMANENTLY_DELETED",
            }
            for row in related
        )
        assert marker not in json.dumps(
            [
                {
                    "before": row.before_state,
                    "after": row.after_state,
                    "details": row.details,
                }
                for row in audits
            ],
            ensure_ascii=False,
        )


@pytest.mark.integration
def test_empty_archived_conversation_cannot_be_permanently_deleted(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/ai/conversations",
        json={"title": "Empty hidden conversation"},
    )
    assert created.status_code == 201, created.text
    conversation = created.json()["conversation"]
    archived = client.post(
        f"/api/ai/conversations/{conversation['id']}/archive",
        json={"expected_revision": conversation["row_version"]},
    )
    assert archived.status_code == 200, archived.text
    archived_conversation = archived.json()["conversation"]

    response = _delete(
        client,
        str(conversation["id"]),
        expected_revision=archived_conversation["row_version"],
        confirm_title=str(conversation["title"]),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "invalid_state_transition"
    assert client.get(f"/api/ai/conversations/{conversation['id']}").status_code == 200
