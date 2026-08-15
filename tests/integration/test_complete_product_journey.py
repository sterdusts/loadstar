"""Product-level journeys that keep framework, route and progress projections aligned.

These tests deliberately exercise the public HTTP surface instead of calling
repositories directly.  They are a compact, repeatable version of the two
real-world journeys used during product acceptance: learning a subject and
building an overview of an unfamiliar field.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from learning_navigator.ui.components.navigation import group_route_by_modules


class _JourneyCollaborationProvider:
    """Small deterministic provider used to exercise the real review boundary."""

    name = "mock"
    model = "journey-collaboration-v1"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.contexts: list[dict[str, Any]] = []

    async def collaborate(
        self,
        context: dict[str, Any],
        *,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        del response_schema
        self.contexts.append(context)
        return next(self.responses)


def _pending_proposal(detail: dict[str, Any], tool_name: str) -> str:
    return next(
        message["structured_content"]["tool_call_id"]
        for message in detail["messages"]
        if message["role"] == "TOOL"
        and message["structured_content"].get("status") == "PENDING"
        and message["structured_content"].get("tool_name") == tool_name
    )


def _create_project_with_ai(
    client: TestClient,
    *,
    title: str,
    prompt: str,
    expected_intent: str,
) -> dict[str, Any]:
    created = client.post(
        "/api/ai/conversations",
        json={"title": title, "purpose": "PLANNING"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    discussed = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": prompt},
    )
    assert discussed.status_code == 200, discussed.text
    discussion = discussed.json()
    draft = discussion["conversation"]["working_plan"]
    assert draft["navigation"]["intent_mode"] == expected_intent

    modules = [node for node in draft["nodes"] if node["node_type"] == "MODULE"]
    concrete = [node for node in draft["nodes"] if node["node_type"] != "MODULE"]
    contains = [edge for edge in draft["edges"] if edge["relation_type"] == "CONTAINS"]
    members = {edge["target_temp_id"] for edge in contains}
    assert len(modules) >= 6
    assert concrete
    assert len(contains) == len(concrete)
    assert members == {node["temp_id"] for node in concrete}
    assert all(stage["node_temp_ids"] for stage in draft["navigation"]["stages"])
    assert not {node["temp_id"] for node in modules}.intersection(
        node_id for stage in draft["navigation"]["stages"] for node_id in stage["node_temp_ids"]
    )

    finalized = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": discussion["conversation"]["row_version"]},
    )
    assert finalized.status_code == 200, finalized.text
    activated = client.post(
        f"/api/ai/conversations/{conversation_id}/activate-plan",
        json={"expected_revision": finalized.json()["conversation"]["row_version"]},
    )
    assert activated.status_code == 200, activated.text
    payload = activated.json()
    payload["conversation_id"] = conversation_id
    return payload


def _outline(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    live_nodes = [node for node in graph["nodes"] if node.get("status") != "ARCHIVED"]
    modules = sorted(
        (node for node in live_nodes if node["node_type"] == "MODULE"),
        key=lambda node: (int(node.get("outline_order", 0)), str(node["id"])),
    )
    concrete_ids = {node["id"] for node in live_nodes if node["node_type"] != "MODULE"}
    order = {node["id"]: int(node.get("outline_order", 0)) for node in live_nodes}
    children: dict[str, list[str]] = {node["id"]: [] for node in modules}
    assigned: set[str] = set()
    for edge in graph["edges"]:
        if edge.get("status") == "ARCHIVED" or edge["relation_type"] != "CONTAINS":
            continue
        source_id = edge["source_node_id"]
        target_id = edge["target_node_id"]
        if source_id in children and target_id in concrete_ids:
            children[source_id].append(target_id)
            assigned.add(target_id)
    return (
        [
            {
                "module_id": module["id"],
                "node_ids": sorted(children[module["id"]], key=lambda node_id: order[node_id]),
            }
            for module in modules
        ],
        sorted(concrete_ids - assigned, key=lambda node_id: order[node_id]),
    )


def _goal_overview(client: TestClient, goal_id: str) -> dict[str, Any]:
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return next(
        item for item in dashboard.json()["goal_overviews"] if item["goal"]["id"] == goal_id
    )


def _complete_route(client: TestClient, goal_id: str) -> list[str]:
    route = _goal_overview(client, goal_id)["route_overview"]
    checked: list[str] = []
    for item in route:
        response = client.post(
            f"/api/goals/{goal_id}/nodes/{item['node_id']}/check-ins",
            json={"score": 10, "note": f"Completed route step {item['title']}"},
        )
        assert response.status_code == 201, response.text
        checked.append(item["node_id"])
    refreshed = _goal_overview(client, goal_id)
    assert all(
        item["display_progress_state"] == "COMPLETED" for item in refreshed["route_overview"]
    )
    return checked


@pytest.mark.integration
def test_parallel_learning_and_understanding_projects_survive_a_full_editing_journey(
    client: TestClient,
) -> None:
    learning_prompt = (
        "Learn systematic watercolor illustration from first principles. "
        "I need a comprehensive, multidisciplinary, end-to-end framework that covers "
        "materials, value, color, composition, deliberate practice, portfolio review, "
        "and a verifiable final illustration. I can spend five hours each week. "
    ) * 8
    understanding_prompt = (
        "Understand the semiconductor industry as an unfamiliar field. Build a comprehensive, "
        "cross-domain, end-to-end map of the value chain, technology, economics, regulation, "
        "risks, evidence, competing perspectives and implications. "
    ) * 8
    learning = _create_project_with_ai(
        client,
        title="Watercolor learning journey",
        prompt=learning_prompt,
        expected_intent="LEARN",
    )
    understanding = _create_project_with_ai(
        client,
        title="Semiconductor field overview",
        prompt=understanding_prompt,
        expected_intent="UNDERSTAND",
    )

    goal_id = learning["conversation"]["goal_id"]
    space_id = learning["conversation"]["space_id"]
    other_goal_id = understanding["conversation"]["goal_id"]
    dashboard = client.get("/api/dashboard").json()
    assert {item["goal"]["id"] for item in dashboard["goal_overviews"]} == {
        goal_id,
        other_goal_id,
    }

    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    route = _goal_overview(client, goal_id)["route_overview"]
    groups = group_route_by_modules(graph, route)
    module_count = sum(node["node_type"] == "MODULE" for node in graph["nodes"])
    assert len(groups) == module_count
    assert all(group["steps"] for group in groups)

    # Create, rename, relate and position new content without rebuilding the project.
    module = client.post(
        f"/api/spaces/{space_id}/nodes",
        json={"title": "Reflection and transfer", "node_type": "MODULE"},
    )
    assert module.status_code == 201, module.text
    module_id = module.json()["id"]
    added = client.post(
        f"/api/spaces/{space_id}/nodes",
        json={
            "title": "Error analysis",
            "description": "Turn recurring mistakes into the next deliberate-practice target.",
            "node_type": "SKILL",
            "difficulty": 3,
        },
    )
    assert added.status_code == 201, added.text
    added_node_id = added.json()["id"]
    renamed = client.patch(
        f"/api/spaces/{space_id}/nodes/{added_node_id}",
        json={"title": "Error analysis and transfer"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Error analysis and transfer"
    assert (
        client.post(
            f"/api/spaces/{space_id}/edges",
            json={
                "source_node_id": module_id,
                "target_node_id": added_node_id,
                "relation_type": "CONTAINS",
                "reason": "The skill belongs to the reflection module.",
            },
        ).status_code
        == 201
    )
    old_route_node_ids = [item["node_id"] for item in route]
    assert (
        client.post(
            f"/api/spaces/{space_id}/edges",
            json={
                "source_node_id": old_route_node_ids[-2],
                "target_node_id": added_node_id,
                "relation_type": "PREREQUISITE",
                "reason": "Review follows a completed attempt.",
            },
        ).status_code
        == 201
    )

    # Work on a draft route: add a step, remove another, then move the whole
    # module and its contents while synchronizing the draft order atomically.
    active_path = learning["activation"]["route"]["path"]
    cloned = client.post(
        f"/api/path-revisions/{active_path['id']}/clone",
        json={"expected_revision": active_path["row_version"], "change_summary": "Add review"},
    )
    assert cloned.status_code == 201, cloned.text
    draft = cloned.json()
    draft_id = draft["path"]["id"]
    added_step = client.post(
        f"/api/path-revisions/{draft_id}/steps",
        json={
            "expected_revision": draft["path"]["row_version"],
            "node_id": added_node_id,
            "preferred_order": len(draft["steps"]),
            "required_mastery_level": 3,
            "recommendation_reason": "Close the feedback loop before completion.",
            "action_kind": "PRACTICE",
            "is_required": True,
        },
    )
    assert added_step.status_code == 201, added_step.text
    draft = added_step.json()
    removed_node_id = draft["steps"][0]["node_id"]
    removed = client.delete(
        f"/api/path-revisions/{draft_id}/steps/{draft['steps'][0]['id']}",
        params={"expected_revision": draft["path"]["row_version"]},
    )
    assert removed.status_code == 200, removed.text
    draft = removed.json()

    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    modules, ungrouped = _outline(graph)
    moved_module = next(item for item in modules if item["module_id"] == module_id)
    modules = [moved_module, *(item for item in modules if item["module_id"] != module_id)]
    step_id_by_node_id = {step["node_id"]: step["id"] for step in draft["steps"]}
    ordered_node_ids = [node_id for item in modules for node_id in item["node_ids"]]
    ordered_node_ids.extend(ungrouped)
    ordered_step_ids = [
        step_id_by_node_id[node_id] for node_id in ordered_node_ids if node_id in step_id_by_node_id
    ]
    synced = client.put(
        f"/api/spaces/{space_id}/outline",
        json={
            "expected_revision": graph["outline_revision"],
            "modules": modules,
            "ungrouped_node_ids": ungrouped,
            "path_id": draft_id,
            "path_expected_revision": draft["path"]["row_version"],
            "path_step_ids": ordered_step_ids,
        },
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["path_sync"]["changed"] is True
    draft = client.get(f"/api/path-revisions/{draft_id}").json()
    assert [step["id"] for step in draft["steps"]] == ordered_step_ids
    activated = client.post(
        f"/api/path-revisions/{draft_id}/activate",
        json={"expected_revision": draft["path"]["row_version"]},
    )
    assert activated.status_code == 200, activated.text

    # A removed route node can now be destroyed; framework edges and every
    # projection must stop exposing it.
    deleted = client.delete(f"/api/spaces/{space_id}/nodes/{removed_node_id}")
    assert deleted.status_code == 200, deleted.text
    assert removed_node_id not in {
        node["id"] for node in client.get(f"/api/spaces/{space_id}/graph").json()["nodes"]
    }
    assert removed_node_id not in {
        item["node_id"] for item in _goal_overview(client, goal_id)["route_overview"]
    }

    # Empty user-created modules are allowed only as a transient editing state;
    # deleting one must remove it from all framework projections immediately.
    temporary = client.post(
        f"/api/spaces/{space_id}/nodes",
        json={"title": "Temporary module", "node_type": "MODULE"},
    )
    assert temporary.status_code == 201, temporary.text
    assert (
        client.delete(f"/api/spaces/{space_id}/nodes/{temporary.json()['id']}").status_code == 200
    )

    # Record one learning session and then complete every route step in both
    # parallel projects through the public daily check-in API.
    first_live_node = _goal_overview(client, goal_id)["route_overview"][0]["node_id"]
    started_at = datetime.now(UTC) - timedelta(minutes=35)
    session = client.post(
        "/api/learning-sessions",
        json={
            "node_id": first_live_node,
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "note": "Applied the framework to an actual exercise.",
        },
    )
    assert session.status_code == 201, session.text
    assert set(_complete_route(client, goal_id)) == {
        item["node_id"] for item in _goal_overview(client, goal_id)["route_overview"]
    }
    assert set(_complete_route(client, other_goal_id)) == {
        item["node_id"] for item in _goal_overview(client, other_goal_id)["route_overview"]
    }

    # Mind-map generation reads the latest reviewed framework, not the original
    # AI draft.  Its source must stay bound to this project.
    mind_map = client.post(
        f"/api/ai/goals/{goal_id}/mind-map/generate",
        json={"confirmed_external_ai": True},
    )
    assert mind_map.status_code == 201, mind_map.text
    assert mind_map.json()["source"]["space_id"] == space_id
    assert mind_map.json()["mind_map"]["node_count"] == len(
        client.get(f"/api/spaces/{space_id}/graph").json()["nodes"]
    )

    # Trash/restore is recoverable; permanent deletion is possible only from
    # the trash and removes the project from the shared dashboard.
    other_title = _goal_overview(client, other_goal_id)["goal"]["title"]
    archived = client.post(f"/api/goals/{other_goal_id}/archive")
    assert archived.status_code == 200, archived.text
    assert other_goal_id not in {
        item["goal"]["id"] for item in client.get("/api/dashboard").json()["goal_overviews"]
    }
    restored = client.post(f"/api/goals/{other_goal_id}/restore")
    assert restored.status_code == 200, restored.text
    assert other_goal_id in {
        item["goal"]["id"] for item in client.get("/api/dashboard").json()["goal_overviews"]
    }
    assert client.post(f"/api/goals/{other_goal_id}/archive").status_code == 200
    destroyed = client.request(
        "DELETE",
        f"/api/goals/{other_goal_id}",
        json={"confirm_title": other_title},
    )
    assert destroyed.status_code == 204, destroyed.text
    assert other_goal_id not in {
        item["goal"]["id"] for item in client.get("/api/dashboard").json()["goal_overviews"]
    }


@pytest.mark.integration
def test_ai_can_extend_an_existing_project_and_route_without_rebuilding_it(
    client: TestClient,
) -> None:
    project = _create_project_with_ai(
        client,
        title="Incremental learning project",
        prompt=(
            "Learn systematic visual composition from first principles with a comprehensive "
            "end-to-end practice framework, verification and transfer. "
        )
        * 6,
        expected_intent="LEARN",
    )
    conversation_id = project["conversation_id"]
    goal_id = project["conversation"]["goal_id"]
    space_id = project["conversation"]["space_id"]
    graph_before = client.get(f"/api/spaces/{space_id}/graph").json()
    original_node_ids = {node["id"] for node in graph_before["nodes"]}
    original_route = _goal_overview(client, goal_id)["route_overview"]
    original_route_ids = [step["node_id"] for step in original_route]
    page_context = {
        "page_key": "project",
        "page_kind": "PROJECT",
        "page_title": "Incremental learning project",
        "section": "overview",
        "space_id": space_id,
        "goal_id": goal_id,
        "page_state": {
            "project_title": "Incremental learning project",
            "current_node": {
                "name": original_route[0]["title"],
                "status": "NOT_STARTED",
                "score": 0,
            },
            "path_summary": {
                "total": len(original_route),
                "completed": 0,
                "in_progress": 0,
                "not_started": len(original_route),
                "steps": [],
            },
            "progress_summary": {
                "percent": 0,
                "completed": 0,
                "total": len(original_route),
            },
        },
    }

    explanation_provider = _JourneyCollaborationProvider(
        [
            {
                "message": (
                    "Start with the visible current node, compare two examples, then explain "
                    "the composition choice in your own words before practising."
                ),
                "tool_calls": [],
            }
        ]
    )
    client.app.state.ai_provider = explanation_provider
    explained = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={
            "content": "Use my current page and route to explain what I should learn next.",
            "page_context": page_context,
        },
    )
    assert explained.status_code == 200, explained.text
    assert explained.json()["conversation"]["id"] == conversation_id
    assert explanation_provider.contexts[0]["project"]["selected_goal_id"] == goal_id
    assert (
        explanation_provider.contexts[0]["page_context"]["page_state"]["progress_summary"][
            "percent"
        ]
        == 0
    )

    current_map_version_id = graph_before["map_version_id"]
    add_provider = _JourneyCollaborationProvider(
        [
            {
                "message": (
                    "Your reflection loop is missing. I propose one additional practice node; "
                    "the existing framework remains intact."
                ),
                "tool_calls": [
                    {
                        "tool_call_id": "add-reflection",
                        "name": "add_node",
                        "arguments": {
                            "expected_map_version_id": current_map_version_id,
                            "title": "Composition reflection loop",
                            "description": "Compare intent, result and the next adjustment.",
                            "node_type": "SKILL",
                            "difficulty": 3,
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = add_provider
    proposed = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={
            "content": "I discovered that reflection is missing. Add it without rebuilding.",
            "page_context": page_context,
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal_id = _pending_proposal(proposed.json(), "add_node")
    assert {node["id"] for node in client.get(f"/api/spaces/{space_id}/graph").json()["nodes"]} == (
        original_node_ids
    )
    approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/approve",
        json={"expected_revision": proposed.json()["conversation"]["row_version"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["proposal_review"]["status"] == "SUCCEEDED"
    new_node_id = approved.json()["proposal_review"]["result"]["id"]
    graph_after_add = client.get(f"/api/spaces/{space_id}/graph").json()
    assert original_node_ids < {node["id"] for node in graph_after_add["nodes"]}

    module_id = next(
        node["id"] for node in graph_after_add["nodes"] if node["node_type"] == "MODULE"
    )
    relation_provider = _JourneyCollaborationProvider(
        [
            {
                "message": "I propose placing the new skill in the existing first module.",
                "tool_calls": [
                    {
                        "tool_call_id": "contain-reflection",
                        "name": "add_relation",
                        "arguments": {
                            "expected_map_version_id": graph_after_add["map_version_id"],
                            "source_node_id": module_id,
                            "target_node_id": new_node_id,
                            "relation_type": "CONTAINS",
                            "reason": "Keep every routeable node inside one visible module.",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = relation_provider
    relation = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Place the new item in the right module.", "page_context": page_context},
    )
    relation_proposal_id = _pending_proposal(relation.json(), "add_relation")
    relation_approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{relation_proposal_id}/approve",
        json={"expected_revision": relation.json()["conversation"]["row_version"]},
    )
    assert relation_approved.status_code == 200, relation_approved.text

    active = next(
        revision["path"]
        for revision in client.get(f"/api/goals/{goal_id}/path-revisions").json()
        if revision["path"]["status"] == "ACTIVE"
    )
    clone_provider = _JourneyCollaborationProvider(
        [
            {
                "message": "I propose an editable copy of the current route.",
                "tool_calls": [
                    {
                        "tool_call_id": "clone-current-route",
                        "name": "clone_path_draft",
                        "arguments": {
                            "path_id": active["id"],
                            "expected_revision": active["row_version"],
                            "change_summary": "Append the reflection loop only",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = clone_provider
    clone_turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Update the route incrementally.", "page_context": page_context},
    )
    clone_proposal_id = _pending_proposal(clone_turn.json(), "clone_path_draft")
    clone_approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{clone_proposal_id}/approve",
        json={"expected_revision": clone_turn.json()["conversation"]["row_version"]},
    )
    assert clone_approved.status_code == 200, clone_approved.text
    draft = clone_approved.json()["proposal_review"]["result"]
    assert [step["node_id"] for step in draft["steps"]] == original_route_ids

    add_step_provider = _JourneyCollaborationProvider(
        [
            {
                "message": "The existing route stays unchanged; the new reflection is appended.",
                "tool_calls": [
                    {
                        "tool_call_id": "append-reflection-step",
                        "name": "add_path_step",
                        "arguments": {
                            "path_id": draft["path"]["id"],
                            "expected_revision": draft["path"]["row_version"],
                            "node_id": new_node_id,
                            "preferred_order": len(draft["steps"]),
                            "required_mastery_level": 3,
                            "recommendation_reason": "Reflect after the existing practice route.",
                            "action_kind": "REVIEW",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = add_step_provider
    step_turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={
            "content": "Add the missing item to the end of the route.",
            "page_context": page_context,
        },
    )
    step_proposal_id = _pending_proposal(step_turn.json(), "add_path_step")
    step_approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{step_proposal_id}/approve",
        json={"expected_revision": step_turn.json()["conversation"]["row_version"]},
    )
    assert step_approved.status_code == 200, step_approved.text
    updated_draft = step_approved.json()["proposal_review"]["result"]
    updated_route_ids = [step["node_id"] for step in updated_draft["steps"]]
    assert updated_route_ids[:-1] == original_route_ids
    assert updated_route_ids[-1] == new_node_id

    activated = client.post(
        f"/api/path-revisions/{updated_draft['path']['id']}/activate",
        json={"expected_revision": updated_draft["path"]["row_version"]},
    )
    assert activated.status_code == 200, activated.text
    assert [item["node_id"] for item in _goal_overview(client, goal_id)["route_overview"]] == (
        updated_route_ids
    )
    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert len([message for message in persisted["messages"] if message["role"] == "USER"]) >= 6
