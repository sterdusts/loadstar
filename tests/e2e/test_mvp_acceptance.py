"""Named MVP acceptance scenarios from the product brief."""

import copy

import pytest
from fastapi.testclient import TestClient


@pytest.mark.e2e
def test_scenario_a_manual_map_route_recalculates(
    client: TestClient, python_map: dict[str, object]
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": "Python 文件项目",
        },
    ).json()
    initial = client.post(f"/api/goals/{goal['id']}/paths").json()["items"]
    for title in ("变量", "条件", "循环"):
        client.put(
            f"/api/nodes/{nodes[title]}/mastery",
            json={"update_kind": "manual_review", "value": 3},
        )
    recalculated = client.post(f"/api/goals/{goal['id']}/paths").json()["items"]
    assert len(recalculated) == len(initial) - 3


@pytest.mark.e2e
def test_scenario_b_cycle_is_rejected_with_path(client: TestClient) -> None:
    space = client.post("/api/spaces", json={"title": "Cycle"}).json()
    ids = {
        title: client.post(f"/api/spaces/{space['id']}/nodes", json={"title": title}).json()["id"]
        for title in ("A", "B", "C")
    }
    for source, target in (("A", "B"), ("B", "C")):
        assert (
            client.post(
                f"/api/spaces/{space['id']}/edges",
                json={
                    "source_node_id": ids[source],
                    "target_node_id": ids[target],
                    "relation_type": "PREREQUISITE",
                },
            ).status_code
            == 201
        )
    rejected = client.post(
        f"/api/spaces/{space['id']}/edges",
        json={
            "source_node_id": ids["C"],
            "target_node_id": ids["A"],
            "relation_type": "PREREQUISITE",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["cycle_path"] == [
        ids["A"],
        ids["B"],
        ids["C"],
        ids["A"],
    ]


@pytest.mark.e2e
def test_scenario_c_ai_review_controls_formal_map(client: TestClient) -> None:
    generated = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "我想学习使用 PyTorch 完成图像分类"},
    ).json()
    edited = copy.deepcopy(generated["raw_structured_output"])
    edited["nodes"] = [node for node in edited["nodes"] if node["temp_id"] != "python"]
    edited["edges"] = [
        edge
        for edge in edited["edges"]
        if edge["source_temp_id"] != "python" and edge["target_temp_id"] != "python"
    ]
    edited["edges"][0]["reason"] = "人工核对后的依赖"
    accepted = client.post(
        f"/api/ai/suggestions/{generated['id']}/review",
        json={"action": "modify_accept", "edited_draft": edited},
    )
    assert accepted.status_code == 200, accepted.text
    graph = client.get(f"/api/spaces/{accepted.json()['space_id']}/graph").json()
    assert "Python 与 NumPy 基础" not in {item["title"] for item in graph["nodes"]}
    assert all(item["manually_locked"] for item in graph["nodes"])


@pytest.mark.e2e
def test_scenario_d_blockage_explains_transitive_first_step(client: TestClient) -> None:
    space = client.post("/api/spaces", json={"title": "反向传播"}).json()
    ids = {
        title: client.post(f"/api/spaces/{space['id']}/nodes", json={"title": title}).json()["id"]
        for title in ("基本求导", "链式法则", "反向传播")
    }
    for source, target in (("基本求导", "链式法则"), ("链式法则", "反向传播")):
        client.post(
            f"/api/spaces/{space['id']}/edges",
            json={
                "source_node_id": ids[source],
                "target_node_id": ids[target],
                "relation_type": "PREREQUISITE",
            },
        )
    result = client.get(f"/api/spaces/{space['id']}/nodes/{ids['反向传播']}/blockage")
    assert result.status_code == 200, result.text
    explanation = result.json()
    assert explanation["blockers"][0]["title"] == "链式法则"
    assert explanation["recommended_first_node_id"] == ids["基本求导"]
    assert explanation["dependency_chain"] == [
        ids["基本求导"],
        ids["链式法则"],
        ids["反向传播"],
    ]


@pytest.mark.e2e
def test_scenario_e_no_model_key_still_supports_manual_loop(
    client: TestClient, python_map: dict[str, object]
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": "无 AI 路线",
        },
    )
    assert goal.status_code == 201
    assert client.post(f"/api/goals/{goal.json()['id']}/paths").status_code == 200
    exported = client.get("/api/data/export")
    assert exported.status_code == 200
    assert client.post("/api/data/import", json={"payload": exported.json()}).status_code == 201
