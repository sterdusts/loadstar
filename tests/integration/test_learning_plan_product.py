"""Product-level contracts for generating a framework and staged learning navigation."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from learning_navigator.config import Settings
from learning_navigator.infrastructure.security.credentials import MemoryCredentialStore
from learning_navigator.main import create_app

STATUS_SECRET = "status-only-secret-4826"


@pytest.fixture
def learning_plan_client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            database_url="sqlite:///:memory:",
            auto_create_schema=True,
            ai_provider="mock",
            ai_model="mock-learning-map-v1",
            ai_api_key=SecretStr(STATUS_SECRET),
        ),
        include_ui=False,
        credential_store=MemoryCredentialStore(),
    )
    with TestClient(app) as client:
        yield client


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key).casefold() for key in value),
            *(key for item in value.values() for key in _nested_keys(item)),
        }
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


@pytest.mark.integration
def test_ai_status_is_ready_and_never_discloses_credentials(
    learning_plan_client: TestClient,
) -> None:
    response = learning_plan_client.get("/api/ai/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["model"] == "mock-learning-map-v1"
    assert payload["is_external"] is False
    assert payload["is_ready"] is True
    assert payload["display_name"] == "Environment default"
    assert STATUS_SECRET not in response.text
    assert {"api_key", "key", "secret", "token"}.isdisjoint(_nested_keys(payload))


@pytest.mark.integration
def test_topic_and_requirements_generate_isolated_complete_learning_plan(
    learning_plan_client: TestClient,
) -> None:
    spaces_before = learning_plan_client.get("/api/spaces")
    assert spaces_before.status_code == 200, spaces_before.text

    response = learning_plan_client.post(
        "/api/ai/learning-plans/generate",
        json={
            "topic": "从零开始学习 Python 数据分析",
            "requirements": "重视实践，希望能独立完成一个数据分析作品集项目",
        },
    )

    assert response.status_code == 201, response.text
    suggestion = response.json()
    assert suggestion["suggestion_type"] == "LEARNING_PLAN"
    assert suggestion["review_status"] == "PENDING"
    assert suggestion["provider"] == "mock"
    assert "conflicts" in suggestion["proposed_changes"]
    assert suggestion["proposed_changes"]["navigation"]

    plan: dict[str, Any] = suggestion["raw_structured_output"]
    assert {"space", "nodes", "edges", "navigation"} <= plan.keys()
    assert plan["space"]["title"].strip()

    nodes: list[dict[str, Any]] = plan["nodes"]
    assert nodes
    assert any(node["node_type"] == "MODULE" for node in nodes)
    assert any(node["node_type"] != "MODULE" for node in nodes)
    node_ids = {node["temp_id"] for node in nodes}
    assert len(node_ids) == len(nodes)

    navigation: dict[str, Any] = plan["navigation"]
    assert navigation["goal_title"].strip()
    assert navigation["success_definition"].strip()
    assert navigation["target_temp_id"] in node_ids

    stages: list[dict[str, Any]] = navigation["stages"]
    assert len(stages) >= 4
    assert [stage["sequence"] for stage in stages] == list(range(1, len(stages) + 1))
    for stage in stages:
        stage_node_ids = stage["node_temp_ids"]
        assert stage_node_ids
        assert set(stage_node_ids) <= node_ids
        criteria = stage["completion_criteria"]
        assert criteria
        assert all(isinstance(item, str) and item.strip() for item in criteria)

    assert navigation["target_temp_id"] in stages[-1]["node_temp_ids"]

    spaces_after = learning_plan_client.get("/api/spaces")
    assert spaces_after.status_code == 200, spaces_after.text
    assert spaces_after.json() == spaces_before.json()


@pytest.mark.integration
def test_accepting_learning_plan_revalidates_it_and_records_temp_id_mapping(
    learning_plan_client: TestClient,
) -> None:
    generated = learning_plan_client.post(
        "/api/ai/learning-plans/generate",
        json={
            "topic": "FastAPI backend engineering",
            "requirements": "Independently deliver a tested production-style API",
        },
    )
    assert generated.status_code == 201, generated.text
    suggestion = generated.json()

    reviewed = learning_plan_client.post(
        f"/api/ai/suggestions/{suggestion['id']}/review",
        json={"action": "accept"},
    )

    assert reviewed.status_code == 200, reviewed.text
    accepted = reviewed.json()
    assert accepted["review_status"] == "ACCEPTED"
    changes = accepted["accepted_changes"]
    temp_ids = {item["temp_id"] for item in suggestion["raw_structured_output"]["nodes"]}
    assert set(changes["node_id_map"]) == temp_ids
    assert set(changes["node_id_map"].values()) == set(changes["node_ids"])
    assert len(changes["node_id_map"].values()) == len(set(changes["node_id_map"].values()))
    assert (
        changes["accepted_draft"]["navigation"] == suggestion["raw_structured_output"]["navigation"]
    )

    graph = learning_plan_client.get(f"/api/spaces/{changes['space_id']}/graph")
    assert graph.status_code == 200, graph.text
    assert {item["id"] for item in graph.json()["nodes"]} == set(changes["node_ids"])


@pytest.mark.integration
def test_learning_plan_accepts_declared_topic_and_requirements_length_boundaries(
    learning_plan_client: TestClient,
) -> None:
    response = learning_plan_client.post(
        "/api/ai/learning-plans/generate",
        json={"topic": "T" * 500, "requirements": "R" * 8000},
    )

    assert response.status_code == 201, response.text
    assert response.json()["suggestion_type"] == "LEARNING_PLAN"


@pytest.mark.integration
@pytest.mark.parametrize(
    "payload",
    [
        {"topic": "", "requirements": "完成一个项目"},
        {"topic": "学习 Python", "requirements": ""},
        {"topic": "   ", "requirements": "完成一个项目"},
        {"topic": "学习 Python", "requirements": " \n\t "},
        {
            "topic": "学习 Python",
            "requirements": "完成一个项目",
            "unexpected": "must be rejected",
        },
    ],
)
def test_learning_plan_rejects_empty_inputs_and_extra_fields(
    learning_plan_client: TestClient,
    payload: dict[str, str],
) -> None:
    response = learning_plan_client.post(
        "/api/ai/learning-plans/generate",
        json=payload,
    )

    assert response.status_code == 422, response.text
    assert learning_plan_client.get("/api/ai/suggestions").json() == []
    assert learning_plan_client.get("/api/spaces").json() == []
