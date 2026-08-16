"""Shared API and database fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from learning_navigator.config import Settings
from learning_navigator.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url="sqlite:///:memory:",
        auto_create_schema=True,
        allow_test_user_header=True,
        ai_provider="mock",
        ai_model="mock-learning-map-v1",
        attachment_storage_path=tmp_path / "check-in-attachments",
    )
    app = create_app(settings, include_ui=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def python_map(client: TestClient) -> dict[str, object]:
    space = client.post(
        "/api/spaces",
        json={"title": "Python 基础", "description": "端到端测试知识地图"},
    ).json()
    titles = [
        "变量",
        "条件",
        "循环",
        "函数",
        "列表",
        "字典",
        "文件读取",
        "异常处理",
        "模块",
        "小型文件处理项目",
    ]
    nodes: dict[str, str] = {}
    for title in titles:
        response = client.post(
            f"/api/spaces/{space['id']}/nodes",
            json={
                "title": title,
                "node_type": "PROJECT" if title == "小型文件处理项目" else "CONCEPT",
                "difficulty": 4 if title == "小型文件处理项目" else 2,
            },
        )
        assert response.status_code == 201, response.text
        nodes[title] = response.json()["id"]
    dependencies = [
        ("变量", "条件"),
        ("变量", "循环"),
        ("条件", "函数"),
        ("循环", "函数"),
        ("变量", "列表"),
        ("列表", "字典"),
        ("函数", "文件读取"),
        ("字典", "文件读取"),
        ("文件读取", "异常处理"),
        ("函数", "模块"),
        ("异常处理", "小型文件处理项目"),
        ("模块", "小型文件处理项目"),
    ]
    for source, target in dependencies:
        response = client.post(
            f"/api/spaces/{space['id']}/edges",
            json={
                "source_node_id": nodes[source],
                "target_node_id": nodes[target],
                "relation_type": "PREREQUISITE",
                "reason": f"{source} 是 {target} 的前置",
            },
        )
        assert response.status_code == 201, response.text
    return {"space": space, "nodes": nodes}
