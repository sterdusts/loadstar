"""Message and plan renderers for the unified AI workspace."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError

TOOL_LABELS = {
    "add_node": "新增框架节点",
    "update_node": "更新框架节点",
    "archive_node": "永久删除框架节点",
    "add_relation": "新增节点关系",
    "create_path_draft": "建立路径草稿",
    "clone_path_draft": "复制可编辑路径",
    "add_path_step": "加入路径步骤",
    "update_path_step": "更新路径步骤",
    "remove_path_step": "移除路径步骤",
    "reorder_path_step": "调整路径顺序",
}

CONVERSATION_PURPOSE_LABELS = {
    "PLANNING": "项目共创",
    "PAGE_ASSISTANT": "页面问答",
    "PROJECT_ASSISTANT": "项目协作",
}

ASSISTANT_FAILURE_VIEWS: dict[str, dict[str, Any]] = {
    "configuration_error": {
        "title": "AI 配置需要处理",
        "detail": "消息已保存在本地。请检查服务、API Key 和模型后重试。",
        "action": "settings",
        "retryable": False,
    },
    "ai_configuration_error": {
        "title": "AI 配置需要处理",
        "detail": "消息已保存在本地。请检查服务、API Key 和模型后重试。",
        "action": "settings",
        "retryable": False,
    },
    "authentication_error": {
        "title": "AI 认证失败",
        "detail": "消息已保存在本地。请检查 API Key 后重试。",
        "action": "settings",
        "retryable": False,
    },
    "timeout_error": {
        "title": "AI 响应超时",
        "detail": "消息已保存在本地。网络或模型可能较慢，可以直接重试。",
        "action": "retry",
        "retryable": True,
    },
    "rate_limit_error": {
        "title": "请求频率已达上限",
        "detail": "消息已保存在本地。请稍等片刻再重试。",
        "action": "retry",
        "retryable": True,
    },
    "connection_error": {
        "title": "暂时无法连接 AI 服务",
        "detail": "消息已保存在本地。请检查网络或服务状态后重试。",
        "action": "retry",
        "retryable": True,
    },
    "upstream_error": {
        "title": "AI 服务暂时不可用",
        "detail": "消息已保存在本地。服务恢复后可以直接重试。",
        "action": "retry",
        "retryable": True,
    },
    "invalid_response": {
        "title": "AI 返回内容无法使用",
        "detail": "消息已保存在本地。可以重试，或在设置中更换模型。",
        "action": "retry",
        "retryable": True,
    },
    "invalid_collaboration_response": {
        "title": "AI 返回内容无法使用",
        "detail": "消息已保存在本地。可以重试，或在设置中更换模型。",
        "action": "retry",
        "retryable": True,
    },
}


def _conversation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get("conversation")
    return value if isinstance(value, dict) else payload


def _conversation_items(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _conversation_messages(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        return []
    return [item for item in payload["messages"] if isinstance(item, dict)]


def _conversation_revision(payload: Any) -> int:
    value = _conversation(payload).get("row_version", 1)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _working_plan(payload: Any) -> dict[str, Any] | None:
    conversation = _conversation(payload)
    plan = conversation.get("final_plan") or conversation.get("working_plan")
    return plan if isinstance(plan, dict) else None


def _plan_stats(plan: Any) -> tuple[int, int, int]:
    if not isinstance(plan, dict):
        return 0, 0, 0
    navigation = plan.get("navigation")
    navigation = navigation if isinstance(navigation, dict) else {}
    return (
        len(plan.get("nodes") or []),
        len(plan.get("edges") or []),
        len(navigation.get("stages") or []),
    )


def _tool_view(message: Any) -> dict[str, str]:
    if not isinstance(message, dict):
        return {"label": "草稿改动", "status": "UNKNOWN", "detail": ""}
    structured = message.get("structured_content")
    structured = structured if isinstance(structured, dict) else {}
    tool_name = str(message.get("tool_name") or structured.get("tool_name") or "")
    status = str(structured.get("status") or "UNKNOWN").upper()
    detail = ""
    if status == "PENDING":
        proposal = _tool_proposal_view(message)
        if proposal is not None:
            detail = proposal["summary"]
    elif status in {"FAILED", "DENIED"}:
        error = structured.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or "这项改动未能写入草稿。")
    else:
        result = structured.get("result")
        if isinstance(result, dict):
            for key in ("change_summary", "title", "message", "status"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    detail = value.strip()
                    break
    return {
        "label": TOOL_LABELS.get(tool_name, "更新草稿"),
        "status": status,
        "detail": detail,
    }


def _proposal_text(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split()).strip()
    return normalized[:80] or fallback


def _tool_proposal_view(message: Any) -> dict[str, str] | None:
    """Summarize a pending tool proposal from a strict field allowlist."""

    if not isinstance(message, dict):
        return None
    structured = message.get("structured_content")
    structured = structured if isinstance(structured, dict) else {}
    if str(structured.get("status") or "").upper() != "PENDING":
        return None
    proposal = structured.get("proposal")
    if not isinstance(proposal, dict):
        return None
    # Review endpoints accept the application's persisted proposal id. The
    # nested provider id is only correlation metadata and cannot authorize a mutation.
    proposal_id = str(structured.get("tool_call_id") or "").strip()
    tool_name = str(
        proposal.get("name") or structured.get("tool_name") or message.get("tool_name") or ""
    ).strip()
    arguments = proposal.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    if not proposal_id or tool_name not in TOOL_LABELS:
        return None

    title = _proposal_text(arguments.get("title"), "未命名节点")
    relation = _proposal_text(arguments.get("relation_type"), "关系")
    summaries = {
        "add_node": f"向框架草稿添加节点“{title}”",
        "update_node": f"更新框架草稿中的节点“{title}”",
        "archive_node": "永久删除一个框架节点，并同步清理关系、路径引用与进度",
        "add_relation": f"向框架草稿添加一条“{relation}”关系",
        "create_path_draft": "创建一份新的可编辑路径草稿",
        "clone_path_draft": "复制当前路径为可编辑草稿",
        "add_path_step": "向路径草稿加入一个步骤",
        "update_path_step": "更新路径草稿中的一个步骤",
        "remove_path_step": "从路径草稿移除一个步骤",
        "reorder_path_step": "调整路径草稿中的步骤顺序",
    }
    return {
        "id": proposal_id,
        "label": TOOL_LABELS[tool_name],
        "summary": summaries[tool_name],
    }


def _conversation_title_from_message(content: str) -> str:
    """Derive a compact local title without adding another setup form."""

    first_line = next(
        (line.strip() for line in content.splitlines() if line.strip()),
        "新项目讨论",
    )
    return first_line[:80]


def _conversation_history_label(item: Any) -> str:
    """Use one compact label wherever the shared conversation history appears."""

    conversation = _conversation(item)
    purpose = str(conversation.get("purpose") or "PAGE_ASSISTANT")
    kind = CONVERSATION_PURPOSE_LABELS.get(purpose, "AI 对话")
    title = str(conversation.get("title") or "未命名对话")
    return f"{kind} · {title}"


def _created_at_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return stamp.astimezone().strftime("%m-%d %H:%M")


def _assistant_failure_view(message: Any) -> dict[str, Any] | None:
    """Map persisted failure codes to safe copy without reflecting provider details."""

    if not isinstance(message, dict) or str(message.get("role") or "").upper() != "ASSISTANT":
        return None
    structured = message.get("structured_content")
    structured = structured if isinstance(structured, dict) else {}
    error = structured.get("error")
    if not isinstance(error, dict):
        return None
    code = str(error.get("code") or "").strip()
    if not code:
        return None
    view = ASSISTANT_FAILURE_VIEWS.get(code)
    if view is not None:
        return dict(view)
    return {
        "title": "AI 请求未完成",
        "detail": "消息已保存在本地。请稍后重试；如持续失败，请检查 AI 设置。",
        "action": "retry",
        "retryable": True,
    }


def _render_message(
    message: dict[str, Any],
    *,
    on_retry: Callable[[], Any] | None = None,
    on_approve: Callable[[], Any] | None = None,
    on_reject: Callable[[], Any] | None = None,
    proposal_decision: str | None = None,
) -> None:
    role = str(message.get("role") or "ASSISTANT").upper()
    if role == "TOOL":
        view = _tool_view(message)
        decision = str(proposal_decision or "").upper()
        reviewed = view["status"] == "PENDING" and decision in {
            "SUCCEEDED",
            "FAILED",
            "REJECTED",
        }
        pending = view["status"] == "PENDING" and not reviewed
        rejected = view["status"] == "REJECTED"
        failed = view["status"] in {"FAILED", "DENIED"}
        with ui.element("article").classes(
            "ln-tool-run ln-tool-run-pending"
            if pending
            else "ln-tool-run ln-tool-run-failed"
            if failed
            else "ln-tool-run"
        ):
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon(
                    "pending_actions"
                    if pending
                    else "error_outline"
                    if failed
                    else "block"
                    if rejected
                    else "draft"
                ).classes("text-lg")
                ui.label(view["label"]).classes("font-bold")
                ui.label(
                    "已应用"
                    if reviewed and decision == "SUCCEEDED"
                    else "应用失败"
                    if reviewed and decision == "FAILED"
                    else "已拒绝"
                    if reviewed and decision == "REJECTED"
                    else "待你确认"
                    if pending
                    else "已拒绝"
                    if rejected
                    else "未写入"
                    if failed
                    else "已应用到草稿"
                ).classes("ml-auto rounded-full px-2 py-0.5 text-xs font-bold")
            if view["detail"]:
                ui.label(view["detail"]).classes("mt-1 text-sm text-gray-600")
            if pending:
                with ui.row().classes("mt-2 items-center gap-2"):
                    ui.button("应用到草稿", icon="check", on_click=on_approve).props(
                        "dense no-caps color=positive" + (" disable" if on_approve is None else "")
                    )
                    ui.button("拒绝", icon="close", on_click=on_reject).props(
                        "flat dense no-caps color=negative"
                        + (" disable" if on_reject is None else "")
                    )
        return

    is_user = role == "USER"
    failure = _assistant_failure_view(message)
    classes = "ln-chat-message ln-chat-message-user" if is_user else "ln-chat-message"
    if failure is not None:
        classes += " ln-chat-message-error"
    with ui.element("article").classes(classes):
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("person" if is_user else "auto_awesome").classes("text-base")
            ui.label("你" if is_user else "AI").classes("text-xs font-bold")
            created_at = _created_at_label(message.get("created_at"))
            if created_at:
                ui.label(created_at).classes("ml-auto text-xs text-gray-500")
        if failure is not None:
            ui.label(str(failure["title"])).classes("font-bold")
            ui.label(str(failure["detail"])).classes(
                "whitespace-pre-wrap break-words text-sm leading-6 text-gray-600"
            )
            with ui.row().classes("mt-1 items-center gap-2"):
                if failure["action"] == "settings":
                    ui.link("打开 AI 设置", "/settings").classes(
                        "font-bold text-green-700 no-underline"
                    )
                elif failure["retryable"] and on_retry is not None:
                    ui.button("重试", icon="refresh", on_click=on_retry).props(
                        "flat dense no-caps color=positive"
                    )
            return
        content = str(message.get("content") or "").strip()
        if content:
            ui.label(content).classes("whitespace-pre-wrap break-words text-sm leading-6")


def _render_plan_summary(plan: dict[str, Any], *, final: bool) -> None:
    raw_space = plan.get("space")
    space: dict[str, Any] = raw_space if isinstance(raw_space, dict) else {}
    node_count, edge_count, stage_count = _plan_stats(plan)
    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("min-w-0 gap-1"):
                ui.label("已锁定方案" if final else "当前方案草稿").classes("ln-kicker")
                ui.label(str(space.get("title") or "等待对话形成方案")).classes(
                    "line-clamp-2 text-lg font-black"
                )
            ui.label("待建立" if final else "可继续讨论").classes(
                "shrink-0 rounded-full bg-green-50 px-2.5 py-1 text-xs font-bold text-green-800"
            )
        description = str(space.get("description") or "").strip()
        if description:
            ui.label(description).classes("line-clamp-3 text-sm text-gray-600")
        with ui.row().classes("w-full flex-wrap gap-2"):
            for label in (
                f"{node_count} 个节点",
                f"{edge_count} 条关系",
                f"{stage_count} 个阶段",
            ):
                ui.label(label).classes("rounded-full bg-gray-100 px-2.5 py-1 text-xs font-bold")
        navigation = plan.get("navigation")
        navigation = navigation if isinstance(navigation, dict) else {}
        stages = [item for item in (navigation.get("stages") or []) if isinstance(item, dict)]
        if stages:
            with ui.column().classes("w-full gap-2"):
                for stage in stages[:6]:
                    with ui.row().classes("w-full items-start gap-2"):
                        ui.label(str(stage.get("sequence") or "·")).classes("ln-plan-stage-number")
                        with ui.column().classes("min-w-0 gap-0"):
                            ui.label(str(stage.get("title") or "未命名阶段")).classes(
                                "line-clamp-1 text-sm font-bold"
                            )
                            objective = str(stage.get("objective") or "").strip()
                            if objective:
                                ui.label(objective).classes("line-clamp-2 text-xs text-gray-500")


async def _get_ai_status(client: UIAPIClient) -> dict[str, Any]:
    try:
        value = await client.get("/ai/status")
    except UIAPIError:
        return {}
    return value if isinstance(value, dict) else {}
