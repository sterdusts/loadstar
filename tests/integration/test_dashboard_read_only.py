"""Regression coverage for the dashboard's read-only persisted-route projection."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.domain.enums import PathStatus
from learning_navigator.infrastructure.database.models import (
    AuditLogModel,
    LearnerNodeStateModel,
    LearningPathModel,
    LearningPathNodeModel,
)


def _row_count(client: TestClient, model: type[Any]) -> int:
    with client.app.state.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_dashboard_reads_persisted_path_without_writes_and_prioritizes_review(
    client: TestClient,
) -> None:
    space = client.post("/api/spaces", json={"title": "Dashboard read model"}).json()
    node_ids: dict[str, str] = {}
    for title in ("Available", "Progress", "Review", "Target"):
        response = client.post(
            f"/api/spaces/{space['id']}/nodes",
            json={"title": title},
        )
        assert response.status_code == 201, response.text
        node_ids[title] = response.json()["id"]
    for source in ("Available", "Progress", "Review"):
        response = client.post(
            f"/api/spaces/{space['id']}/edges",
            json={
                "source_node_id": node_ids[source],
                "target_node_id": node_ids["Target"],
                "relation_type": "PREREQUISITE",
            },
        )
        assert response.status_code == 201, response.text
    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": node_ids["Target"],
            "title": "Dashboard target",
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goal = goal_response.json()

    counts_without_path = (
        _row_count(client, LearningPathModel),
        _row_count(client, AuditLogModel),
    )
    empty_route = client.get("/api/dashboard")
    assert empty_route.status_code == 200, empty_route.text
    assert empty_route.json()["route_overview"] == []
    assert empty_route.json()["current_position"] is None
    assert (
        _row_count(client, LearningPathModel),
        _row_count(client, AuditLogModel),
    ) == counts_without_path

    generated = client.post(f"/api/goals/{goal['id']}/paths")
    assert generated.status_code == 200, generated.text

    progress = client.put(
        f"/api/nodes/{node_ids['Progress']}/mastery",
        json={"update_kind": "exercise_result", "value": 0.5},
    )
    assert progress.status_code == 200, progress.text
    review = client.put(
        f"/api/nodes/{node_ids['Review']}/mastery",
        json={"update_kind": "manual_review", "value": 3},
    )
    assert review.status_code == 200, review.text

    with client.app.state.session_factory() as session:
        review_state = session.scalar(
            select(LearnerNodeStateModel).where(
                LearnerNodeStateModel.user_id == space["owner_id"],
                LearnerNodeStateModel.node_id == node_ids["Review"],
            )
        )
        assert review_state is not None
        review_state.next_review_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

    stable_counts = (
        _row_count(client, LearningPathModel),
        _row_count(client, AuditLogModel),
    )
    first = client.get("/api/dashboard")
    second = client.get("/api/dashboard")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    payload = first.json()
    by_id = {item["node_id"]: item for item in payload["route_overview"]}
    assert by_id[node_ids["Available"]]["status"] == "AVAILABLE"
    assert by_id[node_ids["Progress"]]["status"] == "IN_PROGRESS"
    assert by_id[node_ids["Review"]]["status"] == "NEEDS_REVIEW"
    assert by_id[node_ids["Target"]]["status"] == "AVAILABLE"
    assert set(by_id[node_ids["Target"]]["unmet_prerequisites"]) == {
        node_ids["Available"],
        node_ids["Progress"],
        node_ids["Review"],
    }
    assert "review" in by_id[node_ids["Review"]]["reason"].casefold()
    assert payload["current_position"]["node_id"] == node_ids["Review"]
    assert payload["next_step"] == payload["current_position"]
    assert payload["blocked"] == []
    assert (
        _row_count(client, LearningPathModel),
        _row_count(client, AuditLogModel),
    ) == stable_counts

    with client.app.state.session_factory() as session:
        active_path = session.scalar(
            select(LearningPathModel).where(
                LearningPathModel.goal_id == goal["id"],
                LearningPathModel.status == PathStatus.ACTIVE.value,
            )
        )
        assert active_path is not None
        persisted_review_item = session.scalar(
            select(LearningPathNodeModel).where(
                LearningPathNodeModel.path_id == active_path.id,
                LearningPathNodeModel.node_id == node_ids["Review"],
            )
        )
        assert persisted_review_item is not None
        assert persisted_review_item.computed_status == "AVAILABLE"

    for title in ("Available", "Progress", "Review"):
        mastered = client.put(
            f"/api/nodes/{node_ids[title]}/mastery",
            json={"update_kind": "manual_review", "value": 5},
        )
        assert mastered.status_code == 200, mastered.text

    refreshed = client.get("/api/dashboard")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_by_id = {item["node_id"]: item for item in refreshed.json()["route_overview"]}
    assert refreshed_by_id[node_ids["Target"]]["status"] == "AVAILABLE"
    assert refreshed_by_id[node_ids["Target"]]["unmet_prerequisites"] == []
    assert set(refreshed_by_id[node_ids["Target"]]["satisfied_prerequisites"]) == {
        node_ids["Available"],
        node_ids["Progress"],
        node_ids["Review"],
    }
