"""Persistent, user-scoped learning-plan library contracts."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.infrastructure.database.models import AuditLogModel
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)

SUMMARY_KEYS = {
    "id",
    "title",
    "description",
    "created_at",
    "updated_at",
    "provider",
    "model",
    "review_status",
    "intent_mode",
    "semantic_profile",
    "module_count",
    "node_count",
    "stage_count",
    "activation",
}
DETAIL_KEYS = {
    *SUMMARY_KEYS,
    "raw_structured_output",
    "confidence",
    "sources",
    "generation_input",
    "schema_version",
}


def _generate_plan(client: TestClient, topic: str) -> dict[str, Any]:
    response = client.post(
        "/api/ai/learning-plans/generate",
        json={
            "topic": topic,
            "requirements": "Build a concise practical project independently",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_second_user(client: TestClient) -> str:
    with client.app.state.session_factory() as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        user = repository.ensure_user(
            display_name="Second plan learner",
            email="second-plan-learner@example.test",
        )
        session.commit()
        return user.id


def _not_found_payload(plan_id: str) -> dict[str, Any]:
    return {
        "detail": {
            "code": "entity_not_found",
            "message": f"learning plan '{plan_id}' does not exist or is archived",
        }
    }


@pytest.mark.integration
def test_generated_plans_persist_across_requests_with_detail_and_newest_first(
    client: TestClient,
) -> None:
    first = _generate_plan(client, "First persistent plan")
    ordinary_suggestion = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "This is a knowledge-map suggestion, not a saved learning plan"},
    )
    assert ordinary_suggestion.status_code == 201, ordinary_suggestion.text
    second = _generate_plan(client, "Second persistent plan")

    listed = client.get("/api/learning-plans")

    assert listed.status_code == 200, listed.text
    plans = listed.json()
    assert [plan["id"] for plan in plans] == [second["id"], first["id"]]
    assert ordinary_suggestion.json()["id"] not in {plan["id"] for plan in plans}
    assert all(set(plan) == SUMMARY_KEYS for plan in plans)

    first_raw = first["raw_structured_output"]
    first_summary = plans[1]
    assert first_summary["title"] == first_raw["navigation"]["goal_title"]
    assert first_summary["node_count"] == len(first_raw["nodes"])
    assert first_summary["module_count"] == sum(
        node["node_type"] == "MODULE" for node in first_raw["nodes"]
    )
    assert first_summary["stage_count"] == len(first_raw["navigation"]["stages"])
    assert first_summary["intent_mode"] == first_raw["navigation"]["intent_mode"]
    assert first_summary["semantic_profile"] == first_raw["navigation"].get("semantic_profile")
    assert first_summary["activation"] is None
    assert first["prompt_version"] == "goal-framework-prompt-v1"
    assert first["proposed_changes"]["generation_input"] == {
        "topic": "First persistent plan",
        "requirements": "Build a concise practical project independently",
    }
    assert first["proposed_changes"]["schema_version"] == "learning-plan-v1"

    detail = client.get(f"/api/learning-plans/{first['id']}")
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert set(detail_payload) == DETAIL_KEYS
    assert detail_payload["id"] == first["id"]
    assert detail_payload["raw_structured_output"] == first_raw
    assert detail_payload["intent_mode"] == first_raw["navigation"]["intent_mode"]
    assert detail_payload["semantic_profile"] == first_raw["navigation"].get("semantic_profile")
    assert detail_payload["generation_input"] == first["proposed_changes"]["generation_input"]
    assert detail_payload["schema_version"] == "learning-plan-v1"
    assert detail_payload["confidence"] == first["confidence"]
    assert detail_payload["sources"] == first["sources"]
    assert {
        "user_id",
        "proposed_changes",
        "accepted_changes",
        "prompt_version",
        "reviewed_by",
        "review_note",
    }.isdisjoint(detail_payload)


@pytest.mark.integration
def test_owner_can_delete_plan_once_and_deletion_is_audited(client: TestClient) -> None:
    plan = _generate_plan(client, "Disposable persistent plan")

    deleted = client.delete(f"/api/learning-plans/{plan['id']}")

    assert deleted.status_code == 204, deleted.text
    assert deleted.content == b""
    assert client.get("/api/learning-plans").json() == []

    missing_detail = client.get(f"/api/learning-plans/{plan['id']}")
    repeated_delete = client.delete(f"/api/learning-plans/{plan['id']}")
    assert missing_detail.status_code == 404
    assert repeated_delete.status_code == 404
    assert missing_detail.json() == _not_found_payload(plan["id"])
    assert repeated_delete.json() == _not_found_payload(plan["id"])

    with client.app.state.session_factory() as session:
        audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "DELETE_LEARNING_PLAN",
                    AuditLogModel.entity_id == plan["id"],
                )
            )
        )
    assert len(audits) == 1
    assert audits[0].actor_user_id == plan["user_id"]
    assert audits[0].entity_type == "AISuggestion"
    assert audits[0].details == {
        "suggestion_type": "LEARNING_PLAN",
        "provider": plan["provider"],
        "model": plan["model"],
        "review_status": plan["review_status"],
    }


@pytest.mark.integration
def test_learning_plan_library_is_user_isolated_for_list_detail_and_delete(
    client: TestClient,
) -> None:
    owner_plan = _generate_plan(client, "Owner-only plan")
    second_headers = {"X-User-ID": _create_second_user(client)}

    assert client.get("/api/learning-plans", headers=second_headers).json() == []
    foreign_detail = client.get(
        f"/api/learning-plans/{owner_plan['id']}",
        headers=second_headers,
    )
    foreign_delete = client.delete(
        f"/api/learning-plans/{owner_plan['id']}",
        headers=second_headers,
    )

    assert foreign_detail.status_code == 404
    assert foreign_delete.status_code == 404
    assert foreign_detail.json() == _not_found_payload(owner_plan["id"])
    assert foreign_delete.json() == _not_found_payload(owner_plan["id"])
    retained = client.get(f"/api/learning-plans/{owner_plan['id']}")
    assert retained.status_code == 200, retained.text
    assert retained.json()["id"] == owner_plan["id"]
    assert retained.json()["raw_structured_output"] == owner_plan["raw_structured_output"]


@pytest.mark.integration
def test_non_learning_plan_suggestion_cannot_be_read_or_deleted_as_a_plan(
    client: TestClient,
) -> None:
    generated = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "Ordinary knowledge map proposal"},
    )
    assert generated.status_code == 201, generated.text
    suggestion = generated.json()
    assert suggestion["suggestion_type"] == "KNOWLEDGE_MAP"

    detail = client.get(f"/api/learning-plans/{suggestion['id']}")
    deleted = client.delete(f"/api/learning-plans/{suggestion['id']}")

    assert detail.status_code == 404
    assert deleted.status_code == 404
    assert detail.json() == _not_found_payload(suggestion["id"])
    assert deleted.json() == _not_found_payload(suggestion["id"])
    assert client.get("/api/learning-plans").json() == []
    retained_ids = {item["id"] for item in client.get("/api/ai/suggestions").json()}
    assert suggestion["id"] in retained_ids


@pytest.mark.integration
@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("accept", "ACCEPTED"), ("modify_accept", "MODIFIED_ACCEPTED")],
)
def test_accepted_learning_plan_cannot_be_hard_deleted(
    client: TestClient,
    action: str,
    expected_status: str,
) -> None:
    plan = _generate_plan(client, f"Protected {expected_status} plan")
    review_payload: dict[str, Any] = {"action": action}
    if action == "modify_accept":
        review_payload["edited_draft"] = plan["raw_structured_output"]
    reviewed = client.post(
        f"/api/ai/suggestions/{plan['id']}/review",
        json=review_payload,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_status"] == expected_status

    deleted = client.delete(f"/api/learning-plans/{plan['id']}")

    assert deleted.status_code == 409
    assert deleted.json()["detail"] == {
        "code": "invalid_state_transition",
        "message": "Accepted learning plans cannot be deleted from the plan library",
    }
    retained = client.get(f"/api/learning-plans/{plan['id']}")
    assert retained.status_code == 200, retained.text
    assert retained.json()["review_status"] == expected_status
    with client.app.state.session_factory() as session:
        delete_audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "DELETE_LEARNING_PLAN",
                    AuditLogModel.entity_id == plan["id"],
                )
            )
        )
    assert delete_audits == []
