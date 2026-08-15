"""Editable path revision lifecycle and concurrency contracts."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm.exc import StaleDataError

from learning_navigator.infrastructure.database.models import LearningPathModel


def _goal_with_active_path(
    client: TestClient,
    python_map: dict[str, object],
) -> tuple[dict[str, Any], dict[str, Any]]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    goal_response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": "Editable route",
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    active_response = client.post(f"/api/goals/{goal_response.json()['id']}/paths")
    assert active_response.status_code == 200, active_response.text
    return goal_response.json(), active_response.json()


@pytest.mark.integration
def test_generated_candidate_and_clone_do_not_overwrite_active_path(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, active = _goal_with_active_path(client, python_map)
    active_path = active["path"]
    assert active_path["status"] == "ACTIVE"
    assert active_path["origin"] == "ALGORITHM_GENERATED"

    generated = client.post(
        f"/api/goals/{goal['id']}/path-revisions",
        json={"change_summary": "AI candidate for review"},
    )
    assert generated.status_code == 201, generated.text
    generated_path = generated.json()["path"]
    assert generated_path["status"] == "DRAFT"
    assert generated_path["base_active_path_id"] == active_path["id"]
    assert generated.json()["steps"]
    assert all(step["id"] for step in generated.json()["steps"])

    clone = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": 1, "change_summary": "My editable route"},
    )
    assert clone.status_code == 201, clone.text
    clone_payload = clone.json()
    clone_path = clone_payload["path"]
    assert clone_path["status"] == "DRAFT"
    assert clone_path["parent_path_id"] == active_path["id"]
    assert clone_path["base_active_path_id"] == active_path["id"]
    assert clone_path["origin"] == "USER_EDITED"
    assert {step["source"] for step in clone_payload["steps"]} == {"INHERITED"}

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    listed = client.get(f"/api/goals/{goal['id']}/path-revisions")
    assert listed.status_code == 200, listed.text
    by_id = {item["path"]["id"]: item["path"] for item in listed.json()}
    assert by_id[active_path["id"]]["status"] == "ACTIVE"
    assert by_id[generated_path["id"]]["status"] == "DRAFT"
    assert by_id[clone_path["id"]]["status"] == "DRAFT"


@pytest.mark.integration
def test_user_edit_requires_revision_but_prerequisite_conflicts_are_advisory(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, active = _goal_with_active_path(client, python_map)
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    active_path = active["path"]
    clone_response = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": 1, "change_summary": "Reorder with review"},
    )
    clone = clone_response.json()
    path_id = clone["path"]["id"]
    by_node = {step["node_id"]: step for step in clone["steps"]}
    variable_step = by_node[nodes["变量"]]
    condition_step = by_node[nodes["条件"]]

    invalid_edit = client.patch(
        f"/api/path-revisions/{path_id}/steps/{condition_step['id']}",
        json={
            "expected_revision": 1,
            "preferred_order": 0,
            "action_kind": "PRACTICE",
            "stage": "基础练习",
            "priority": 90,
            "estimated_minutes": 45,
            "is_pinned": True,
            "user_note": "先测试自己的理解",
        },
    )
    assert invalid_edit.status_code == 200, invalid_edit.text
    edited = invalid_edit.json()
    assert edited["path"]["row_version"] == 2
    assert edited["path"]["validity_status"] == "STALE"
    condition_after = next(step for step in edited["steps"] if step["id"] == condition_step["id"])
    assert condition_after["source"] == "USER_EDITED"
    assert condition_after["action_kind"] == "PRACTICE"
    assert condition_after["stage"] == "基础练习"
    assert condition_after["is_pinned"] is True

    stale_write = client.patch(
        f"/api/path-revisions/{path_id}/steps/{variable_step['id']}",
        json={"expected_revision": 1, "user_note": "stale write"},
    )
    assert stale_write.status_code == 409
    assert stale_write.json()["detail"] == {
        "code": "revision_conflict",
        "message": ("Path revision changed while it was being edited (expected 1, current 2)"),
        "expected_revision": 1,
        "current_revision": 2,
    }

    validation = client.post(
        f"/api/path-revisions/{path_id}/validate",
        json={"expected_revision": 2},
    )
    assert validation.status_code == 200, validation.text
    validation_payload = validation.json()
    assert validation_payload["valid"] is True
    prerequisite_issues = [
        issue for issue in validation_payload["issues"] if issue["code"] == "PREREQUISITE_ORDER"
    ]
    assert prerequisite_issues
    assert {issue["severity"] for issue in prerequisite_issues} == {"WARNING"}

    activated = client.post(
        f"/api/path-revisions/{path_id}/activate",
        json={"expected_revision": 2},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["path"]["status"] == "ACTIVE"
    assert activated.json()["path"]["row_version"] == 3

    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    statuses = {item["path"]["id"]: item["path"]["status"] for item in revisions}
    assert statuses[active_path["id"]] == "SUPERSEDED"
    assert statuses[path_id] == "ACTIVE"


@pytest.mark.integration
def test_missing_prerequisite_warns_but_draft_can_be_activated(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    _, active = _goal_with_active_path(client, python_map)
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    active_path = active["path"]
    clone = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": 1, "change_summary": "Omit a suggested foundation"},
    ).json()
    path_id = clone["path"]["id"]
    variable_step = next(step for step in clone["steps"] if step["node_id"] == nodes["变量"])

    removed = client.delete(
        f"/api/path-revisions/{path_id}/steps/{variable_step['id']}",
        params={"expected_revision": 1},
    )
    assert removed.status_code == 200, removed.text

    validation = client.post(
        f"/api/path-revisions/{path_id}/validate",
        json={"expected_revision": 2},
    )
    assert validation.status_code == 200, validation.text
    payload = validation.json()
    assert payload["valid"] is True
    missing = [issue for issue in payload["issues"] if issue["code"] == "MISSING_PREREQUISITE"]
    assert missing
    assert {issue["severity"] for issue in missing} == {"WARNING"}

    activated = client.post(
        f"/api/path-revisions/{path_id}/activate",
        json={"expected_revision": 2},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["path"]["status"] == "ACTIVE"


@pytest.mark.integration
def test_learning_session_can_start_with_unmet_prerequisites(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, _ = _goal_with_active_path(client, python_map)
    target_node_id = goal["target_node_id"]

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    target = next(
        item for item in dashboard.json()["route_overview"] if item["node_id"] == target_node_id
    )
    assert target["status"] == "AVAILABLE"
    assert target["unmet_prerequisites"]

    started = client.post(
        "/api/learning-sessions",
        json={
            "node_id": target_node_id,
            "started_at": datetime.now(UTC).isoformat(),
            "note": "The user intentionally starts before completing suggested foundations.",
        },
    )
    assert started.status_code == 201, started.text
    assert started.json()["session"]["node_id"] == target_node_id


@pytest.mark.integration
def test_draft_step_add_and_remove_are_versioned(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space = python_map["space"]
    assert isinstance(space, dict)
    extra_node_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": "可选的调试实践", "node_type": "SKILL"},
    )
    assert extra_node_response.status_code == 201, extra_node_response.text
    extra_node = extra_node_response.json()
    _, active = _goal_with_active_path(client, python_map)
    active_path = active["path"]
    clone = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": 1},
    ).json()
    path_id = clone["path"]["id"]

    added = client.post(
        f"/api/path-revisions/{path_id}/steps",
        json={
            "expected_revision": 1,
            "node_id": extra_node["id"],
            "preferred_order": 1,
            "required_mastery_level": 2,
            "recommendation_reason": "用户增加的可选实践",
            "is_required": False,
            "action_kind": "PRACTICE",
            "estimated_minutes": 30,
        },
    )
    assert added.status_code == 201, added.text
    added_payload = added.json()
    assert added_payload["path"]["row_version"] == 2
    added_step = next(
        step for step in added_payload["steps"] if step["node_id"] == extra_node["id"]
    )
    assert added_step["source"] == "USER_CREATED"
    assert added_step["is_required"] is False
    assert added_step["preferred_order"] == 1

    removed = client.delete(
        f"/api/path-revisions/{path_id}/steps/{added_step['id']}",
        params={"expected_revision": 2},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["path"]["row_version"] == 3
    assert extra_node["id"] not in {step["node_id"] for step in removed.json()["steps"]}
    assert [step["preferred_order"] for step in removed.json()["steps"]] == list(
        range(len(removed.json()["steps"]))
    )


@pytest.mark.integration
def test_cloned_path_rebases_to_current_framework_before_adding_new_node(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, active = _goal_with_active_path(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    extra = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": "New current-framework node", "node_type": "SKILL"},
    )
    assert extra.status_code == 201, extra.text

    clone = client.post(
        f"/api/path-revisions/{active['path']['id']}/clone",
        json={"expected_revision": active["path"]["row_version"]},
    )
    assert clone.status_code == 201, clone.text
    payload = clone.json()
    current_graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert payload["path"]["goal_id"] == goal["id"]
    assert payload["path"]["map_version_id"] == current_graph["map_version_id"]

    added = client.post(
        f"/api/path-revisions/{payload['path']['id']}/steps",
        json={
            "expected_revision": payload["path"]["row_version"],
            "node_id": extra.json()["id"],
            "preferred_order": len(payload["steps"]),
            "required_mastery_level": 2,
            "recommendation_reason": "The draft follows the current framework.",
            "is_required": True,
            "action_kind": "PRACTICE",
        },
    )
    assert added.status_code == 201, added.text
    assert extra.json()["id"] in {step["node_id"] for step in added.json()["steps"]}


@pytest.mark.integration
def test_full_path_order_replacement_is_atomic_and_updates_dashboard(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, active = _goal_with_active_path(client, python_map)
    active_path = active["path"]
    clone = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": 1},
    ).json()
    path_id = clone["path"]["id"]
    original_ids = [step["id"] for step in clone["steps"]]
    reversed_ids = list(reversed(original_ids))

    reordered = client.put(
        f"/api/path-revisions/{path_id}/order",
        json={"expected_revision": 1, "step_ids": reversed_ids},
    )
    assert reordered.status_code == 200, reordered.text
    payload = reordered.json()
    assert payload["path"]["row_version"] == 2
    assert [step["id"] for step in payload["steps"]] == reversed_ids
    assert [step["preferred_order"] for step in payload["steps"]] == list(range(len(reversed_ids)))

    incomplete = client.put(
        f"/api/path-revisions/{path_id}/order",
        json={"expected_revision": 2, "step_ids": reversed_ids[:-1]},
    )
    assert incomplete.status_code == 409, incomplete.text
    unchanged = client.get(f"/api/path-revisions/{path_id}").json()
    assert [step["id"] for step in unchanged["steps"]] == reversed_ids
    assert unchanged["path"]["row_version"] == 2

    activated = client.post(
        f"/api/path-revisions/{path_id}/activate",
        json={"expected_revision": 2},
    )
    assert activated.status_code == 200, activated.text
    overview = next(
        item
        for item in client.get("/api/dashboard").json()["goal_overviews"]
        if item["goal"]["id"] == goal["id"]
    )
    assert [item["node_id"] for item in overview["route_overview"]] == [
        step["node_id"] for step in payload["steps"]
    ]


@pytest.mark.integration
def test_node_rename_updates_framework_path_and_dashboard_without_reordering(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal, active = _goal_with_active_path(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    path_id = active["path"]["id"]
    active_detail = client.get(f"/api/path-revisions/{path_id}")
    assert active_detail.status_code == 200, active_detail.text
    before_node_ids = [step["node_id"] for step in active_detail.json()["steps"]]
    renamed_node_id = before_node_ids[0]
    renamed_title = "同步后的框架节点名称"

    renamed = client.patch(
        f"/api/spaces/{space['id']}/nodes/{renamed_node_id}",
        json={"title": renamed_title},
    )
    assert renamed.status_code == 200, renamed.text

    framework = client.get(f"/api/spaces/{space['id']}/graph")
    assert framework.status_code == 200, framework.text
    framework_node = next(
        node for node in framework.json()["nodes"] if node["id"] == renamed_node_id
    )
    assert framework_node["title"] == renamed_title

    path = client.get(f"/api/path-revisions/{path_id}")
    assert path.status_code == 200, path.text
    assert [step["node_id"] for step in path.json()["steps"]] == before_node_ids
    assert path.json()["steps"][0]["title"] == renamed_title

    overview = next(
        item
        for item in client.get("/api/dashboard").json()["goal_overviews"]
        if item["goal"]["id"] == goal["id"]
    )
    assert [item["node_id"] for item in overview["route_overview"]] == before_node_ids
    assert overview["route_overview"][0]["title"] == renamed_title


@pytest.mark.integration
def test_database_optimistic_lock_rejects_simultaneous_path_edits(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    _, active = _goal_with_active_path(client, python_map)
    path_id = active["path"]["id"]
    factory = client.app.state.session_factory
    with factory() as first_session, factory() as second_session:
        first = first_session.get(LearningPathModel, path_id)
        second = second_session.get(LearningPathModel, path_id)
        assert first is not None
        assert second is not None
        first.change_summary = "first writer"
        first.row_version += 1
        first_session.commit()

        second.change_summary = "stale second writer"
        second.row_version += 1
        with pytest.raises(StaleDataError):
            second_session.commit()
