"""UI contracts for durable, draft-only AI collaboration."""

from __future__ import annotations

import inspect

from learning_navigator.ui.components import ai_collaboration, global_ai_assistant
from learning_navigator.ui.pages import onboarding, projects


def test_first_message_becomes_a_compact_local_conversation_title() -> None:
    assert (
        ai_collaboration._conversation_title_from_message("\n  半年建立 AI 数学基础  \n每天一小时")
        == "半年建立 AI 数学基础"
    )
    assert ai_collaboration._conversation_title_from_message("\n\n") == "新项目讨论"
    assert len(ai_collaboration._conversation_title_from_message("目标" * 100)) == 32


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


def test_shared_history_labels_keep_conversation_scope_visible() -> None:
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


def test_pending_tool_proposal_has_safe_human_review_summary() -> None:
    proposal = ai_collaboration._tool_proposal_view(
        {
            "role": "TOOL",
            "structured_content": {
                "status": "PENDING",
                "tool_call_id": "proposal-internal-7",
                "tool_name": "add_node",
                "proposal": {
                    "tool_call_id": "provider-call-7",
                    "name": "add_node",
                    "arguments": {
                        "title": "概率基础",
                        "description": "bounded user content",
                        "api_key": "must-not-be-rendered",
                    },
                },
            },
        }
    )

    assert proposal == {
        "id": "proposal-internal-7",
        "label": "新增框架节点",
        "summary": "向框架草稿添加节点“概率基础”",
    }
    assert "api_key" not in str(proposal)
    assert "must-not-be-rendered" not in str(proposal)


def test_pending_and_rejected_tool_statuses_are_not_reported_as_applied() -> None:
    pending = ai_collaboration._tool_view(
        {
            "role": "TOOL",
            "structured_content": {
                "status": "PENDING",
                "tool_call_id": "proposal-internal-8",
                "tool_name": "archive_node",
                "proposal": {
                    "tool_call_id": "call-8",
                    "name": "archive_node",
                    "arguments": {},
                },
            },
        }
    )
    rejected = ai_collaboration._tool_view(
        {
            "role": "TOOL",
            "tool_name": "archive_node",
            "structured_content": {"status": "REJECTED"},
        }
    )

    assert pending["status"] == "PENDING"
    assert rejected["status"] == "REJECTED"
    source = inspect.getsource(ai_collaboration._render_message)
    assert "待你确认" in source
    assert "已拒绝" in source
    assert "应用到草稿" in source
    assert "proposal_decision" in source
    assert "reviewed and decision" in source


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


def test_assistant_failures_use_safe_actionable_copy_by_error_code() -> None:
    configuration = ai_collaboration._assistant_failure_view(
        {
            "role": "ASSISTANT",
            "content": "AI 请求未完成。",
            "structured_content": {
                "error": {
                    "code": "ai_configuration_error",
                    "message": "secret provider trace sk-live-should-not-leak",
                }
            },
            "message_metadata": {"request_failed": True},
        }
    )
    timeout = ai_collaboration._assistant_failure_view(
        {
            "role": "ASSISTANT",
            "structured_content": {"error": {"code": "timeout_error"}},
        }
    )

    assert configuration == {
        "title": "AI 配置需要处理",
        "detail": "消息已保存在本地。请检查服务、API Key 和模型后重试。",
        "action": "settings",
        "retryable": False,
    }
    assert "secret" not in str(configuration)
    assert timeout is not None
    assert timeout["title"] == "AI 响应超时"
    assert timeout["retryable"] is True
    assert timeout["action"] == "retry"


def test_normal_assistant_message_is_not_misclassified_as_failure() -> None:
    assert (
        ai_collaboration._assistant_failure_view({"role": "ASSISTANT", "content": "这是正常回答。"})
        is None
    )


def test_failure_card_offers_settings_or_retry_without_raw_provider_message() -> None:
    source = inspect.getsource(ai_collaboration._render_message)
    assistant_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert 'ui.link("打开 AI 设置", "/settings")' in source
    assert 'ui.button("重试"' in source
    assert 'error.get("message")' not in inspect.getsource(ai_collaboration._assistant_failure_view)
    assert "retry_failed_message" in assistant_source


def test_unified_assistant_keeps_human_confirmation_before_project_activation() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    page_source = inspect.getsource(onboarding.register)

    assert 'f"/ai/conversations/{conversation_id}/finalize-plan"' in source
    assert 'f"/ai/conversations/{conversation_id}/activate-plan"' in source
    assert '"锁定当前方案"' in source
    assert '"确认并建立项目"' in source
    assert '"/ai/learning-plans/generate"' not in page_source
    assert "render_new_project_collaboration" not in page_source


def test_project_workspace_uses_shared_assistant_instead_of_a_second_chat_tab() -> None:
    project_source = inspect.getsource(projects._render_project_page)
    assistant_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert ("collaboration", "AI 协作", "forum") not in projects.PROJECT_SECTIONS
    assert "render_project_collaboration" not in project_source
    assert "assistant_enabled=False" not in project_source
    assert "改动只进入草稿" in assistant_source
    assert "只有你确认后" in assistant_source


def test_old_new_project_url_is_only_a_compatibility_redirect() -> None:
    source = inspect.getsource(onboarding.register)

    assert '@ui.page("/projects/new")' in source
    assert 'ui.navigate.to("/?ai=new-project")' in source
    assert "render_new_project_collaboration" not in source
    assert "page_shell(" not in source
