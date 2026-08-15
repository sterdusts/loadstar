"""Atomic Photoshop-style framework outline ordering."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from learning_navigator.infrastructure.database.models import LearningPathNodeModel


def _outline(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    modules = sorted(
        (node for node in graph["nodes"] if node["node_type"] == "MODULE"),
        key=lambda node: (node["outline_order"], node["id"]),
    )
    items = {node["id"] for node in graph["nodes"] if node["node_type"] != "MODULE"}
    contains = {node["id"]: [] for node in modules}
    assigned: set[str] = set()
    order = {node["id"]: node["outline_order"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["relation_type"] != "CONTAINS" or edge["status"] == "ARCHIVED":
            continue
        if edge["source_node_id"] in contains and edge["target_node_id"] in items:
            contains[edge["source_node_id"]].append(edge["target_node_id"])
            assigned.add(edge["target_node_id"])
    return (
        [
            {
                "module_id": module["id"],
                "node_ids": sorted(contains[module["id"]], key=lambda node_id: order[node_id]),
            }
            for module in modules
        ],
        sorted(items - assigned, key=lambda node_id: order[node_id]),
    )


def _add_two_modules(client: TestClient, space_id: str) -> None:
    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    items = [node for node in graph["nodes"] if node["node_type"] != "MODULE"]
    midpoint = max(1, len(items) // 2)
    for index, members in enumerate((items[:midpoint], items[midpoint:]), start=1):
        module = client.post(
            f"/api/spaces/{space_id}/nodes",
            json={"title": f"Module {index}", "node_type": "MODULE"},
        )
        assert module.status_code == 201, module.text
        for member in members:
            edge = client.post(
                f"/api/spaces/{space_id}/edges",
                json={
                    "source_node_id": module.json()["id"],
                    "target_node_id": member["id"],
                    "relation_type": "CONTAINS",
                },
            )
            assert edge.status_code == 201, edge.text


@pytest.mark.integration
def test_outline_reorder_moves_modules_and_elements_without_changing_path_order(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": list(nodes.values())[-1],
            "title": "Outline test",
        },
    ).json()
    path = client.post(f"/api/goals/{goal['id']}/paths").json()
    path_id = path["path"]["id"]
    before_path_nodes = [item["node_id"] for item in path["items"]]

    _add_two_modules(client, str(space["id"]))
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    modules, ungrouped = _outline(graph)
    assert len(modules) >= 2
    moved_node = modules[0]["node_ids"].pop(0)
    modules[1]["node_ids"].insert(0, moved_node)
    modules.reverse()

    response = client.put(
        f"/api/spaces/{space['id']}/outline",
        json={
            "expected_revision": graph["outline_revision"],
            "modules": modules,
            "ungrouped_node_ids": ungrouped,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["outline_revision"] == graph["outline_revision"] + 1
    new_modules, new_ungrouped = _outline(updated)
    assert new_modules == modules
    assert new_ungrouped == ungrouped

    path_after = client.get(f"/api/path-revisions/{path_id}").json()
    assert [item["node_id"] for item in path_after["steps"]] == before_path_nodes


@pytest.mark.integration
def test_outline_reorder_rejects_stale_or_incomplete_payload_atomically(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    assert isinstance(space, dict)
    _add_two_modules(client, str(space["id"]))
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    modules, ungrouped = _outline(graph)
    valid = {
        "expected_revision": graph["outline_revision"],
        "modules": modules,
        "ungrouped_node_ids": ungrouped,
    }
    first = client.put(f"/api/spaces/{space['id']}/outline", json=valid)
    assert first.status_code == 200, first.text

    stale = client.put(f"/api/spaces/{space['id']}/outline", json=valid)
    assert stale.status_code == 409, stale.text
    current = client.get(f"/api/spaces/{space['id']}/graph").json()
    current_modules, current_ungrouped = _outline(current)
    assert current_modules == modules
    assert current_ungrouped == ungrouped

    incomplete_modules = [dict(item) for item in current_modules]
    incomplete_modules[0] = {
        **incomplete_modules[0],
        "node_ids": incomplete_modules[0]["node_ids"][1:],
    }
    incomplete = client.put(
        f"/api/spaces/{space['id']}/outline",
        json={
            "expected_revision": current["outline_revision"],
            "modules": incomplete_modules,
            "ungrouped_node_ids": current_ungrouped,
        },
    )
    assert incomplete.status_code == 409, incomplete.text
    unchanged = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert unchanged["outline_revision"] == current["outline_revision"]


@pytest.mark.integration
def test_outline_reorder_does_not_rewrite_path_rows(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    assert isinstance(space, dict)
    _add_two_modules(client, str(space["id"]))
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    modules, ungrouped = _outline(graph)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        before = list(
            session.execute(
                select(
                    LearningPathNodeModel.id,
                    LearningPathNodeModel.preferred_order,
                    LearningPathNodeModel.sequence_number,
                )
            ).all()
        )
    response = client.put(
        f"/api/spaces/{space['id']}/outline",
        json={
            "expected_revision": graph["outline_revision"],
            "modules": list(reversed(modules)),
            "ungrouped_node_ids": ungrouped,
        },
    )
    assert response.status_code == 200, response.text
    with app.state.session_factory() as session:
        after = list(
            session.execute(
                select(
                    LearningPathNodeModel.id,
                    LearningPathNodeModel.preferred_order,
                    LearningPathNodeModel.sequence_number,
                )
            ).all()
        )
    assert after == before


@pytest.mark.integration
def test_outline_reorder_can_sync_the_selected_draft_path_atomically(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": list(nodes.values())[-1],
            "title": "Outline and path sync",
        },
    ).json()
    path = client.post(f"/api/goals/{goal['id']}/paths").json()["path"]
    path_id = path["id"]
    cloned = client.post(
        f"/api/path-revisions/{path_id}/clone",
        json={"expected_revision": path["row_version"]},
    )
    assert cloned.status_code == 201, cloned.text
    path_id = cloned.json()["path"]["id"]
    _add_two_modules(client, str(space["id"]))
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    modules, ungrouped = _outline(graph)
    current_path = client.get(f"/api/path-revisions/{path_id}").json()
    step_id_by_node_id = {item["node_id"]: item["id"] for item in current_path["steps"]}
    outline_node_order = [
        node_id
        for module in reversed(modules)
        for node_id in [module["module_id"], *module["node_ids"]]
    ] + ungrouped
    synced_step_ids = [
        step_id_by_node_id[node_id]
        for node_id in outline_node_order
        if node_id in step_id_by_node_id
    ]

    response = client.put(
        f"/api/spaces/{space['id']}/outline",
        json={
            "expected_revision": graph["outline_revision"],
            "modules": list(reversed(modules)),
            "ungrouped_node_ids": ungrouped,
            "path_id": path_id,
            "path_expected_revision": current_path["path"]["row_version"],
            "path_step_ids": synced_step_ids,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["path_sync"]["changed"] is True
    updated_path = client.get(f"/api/path-revisions/{path_id}").json()
    assert [item["id"] for item in updated_path["steps"]] == synced_step_ids


@pytest.mark.integration
def test_outline_and_path_order_roll_back_together_on_stale_path(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": list(nodes.values())[-1],
            "title": "Outline and path atomic rollback",
        },
    ).json()
    source_path = client.post(f"/api/goals/{goal['id']}/paths").json()["path"]
    cloned = client.post(
        f"/api/path-revisions/{source_path['id']}/clone",
        json={"expected_revision": source_path["row_version"]},
    )
    assert cloned.status_code == 201, cloned.text
    path_id = cloned.json()["path"]["id"]
    _add_two_modules(client, str(space["id"]))
    before_graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    before_path = client.get(f"/api/path-revisions/{path_id}").json()
    modules, ungrouped = _outline(before_graph)
    step_ids = [item["id"] for item in before_path["steps"]]

    response = client.put(
        f"/api/spaces/{space['id']}/outline",
        json={
            "expected_revision": before_graph["outline_revision"],
            "modules": list(reversed(modules)),
            "ungrouped_node_ids": ungrouped,
            "path_id": path_id,
            "path_expected_revision": before_path["path"]["row_version"] + 1,
            "path_step_ids": list(reversed(step_ids)),
        },
    )
    assert response.status_code == 409, response.text
    after_graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    after_path = client.get(f"/api/path-revisions/{path_id}").json()
    assert after_graph["outline_revision"] == before_graph["outline_revision"]
    assert [item["id"] for item in after_path["steps"]] == step_ids
