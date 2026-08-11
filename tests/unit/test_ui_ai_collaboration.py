"""UI contracts for durable, draft-only AI collaboration."""

from __future__ import annotations

import inspect

from learning_navigator.ui.components import ai_collaboration
from learning_navigator.ui.pages import onboarding, projects


def test_first_message_becomes_a_compact_local_conversation_title() -> None:
    assert (
        ai_collaboration._conversation_title_from_message("\n  半年建立 AI 数学基础  \n每天一小时")
        == "半年建立 AI 数学基础"
    )
    assert ai_collaboration._conversation_title_from_message("\n\n") == "新项目讨论"
    assert len(ai_collaboration._conversation_title_from_message("目标" * 100)) == 80


def test_conversation_payload_helpers_are_resilient() -> None:
    detail = {
        "conversation": {
            "id": "conversation-1",
            "row_version": 7,
            "working_plan": {
                "nodes": [{}, {}],
                "edges": [{}],
                "navigation": {"stages": [{}, {}, {}]},
            },
        },
        "messages": [{"role": "USER", "content": "hello"}, "bad"],
    }

    assert ai_collaboration._conversation(detail)["id"] == "conversation-1"
    assert ai_collaboration._conversation_revision(detail) == 7
    assert ai_collaboration._conversation_messages(detail) == [{"role": "USER", "content": "hello"}]
    assert ai_collaboration._plan_stats(ai_collaboration._working_plan(detail)) == (2, 1, 3)


def test_shared_history_labels_and_focus_links_keep_scope_visible() -> None:
    planning = {"id": "plan-1", "purpose": "PLANNING", "title": "理解量化交易"}
    project = {
        "id": "chat-2",
        "purpose": "PROJECT_ASSISTANT",
        "goal_id": "goal-2",
        "title": "调整统计路径",
    }
    page = {"id": "chat-3", "purpose": "PAGE_ASSISTANT", "title": "解释当前页面"}

    assert ai_collaboration._conversation_history_label(planning) == "项目共创 · 理解量化交易"
    assert ai_collaboration._conversation_history_label(project) == "项目协作 · 调整统计路径"
    assert ai_collaboration._conversation_history_label(page) == "页面问答 · 解释当前页面"
    assert ai_collaboration._conversation_focus_href(planning) == (
        "/projects/new?conversation=plan-1"
    )
    assert ai_collaboration._conversation_focus_href(project) == ("/projects/goal-2/collaboration")
    assert ai_collaboration._conversation_focus_href(page) is None


def test_tool_runs_are_presented_as_draft_changes_not_opaque_payloads() -> None:
    success = ai_collaboration._tool_view(
        {
            "role": "TOOL",
            "tool_name": "reorder_path_step",
            "structured_content": {
                "status": "SUCCEEDED",
                "result": {"change_summary": "把统计基础提前"},
            },
        }
    )
    failure = ai_collaboration._tool_view(
        {
            "role": "TOOL",
            "tool_name": "add_relation",
            "structured_content": {
                "status": "FAILED",
                "error": {"message": "关系形成循环"},
            },
        }
    )

    assert success == {
        "label": "调整路径顺序",
        "status": "SUCCEEDED",
        "detail": "把统计基础提前",
    }
    assert failure == {
        "label": "新增节点关系",
        "status": "FAILED",
        "detail": "关系形成循环",
    }


def test_denied_tool_run_preserves_provider_explanation() -> None:
    denied = ai_collaboration._tool_view(
        {
            "role": "TOOL",
            "tool_name": "archive_node",
            "structured_content": {
                "status": "DENIED",
                "error": {"message": "需要确认当前地图版本"},
            },
        }
    )

    assert denied["status"] == "DENIED"
    assert denied["detail"] == "需要确认当前地图版本"


def test_new_project_stays_ephemeral_until_the_first_message_without_a_setup_gate() -> None:
    source = inspect.getsource(ai_collaboration.render_new_project_collaboration)

    # Opening /projects/new is already the creation conversation. The first
    # message creates persistence; there is no separate setup form or start gate.
    assert 'params={"pre_project_only": True, "purpose": "PLANNING"}' in source
    assert '"/ai/conversations"' in source
    assert 'f"/ai/conversations/{conversation_id}/messages"' in source
    assert "async def start()" not in source
    assert "goal_input" not in source
    assert "requirements_input" not in source
    assert 'ui.button("开始讨论"' not in source
    assert '"目标或问题"' not in source
    assert '"达成标准与约束"' not in source
    assert "_initial_goal_message(goal, requirements)" not in source

    # The unified surface opens with guidance, the message composer and the
    # draft preview visible together instead of swapping a setup card away.
    assert "描述你想理解、学习或完成的事" in source
    assert "我想学习一个领域" in source
    assert 'ui.label("方案草稿")' in source
    assert "ui.textarea(" in source
    assert '"和 AI 讨论"' in source
    assert 'state["detail"] = None' in source
    assert "await resume(latest_id)" in source
    assert "initial_conversation_id" in source
    assert "await resume(selected_id)" in source
    assert "_conversation_history_label(item)" in source

    # Merely opening the page must not create a history record. Persistence
    # starts only after send has accepted a non-empty first message.
    creation_post = 'created = await client.post(\n                    "/ai/conversations"'
    assert source.count(creation_post) == 1
    assert source.index(creation_post) > source.index("    async def send()")


def test_project_collaboration_new_chat_is_local_until_the_first_message() -> None:
    source = inspect.getsource(ai_collaboration.render_project_collaboration)
    new_chat_source = source[
        source.index("    def start_new()") : source.index("    def remember_detail()")
    ]
    send_source = source[source.index("    async def send()") : source.index("    def render()")]

    assert 'state["detail"] = None' in new_chat_source
    assert 'await client.post(\n                "/ai/conversations"' not in new_chat_source
    assert 'await client.post(\n                    "/ai/conversations"' in send_source
    assert 'ui.button("开始协作", icon="add_comment", on_click=start_new)' in source
    assert 'ui.button("新对话", icon="add", on_click=start_new)' in source


def test_new_project_plan_must_be_confirmed_before_it_becomes_a_project() -> None:
    source = inspect.getsource(ai_collaboration.render_new_project_collaboration)
    page_source = inspect.getsource(onboarding.register)

    assert 'f"/ai/conversations/{conversation_id}/finalize-plan"' in source
    assert 'f"/ai/conversations/{conversation_id}/activate-plan"' in source
    assert '"锁定当前方案"' in source
    assert '"确认并建立项目"' in source
    assert "if isinstance(final_plan, dict):" in source
    activate_branch = source[source.index("if isinstance(final_plan, dict):") :]
    assert "on_click=activate_final_plan" in activate_branch
    assert '"/ai/learning-plans/generate"' not in page_source
    assert '"与 AI 共创新项目"' in page_source
    assert "conversation: str | None = None" in page_source
    assert "initial_conversation_id=conversation" in page_source


def test_new_project_composer_sends_inline_without_a_separate_consent_gate() -> None:
    source = inspect.getsource(ai_collaboration.render_new_project_collaboration)
    send_source = source[
        source.index("    async def send()") : source.index("    def render_conversation()")
    ]
    render_source = source[
        source.index("    def render_conversation()") : source.index("    async def resume(")
    ]

    assert "ui.checkbox(" not in render_source
    assert "send_external" not in source
    assert "发送前请确认外部 AI 数据授权" not in send_source
    assert '"confirmed_external_ai": bool(is_external)' in send_source

    composer = render_source[render_source.index('with ui.row().classes("ln-ai-composer-row') :]
    assert "ui.textarea(" in composer
    assert '"和 AI 讨论"' in composer
    assert 'ui.button("发送", icon="send", on_click=send)' in composer


def test_project_collaboration_uses_the_same_inline_consent_free_composer() -> None:
    source = inspect.getsource(ai_collaboration.render_project_collaboration)
    send_source = source[source.index("    async def send()") : source.index("    def render()")]
    render_source = source[source.index("    def render()") :]

    assert "ui.checkbox(" not in render_source
    assert "external_confirm" not in source
    assert "发送前请确认外部 AI 数据授权" not in send_source
    assert '"confirmed_external_ai": bool(is_external)' in send_source

    composer = render_source[render_source.index('with ui.row().classes("ln-ai-composer-row') :]
    assert "ui.textarea(" in composer
    assert '"告诉 AI 要怎样修改"' in composer
    assert 'ui.button("发送", icon="send", on_click=send)' in composer


def test_project_workspace_has_one_collaboration_tab_and_draft_boundary() -> None:
    source = inspect.getsource(ai_collaboration.render_project_collaboration)

    assert projects.PROJECT_SECTIONS.count(("collaboration", "AI 协作", "forum")) == 1
    assert '@ui.page("/projects/{project_id}/collaboration")' in inspect.getsource(
        projects.register
    )
    assert "AI 写入仅进入草稿" in source
    assert "启用始终由你完成" in source
    assert "前置关系只会提示风险" in source
    assert "不允许" not in source
    assert 'f"/projects/{project_id}/overview?edit=path"' in source
    assert 'f"/projects/{project_id}/path"' not in source
    assert 'f"/projects/{project_id}/progress"' not in source
