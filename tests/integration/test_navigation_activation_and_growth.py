"""P0 contracts connecting generated plans to the formal navigation lifecycle."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.infrastructure.database.models import (
    AISuggestionModel,
    KnowledgeEdgeModel,
    KnowledgeMapVersionModel,
    KnowledgeSpaceModel,
    LearnerNodeStateModel,
    LearningGoalModel,
    LearningPathModel,
)


def _generate_plan(client: TestClient, topic: str = "Graph-based learning") -> dict[str, Any]:
    response = client.post(
        "/api/ai/learning-plans/generate",
        json={
            "topic": topic,
            "requirements": "Reach a verifiable project-level outcome without skipping basics",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
def test_learning_plan_activation_is_formal_auditable_and_idempotent(
    client: TestClient,
) -> None:
    plan = _generate_plan(client)

    activated = client.post(f"/api/learning-plans/{plan['id']}/activate")

    assert activated.status_code == 200, activated.text
    result = activated.json()
    activation = result["activation"]
    assert result["space"]["status"] == "ACTIVE"
    assert result["goal"]["space_id"] == result["space"]["id"]
    assert result["goal"]["target_node_id"] in {
        item["node_id"] for item in result["route"]["items"]
    }
    assert result["route"]["path"]["map_version_id"] == activation["published_map_version_id"]

    graph = client.get(f"/api/spaces/{result['space']['id']}/graph")
    assert graph.status_code == 200, graph.text
    assert graph.json()["cycle"] is None
    detail = client.get(f"/api/learning-plans/{plan['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["review_status"] == "ACCEPTED"
    source = plan["raw_structured_output"]
    title_by_temp_id = {node["temp_id"]: node["title"] for node in source["nodes"]}
    module_temp_ids = {node["temp_id"] for node in source["nodes"] if node["node_type"] == "MODULE"}
    expected_temp_order = [
        temp_id for stage in source["navigation"]["stages"] for temp_id in stage["node_temp_ids"]
    ]
    assert not module_temp_ids.intersection(expected_temp_order)
    assert [item["title"] for item in result["route"]["items"]] == [
        title_by_temp_id[temp_id] for temp_id in expected_temp_order
    ]

    repeated = client.post(f"/api/learning-plans/{plan['id']}/activate")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["activation"] == activation

    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSpaceModel)) == 1
        assert session.scalar(select(func.count()).select_from(LearningGoalModel)) == 1
        assert session.scalar(select(func.count()).select_from(LearningPathModel)) == 1
        assert session.scalar(select(func.count()).select_from(LearnerNodeStateModel)) == 0
        published = session.get(
            KnowledgeMapVersionModel,
            activation["published_map_version_id"],
        )
        assert published is not None
        assert published.status == "PUBLISHED"
        edges = list(
            session.scalars(
                select(KnowledgeEdgeModel).where(KnowledgeEdgeModel.map_version_id == published.id)
            )
        )
        assert edges
        assert all(
            any(source.get("suggestion_id") == plan["id"] for source in edge.source_reference)
            for edge in edges
        )
        suggestion = session.get(AISuggestionModel, plan["id"])
        assert suggestion is not None
        assert suggestion.accepted_changes["activation"]["goal_id"] == result["goal"]["id"]


@pytest.mark.integration
def test_activating_plans_switches_dashboard_to_the_selected_goal_and_space(
    client: TestClient,
) -> None:
    first_plan = _generate_plan(client, "First selectable plan")
    second_plan = _generate_plan(client, "Second selectable plan")

    first = client.post(f"/api/learning-plans/{first_plan['id']}/activate")
    assert first.status_code == 200, first.text
    first_activation = first.json()
    first_dashboard = client.get("/api/dashboard")
    assert first_dashboard.status_code == 200, first_dashboard.text
    assert first_dashboard.json()["current_goal"]["id"] == first_activation["goal"]["id"]
    assert first_dashboard.json()["current_goal"]["space_id"] == first_activation["space"]["id"]

    second = client.post(f"/api/learning-plans/{second_plan['id']}/activate")
    assert second.status_code == 200, second.text
    second_activation = second.json()
    assert second_activation["goal"]["id"] != first_activation["goal"]["id"]
    assert second_activation["space"]["id"] != first_activation["space"]["id"]

    second_dashboard = client.get("/api/dashboard")
    assert second_dashboard.status_code == 200, second_dashboard.text
    assert second_dashboard.json()["current_goal"]["id"] == second_activation["goal"]["id"]
    assert second_dashboard.json()["current_goal"]["space_id"] == second_activation["space"]["id"]
    assert (
        second_dashboard.json()["current_goal"]["title"]
        == second_plan["raw_structured_output"]["navigation"]["goal_title"]
    )
    second_payload = second_dashboard.json()
    assert second_payload["current_goal_id"] == second_activation["goal"]["id"]
    assert [item["goal"]["id"] for item in second_payload["goal_overviews"]] == [
        second_activation["goal"]["id"],
        first_activation["goal"]["id"],
    ]
    assert [item["is_current"] for item in second_payload["goal_overviews"]] == [True, False]
    assert second_payload["route_overview"] == second_payload["goal_overviews"][0]["route_overview"]
    assert {item["goal"]["space_id"] for item in second_payload["goal_overviews"]} == {
        first_activation["space"]["id"],
        second_activation["space"]["id"],
    }

    selected_again = client.post(f"/api/learning-plans/{first_plan['id']}/activate")
    assert selected_again.status_code == 200, selected_again.text
    assert selected_again.json()["goal"]["id"] == first_activation["goal"]["id"]
    assert selected_again.json()["space"]["id"] == first_activation["space"]["id"]

    selected_dashboard = client.get("/api/dashboard")
    assert selected_dashboard.status_code == 200, selected_dashboard.text
    assert selected_dashboard.json()["current_goal"]["id"] == first_activation["goal"]["id"]
    assert selected_dashboard.json()["current_goal"]["space_id"] == first_activation["space"]["id"]
    assert [item["goal"]["id"] for item in selected_dashboard.json()["goal_overviews"]] == [
        first_activation["goal"]["id"],
        second_activation["goal"]["id"],
    ]

    summaries = {plan["id"]: plan for plan in client.get("/api/learning-plans").json()}
    assert summaries[first_plan["id"]]["activation"] == {
        "space_id": first_activation["space"]["id"],
        "goal_id": first_activation["goal"]["id"],
        "activated_at": first_activation["activation"]["activated_at"],
    }
    assert summaries[second_plan["id"]]["activation"] == {
        "space_id": second_activation["space"]["id"],
        "goal_id": second_activation["goal"]["id"],
        "activated_at": second_activation["activation"]["activated_at"],
    }
    second_graph = client.get(f"/api/spaces/{second_activation['space']['id']}/graph")
    assert second_graph.status_code == 200, second_graph.text
    assert (
        sum(
            node["status"] != "ARCHIVED" and node["node_type"] == "MODULE"
            for node in second_graph.json()["nodes"]
        )
        == summaries[second_plan["id"]]["module_count"]
    )


@pytest.mark.integration
def test_sessions_have_a_scoped_paginated_timeline_and_feed_growth(
    client: TestClient,
) -> None:
    activated = client.post(
        f"/api/learning-plans/{_generate_plan(client, 'Timeline growth')['id']}/activate"
    ).json()
    node_id = activated["route"]["items"][0]["node_id"]
    now = datetime.now(UTC)
    first = client.post(
        "/api/learning-sessions",
        json={
            "node_id": node_id,
            "started_at": (now - timedelta(hours=2)).isoformat(),
            "ended_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
            "note": "First study session",
            "evidence": [{"evidence_type": "NOTE", "title": "Study note"}],
        },
    )
    second = client.post(
        "/api/learning-sessions",
        json={
            "node_id": node_id,
            "started_at": (now - timedelta(hours=1)).isoformat(),
            "ended_at": (now - timedelta(minutes=15)).isoformat(),
            "note": "Most recent study session",
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    page = client.get("/api/learning-sessions?limit=1&offset=0")
    assert page.status_code == 200, page.text
    payload = page.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert [item["id"] for item in payload["items"]] == [second.json()["session"]["id"]]
    assert payload["items"][0]["node"]["id"] == node_id
    assert payload["items"][0]["node"]["title"]
    assert payload["items"][0]["duration_minutes"] == 45.0

    growth = client.get("/api/growth?days=7")
    assert growth.status_code == 200, growth.text
    summary = growth.json()["summary"]
    assert summary["total_sessions"] == 2
    assert summary["total_evidence"] == 1
    assert summary["total_learning_minutes"] == 75.0
    assert summary["touched_nodes"] == 1
    assert summary["coverage_rate"] > 0
    assert len(growth.json()["series"]) == 7
    assert sum(item["session_count"] for item in growth.json()["series"]) == 2


@pytest.mark.integration
def test_growth_has_a_stable_zero_shape_without_learning_data(client: TestClient) -> None:
    response = client.get("/api/growth?days=7")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"] == {
        "total_nodes": 0,
        "touched_nodes": 0,
        "tracked_nodes": 0,
        "mastered_nodes": 0,
        "review_due_nodes": 0,
        "coverage_rate": 0.0,
        "average_mastery_score": 0.0,
        "total_sessions": 0,
        "total_check_ins": 0,
        "total_evidence": 0,
        "total_learning_minutes": 0,
        "active_days": 0,
        "last_activity_at": None,
    }
    assert len(payload["series"]) == 7
    assert all(item["coverage_rate"] == 0.0 for item in payload["series"])
