"""Persistent contextual AI assistant mounted by the shared page shell."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nicegui import ui

from learning_navigator.ui.components.ai_collaboration import (
    _conversation,
    _conversation_focus_href,
    _conversation_history_label,
    _conversation_items,
    _conversation_messages,
    _get_ai_status,
    _render_message,
)
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import uses_mock_provider


@dataclass(slots=True)
class GlobalAssistantHandle:
    """Small handle used by the shared header to control the drawer."""

    drawer: Any

    def toggle(self) -> None:
        self.drawer.toggle()


def mount_global_ai_assistant(
    client: UIAPIClient,
    context: AssistantPageContext,
) -> GlobalAssistantHandle:
    """Mount one responsive assistant drawer for the current page."""

    state: dict[str, Any] = {
        "detail": None,
        "conversations": [],
        "ai_status": {},
        "loading": True,
        "error": None,
        "message_input": None,
    }

    with (
        ui.right_drawer(value=None, fixed=True, bordered=True)
        .props("width=400 breakpoint=1320 aria-label='上下文 AI 助手'")
        .classes("ln-ai-drawer") as drawer
    ):
        with ui.column().classes("ln-ai-assistant-root h-full w-full gap-0"):
            with ui.row().classes("ln-ai-panel-header w-full items-center gap-2 px-4 py-3"):
                with ui.column().classes("min-w-0 grow gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("auto_awesome").classes("text-lg text-green-700")
                        ui.label("AI 助手").classes("font-black")
                        ui.label("本地保存").classes("ln-ai-local-badge")
                    context_label = (
                        ui.label(context.display_label)
                        .classes("ln-ai-context-label max-w-full truncate text-xs text-gray-500")
                        .tooltip(context.display_label)
                    )
                history_slot = ui.row().classes("shrink-0 gap-0")
                ui.button(icon="close", on_click=drawer.hide).props(
                    "flat round dense aria-label='关闭 AI 助手'"
                ).tooltip("关闭")
            body = ui.column().classes("ln-ai-panel-body min-h-0 w-full grow gap-0")

    handle = GlobalAssistantHandle(drawer=drawer)

    def is_external_provider() -> bool:
        ai_status = state.get("ai_status")
        if not isinstance(ai_status, dict):
            return True
        is_mock = uses_mock_provider(ai_status)
        return bool(ai_status.get("is_external", not is_mock))

    def creation_scope() -> tuple[str, str | None]:
        if context.space_id and context.goal_id:
            return "PROJECT_ASSISTANT", context.context_key
        return "PLANNING", context.context_key

    def page_context_for(_conversation: dict[str, Any]) -> dict[str, Any]:
        """Always describe the page that owns this composer, never a stale history snapshot."""

        return context.to_payload()

    def matches_current_focus(item: dict[str, Any]) -> bool:
        if context.goal_id and context.space_id:
            return (
                item.get("purpose") == "PROJECT_ASSISTANT"
                and item.get("goal_id") == context.goal_id
                and item.get("space_id") == context.space_id
            )
        return (
            item.get("purpose") == "PLANNING"
            and item.get("space_id") is None
            and item.get("goal_id") is None
        )

    async def refresh_detail(conversation_id: str) -> None:
        state["detail"] = await client.get(f"/ai/conversations/{conversation_id}")

    async def load(conversation_id: str) -> None:
        state["loading"] = True
        state["error"] = None
        render()
        try:
            await refresh_detail(conversation_id)
        except UIAPIError as exc:
            state["error"] = f"无法打开对话：{exc}"
        finally:
            state["loading"] = False
            render()

    def remember_detail() -> None:
        """Add a conversation to history only after it contains a real turn."""

        detail = state.get("detail")
        if not _conversation_messages(detail):
            return
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        conversations = state.get("conversations")
        if not conversation_id or not isinstance(conversations, list):
            return
        conversations[:] = [
            item for item in conversations if str(item.get("id") or "") != conversation_id
        ]
        conversations.insert(0, conversation)

    async def create() -> str | None:
        state["error"] = None
        purpose, context_key = creation_scope()
        try:
            raw = await client.post(
                "/ai/conversations",
                json={
                    "title": f"{context.page_title} · {datetime.now().astimezone():%m-%d %H:%M}",
                    "space_id": context.space_id,
                    "goal_id": context.goal_id,
                    "purpose": purpose,
                    "context_key": context_key,
                    "context_snapshot": context.to_payload(),
                },
            )
        except UIAPIError as exc:
            state["error"] = f"无法新建对话：{exc}"
            render()
            return None
        detail = raw if isinstance(raw, dict) else {}
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            state["error"] = "服务没有返回可用的对话。"
            render()
            return None
        state["detail"] = detail
        return conversation_id

    def new_conversation() -> None:
        """Open an unsaved composer; the first message creates persistence."""

        state["detail"] = None
        state["error"] = None
        render()

    async def send() -> None:
        current_input = state.get("message_input")
        content = str(getattr(current_input, "value", "") or "").strip()
        if not content or state.get("loading"):
            return
        external = is_external_provider()
        conversation = _conversation(state.get("detail"))
        conversation_id = str(conversation.get("id") or "")
        state["loading"] = True
        state["error"] = None
        render()
        if conversation_id and not matches_current_focus(conversation):
            # A history item from another page/project remains readable, but sending from this
            # composer must use the current page's persisted scope. This keeps one shared history
            # without letting an old planning thread masquerade as a project assistant.
            state["detail"] = None
            conversation_id = ""
        if not conversation_id:
            conversation_id = str(await create() or "")
        if not conversation_id:
            state["loading"] = False
            render()
            return
        conversation = _conversation(state.get("detail"))
        try:
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/messages",
                json={
                    "content": content,
                    "confirmed_external_ai": bool(external),
                    "page_context": page_context_for(conversation),
                },
            )
            remember_detail()
        except UIAPIError as exc:
            state["error"] = f"发送失败：{exc}"
            with suppress(UIAPIError):
                await refresh_detail(conversation_id)
                remember_detail()
        finally:
            state["loading"] = False
            render()

    def render_history() -> None:
        history_slot.clear()
        conversations = state.get("conversations")
        items = conversations if isinstance(conversations, list) else []
        with history_slot:
            with (
                ui.button(icon="history")
                .props("flat round dense aria-label='切换 AI 对话历史'")
                .tooltip("对话历史")
            ):
                with ui.menu().classes("ln-ai-history-menu"):
                    ui.label("对话历史").classes("px-4 pt-3 text-xs font-bold text-gray-500")
                    if not items:
                        ui.label("暂无记录").classes("px-4 py-3 text-sm text-gray-500")
                    for item in items:
                        conversation_id = str(item.get("id") or "")
                        if not conversation_id:
                            continue

                        async def open_history(
                            item: dict[str, Any] = item,
                            conversation_id: str = conversation_id,
                        ) -> None:
                            if matches_current_focus(item):
                                await load(conversation_id)
                                return
                            target = _conversation_focus_href(item)
                            if target:
                                ui.navigate.to(target)
                                return
                            await load(conversation_id)

                        ui.menu_item(
                            _conversation_history_label(item),
                            on_click=open_history,
                        )
            ui.button(icon="add_comment", on_click=new_conversation).props(
                "flat round dense aria-label='新建 AI 对话'"
            ).tooltip("新对话")

    def render() -> None:
        render_history()
        body.clear()
        detail = state.get("detail")
        conversation = _conversation(detail)
        messages = _conversation_messages(detail)
        context_label.set_text(
            _conversation_history_label(conversation)
            if conversation.get("id")
            else context.display_label
        )
        with body:
            with ui.column().classes("ln-ai-message-log min-h-0 w-full grow gap-3 p-4"):
                if messages:
                    for item in messages:
                        _render_message(item)
                elif state.get("loading"):
                    with ui.row().classes("w-full items-center justify-center gap-2 py-8"):
                        ui.spinner("dots", size="lg", color="positive")
                        ui.label("读取上下文…").classes("text-sm text-gray-500")
                else:
                    with ui.column().classes("ln-ai-welcome w-full gap-2 p-4"):
                        ui.icon("forum").classes("text-2xl text-green-700")
                        ui.label("就当前内容提问").classes("font-black")
                        ui.label(
                            "可结合当前项目回答并修改草稿。"
                            if context.goal_id
                            else "可结合当前页面回答。"
                        ).classes("text-sm text-gray-600")
                if state.get("error"):
                    ui.label(str(state["error"])).classes(
                        "ln-ai-inline-error w-full rounded-xl px-3 py-2 text-sm"
                    )
            with ui.column().classes("ln-ai-composer w-full gap-2 p-3"):
                with ui.row().classes("ln-ai-composer-row w-full items-end gap-2"):
                    state["message_input"] = (
                        ui.textarea(
                            "向 AI 提问",
                            placeholder="提问、解释，或要求调整当前方案…",
                        )
                        .classes("ln-ai-composer-input min-w-0 grow")
                        .props("outlined autogrow maxlength=40000 rows=2 aria-label='向 AI 提问'")
                    )
                    ui.button("发送", icon="send", on_click=send).props(
                        "color=positive aria-label='发送给 AI'"
                        + (" loading disable" if state.get("loading") else "")
                    ).classes("ln-ai-send-button")
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    purpose = str(conversation.get("purpose") or context.purpose)
                    if purpose == "PLANNING":
                        status_text = "项目共创 · 方案改动只进入草稿"
                    elif purpose == "PROJECT_ASSISTANT":
                        status_text = "项目改动只进入草稿"
                    else:
                        status_text = "当前页面问答"
                    ui.label(status_text).classes("text-xs text-gray-500")
                    focus_href = _conversation_focus_href(conversation)
                    if focus_href:
                        ui.button(
                            "展开",
                            on_click=lambda target=focus_href: ui.navigate.to(target),
                        ).props("flat dense no-caps").classes("text-xs font-bold text-green-700")

    async def initialize() -> None:
        state["loading"] = True
        render()
        state["ai_status"] = await _get_ai_status(client)
        try:
            raw = await client.get("/ai/conversations")
            conversations = _conversation_items(raw)
            state["conversations"] = conversations
            preferred = next(
                (
                    item
                    for item in conversations
                    if item.get("status") == "ACTIVE" and matches_current_focus(item)
                ),
                {},
            )
            conversation_id = str(preferred.get("id") or "")
            if conversation_id:
                await refresh_detail(conversation_id)
        except UIAPIError as exc:
            state["error"] = f"无法读取对话记录：{exc}"
        finally:
            state["loading"] = False
            render()

    render()
    ui.timer(0.05, initialize, once=True)
    return handle
