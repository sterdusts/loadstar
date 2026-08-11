"""Integration coverage for durable collaboration and draft-only AI tools."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from learning_navigator.application.collaboration import (
    MAX_PROJECT_CONTEXT_EDGES,
    MAX_PROJECT_CONTEXT_NODES,
)
from learning_navigator.application.services import NavigatorApplication
from learning_navigator.infrastructure.ai.providers import AIProviderError, MockProvider


class FakeCollaborationProvider:
    def __init__(
        self,
        responses: list[dict[str, Any] | Exception],
        *,
        name: str = "mock",
    ) -> None:
        self.name = name
        self.model = "fake-collaboration-v1"
        self.responses = iter(responses)
        self.contexts: list[dict[str, Any]] = []
        self.schemas: list[dict[str, Any]] = []

    async def collaborate(
        self,
        context: dict[str, Any],
        *,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.contexts.append(context)
        self.schemas.append(response_schema)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def learning_plan_payload() -> dict[str, Any]:
    plan = asyncio.run(
        MockProvider().generate_learning_plan(
            "Python 自动化",
            "从零开始，最终完成一个可验证的小型自动化项目",
        )
    )
    return plan.model_dump(mode="json")


def _create_goal(client: TestClient, python_map: dict[str, object]) -> dict[str, Any]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": "完成 Python 文件处理项目",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_offline_mock_can_create_a_finalizable_pre_project_draft(client: TestClient) -> None:
    created = client.post(
        "/api/ai/conversations",
        json={"title": "Offline end-to-end"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]
    assert created.json()["conversation"]["purpose"] == "PLANNING"
    assert created.json()["conversation"]["context_key"] is None
    assert created.json()["conversation"]["context_snapshot"] == {}

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "建立一个学习数据分析的框架"},
    )
    assert turn.status_code == 200, turn.text
    conversation = turn.json()["conversation"]
    assert conversation["working_plan"]["navigation"]["goal_title"]
    assistant = turn.json()["messages"][1]
    assert assistant["structured_content"]["plan_ready"] is True

    finalized = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": conversation["row_version"]},
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["conversation"]["learning_plan_id"]


def test_pre_project_conversation_finalizes_then_explicitly_activates(
    client: TestClient,
    learning_plan_payload: dict[str, Any],
) -> None:
    provider = FakeCollaborationProvider(
        [
            {
                "message": "我已把目标整理成一份可继续修改的框架草案。",
                "tool_calls": [],
                "working_plan": learning_plan_payload,
                "plan_ready": True,
                "conversation_summary": "用户希望从零完成 Python 自动化项目。",
            }
        ]
    )
    client.app.state.ai_provider = provider

    created = client.post(
        "/api/ai/conversations",
        json={"title": "讨论 Python 自动化目标"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "我希望先把目标聊清楚，再决定是否建立项目"},
    )
    assert turn.status_code == 200, turn.text
    turn_payload = turn.json()
    assert turn_payload["conversation"]["space_id"] is None
    assert turn_payload["conversation"]["goal_id"] is None
    assert turn_payload["conversation"]["working_plan"]["navigation"]
    assert [message["role"] for message in turn_payload["messages"]] == [
        "USER",
        "ASSISTANT",
    ]
    assert provider.contexts[0]["project"] == {"exists": False, "goal_id": None}
    assert provider.contexts[0]["tool_policy"]["enabled"] is False

    revision = turn_payload["conversation"]["row_version"]
    finalized = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": revision},
    )
    assert finalized.status_code == 200, finalized.text
    finalized_payload = finalized.json()["conversation"]
    assert finalized_payload["learning_plan_id"]
    assert finalized_payload["final_plan"] == finalized_payload["working_plan"]
    assert finalized_payload["space_id"] is None
    assert client.get("/api/spaces").json() == []

    duplicate_finalize = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": finalized_payload["row_version"]},
    )
    assert duplicate_finalize.status_code == 409
    assert duplicate_finalize.json()["detail"]["code"] == "invalid_state_transition"

    activated = client.post(
        f"/api/ai/conversations/{conversation_id}/activate-plan",
        json={"expected_revision": finalized_payload["row_version"]},
    )
    assert activated.status_code == 200, activated.text
    activation_payload = activated.json()
    assert activation_payload["conversation"]["space_id"]
    assert activation_payload["conversation"]["goal_id"]
    assert activation_payload["conversation"]["purpose"] == "PROJECT_ASSISTANT"
    assert activation_payload["conversation"]["context_key"] == (
        f"project:{activation_payload['conversation']['goal_id']}"
    )
    assert activation_payload["activation"]["route"]["path"]["status"] == "ACTIVE"

    repeated = client.post(
        f"/api/ai/conversations/{conversation_id}/activate-plan",
        json={
            "expected_revision": activation_payload["conversation"]["row_version"],
        },
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "invalid_state_transition"
    assert len(client.get("/api/spaces").json()) == 1


def test_continuing_after_finalization_supersedes_the_locked_plan(
    client: TestClient,
    learning_plan_payload: dict[str, Any],
) -> None:
    provider = FakeCollaborationProvider(
        [
            {
                "message": "Draft ready.",
                "tool_calls": [],
                "working_plan": learning_plan_payload,
                "plan_ready": True,
            },
            {
                "message": "The draft is open for another revision.",
                "tool_calls": [],
                "working_plan": learning_plan_payload,
                "plan_ready": True,
            },
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={"title": "Reopen a finalized draft"},
    ).json()["conversation"]["id"]
    first_turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Build the initial framework."},
    ).json()
    finalized = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": first_turn["conversation"]["row_version"]},
    ).json()["conversation"]
    old_plan_id = finalized["learning_plan_id"]

    continued = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Add a stronger verification requirement."},
    )
    assert continued.status_code == 200, continued.text
    reopened = continued.json()["conversation"]
    assert reopened["final_plan"] is None
    assert reopened["learning_plan_id"] is None
    assert reopened["working_plan"] == learning_plan_payload
    old_plan = client.get(f"/api/learning-plans/{old_plan_id}")
    assert old_plan.status_code == 200, old_plan.text
    assert old_plan.json()["review_status"] == "REJECTED"


def test_project_tools_modify_only_drafts_and_persist_results(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    provider = FakeCollaborationProvider(
        [
            {
                "message": "已更新草稿节点，并创建一条仍待用户确认的路径草稿。",
                "tool_calls": [
                    {
                        "tool_call_id": "rename-node",
                        "name": "update_node",
                        "arguments": {
                            "expected_map_version_id": space["draft_version_id"],
                            "node_id": nodes["变量"],
                            "title": "变量与基本数据",
                        },
                    },
                    {
                        "tool_call_id": "draft-path",
                        "name": "create_path_draft",
                        "arguments": {
                            "expected_map_version_id": space["draft_version_id"],
                            "goal_id": goal["id"],
                            "change_summary": "Conversation path candidate",
                        },
                    },
                ],
            }
        ]
    )
    client.app.state.ai_provider = provider
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "优化当前项目",
            "space_id": space["id"],
            "goal_id": goal["id"],
        },
    ).json()
    conversation_id = created["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "把变量节点说清楚，并先给我一个可编辑路径"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    tool_messages = [message for message in payload["messages"] if message["role"] == "TOOL"]
    assert [message["structured_content"]["status"] for message in tool_messages] == [
        "PENDING",
        "PENDING",
    ]
    assert all(message["message_metadata"]["full_result_persisted"] for message in tool_messages)
    assert provider.contexts[0]["tool_policy"]["requires_human_approval"] is True
    rename_proposal_id = tool_messages[0]["structured_content"]["tool_call_id"]
    path_proposal_id = tool_messages[1]["structured_content"]["tool_call_id"]

    proposed_title = tool_messages[0]["structured_content"]["proposal"]["arguments"]["title"]
    target_node_id = tool_messages[0]["structured_content"]["proposal"]["arguments"]["node_id"]
    before_review = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert (
        next(node for node in before_review["nodes"] if node["id"] == target_node_id)["title"]
        != proposed_title
    )
    assert client.get(f"/api/goals/{goal['id']}/path-revisions").json() == []

    approved_node = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{rename_proposal_id}/approve",
        json={"expected_revision": payload["conversation"]["row_version"]},
    )
    assert approved_node.status_code == 200, approved_node.text
    approved_node_payload = approved_node.json()
    assert approved_node_payload["proposal_review"]["status"] == "SUCCEEDED"
    approved_path = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{path_proposal_id}/approve",
        json={"expected_revision": approved_node_payload["conversation"]["row_version"]},
    )
    assert approved_path.status_code == 200, approved_path.text
    assert approved_path.json()["proposal_review"]["status"] == "SUCCEEDED"

    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert any(node["title"] == "变量与基本数据" for node in graph["nodes"])
    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    assert len(revisions) == 1
    assert revisions[0]["path"]["status"] == "DRAFT"
    assert provider.contexts[0]["project"]["exists"] is True
    assert provider.contexts[0]["tool_policy"]["draft_only"] is True


def test_repeated_provider_tool_call_ids_get_unique_persisted_proposal_ids(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    target = client.get(f"/api/spaces/{space['id']}/graph").json()["nodes"][0]
    call = {
        "tool_call_id": "call_1",
        "name": "update_node",
        "arguments": {
            "expected_map_version_id": space["draft_version_id"],
            "node_id": target["id"],
            "title": "A proposed title",
        },
    }
    client.app.state.ai_provider = FakeCollaborationProvider(
        [
            {"message": "first", "tool_calls": [call]},
            {"message": "second", "tool_calls": [call]},
        ]
    )
    created = client.post(
        "/api/ai/conversations",
        json={"title": "Repeated provider ids", "space_id": space["id"], "goal_id": goal["id"]},
    ).json()
    conversation_id = created["conversation"]["id"]
    assert (
        client.post(
            f"/api/ai/conversations/{conversation_id}/messages", json={"content": "first"}
        ).status_code
        == 200
    )
    second = client.post(
        f"/api/ai/conversations/{conversation_id}/messages", json={"content": "second"}
    )
    assert second.status_code == 200, second.text
    proposals = [
        message
        for message in second.json()["messages"]
        if message["role"] == "TOOL" and message["structured_content"].get("status") == "PENDING"
    ]
    assert len(proposals) == 2
    assert {item["structured_content"]["provider_tool_call_id"] for item in proposals} == {"call_1"}
    assert len({item["structured_content"]["tool_call_id"] for item in proposals}) == 2


def test_project_provider_context_excludes_archived_goal_path_revisions(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    """A shared framework must not leak an archived project's route into AI context."""

    archived_goal = _create_goal(client, python_map)
    archived_path_response = client.post(f"/api/goals/{archived_goal['id']}/paths")
    assert archived_path_response.status_code == 200, archived_path_response.text
    archived_path_id = archived_path_response.json()["path"]["id"]

    active_goal = _create_goal(client, python_map)
    active_path_response = client.post(f"/api/goals/{active_goal['id']}/paths")
    assert active_path_response.status_code == 200, active_path_response.text
    active_path_id = active_path_response.json()["path"]["id"]

    archived = client.post(f"/api/goals/{archived_goal['id']}/archive")
    assert archived.status_code == 200, archived.text

    space = python_map["space"]
    assert isinstance(space, dict)
    provider = FakeCollaborationProvider(
        [{"message": "I only used the active project's route.", "tool_calls": []}]
    )
    client.app.state.ai_provider = provider
    conversation = client.post(
        "/api/ai/conversations",
        json={
            "title": "Shared-space active project",
            "space_id": space["id"],
            "goal_id": active_goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": f"project:{active_goal['id']}",
        },
    )
    assert conversation.status_code == 201, conversation.text

    turn = client.post(
        f"/api/ai/conversations/{conversation.json()['conversation']['id']}/messages",
        json={"content": "Describe my current route."},
    )
    assert turn.status_code == 200, turn.text

    project_context = provider.contexts[0]["project"]
    assert [goal["id"] for goal in project_context["goals"]] == [active_goal["id"]]
    path_revision_ids = {path["id"] for path in project_context["path_revisions"]}
    assert active_path_id in path_revision_ids
    assert archived_path_id not in path_revision_ids


def test_project_provider_context_is_bounded_and_reports_omitted_counts(
    client: TestClient,
    python_map: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    priority_node_id = "synthetic-current-node"
    raw_node_count = MAX_PROJECT_CONTEXT_NODES + 5
    raw_edge_count = MAX_PROJECT_CONTEXT_EDGES + 10
    synthetic_node_ids = [
        goal["target_node_id"],
        *(f"synthetic-node-{index}" for index in range(raw_node_count - 2)),
        priority_node_id,
    ]
    oversized_graph = {
        "space_id": space["id"],
        "map_version_id": space["draft_version_id"],
        "nodes": [
            {
                "id": node_id,
                "title": f"Node {index}",
                "description": "x" * 5_000,
                "node_type": "CONCEPT",
                "difficulty": 2,
                "depth_level": 1,
                "status": "ACTIVE",
                "source_basis": [{"private": "must-not-be-forwarded"}],
            }
            for index, node_id in enumerate(synthetic_node_ids)
        ],
        "edges": [
            {
                "id": f"edge-{index}",
                "source_node_id": synthetic_node_ids[index % raw_node_count],
                "target_node_id": synthetic_node_ids[(index + 1) % raw_node_count],
                "relation_type": "PREREQUISITE",
                "reason": "r" * 2_000,
            }
            for index in range(raw_edge_count)
        ],
        "cycle": None,
    }

    monkeypatch.setattr(
        NavigatorApplication,
        "graph_view",
        lambda _application, **_kwargs: oversized_graph,
    )
    provider = FakeCollaborationProvider(
        [{"message": "I used the bounded project context.", "tool_calls": []}]
    )
    client.app.state.ai_provider = provider
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "Bounded project context",
            "space_id": space["id"],
            "goal_id": goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": f"project:{goal['id']}",
        },
    )
    assert created.status_code == 201, created.text
    turn = client.post(
        f"/api/ai/conversations/{created.json()['conversation']['id']}/messages",
        json={
            "content": "Use the current project context.",
            "page_context": {
                "page_key": "project-overview",
                "page_kind": "project",
                "space_id": space["id"],
                "goal_id": goal["id"],
                "node_id": priority_node_id,
            },
        },
    )
    assert turn.status_code == 200, turn.text

    project_context = provider.contexts[0]["project"]
    bounded_map = project_context["editable_map"]
    forwarded_node_ids = {node["id"] for node in bounded_map["nodes"]}
    assert len(bounded_map["nodes"]) == MAX_PROJECT_CONTEXT_NODES
    assert len(bounded_map["edges"]) <= MAX_PROJECT_CONTEXT_EDGES
    assert goal["target_node_id"] in forwarded_node_ids
    assert priority_node_id in forwarded_node_ids
    assert bounded_map["omitted_counts"]["nodes"] == 5
    assert bounded_map["omitted_counts"]["edges"] > 0
    assert project_context["omitted_counts"]["map_nodes"] == 5
    assert project_context["omitted_counts"]["map_edges"] > 0
    assert all(len(node.get("description", "")) <= 1_000 for node in bounded_map["nodes"])
    assert all("source_basis" not in node for node in bounded_map["nodes"])
    assert len(json.dumps(project_context, ensure_ascii=False)) < 150_000

    assistant = next(
        message for message in turn.json()["messages"] if message["role"] == "ASSISTANT"
    )
    assert assistant["message_metadata"]["project_context_truncated"] is True
    assert assistant["message_metadata"]["project_context_omitted_counts"]["map_nodes"] == 5


def test_map_tool_rejects_a_stale_draft_version(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    provider = FakeCollaborationProvider(
        [
            {
                "message": "I prepared a node edit.",
                "tool_calls": [
                    {
                        "tool_call_id": "stale-map-edit",
                        "name": "update_node",
                        "arguments": {
                            "expected_map_version_id": "stale-map-version",
                            "node_id": nodes["变量"],
                            "title": "This stale edit must not be applied",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={
            "title": "Map version guard",
            "space_id": space["id"],
            "goal_id": goal["id"],
        },
    ).json()["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Apply only if the map context is still current."},
    )
    assert response.status_code == 200, response.text
    tool_message = next(
        message for message in response.json()["messages"] if message["role"] == "TOOL"
    )
    assert tool_message["structured_content"]["status"] == "PENDING"
    proposal_id = tool_message["structured_content"]["tool_call_id"]
    approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/approve",
        json={"expected_revision": response.json()["conversation"]["row_version"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["proposal_review"]["status"] == "FAILED"
    assert approved.json()["proposal_review"]["error"]["code"] == ("invalid_state_transition")
    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    persisted = next(node for node in graph["nodes"] if node["id"] == nodes["变量"])
    assert persisted["title"] == "变量"


def test_provider_failure_persists_user_message_and_visible_error(client: TestClient) -> None:
    provider = FakeCollaborationProvider(
        [
            AIProviderError(
                "provider unavailable",
                code="connection_error",
                retryable=True,
            )
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={"title": "保留失败消息"},
    ).json()["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "这条消息不能因为上游失败而丢失"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["turn"]["error"]["code"] == "connection_error"
    assert "provider unavailable" not in response.text
    assert [message["role"] for message in payload["messages"]] == ["USER", "ASSISTANT"]
    assert payload["messages"][1]["message_metadata"]["request_failed"] is True
    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert persisted["messages"][0]["content"] == "这条消息不能因为上游失败而丢失"


def test_tool_proposal_rejection_is_revision_bound_scoped_and_non_mutating(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    graph_before = client.get(f"/api/spaces/{space['id']}/graph").json()
    target = graph_before["nodes"][0]
    provider = FakeCollaborationProvider(
        [
            {
                "message": "I prepared a draft rename for review.",
                "tool_calls": [
                    {
                        "tool_call_id": "reject-this-rename",
                        "name": "update_node",
                        "arguments": {
                            "expected_map_version_id": space["draft_version_id"],
                            "node_id": target["id"],
                            "title": "This title must never be applied",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = provider
    created = client.post(
        "/api/ai/conversations",
        json={"title": "Human review", "space_id": space["id"], "goal_id": goal["id"]},
    ).json()
    conversation_id = created["conversation"]["id"]
    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Propose a rename, but do not apply it."},
    )
    assert turn.status_code == 200, turn.text
    revision = turn.json()["conversation"]["row_version"]
    proposal_message = next(
        message for message in turn.json()["messages"] if message["role"] == "TOOL"
    )
    proposal_id = proposal_message["structured_content"]["tool_call_id"]

    stale = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/reject",
        json={"expected_revision": revision - 1},
    )
    assert stale.status_code == 409
    other_user = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/reject",
        json={"expected_revision": revision},
        headers={"X-User-ID": "another-user"},
    )
    assert other_user.status_code == 404

    rejected = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/reject",
        json={"expected_revision": revision},
    )
    assert rejected.status_code == 200, rejected.text
    rejected_payload = rejected.json()
    assert rejected_payload["proposal_review"]["status"] == "REJECTED"
    graph_after = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert (
        next(node for node in graph_after["nodes"] if node["id"] == target["id"])["title"]
        == target["title"]
    )

    repeated = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/approve",
        json={
            "expected_revision": rejected_payload["conversation"]["row_version"],
        },
    )
    assert repeated.status_code == 409


def test_unexpected_provider_bug_rolls_back_turn_without_reflecting_exception(
    client: TestClient,
) -> None:
    client.app.state.ai_provider = FakeCollaborationProvider(
        [RuntimeError("sensitive internal provider detail")]
    )
    conversation_id = client.post(
        "/api/ai/conversations",
        json={"title": "Unexpected provider failure"},
    ).json()["conversation"]["id"]

    with pytest.raises(RuntimeError) as exc_info:
        client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "This turn must remain atomic."},
        )

    assert "trace_id=" in str(exc_info.value)
    assert "sensitive internal provider detail" not in str(exc_info.value)
    assert client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"] == []


def test_misconfigured_provider_preserves_local_turn_and_exposes_it_in_history(
    client: TestClient,
) -> None:
    profile_response = client.post(
        "/api/ai/provider-profiles",
        json={
            "display_name": "OpenAI without a key",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "is_default": True,
        },
    )
    assert profile_response.status_code == 201, profile_response.text
    profile = profile_response.json()
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "配置失败也要保存",
            "provider_profile_id": profile["id"],
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "即使 API Key 缺失，也请保留这条本地消息"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["turn"]["error"]["code"] == "ai_configuration_error"
    assert [message["role"] for message in payload["messages"]] == ["USER", "ASSISTANT"]
    failure = payload["messages"][1]
    assert failure["provider"] == "openai"
    assert failure["model"] == "gpt-4o-mini"
    assert failure["message_metadata"]["provider_profile_id"] == profile["id"]
    assert failure["message_metadata"]["request_failed"] is True

    history = client.get("/api/ai/conversations")
    assert history.status_code == 200, history.text
    assert conversation_id in {item["id"] for item in history.json()}
    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert persisted["messages"][0]["content"] == "即使 API Key 缺失，也请保留这条本地消息"


def test_external_provider_denial_is_saved_locally_and_required_on_each_send(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [
            {"message": "first", "tool_calls": []},
            {"message": "second", "tool_calls": []},
        ],
        name="remote-fake",
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={"title": "外部模型确认"},
    ).json()["conversation"]["id"]

    denied = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "未确认"},
    )
    assert denied.status_code == 200, denied.text
    denied_payload = denied.json()
    assert denied_payload["turn"]["error"]["code"] == "ai_configuration_error"
    assert [message["role"] for message in denied_payload["messages"]] == [
        "USER",
        "ASSISTANT",
    ]
    assert denied_payload["messages"][1]["provider"] == "remote-fake"
    assert denied_payload["messages"][1]["message_metadata"]["request_failed"] is True
    assert len(provider.contexts) == 0

    allowed = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "本次确认", "confirmed_external_ai": True},
    )
    assert allowed.status_code == 200
    denied_again = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "下一次仍需确认"},
    )
    assert denied_again.status_code == 200, denied_again.text
    assert denied_again.json()["turn"]["error"]["code"] == "ai_configuration_error"
    assert len(provider.contexts) == 1
    history_ids = {item["id"] for item in client.get("/api/ai/conversations").json()}
    assert conversation_id in history_ids


def test_archive_removes_conversation_from_default_list(client: TestClient) -> None:
    created = client.post(
        "/api/ai/conversations",
        json={"title": "将被归档"},
    ).json()["conversation"]
    turn = client.post(
        f"/api/ai/conversations/{created['id']}/messages",
        json={"content": "这是一条需要保留的真实对话"},
    )
    assert turn.status_code == 200, turn.text
    persisted = turn.json()["conversation"]
    archived = client.post(
        f"/api/ai/conversations/{created['id']}/archive",
        json={"expected_revision": persisted["row_version"]},
    )
    assert archived.status_code == 200
    assert archived.json()["conversation"]["status"] == "ARCHIVED"
    assert client.get("/api/ai/conversations").json() == []
    with_archived = client.get(
        "/api/ai/conversations",
        params={"include_archived": True},
    ).json()
    assert [item["id"] for item in with_archived] == [created["id"]]
    restored = client.post(
        f"/api/ai/conversations/{created['id']}/restore",
        json={"expected_revision": archived.json()["conversation"]["row_version"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["conversation"]["status"] == "ACTIVE"
    assert [item["id"] for item in client.get("/api/ai/conversations").json()] == [created["id"]]


def test_empty_conversation_is_not_returned_as_history(client: TestClient) -> None:
    empty = client.post(
        "/api/ai/conversations",
        json={"title": "Never sent"},
    )
    assert empty.status_code == 201, empty.text

    active = client.post(
        "/api/ai/conversations",
        json={"title": "Has a real turn"},
    )
    assert active.status_code == 201, active.text
    active_id = active.json()["conversation"]["id"]
    turn = client.post(
        f"/api/ai/conversations/{active_id}/messages",
        json={"content": "Start this discussion"},
    )
    assert turn.status_code == 200, turn.text

    history = client.get("/api/ai/conversations")
    assert history.status_code == 200, history.text
    history_ids = {item["id"] for item in history.json()}
    assert active_id in history_ids
    assert empty.json()["conversation"]["id"] not in history_ids


def test_history_thread_continues_after_page_change_with_its_persisted_safe_context(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [
            {"message": "第一次回答", "tool_calls": []},
            {"message": "跨页后仍在同一对话", "tool_calls": []},
        ]
    )
    client.app.state.ai_provider = provider
    safe_context = {
        "page_key": "activity",
        "page_kind": "PAGE",
        "page_title": "动态",
        "section": "overview",
    }
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "跨页保留的对话",
            "purpose": "PAGE_ASSISTANT",
            "context_key": "page:activity",
            "context_snapshot": safe_context,
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    first = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "记录第一条消息", "page_context": safe_context},
    )
    assert first.status_code == 200, first.text

    # This represents selecting the same history item while another page is open.
    # Omitting that other page's context makes the service fall back to the
    # conversation's persisted, already validated snapshot instead of changing scope.
    continued = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "继续原来的讨论"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["conversation"]["id"] == conversation_id
    assert provider.contexts[1]["page_context"] == safe_context

    persisted = client.get(f"/api/ai/conversations/{conversation_id}")
    assert persisted.status_code == 200, persisted.text
    messages = persisted.json()["messages"]
    assert [item["content"] for item in messages if item["role"] == "USER"] == [
        "记录第一条消息",
        "继续原来的讨论",
    ]


def test_unified_history_keeps_planning_and_page_threads_in_place(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [
            {"message": "项目方案先继续讨论。", "tool_calls": []},
            {"message": "页面问题已经记录。", "tool_calls": []},
            {"message": "回到原项目讨论，仍沿用同一记录。", "tool_calls": []},
        ]
    )
    client.app.state.ai_provider = provider
    planning = client.post(
        "/api/ai/conversations",
        json={"title": "共创新项目"},
    )
    assert planning.status_code == 201, planning.text
    planning_id = planning.json()["conversation"]["id"]

    page_context = {
        "page_key": "activity",
        "page_kind": "PAGE",
        "page_title": "动态",
        "section": "overview",
    }
    page = client.post(
        "/api/ai/conversations",
        json={
            "title": "动态页面问答",
            "purpose": "PAGE_ASSISTANT",
            "context_key": "page:activity",
            "context_snapshot": page_context,
        },
    )
    assert page.status_code == 201, page.text
    page_id = page.json()["conversation"]["id"]

    planning_seed = client.post(
        f"/api/ai/conversations/{planning_id}/messages",
        json={"content": "先讨论新项目的目标"},
    )
    assert planning_seed.status_code == 200, planning_seed.text
    page_seed = client.post(
        f"/api/ai/conversations/{page_id}/messages",
        json={"content": "记录当前页面的问题", "page_context": page_context},
    )
    assert page_seed.status_code == 200, page_seed.text

    # The shared sidebar loads one unfiltered history for both entry modes.
    history = client.get("/api/ai/conversations")
    assert history.status_code == 200, history.text
    history_by_id = {item["id"]: item for item in history.json()}
    assert set(history_by_id) == {planning_id, page_id}
    assert history_by_id[planning_id]["purpose"] == "PLANNING"
    assert history_by_id[page_id]["purpose"] == "PAGE_ASSISTANT"

    # Selecting the planning item while another page is open must continue the
    # original thread instead of creating a replacement or navigating away.
    continued = client.post(
        f"/api/ai/conversations/{planning_id}/messages",
        json={"content": "继续刚才的新项目讨论"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["conversation"]["id"] == planning_id
    assert continued.json()["conversation"]["purpose"] == "PLANNING"

    persisted_planning = client.get(f"/api/ai/conversations/{planning_id}").json()
    persisted_page = client.get(f"/api/ai/conversations/{page_id}").json()
    assert [
        item["content"] for item in persisted_planning["messages"] if item["role"] == "USER"
    ] == ["先讨论新项目的目标", "继续刚才的新项目讨论"]
    assert [item["content"] for item in persisted_page["messages"] if item["role"] == "USER"] == [
        "记录当前页面的问题"
    ]


def test_contextual_assistant_purpose_and_context_key_isolate_history(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [
            {"message": "Planning history exists after a real turn.", "tool_calls": []},
            {"message": "Page history exists after a real turn.", "tool_calls": []},
            {"message": "This remains a page-only answer.", "tool_calls": []},
        ]
    )
    client.app.state.ai_provider = provider
    planning = client.post(
        "/api/ai/conversations",
        json={"title": "Legacy planning history"},
    )
    assert planning.status_code == 201, planning.text
    page = client.post(
        "/api/ai/conversations",
        json={
            "title": "Growth page assistant",
            "purpose": "PAGE_ASSISTANT",
            "context_key": "page:/growth",
            "context_snapshot": {
                "page_key": "/growth",
                "page_kind": "growth",
                "page_title": "成长",
            },
        },
    )
    assert page.status_code == 201, page.text

    planning_seed = client.post(
        f"/api/ai/conversations/{planning.json()['conversation']['id']}/messages",
        json={"content": "建立这个项目的讨论记录"},
    )
    assert planning_seed.status_code == 200, planning_seed.text
    page_seed = client.post(
        f"/api/ai/conversations/{page.json()['conversation']['id']}/messages",
        json={"content": "建立这个页面的讨论记录"},
    )
    assert page_seed.status_code == 200, page_seed.text

    pre_project = client.get(
        "/api/ai/conversations",
        params={"pre_project_only": True},
    )
    assert pre_project.status_code == 200, pre_project.text
    assert [item["id"] for item in pre_project.json()] == [planning.json()["conversation"]["id"]]

    page_only = client.get(
        "/api/ai/conversations",
        params={"purpose": "PAGE_ASSISTANT", "context_key": "page:/growth"},
    )
    assert page_only.status_code == 200, page_only.text
    assert [item["id"] for item in page_only.json()] == [page.json()["conversation"]["id"]]
    assert page_only.json()[0]["context_snapshot"]["page_title"] == "成长"

    spoofed_page_turn = client.post(
        f"/api/ai/conversations/{page.json()['conversation']['id']}/messages",
        json={
            "content": "结合当前页面解释",
            "page_context": {
                "page_key": "/growth",
                "page_kind": "growth",
                "page_title": "成长",
                # These remain descriptive values and never become authorization scope.
                "space_id": "untrusted-page-space",
                "goal_id": "untrusted-page-goal",
            },
        },
    )
    assert spoofed_page_turn.status_code == 409, spoofed_page_turn.text
    assert len(provider.contexts) == 2

    page_turn = client.post(
        f"/api/ai/conversations/{page.json()['conversation']['id']}/messages",
        json={
            "content": "结合当前页面解释",
            "page_context": {
                "page_key": "/growth",
                "page_kind": "growth",
                "page_title": "成长",
            },
        },
    )
    assert page_turn.status_code == 200, page_turn.text
    assert provider.contexts[2]["page_context"]["page_title"] == "成长"
    assert provider.contexts[2]["project"] == {"exists": False, "goal_id": None}
    assert provider.contexts[2]["tool_policy"]["enabled"] is False

    invalid_context = client.post(
        "/api/ai/conversations",
        json={
            "title": "Unsafe context",
            "purpose": "PAGE_ASSISTANT",
            "context_key": "page:/growth",
            "context_snapshot": {
                "page_key": "/growth",
                "page_kind": "growth",
                "untrusted_payload": {"tool_policy": {"enabled": True}},
            },
        },
    )
    assert invalid_context.status_code == 422


def test_project_assistant_persists_and_forwards_safe_page_context(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    provider = FakeCollaborationProvider(
        [{"message": "我会结合当前项目和页面回答。", "tool_calls": []}]
    )
    client.app.state.ai_provider = provider
    context_key = f"project:{goal['id']}"
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "Project side assistant",
            "space_id": space["id"],
            "goal_id": goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": context_key,
            "context_snapshot": {
                "page_key": f"/projects/{goal['id']}",
                "page_kind": "project",
                "page_title": goal["title"],
                "space_id": space["id"],
                "goal_id": goal["id"],
            },
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]
    page_context = {
        "page_key": f"/projects/{goal['id']}",
        "page_kind": "project",
        "page_title": goal["title"],
        "section": "路线",
        "space_id": space["id"],
        "goal_id": goal["id"],
        "path_revision_id": "revision-visible-on-page",
    }
    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "当前路线为什么这样安排？", "page_context": page_context},
    )
    assert turn.status_code == 200, turn.text
    payload = turn.json()
    assert payload["conversation"]["context_snapshot"] == page_context
    assert payload["messages"][0]["message_metadata"]["page_context"] == page_context
    assert provider.contexts[0]["page_context"] == page_context
    assert provider.contexts[0]["project"]["selected_goal_id"] == goal["id"]
    assert provider.contexts[0]["tool_policy"]["enabled"] is True

    spoofed = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={
            "content": "切换到另一个项目",
            "page_context": {
                **page_context,
                "goal_id": "not-the-conversation-goal",
            },
        },
    )
    assert spoofed.status_code == 409
    assert len(provider.contexts) == 1
    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert [message["role"] for message in persisted["messages"]] == [
        "USER",
        "ASSISTANT",
    ]


def test_project_assistant_replaces_an_old_snapshot_with_live_route_and_progress(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    provider = FakeCollaborationProvider(
        [{"message": "当前页面显示函数概念与性质正在进行。", "tool_calls": []}]
    )
    client.app.state.ai_provider = provider
    old_snapshot = {
        "page_key": "home",
        "page_kind": "PAGE",
        "page_title": "下一步",
        "section": "overview",
        "page_state": {
            "project_title": "旧页面",
            "current_node": None,
            "path_summary": {
                "total": 0,
                "completed": 0,
                "in_progress": 0,
                "not_started": 0,
                "steps": [],
            },
            "progress_summary": {
                "percent": 0,
                "completed": 0,
                "total": 0,
            },
        },
    }
    context_key = f"project:{goal['id']}"
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "旧页面建立的项目会话",
            "space_id": space["id"],
            "goal_id": goal["id"],
            "purpose": "PROJECT_ASSISTANT",
            "context_key": context_key,
            # The persisted scope remains this project even when its first UI snapshot is stale.
            "context_snapshot": {
                **old_snapshot,
                "page_key": "project",
                "page_kind": "PROJECT",
                "space_id": space["id"],
                "goal_id": goal["id"],
            },
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]
    live_page_state = {
        "project_title": goal["title"],
        "current_node": {
            "node_id": "node-functions",
            "name": "函数概念与性质",
            "status": "IN_PROGRESS",
            "path_position": 4,
            "score": 6,
        },
        "path_summary": {
            "total": 13,
            "completed": 3,
            "in_progress": 1,
            "not_started": 9,
            "steps": [
                {
                    "path_position": 4,
                    "node_id": "node-functions",
                    "name": "函数概念与性质",
                    "status": "IN_PROGRESS",
                    "score": 6,
                },
                {
                    "path_position": 5,
                    "node_id": "node-calculus",
                    "name": "极限与连续",
                    "status": "NOT_STARTED",
                    "score": None,
                },
            ],
        },
        "progress_summary": {
            "percent": 28,
            "completed": 3,
            "total": 13,
        },
    }
    live_context = {
        "page_key": "project",
        "page_kind": "PROJECT",
        "page_title": goal["title"],
        "section": "overview",
        "space_id": space["id"],
        "goal_id": goal["id"],
        "node_id": "node-functions",
        "path_revision_id": "active-path",
        "page_state": live_page_state,
    }

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "描述当前页面以及我的路线进度", "page_context": live_context},
    )

    assert turn.status_code == 200, turn.text
    forwarded_context = provider.contexts[0]["page_context"]
    assert forwarded_context["page_title"] == goal["title"]
    assert forwarded_context["page_state"]["project_title"] == goal["title"]
    assert forwarded_context["page_state"]["current_node"]["name"] == "函数概念与性质"
    assert forwarded_context["page_state"]["path_summary"]["total"] == 13
    assert forwarded_context["page_state"]["progress_summary"]["percent"] == 28
    assert forwarded_context != old_snapshot
    assert turn.json()["conversation"]["context_snapshot"] == forwarded_context
    assert turn.json()["messages"][0]["message_metadata"]["page_context"] == forwarded_context
    assert provider.contexts[0]["project"]["selected_goal_id"] == goal["id"]
    assert provider.contexts[0]["tool_policy"]["enabled"] is True


def test_planning_assistant_can_receive_the_live_next_page_goal_and_recommendation(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [{"message": "当前推荐是先学习实数与代数式。", "tool_calls": []}]
    )
    client.app.state.ai_provider = provider
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "下一步页面",
            "context_snapshot": {
                "page_key": "home",
                "page_kind": "PAGE",
                "page_title": "下一步",
            },
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]
    live_context = {
        "page_key": "home",
        "page_kind": "PAGE",
        "page_title": "下一步",
        "section": "overview",
        # The new-project thread may be launched from a project-aware page. These
        # identifiers are authorization-like and must not cross into PLANNING.
        "space_id": "existing-project-space",
        "goal_id": "existing-project-goal",
        "node_id": "node-real-algebra",
        "path_revision_id": "existing-active-path",
        "page_state": {
            "project_title": "建立系统数学体系并应用于 AI/量化",
            "current_node": {
                "node_id": "node-real-algebra",
                "name": "实数与代数式",
                "status": "NOT_STARTED",
                "path_position": 1,
                "score": None,
            },
            "path_summary": {
                "total": 13,
                "completed": 0,
                "in_progress": 0,
                "not_started": 13,
                "steps": [
                    {
                        "path_position": 1,
                        "node_id": "node-real-algebra",
                        "name": "实数与代数式",
                        "status": "NOT_STARTED",
                        "score": None,
                    }
                ],
            },
            "progress_summary": {
                "percent": 0,
                "completed": 0,
                "total": 13,
            },
        },
    }

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "描述当前页面", "page_context": live_context},
    )

    assert turn.status_code == 200, turn.text
    forwarded_context = provider.contexts[0]["page_context"]
    assert forwarded_context["page_key"] == live_context["page_key"]
    assert forwarded_context["page_state"]["project_title"].startswith("建立系统数学体系")
    assert forwarded_context["page_state"]["current_node"]["name"] == ("实数与代数式")
    assert forwarded_context["page_state"]["path_summary"]["total"] == 13
    assert "space_id" not in forwarded_context
    assert "goal_id" not in forwarded_context
    assert "node_id" not in forwarded_context
    assert "path_revision_id" not in forwarded_context
    assert provider.contexts[0]["project"] == {"exists": False, "goal_id": None}
    assert provider.contexts[0]["tool_policy"]["enabled"] is False


@pytest.mark.parametrize(
    "unsafe_page_state",
    [
        {
            "project_title": "项目",
            "dom": "<main>must never be forwarded</main>",
        },
        {
            "project_title": "项目",
            "tool_policy": {"enabled": True},
        },
        {
            "project_title": "项目",
            "path_summary": {
                "total": 41,
                "completed": 0,
                "in_progress": 0,
                "not_started": 41,
                "steps": [
                    {
                        "path_position": index + 1,
                        "node_id": f"node-{index}",
                        "name": f"节点 {index}",
                        "status": "NOT_STARTED",
                    }
                    for index in range(41)
                ],
            },
        },
        {"project_title": "x" * 241},
    ],
)
def test_page_state_rejects_unapproved_or_unbounded_browser_content(
    client: TestClient,
    unsafe_page_state: dict[str, Any],
) -> None:
    created = client.post(
        "/api/ai/conversations",
        json={"title": "Context validation"},
    )
    assert created.status_code == 201, created.text

    turn = client.post(
        f"/api/ai/conversations/{created.json()['conversation']['id']}/messages",
        json={
            "content": "Describe the page",
            "page_context": {
                "page_key": "home",
                "page_kind": "PAGE",
                "page_title": "下一步",
                "page_state": unsafe_page_state,
            },
        },
    )

    assert turn.status_code == 422


def test_forbidden_provider_tool_is_denied_and_persisted(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    active = client.post(f"/api/goals/{goal['id']}/paths")
    assert active.status_code == 200, active.text
    active_path = active.json()["path"]
    provider = FakeCollaborationProvider(
        [
            {
                "message": "I will activate the route directly.",
                "tool_calls": [
                    {
                        "tool_call_id": "forbidden-activation",
                        "name": "activate_path",
                        "arguments": {
                            "path_id": active_path["id"],
                            "expected_revision": active_path["row_version"],
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={
            "title": "Controlled tool boundary",
            "space_id": space["id"],
            "goal_id": goal["id"],
        },
    ).json()["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Do not bypass user activation."},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["turn"]["error"]["code"] == "invalid_collaboration_response"
    tool_messages = [message for message in payload["messages"] if message["role"] == "TOOL"]
    assert len(tool_messages) == 1
    denied = tool_messages[0]
    assert denied["structured_content"]["status"] == "DENIED"
    assert denied["structured_content"]["tool_name"] == "activate_path"
    assert denied["structured_content"]["provider_tool_call_id"] == "forbidden-activation"
    assert denied["message_metadata"]["denied"] is True

    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    persisted_active = next(
        item["path"] for item in revisions if item["path"]["id"] == active_path["id"]
    )
    assert persisted_active["status"] == "ACTIVE"
    assert persisted_active["row_version"] == active_path["row_version"]


def test_ai_tool_cannot_edit_an_active_path_revision(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map)
    space = python_map["space"]
    assert isinstance(space, dict)
    active_response = client.post(f"/api/goals/{goal['id']}/paths")
    assert active_response.status_code == 200, active_response.text
    active = active_response.json()
    active_path = active["path"]
    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    active_revision = next(item for item in revisions if item["path"]["id"] == active_path["id"])
    active_step = active_revision["steps"][0]
    provider = FakeCollaborationProvider(
        [
            {
                "message": "I prepared a path note.",
                "tool_calls": [
                    {
                        "tool_call_id": "edit-active-step",
                        "name": "update_path_step",
                        "arguments": {
                            "path_id": active_path["id"],
                            "step_id": active_step["id"],
                            "expected_revision": active_path["row_version"],
                            "user_note": "AI must not write this into an active route.",
                        },
                    }
                ],
            }
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={
            "title": "Draft-only path editing",
            "space_id": space["id"],
            "goal_id": goal["id"],
        },
    ).json()["conversation"]["id"]

    response = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "Suggest an edit without changing my active route."},
    )
    assert response.status_code == 200, response.text
    tool_message = next(
        message for message in response.json()["messages"] if message["role"] == "TOOL"
    )
    assert tool_message["structured_content"]["status"] == "PENDING"
    assert tool_message["structured_content"]["tool_name"] == "update_path_step"
    proposal_id = tool_message["structured_content"]["tool_call_id"]
    approved = client.post(
        f"/api/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/approve",
        json={"expected_revision": response.json()["conversation"]["row_version"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["proposal_review"]["status"] == "FAILED"

    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    persisted = next(item for item in revisions if item["path"]["id"] == active_path["id"])
    assert persisted["path"]["status"] == "ACTIVE"
    assert persisted["path"]["row_version"] == active_path["row_version"]
    persisted_step = next(step for step in persisted["steps"] if step["id"] == active_step["id"])
    assert persisted_step["user_note"] == active_step["user_note"]


def test_full_history_stays_local_while_provider_context_is_bounded(
    client: TestClient,
) -> None:
    provider = FakeCollaborationProvider(
        [
            {"message": "a" * 7_000, "tool_calls": []},
            {"message": "b" * 7_000, "tool_calls": []},
            {"message": "c" * 7_000, "tool_calls": []},
        ]
    )
    client.app.state.ai_provider = provider
    conversation_id = client.post(
        "/api/ai/conversations",
        json={"title": "Bounded provider context"},
    ).json()["conversation"]["id"]

    original_messages = ["u" * 7_000, "v" * 7_000, "w" * 7_000]
    for content in original_messages:
        response = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": content},
        )
        assert response.status_code == 200, response.text

    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert len(persisted["messages"]) == 6
    assert persisted["messages"][0]["content"] == original_messages[0]
    metadata = persisted["conversation"]["last_context_metadata"]
    assert metadata["history_message_count"] == 5
    assert metadata["truncated"] is True
    assert metadata["omitted_message_count"] > 0
    assert len(provider.contexts[-1]["history"]) < 5
    assert provider.contexts[-1]["prior_summary"]
