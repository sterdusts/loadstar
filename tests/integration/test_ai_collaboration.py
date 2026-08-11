"""Integration coverage for durable collaboration and draft-only AI tools."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert all(message["message_metadata"]["full_result_persisted"] for message in tool_messages)

    graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    assert any(node["title"] == "变量与基本数据" for node in graph["nodes"])
    revisions = client.get(f"/api/goals/{goal['id']}/path-revisions").json()
    assert len(revisions) == 1
    assert revisions[0]["path"]["status"] == "DRAFT"
    assert provider.contexts[0]["project"]["exists"] is True
    assert provider.contexts[0]["tool_policy"]["draft_only"] is True


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

    archived = client.delete(f"/api/goals/{archived_goal['id']}")
    assert archived.status_code == 204, archived.text

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
    assert tool_message["structured_content"]["status"] == "FAILED"
    assert tool_message["structured_content"]["error"]["code"] == ("invalid_state_transition")
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
    assert [message["role"] for message in payload["messages"]] == ["USER", "ASSISTANT"]
    assert payload["messages"][1]["message_metadata"]["request_failed"] is True
    persisted = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert persisted["messages"][0]["content"] == "这条消息不能因为上游失败而丢失"


def test_external_provider_requires_consent_on_each_send(client: TestClient) -> None:
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
    assert denied.status_code == 400
    assert client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"] == []

    allowed = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "本次确认", "confirmed_external_ai": True},
    )
    assert allowed.status_code == 200
    denied_again = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "下一次仍需确认"},
    )
    assert denied_again.status_code == 400
    assert len(provider.contexts) == 1


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
    assert tool_message["structured_content"]["status"] == "FAILED"
    assert tool_message["structured_content"]["tool_name"] == "update_path_step"

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
