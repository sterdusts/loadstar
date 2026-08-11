"""AI firewall, human review and JSON portability tests."""

import copy

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_ai_draft_does_not_create_map_until_acceptance(client: TestClient) -> None:
    before = client.get("/api/spaces").json()
    generated = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "我想学习使用 PyTorch 完成图像分类"},
    )
    assert generated.status_code == 201, generated.text
    suggestion = generated.json()
    assert suggestion["review_status"] == "PENDING"
    assert client.get("/api/spaces").json() == before

    accepted = client.post(
        f"/api/ai/suggestions/{suggestion['id']}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_data = accepted.json()
    assert accepted_data["review_status"] == "ACCEPTED"
    assert accepted_data["reviewed_by"] is not None
    assert len(client.get("/api/spaces").json()) == len(before) + 1
    graph = client.get(f"/api/spaces/{accepted_data['space_id']}/graph").json()
    assert len([node for node in graph["nodes"] if node["status"] != "ARCHIVED"]) == 7
    assert all(node["manually_locked"] for node in graph["nodes"])


@pytest.mark.integration
def test_reject_and_modified_accept_apply_only_reviewed_draft(client: TestClient) -> None:
    rejected = client.post(
        "/api/ai/suggestions/generate", json={"source_text": "拒绝用示例"}
    ).json()
    reject_result = client.post(
        f"/api/ai/suggestions/{rejected['id']}/review", json={"action": "reject"}
    )
    assert reject_result.json()["review_status"] == "REJECTED"
    assert client.get("/api/spaces").json() == []

    generated = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "我想学习使用 PyTorch 完成图像分类"},
    ).json()
    edited = copy.deepcopy(generated["raw_structured_output"])
    edited["nodes"] = [node for node in edited["nodes"] if node["temp_id"] != "data"]
    edited["edges"] = [
        edge
        for edge in edited["edges"]
        if edge["source_temp_id"] != "data" and edge["target_temp_id"] != "data"
    ]
    for edge in edited["edges"]:
        if edge["source_temp_id"] == "nn" and edge["target_temp_id"] == "train":
            edge["reason"] = "人工修改后的前置理由"
    accepted = client.post(
        f"/api/ai/suggestions/{generated['id']}/review",
        json={"action": "modify_accept", "edited_draft": edited},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["review_status"] == "MODIFIED_ACCEPTED"
    graph = client.get(f"/api/spaces/{accepted.json()['space_id']}/graph").json()
    assert {node["title"] for node in graph["nodes"]}.isdisjoint({"图像数据管线"})
    assert len(graph["nodes"]) == 6


@pytest.mark.integration
def test_export_then_import_map(client: TestClient, python_map: dict[str, object]) -> None:
    exported = client.get("/api/data/export")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "learning-navigator-export-v1"
    assert payload["maps"][0]["nodes"]

    imported = client.post("/api/data/import", json={"payload": payload})
    assert imported.status_code == 201, imported.text
    assert len(imported.json()["nodes"]) == len(payload["maps"][0]["nodes"])
    assert len(client.get("/api/spaces").json()) == 2
