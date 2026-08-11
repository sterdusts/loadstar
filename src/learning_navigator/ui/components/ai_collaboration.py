"""Conversation-first AI collaboration UI shared by creation and project workspaces."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import uses_mock_provider

TOOL_LABELS = {
    "add_node": "新增框架节点",
    "update_node": "更新框架节点",
    "archive_node": "归档框架节点",
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
    if status in {"FAILED", "DENIED"}:
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


def _conversation_focus_href(item: Any) -> str | None:
    """Return the full workspace suited to a conversation's persisted scope."""

    conversation = _conversation(item)
    conversation_id = str(conversation.get("id") or "")
    purpose = str(conversation.get("purpose") or "")
    if purpose == "PLANNING" and conversation_id:
        return f"/projects/new?conversation={conversation_id}"
    goal_id = str(conversation.get("goal_id") or "")
    if purpose == "PROJECT_ASSISTANT" and goal_id:
        return f"/projects/{goal_id}/collaboration"
    return None


def _created_at_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return stamp.astimezone().strftime("%m-%d %H:%M")


def _render_message(message: dict[str, Any]) -> None:
    role = str(message.get("role") or "ASSISTANT").upper()
    if role == "TOOL":
        view = _tool_view(message)
        failed = view["status"] in {"FAILED", "DENIED"}
        with ui.element("article").classes(
            "ln-tool-run ln-tool-run-failed" if failed else "ln-tool-run"
        ):
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon("error_outline" if failed else "draft").classes("text-lg")
                ui.label(view["label"]).classes("font-bold")
                ui.label("未写入" if failed else "已写入草稿").classes(
                    "ml-auto rounded-full px-2 py-0.5 text-xs font-bold"
                )
            if view["detail"]:
                ui.label(view["detail"]).classes("mt-1 text-sm text-gray-600")
        return

    is_user = role == "USER"
    classes = "ln-chat-message ln-chat-message-user" if is_user else "ln-chat-message"
    with ui.element("article").classes(classes):
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("person" if is_user else "auto_awesome").classes("text-base")
            ui.label("你" if is_user else "AI").classes("text-xs font-bold")
            created_at = _created_at_label(message.get("created_at"))
            if created_at:
                ui.label(created_at).classes("ml-auto text-xs text-gray-500")
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


async def render_new_project_collaboration(
    client: UIAPIClient,
    *,
    on_activated: Callable[[str], None],
    initial_conversation_id: str | None = None,
) -> None:
    """Render a pre-project conversation that can explicitly become a project."""

    ai_status = await _get_ai_status(client)
    is_mock = uses_mock_provider(ai_status)
    is_external = bool(ai_status.get("is_external", not is_mock))
    is_ready = bool(ai_status.get("is_ready", True))
    state: dict[str, Any] = {"detail": None}
    try:
        previous = _conversation_items(
            await client.get(
                "/ai/conversations",
                params={"pre_project_only": True, "purpose": "PLANNING"},
            )
        )
    except UIAPIError:
        previous = []

    with ui.element("section").classes("ln-collaboration-grid"):
        with ui.column().classes("ln-collaboration-main min-w-0 gap-4"):
            conversation_panel = ui.column().classes("w-full gap-4")
        plan_panel = ui.card().classes("ln-card ln-collaboration-plan w-full p-5")

    message_input: Any = None
    send_button: Any = None
    finalize_button: Any = None
    activate_button: Any = None

    async def activate_final_plan() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            return
        activate_button.props("loading disable")
        try:
            response = await client.post(
                f"/ai/conversations/{conversation_id}/activate-plan",
                json={"expected_revision": _conversation_revision(detail)},
            )
            activation = response.get("activation") if isinstance(response, dict) else None
            goal = activation.get("goal") if isinstance(activation, dict) else None
            goal_id = str(goal.get("id") or "") if isinstance(goal, dict) else ""
            if not goal_id:
                raise ValueError("项目建立结果不完整")
            ui.notify("项目已建立", type="positive")
            on_activated(goal_id)
        except (UIAPIError, ValueError) as exc:
            error_notice(f"无法建立项目：{exc}")
        finally:
            activate_button.props(remove="loading disable")

    async def finalize_plan() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id or not isinstance(conversation.get("working_plan"), dict):
            ui.notify("先和 AI 形成一份完整草稿。", type="warning")
            return
        finalize_button.props("loading disable")
        try:
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/finalize-plan",
                json={"expected_revision": _conversation_revision(detail)},
            )
            render_conversation()
            ui.notify("方案已锁定，请确认后建立项目。", type="positive")
        except UIAPIError as exc:
            error_notice(f"无法锁定方案：{exc}")
        finally:
            finalize_button.props(remove="loading disable")

    def remember_detail() -> None:
        """Expose a planning conversation in history after its first turn only."""

        detail = state.get("detail")
        if not _conversation_messages(detail):
            return
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            return
        previous[:] = [item for item in previous if str(item.get("id") or "") != conversation_id]
        previous.insert(0, conversation)

    async def send() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        content = str(message_input.value or "").strip()
        if not content:
            return
        if not is_ready:
            ui.notify("请先完成 AI 连接设置。", type="warning")
            return
        send_button.props("loading disable")
        try:
            if not conversation_id:
                created = await client.post(
                    "/ai/conversations",
                    json={
                        "title": _conversation_title_from_message(content),
                        "purpose": "PLANNING",
                    },
                )
                conversation = _conversation(created)
                conversation_id = str(conversation.get("id") or "")
                if not conversation_id:
                    raise ValueError("会话建立结果不完整")
                state["detail"] = created
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/messages",
                json={
                    "content": content,
                    "confirmed_external_ai": bool(is_external),
                },
            )
            remember_detail()
            message_input.value = ""
            render_conversation()
        except (UIAPIError, ValueError) as exc:
            error_notice(f"发送失败：{exc}")
        finally:
            send_button.props(remove="loading disable")

    def render_conversation() -> None:
        nonlocal message_input, send_button, finalize_button, activate_button
        detail = state.get("detail")
        conversation = _conversation(detail)
        final_plan = conversation.get("final_plan")
        working_plan = conversation.get("working_plan")
        conversation_panel.clear()
        plan_panel.clear()
        with conversation_panel:
            with ui.card().classes("ln-card w-full overflow-hidden"):
                with ui.row().classes("w-full items-center gap-2 border-b border-gray-200 p-4"):
                    ui.icon("forum").classes("text-xl text-green-700")
                    ui.label(str(conversation.get("title") or "新项目讨论")).classes(
                        "min-w-0 grow truncate font-black"
                    )
                    ui.label("本地保存").classes(
                        "rounded-full bg-green-50 px-2 py-1 text-xs font-bold text-green-800"
                    )
                    if previous:
                        with ui.button(icon="history").props(
                            "flat round dense aria-label='切换未完成讨论'"
                        ):
                            with ui.menu().classes("ln-ai-history-menu"):
                                for item in previous[:12]:
                                    saved_id = str(item.get("id") or "")
                                    if not saved_id:
                                        continue
                                    ui.menu_item(
                                        _conversation_history_label(item),
                                        on_click=lambda saved_id=saved_id: resume(saved_id),
                                    )
                    ui.button(icon="add_comment", on_click=start_new).props(
                        "flat round dense aria-label='开始新的项目讨论'"
                    ).tooltip("新讨论")
                with ui.column().classes("ln-chat-log w-full gap-3 p-4"):
                    messages = _conversation_messages(detail)
                    if messages:
                        for item in messages:
                            _render_message(item)
                    else:
                        with ui.element("article").classes("ln-ai-welcome w-full p-4"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("auto_awesome").classes("text-xl text-green-700")
                                ui.label("描述你想理解、学习或完成的事").classes("font-black")
                            ui.label(
                                "可以是想学的领域、想看懂的行业，或想完成的一件事。"
                                "不必一次说完整，我会通过追问和你一起把它梳理清楚。"
                            ).classes("mt-2 text-sm leading-6 text-gray-600")
                with ui.column().classes(
                    "ln-ai-composer w-full gap-2 border-t border-gray-200 p-4"
                ):
                    with ui.row().classes("ln-ai-composer-row w-full items-end gap-2"):
                        message_input = (
                            ui.textarea(
                                "和 AI 讨论",
                                placeholder="例如：我想系统理解量化交易，但不知道应该先建立什么框架",
                            )
                            .classes("ln-ai-composer-input min-w-0 grow")
                            .props("outlined autogrow maxlength=40000")
                        )
                        send_button = (
                            ui.button("发送", icon="send", on_click=send)
                            .classes("ln-action-button ln-ai-send-button")
                            .props("color=positive")
                        )
                        if not is_ready:
                            send_button.props("disable")
                    if not messages:
                        with ui.row().classes("w-full flex-wrap gap-2"):
                            for prompt in (
                                "我想学习一个领域",
                                "我想看懂一个行业",
                                "我想完成一件复杂的事",
                            ):
                                ui.button(
                                    prompt,
                                    on_click=lambda prompt=prompt: setattr(
                                        message_input, "value", prompt
                                    ),
                                ).props("outline dense color=positive")
                    if not is_ready:
                        status_text = "AI 尚未连接 · 请先在设置中完成配置"
                    elif is_mock:
                        status_text = "当前使用本地演示 AI · 对话保存在本机"
                    else:
                        status_text = "完整记录长期保存在本机"
                    ui.label(status_text).classes("text-xs text-gray-500")
        with plan_panel:
            plan = final_plan if isinstance(final_plan, dict) else working_plan
            if isinstance(plan, dict):
                _render_plan_summary(plan, final=isinstance(final_plan, dict))
                ui.separator().classes("my-2")
                if isinstance(final_plan, dict):
                    activate_button = (
                        ui.button(
                            "确认并建立项目",
                            icon="check_circle",
                            on_click=activate_final_plan,
                        )
                        .classes("ln-action-button w-full")
                        .props("color=positive")
                    )
                    ui.label("只有这个按钮会建立正式地图与路径。 ").classes(
                        "text-center text-xs text-gray-500"
                    )
                else:
                    finalize_button = (
                        ui.button(
                            "锁定当前方案",
                            icon="task_alt",
                            on_click=finalize_plan,
                        )
                        .classes("ln-action-button w-full")
                        .props("outline color=positive")
                    )
                    ui.label("锁定前仍可继续让 AI 调整草稿。 ").classes(
                        "text-center text-xs text-gray-500"
                    )
            else:
                ui.icon("account_tree").classes("text-3xl text-gray-400")
                ui.label("方案草稿").classes("text-lg font-black")
                ui.label("讨论清楚后，框架和路径会在这里出现。 ").classes("text-sm text-gray-600")

    async def resume(conversation_id: str) -> None:
        try:
            state["detail"] = await client.get(f"/ai/conversations/{conversation_id}")
            render_conversation()
        except UIAPIError as exc:
            error_notice(f"无法打开对话：{exc}")

    def start_new() -> None:
        """Show a fresh composer; persistence begins with the first message."""

        state["detail"] = None
        render_conversation()

    selected_id = str(initial_conversation_id or "")
    if selected_id and any(str(item.get("id") or "") == selected_id for item in previous):
        await resume(selected_id)
    elif previous:
        latest_id = str(previous[0].get("id") or "")
        if latest_id:
            await resume(latest_id)
        else:
            render_conversation()
    else:
        render_conversation()


async def render_project_collaboration(
    client: UIAPIClient,
    *,
    project_id: str,
    space_id: str,
) -> None:
    """Render durable project chat. AI tool writes remain visibly draft-only."""

    ai_status = await _get_ai_status(client)
    is_mock = uses_mock_provider(ai_status)
    is_external = bool(ai_status.get("is_external", not is_mock))
    state: dict[str, Any] = {"detail": None, "draft_open": False}

    try:
        raw = await client.get(
            "/ai/conversations",
            params={
                "goal_id": project_id,
                "space_id": space_id,
                "purpose": "PROJECT_ASSISTANT",
                "context_key": f"project:{project_id}",
            },
        )
        conversations = _conversation_items(raw)
    except UIAPIError as exc:
        conversations = []
        error_notice(f"无法读取协作记录：{exc}")

    with ui.element("section").classes("ln-collaboration-grid"):
        chat_panel = ui.column().classes("ln-collaboration-main min-w-0 gap-4")
        side_panel = ui.card().classes("ln-card ln-collaboration-plan w-full p-5")

    message_input: Any = None
    send_button: Any = None

    async def load(conversation_id: str) -> None:
        try:
            state["detail"] = await client.get(f"/ai/conversations/{conversation_id}")
            state["draft_open"] = True
            render()
        except UIAPIError as exc:
            error_notice(f"无法打开对话：{exc}")

    def start_new() -> None:
        """Open an unsaved project composer until the first message is sent."""

        state["detail"] = None
        state["draft_open"] = True
        render()

    def remember_detail() -> None:
        detail = state.get("detail")
        if not _conversation_messages(detail):
            return
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            return
        conversations[:] = [
            item for item in conversations if str(item.get("id") or "") != conversation_id
        ]
        conversations.insert(0, conversation)

    async def send() -> None:
        detail = state.get("detail")
        conversation_id = str(_conversation(detail).get("id") or "")
        content = str(message_input.value or "").strip()
        if not content:
            return
        send_button.props("loading disable")
        try:
            if not conversation_id:
                created = await client.post(
                    "/ai/conversations",
                    json={
                        "title": f"项目协作 {datetime.now().astimezone():%m-%d %H:%M}",
                        "space_id": space_id,
                        "goal_id": project_id,
                        "purpose": "PROJECT_ASSISTANT",
                        "context_key": f"project:{project_id}",
                        "context_snapshot": {
                            "page_key": "project",
                            "page_kind": "PROJECT",
                            "page_title": "项目 AI 协作",
                            "section": "collaboration",
                            "space_id": space_id,
                            "goal_id": project_id,
                        },
                    },
                )
                conversation_id = str(_conversation(created).get("id") or "")
                if not conversation_id:
                    raise ValueError("会话建立结果不完整")
                state["detail"] = created
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/messages",
                json={
                    "content": content,
                    "confirmed_external_ai": bool(is_external),
                    "page_context": {
                        "page_key": "project",
                        "page_kind": "PROJECT",
                        "page_title": "项目 AI 协作",
                        "section": "collaboration",
                        "space_id": space_id,
                        "goal_id": project_id,
                    },
                },
            )
            remember_detail()
            message_input.value = ""
            render()
        except (UIAPIError, ValueError) as exc:
            error_notice(f"发送失败：{exc}")
        finally:
            send_button.props(remove="loading disable")

    def render() -> None:
        nonlocal message_input, send_button
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        chat_panel.clear()
        side_panel.clear()
        with chat_panel:
            if not conversation_id and not state.get("draft_open"):
                with ui.card().classes("ln-card w-full items-center p-7 text-center"):
                    ui.icon("forum").classes("text-4xl text-green-700")
                    ui.label("和 AI 一起调整项目").classes("text-xl font-black")
                    ui.label("AI 可修改框架和路径草稿，不会替你启用版本。 ").classes(
                        "text-sm text-gray-600"
                    )
                    ui.button("开始协作", icon="add_comment", on_click=start_new).props(
                        "color=positive"
                    )
                return
            with ui.card().classes("ln-card w-full overflow-hidden"):
                with ui.row().classes("w-full items-center gap-2 border-b border-gray-200 p-4"):
                    ui.icon("forum").classes("text-xl text-green-700")
                    ui.label(str(conversation.get("title") or "项目协作")).classes(
                        "min-w-0 grow truncate font-black"
                    )
                    ui.label("本地保存").classes(
                        "rounded-full bg-green-50 px-2 py-1 text-xs font-bold text-green-800"
                    )
                    if conversations:
                        with ui.button(icon="history").props(
                            "flat round dense aria-label='切换历史对话'"
                        ):
                            with ui.menu():
                                ui.label("历史对话").classes(
                                    "px-4 pt-3 text-xs font-bold text-gray-500"
                                )
                                for item in conversations:
                                    item_id = str(item.get("id") or "")
                                    if not item_id:
                                        continue
                                    ui.menu_item(
                                        str(item.get("title") or "未命名对话"),
                                        on_click=lambda item_id=item_id: load(item_id),
                                    )
                    ui.button("新对话", icon="add", on_click=start_new).props(
                        "flat dense color=positive"
                    )
                with ui.column().classes("ln-chat-log w-full gap-3 p-4"):
                    messages = _conversation_messages(detail)
                    if messages:
                        for item in messages:
                            _render_message(item)
                    else:
                        ui.label("说明要调整的结构、顺序或内容。 ").classes("ln-empty w-full")
                with ui.column().classes(
                    "ln-ai-composer w-full gap-2 border-t border-gray-200 p-4"
                ):
                    with ui.row().classes("ln-ai-composer-row w-full items-end gap-2"):
                        message_input = (
                            ui.textarea(
                                "告诉 AI 要怎样修改",
                                placeholder="例如：把统计基础提前，并补充两个验证节点",
                            )
                            .classes("ln-ai-composer-input min-w-0 grow")
                            .props("outlined autogrow maxlength=40000")
                        )
                        send_button = (
                            ui.button("发送", icon="send", on_click=send)
                            .classes("ln-action-button ln-ai-send-button")
                            .props("color=positive")
                        )
                    ui.label("AI 写入仅进入草稿").classes("text-xs font-bold text-green-800")
        with side_panel:
            ui.label("草稿与启用").classes("text-lg font-black")
            ui.label("AI 的改动会保留在草稿；启用始终由你完成。 ").classes("text-sm text-gray-600")
            tool_messages = [
                item
                for item in _conversation_messages(detail)
                if str(item.get("role") or "").upper() == "TOOL"
            ]
            if tool_messages:
                succeeded = sum(_tool_view(item)["status"] == "SUCCEEDED" for item in tool_messages)
                ui.label(f"本次对话已写入 {succeeded} 项草稿改动").classes(
                    "rounded-xl bg-green-50 px-3 py-2 text-sm font-bold text-green-800"
                )
            with ui.column().classes("mt-2 w-full gap-2"):
                ui.link("查看框架草稿", f"/projects/{project_id}/map").classes(
                    "font-bold no-underline"
                )
                ui.link(
                    "查看并启用路径草稿",
                    f"/projects/{project_id}/overview?edit=path",
                ).classes("font-bold no-underline")
            ui.separator().classes("my-2")
            ui.label("前置关系只会提示风险，不会限制你调整或启用路径。 ").classes(
                "text-xs text-gray-500"
            )

    if conversations:
        preferred = next(
            (item for item in conversations if item.get("status") == "ACTIVE"),
            conversations[0],
        )
        conversation_id = str(preferred.get("id") or "")
        if conversation_id:
            await load(conversation_id)
            return
    render()
