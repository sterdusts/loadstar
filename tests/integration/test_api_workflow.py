"""Database/API boundary tests for the core learning loop."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.infrastructure.database.models import LearningPathNodeModel


@pytest.mark.integration
def test_health_and_empty_dashboard(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "reachable"}

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["current_goal"] is None
    assert dashboard.json()["current_goal_id"] is None
    assert dashboard.json()["goal_overviews"] == []


@pytest.mark.integration
def test_create_map_reject_cycle_and_shorten_route(
    client: TestClient, python_map: dict[str, object]
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)

    graph_response = client.get(f"/api/spaces/{space['id']}/graph")
    assert graph_response.status_code == 200, graph_response.text
    assert all(edge["reason"] for edge in graph_response.json()["edges"])

    cycle = client.post(
        f"/api/spaces/{space['id']}/edges",
        json={
            "source_node_id": nodes["小型文件处理项目"],
            "target_node_id": nodes["变量"],
            "relation_type": "PREREQUISITE",
        },
    )
    assert cycle.status_code == 409
    assert cycle.json()["detail"]["code"] == "circular_prerequisite"
    assert len(cycle.json()["detail"]["cycle_path"]) >= 3

    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": "完成小型文件处理项目",
            "target_mastery_level": 3,
            "route_preference": "FOUNDATION_COMPLETE",
        },
    )
    assert goal.status_code == 201, goal.text
    first_path = client.post(f"/api/goals/{goal.json()['id']}/paths")
    assert first_path.status_code == 200, first_path.text
    first_payload = first_path.json()
    first_ids = [item["node_id"] for item in first_payload["items"]]
    assert nodes["变量"] in first_ids
    assert nodes["小型文件处理项目"] in first_ids
    assert all(item["required_mastery_level"] == 3 for item in first_payload["items"])
    with client.app.state.session_factory() as session:
        persisted_items = list(
            session.scalars(
                select(LearningPathNodeModel).where(
                    LearningPathNodeModel.path_id == first_payload["path"]["id"]
                )
            )
        )
    assert persisted_items
    assert all(item.required_mastery_level == 3 for item in persisted_items)

    for title in ("变量", "条件", "循环"):
        update = client.put(
            f"/api/nodes/{nodes[title]}/mastery",
            json={"update_kind": "manual_review", "value": 3},
        )
        assert update.status_code == 200, update.text
    shortened = client.post(f"/api/goals/{goal.json()['id']}/paths")
    shortened_ids = [item["node_id"] for item in shortened.json()["items"]]
    assert len(shortened_ids) == len(first_ids) - 3
    assert nodes["变量"] not in shortened_ids
    assert nodes["函数"] in shortened_ids


@pytest.mark.integration
def test_state_rules_and_learning_session(
    client: TestClient, python_map: dict[str, object]
) -> None:
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = nodes["变量"]

    self_report = client.put(
        f"/api/nodes/{node_id}/mastery",
        json={"update_kind": "self_report", "value": 0.8},
    )
    assert self_report.json()["mastery_level"] == 0
    assert self_report.json()["confidence"] == 0.8

    exercise = client.put(
        f"/api/nodes/{node_id}/mastery",
        json={"update_kind": "exercise_result", "value": 1.0},
    )
    assert exercise.json()["mastery_level"] == 0
    assert exercise.json()["mastery_score"] == 1.0
    assert exercise.json()["confidence"] == 0.85
    assert exercise.json()["numeric_evidence_count"] == 1

    reviewed = client.put(
        f"/api/nodes/{node_id}/mastery",
        json={"update_kind": "manual_review", "value": 3},
    )
    assert reviewed.json()["mastery_level"] == 3
    assert reviewed.json()["algorithm_version"] == "mastery-rule-v1"

    started = datetime.now(UTC) - timedelta(minutes=20)
    session = client.post(
        "/api/learning-sessions",
        json={
            "node_id": node_id,
            "started_at": started.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "note": "练习变量赋值",
            "difficulties": "命名",
            "self_rating": 3,
            "evidence": [
                {
                    "evidence_type": "NOTE",
                    "title": "变量笔记",
                    "content": "变量绑定对象。",
                    "metadata": {},
                }
            ],
        },
    )
    assert session.status_code == 201, session.text
    assert session.json()["evidence"][0]["evidence_type"] == "NOTE"


@pytest.mark.integration
def test_duplicate_edge_is_rejected(client: TestClient) -> None:
    space = client.post("/api/spaces", json={"title": "重复边"}).json()
    node_ids = [
        client.post(f"/api/spaces/{space['id']}/nodes", json={"title": title}).json()["id"]
        for title in ("A", "B")
    ]
    payload = {
        "source_node_id": node_ids[0],
        "target_node_id": node_ids[1],
        "relation_type": "PREREQUISITE",
    }
    assert client.post(f"/api/spaces/{space['id']}/edges", json=payload).status_code == 201
    duplicate = client.post(f"/api/spaces/{space['id']}/edges", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_edge"
