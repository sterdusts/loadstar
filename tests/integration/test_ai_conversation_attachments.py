"""Durable upload, multimodal context and history behavior for AI attachments."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from learning_navigator.infrastructure.ai.providers import MockProvider, _collaboration_prompt


class RecordingMockProvider:
    name = "mock"
    model = "recording-attachment-provider"

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []
        self.delegate = MockProvider()

    async def collaborate(
        self,
        context: dict[str, Any],
        *,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.contexts.append(context)
        return await self.delegate.collaborate(context, response_schema=response_schema)


def _upload(
    client: TestClient,
    *,
    name: str,
    content: bytes,
    media_type: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/ai/attachments",
        content=content,
        headers={
            "Content-Type": media_type,
            "X-File-Name": quote(name),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_uploaded_file_can_generate_a_durable_planning_turn(client: TestClient) -> None:
    provider = RecordingMockProvider()
    client.app.state.ai_provider = provider
    created = client.post("/api/ai/conversations", json={"title": "附件生成学习路径"})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    attachment = _upload(
        client,
        name="学习需求.md",
        content=(
            "目标：从零学习数据分析。\n"
            "现状：只会基础表格。\n"
            "附件专属依据：所有练习都必须保留可复现步骤和结果说明。\n"
            "成果：完成一次可复现的数据清洗与回归分析。"
        ).encode(),
        media_type="text/markdown",
    )
    assert client.get("/api/ai/conversations").json() == []

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={
            "content": "请以附件为主，并结合我希望侧重可复现工作流的说明创建项目。",
            "attachment_ids": [attachment["id"]],
        },
    )

    assert turn.status_code == 200, turn.text
    detail = turn.json()
    assert detail["conversation"]["working_plan"] is not None
    concrete_nodes = [
        node
        for node in detail["conversation"]["working_plan"]["nodes"]
        if node["node_type"] != "MODULE"
    ]
    assert concrete_nodes
    assert all(node["description"].strip() for node in concrete_nodes)
    assert all(node["detailed_description"].strip() for node in concrete_nodes)
    assert detail["messages"][0]["attachments"][0]["original_name"] == "学习需求.md"
    context = provider.contexts[-1]
    assert context["attachments"]["file_count"] == 1
    assert "可复现的数据清洗与回归分析" in context["attachments"]["files"][0]["text_excerpt"]

    restored = client.get(f"/api/ai/conversations/{conversation_id}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["messages"][0]["attachments"][0]["id"] == attachment["id"]

    finalized = client.post(
        f"/api/ai/conversations/{conversation_id}/finalize-plan",
        json={"expected_revision": detail["conversation"]["row_version"]},
    )
    assert finalized.status_code == 200, finalized.text
    activated = client.post(
        f"/api/ai/conversations/{conversation_id}/activate-plan",
        json={"expected_revision": finalized.json()["conversation"]["row_version"]},
    )
    assert activated.status_code == 200, activated.text
    activated_conversation = activated.json()["conversation"]
    assert activated_conversation["id"] == conversation_id
    assert activated_conversation["purpose"] == "PROJECT_ASSISTANT"
    assert activated_conversation["goal_id"]

    follow_up = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "请说明创建这个项目时依据了哪些来源，不要修改项目。"},
    )
    assert follow_up.status_code == 200, follow_up.text
    creation_context = provider.contexts[-1]["project"]["creation_context"]
    assert creation_context["available"] is True
    assert creation_context["conversation_id"] == conversation_id
    assert creation_context["source_mode"] == "ATTACHMENT_CONTENT"
    assert creation_context["source_priority"] == [
        "ATTACHMENT_CONTENT",
        "USER_TEXT",
        "AI_GENERATED",
    ]
    assert "附件专属依据" in creation_context["attachments"][0]["text_excerpt"]
    assert any("可复现工作流" in excerpt for excerpt in creation_context["user_text_excerpts"])

    durable = client.get(f"/api/ai/conversations/{conversation_id}")
    assert durable.status_code == 200, durable.text
    assert durable.json()["conversation"]["goal_id"] == activated_conversation["goal_id"]
    assert durable.json()["messages"][0]["attachments"][0]["id"] == attachment["id"]
    assert len(durable.json()["messages"]) == 4
    content = client.get(attachment["content_url"])
    assert content.status_code == 200
    assert content.content.startswith("目标：从零学习数据分析".encode())
    assert client.delete(f"/api/ai/attachments/{attachment['id']}").status_code == 409


def test_image_is_forwarded_ephemerally_and_never_serialized_into_prompt(
    client: TestClient,
) -> None:
    provider = RecordingMockProvider()
    client.app.state.ai_provider = provider
    created = client.post("/api/ai/conversations", json={"title": "分析截图"}).json()
    conversation_id = created["conversation"]["id"]
    image_bytes = b"\x89PNG\r\n\x1a\nprivate-local-image"
    attachment = _upload(
        client,
        name="截图.png",
        content=image_bytes,
        media_type="image/png",
    )

    turn = client.post(
        f"/api/ai/conversations/{conversation_id}/messages",
        json={"content": "请结合截图整理学习重点", "attachment_ids": [attachment["id"]]},
    )

    assert turn.status_code == 200, turn.text
    context = provider.contexts[-1]
    assert context["attachments"]["vision_input_count"] == 1
    assert base64.b64decode(context["_vision_attachments"][0]["data_base64"]) == image_bytes
    serialized_prompt = _collaboration_prompt(context)
    assert "private-local-image" not in serialized_prompt
    assert "data_base64" not in serialized_prompt
    assert "_vision_attachments" not in serialized_prompt


def test_staged_attachment_is_owner_scoped_and_can_be_removed(client: TestClient) -> None:
    attachment = _upload(
        client,
        name="private.txt",
        content=b"private attachment",
        media_type="text/plain",
    )

    other_headers = {"X-User-ID": "00000000-0000-0000-0000-000000000002"}
    with client.app.state.session_factory() as session:
        from learning_navigator.infrastructure.database.models import UserModel

        session.add(
            UserModel(
                id=other_headers["X-User-ID"],
                email="attachment-owner-two@example.com",
                display_name="Attachment owner two",
            )
        )
        session.commit()

    assert client.get(attachment["content_url"], headers=other_headers).status_code == 404
    assert (
        client.delete(f"/api/ai/attachments/{attachment['id']}", headers=other_headers).status_code
        == 404
    )
    assert client.delete(f"/api/ai/attachments/{attachment['id']}").status_code == 204
    assert client.get(attachment["content_url"]).status_code == 404
