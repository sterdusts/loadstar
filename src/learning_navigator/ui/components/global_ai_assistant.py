"""Persistent AI workspace shared by every page and project-creation flow."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nicegui import app, background_tasks, events, ui

from learning_navigator.domain.collaboration import (
    NEW_PROJECT_DISCOVERY_PROMPT,
    ConversationMessageOrigin,
)
from learning_navigator.ui.components.ai_collaboration import (
    _assistant_failure_view,
    _conversation,
    _conversation_history_label,
    _conversation_items,
    _conversation_messages,
    _conversation_revision,
    _conversation_title_from_message,
    _get_ai_status,
    _render_message,
    _render_plan_summary,
    _tool_proposal_view,
)
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import uses_mock_provider

MODE_NEW_PROJECT = "PLANNING"
ACTIVE_CONVERSATION_STORAGE_KEY = "ln-ai-active-conversation-id"
ASSISTANT_WORKSPACE_STORAGE_KEY = "ln-ai-workspace"
NEW_PROJECT_PROMPT = NEW_PROJECT_DISCOVERY_PROMPT
ATTACHMENT_PATH_PROMPT = (
    "请以本轮附件作为主要依据：先归纳材料覆盖的主题、层级、依赖、缺口与限制，"
    "再生成或更新一份模块化学习路径。不要推翻已有项目中仍然有效的结构；"
    "如果当前对话已关联项目，只提出可逐项审核的增量修改。"
)
_SAFE_AI_PREVIEW_IMAGE_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

_AI_ATTACHMENT_PASTE_BOOTSTRAP = r"""
(() => {
  if (window.LearningNavigatorAiAttachmentPaste) return;

  const extensionFor = mediaType => ({
    'image/avif': 'avif',
    'image/gif': 'gif',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
  })[mediaType] || 'png';
  const timestamp = () => {
    const now = new Date();
    const two = value => String(value).padStart(2, '0');
    return `${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}` +
      `-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  };
  const visibleUploader = () => Array.from(
    document.querySelectorAll('.ln-ai-attachment-upload')
  ).find(element => element.offsetParent !== null);

  document.addEventListener('paste', event => {
    const uploader = visibleUploader();
    if (!uploader) return;
    const files = Array.from(event.clipboardData?.files || []);
    if (!files.length) return;
    const input = uploader.querySelector('input[type="file"]');
    if (!input || typeof DataTransfer === 'undefined') return;
    const transfer = new DataTransfer();
    const stamp = timestamp();
    files.forEach((file, index) => {
      const type = file.type || 'application/octet-stream';
      const originalName = String(file.name || '').trim();
      const isImage = type.toLowerCase().startsWith('image/');
      const name = originalName || (isImage
        ? `截图-${stamp}${files.length > 1 ? `-${index + 1}` : ''}.${extensionFor(type)}`
        : `粘贴文件-${stamp}${files.length > 1 ? `-${index + 1}` : ''}`);
      transfer.items.add(new File([file], name, {type, lastModified: Date.now()}));
    });
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
    event.preventDefault();
  });

  window.LearningNavigatorAiAttachmentPaste = {enabled: true};
})();
"""


def _is_history_eligible_detail(detail: Any) -> bool:
    """Return whether a conversation contains genuine user-authored content."""

    for message in _conversation_messages(detail):
        if message.get("role") != "USER":
            continue
        content = str(message.get("content") or "").strip()
        metadata = message.get("message_metadata")
        origin = metadata.get("message_origin") if isinstance(metadata, dict) else None
        if (
            content
            and content != NEW_PROJECT_PROMPT
            and origin != ConversationMessageOrigin.PROJECT_CREATION_SHORTCUT.value
        ):
            return True
    return False


def _persist_active_conversation_id(conversation_id: str | None) -> None:
    """Keep the selected thread stable while NiceGUI remounts across pages."""

    try:
        user_storage = app.storage.user
        if conversation_id:
            user_storage[ACTIVE_CONVERSATION_STORAGE_KEY] = conversation_id
        else:
            user_storage.pop(ACTIVE_CONVERSATION_STORAGE_KEY, None)
    except RuntimeError:
        # Unit tests and script-mode rendering have no browser-scoped user storage.
        pass

    key = json.dumps(ACTIVE_CONVERSATION_STORAGE_KEY)
    # Prompt shortcuts run in a NiceGUI background task, which can outlive the
    # originating client context.  Browser persistence is an enhancement; it
    # must never abort a durable message after the conversation was created.
    with suppress(RuntimeError, TimeoutError):
        if conversation_id:
            value = json.dumps(conversation_id)
            ui.run_javascript(f"window.localStorage.setItem({key}, {value})")
        else:
            ui.run_javascript(f"window.localStorage.removeItem({key})")


async def _stored_active_conversation_id() -> str:
    try:
        stored = app.storage.user.get(ACTIVE_CONVERSATION_STORAGE_KEY)
    except RuntimeError:
        stored = None
    if isinstance(stored, str) and stored:
        return stored

    key = json.dumps(ACTIVE_CONVERSATION_STORAGE_KEY)
    try:
        value = await ui.run_javascript(f"window.localStorage.getItem({key}) || ''")
    except (RuntimeError, TimeoutError):
        return ""
    return str(value or "")


def _cached_assistant_workspace() -> dict[str, Any]:
    """Restore the visible chat workspace before a new page finishes loading."""

    try:
        value = app.storage.user.get(ASSISTANT_WORKSPACE_STORAGE_KEY)
    except RuntimeError:
        return {}
    return value if isinstance(value, dict) else {}


def _persist_assistant_workspace(
    *,
    detail: Any,
    draft: str,
    history_kind: str,
    history_view: str,
    staged_attachments: list[dict[str, Any]],
) -> None:
    """Keep the assistant visually stable while the surrounding page changes."""

    with suppress(RuntimeError):
        app.storage.user[ASSISTANT_WORKSPACE_STORAGE_KEY] = {
            "detail": detail if isinstance(detail, dict) else None,
            "draft": draft[:40_000],
            "history_kind": history_kind,
            "history_view": history_view,
            "staged_attachments": staged_attachments,
        }


def _attachment_size_label(value: Any) -> str:
    try:
        size = max(int(value), 0)
    except (TypeError, ValueError):
        return "未知大小"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024 or candidate == units[-1]:
            break
        amount /= 1024
    return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"


def _attachment_browser_url(client: UIAPIClient, raw_url: str) -> str:
    if raw_url.startswith("/api/"):
        return f"{client.base_url.rstrip('/')}/{raw_url.removeprefix('/api/')}"
    return raw_url


def _history_group_label(value: Any, *, now: datetime | None = None) -> str:
    """Group recent conversations like a modern persistent chat history."""

    if not isinstance(value, str) or not value:
        return "更早"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return "更早"
    today = (now or datetime.now().astimezone()).date()
    days = (today - stamp.date()).days
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days <= 7:
        return "过去 7 天"
    if days <= 30:
        return "过去 30 天"
    return "更早"


def _planning_page_context() -> dict[str, Any]:
    return {
        "page_key": "new-project",
        "page_kind": "PLANNING",
        "page_title": "新建项目",
        "section": "planning",
    }


def _context_matches_project(payload: Any, *, space_id: str, goal_id: str) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("space_id") == space_id
        and payload.get("goal_id") == goal_id
    )


def _scoped_page_context(
    conversation: dict[str, Any],
    current_context: dict[str, Any],
) -> dict[str, Any]:
    """Keep the selected history thread in scope without changing its identity.

    Current-page facts are used only when they match the persisted conversation scope.
    Otherwise the last safe snapshot (or a minimal persisted-scope snapshot) is used.
    """

    purpose = str(conversation.get("purpose") or "")
    snapshot = conversation.get("context_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    if purpose == MODE_NEW_PROJECT:
        if not snapshot.get("space_id") and not snapshot.get("goal_id"):
            return snapshot or _planning_page_context()
        return _planning_page_context()

    if purpose == "PROJECT_ASSISTANT":
        space_id = str(conversation.get("space_id") or "")
        goal_id = str(conversation.get("goal_id") or "")
        if (
            space_id
            and goal_id
            and _context_matches_project(
                current_context,
                space_id=space_id,
                goal_id=goal_id,
            )
        ):
            return current_context
        if (
            space_id
            and goal_id
            and _context_matches_project(
                snapshot,
                space_id=space_id,
                goal_id=goal_id,
            )
        ):
            return snapshot
        return {
            "page_key": "project",
            "page_kind": "PROJECT",
            "page_title": str(conversation.get("title") or "关联项目"),
            "section": "assistant",
            "space_id": space_id,
            "goal_id": goal_id,
        }

    context_key = str(conversation.get("context_key") or "")
    expected_page = context_key.removeprefix("page:") if context_key.startswith("page:") else ""
    if (
        expected_page
        and current_context.get("page_key") == expected_page
        and not current_context.get("space_id")
        and not current_context.get("goal_id")
    ):
        return current_context
    if (
        expected_page
        and snapshot.get("page_key") == expected_page
        and not snapshot.get("space_id")
        and not snapshot.get("goal_id")
    ):
        return snapshot
    return {
        "page_key": expected_page or "assistant-history",
        "page_kind": "PAGE",
        "page_title": str(conversation.get("title") or "历史对话"),
    }


@dataclass(slots=True)
class GlobalAssistantHandle:
    """Controls the one shared assistant surface from page-level actions."""

    drawer: Any
    _start_chat: Callable[[], None]
    _start_new_project: Callable[[], None]
    _toggle_fullscreen: Callable[[], None]
    _start_context_prompt: Callable[[str], None] = lambda _prompt: None

    def toggle(self) -> None:
        self.drawer.toggle()

    def show(self) -> None:
        self.drawer.show()

    def start_chat(self) -> None:
        self._start_chat()
        self.drawer.show()

    def start_project(self) -> None:
        """Backward-compatible alias for the unified new-project action."""

        self.start_new_project()

    def start_new_project(self) -> None:
        self._start_new_project()
        self.drawer.show()

    def start_context_prompt(self, prompt: str) -> None:
        """Start a fresh contextual turn without creating a second assistant surface."""

        self._start_context_prompt(prompt)
        self.drawer.show()

    def toggle_fullscreen(self) -> None:
        self._toggle_fullscreen()
        self.drawer.show()


def mount_global_ai_assistant(
    client: UIAPIClient,
    context: AssistantPageContext,
) -> GlobalAssistantHandle:
    """Mount the unified, resizable AI workspace for the current page."""

    cached_workspace = _cached_assistant_workspace()
    cached_detail = cached_workspace.get("detail")
    cached_attachments = cached_workspace.get("staged_attachments")
    state: dict[str, Any] = {
        "detail": cached_detail if isinstance(cached_detail, dict) else None,
        "conversations": [],
        "ai_status": {},
        "loading": not isinstance(cached_detail, dict),
        "error": None,
        "message_input": None,
        "fullscreen": False,
        "history_query": "",
        "history_view": str(cached_workspace.get("history_view") or "active"),
        "history_kind": str(cached_workspace.get("history_kind") or "chat"),
        "user_selected": False,
        "message_draft": str(cached_workspace.get("draft") or ""),
        "project_prompt_pending": False,
        "retry_pending": False,
        "staged_attachments": (
            [item for item in cached_attachments if isinstance(item, dict)]
            if isinstance(cached_attachments, list)
            else []
        ),
        "pending_upload_files": [],
        "attachment_uploading": False,
    }

    with (
        ui.right_drawer(value=None, fixed=True, bordered=True)
        .props("width=400 breakpoint=1320 aria-label='AI 工作区'")
        .classes("ln-ai-drawer") as drawer
    ):
        ui.element("div").classes("ln-ai-resize-handle").props(
            "role=separator aria-label='调整 AI 侧栏宽度' aria-orientation=vertical"
        )
        with ui.column().classes("ln-ai-assistant-root h-full w-full gap-0") as root:
            with ui.row().classes("ln-ai-panel-header w-full items-center gap-2 px-4 py-3"):
                with ui.column().classes("ln-ai-header-identity min-w-0 grow gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("auto_awesome").classes("text-lg text-green-700")
                        ui.label("AI").classes("font-black")
                        ui.label("本地保存").classes("ln-ai-local-badge")
                    context_label = (
                        ui.label(context.display_label)
                        .classes("ln-ai-context-label max-w-full truncate text-xs text-gray-500")
                        .tooltip(context.display_label)
                    )
                history_slot = ui.row().classes("ln-ai-header-actions shrink-0 items-center gap-1")
            body = ui.column().classes("ln-ai-panel-body min-h-0 w-full grow gap-0")

    def is_external_provider() -> bool:
        ai_status = state.get("ai_status")
        if not isinstance(ai_status, dict):
            return True
        is_mock = uses_mock_provider(ai_status)
        return bool(ai_status.get("is_external", not is_mock))

    def creation_scope(purpose: str | None = None) -> dict[str, Any]:
        resolved_purpose = purpose or context.purpose
        if resolved_purpose == MODE_NEW_PROJECT:
            return {
                "purpose": MODE_NEW_PROJECT,
                "context_key": "page:new-project",
                "space_id": None,
                "goal_id": None,
                "context_snapshot": _planning_page_context(),
            }
        if context.space_id and context.goal_id:
            return {
                "purpose": "PROJECT_ASSISTANT",
                "context_key": context.context_key,
                "space_id": context.space_id,
                "goal_id": context.goal_id,
                "context_snapshot": context.to_payload(),
            }
        return {
            "purpose": "PAGE_ASSISTANT",
            "context_key": context.context_key,
            "space_id": None,
            "goal_id": None,
            "context_snapshot": context.to_payload(),
        }

    def matches_current_focus(item: dict[str, Any]) -> bool:
        if context.goal_id and context.space_id:
            return (
                item.get("purpose") == "PROJECT_ASSISTANT"
                and item.get("goal_id") == context.goal_id
                and item.get("space_id") == context.space_id
            )
        return (
            item.get("purpose") == "PAGE_ASSISTANT"
            and item.get("context_key") == context.context_key
        )

    def persist_workspace() -> None:
        staged = state.get("staged_attachments")
        _persist_assistant_workspace(
            detail=state.get("detail"),
            draft=str(state.get("message_draft") or ""),
            history_kind=str(state.get("history_kind") or "chat"),
            history_view=str(state.get("history_view") or "active"),
            staged_attachments=(
                [item for item in staged if isinstance(item, dict)]
                if isinstance(staged, list)
                else []
            ),
        )

    async def refresh_detail(conversation_id: str) -> None:
        detail = await client.get(f"/ai/conversations/{conversation_id}")
        state["detail"] = detail
        persist_workspace()

    async def load(conversation_id: str) -> None:
        if state.get("loading"):
            return
        state["loading"] = True
        state["error"] = None
        render()
        try:
            await refresh_detail(conversation_id)
            _persist_active_conversation_id(conversation_id)
        except UIAPIError as exc:
            state["error"] = f"无法打开对话：{exc}"
        finally:
            state["loading"] = False
            render()

    def remember_detail() -> None:
        """Expose a conversation only after genuine user-authored content."""

        detail = state.get("detail")
        if not _is_history_eligible_detail(detail):
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

    async def create(content: str, *, purpose: str | None = None) -> str | None:
        state["error"] = None
        scope = creation_scope(purpose)
        staged = state.get("staged_attachments")
        first_attachment_name = ""
        if isinstance(staged, list) and staged and isinstance(staged[0], dict):
            first_attachment_name = str(staged[0].get("original_name") or "")
        title_source = content or f"分析附件：{first_attachment_name or '新材料'}"
        title = (
            _conversation_title_from_message(title_source)
            if scope["purpose"] == MODE_NEW_PROJECT
            else f"{context.page_title} · {datetime.now().astimezone():%m-%d %H:%M}"
        )
        try:
            raw = await client.post(
                "/ai/conversations",
                json={"title": title, **scope},
            )
        except UIAPIError as exc:
            state["error"] = f"无法新建对话：{exc}"
            return None
        detail = raw if isinstance(raw, dict) else {}
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            state["error"] = "服务没有返回可用的对话。"
            return None
        state["detail"] = detail
        _persist_active_conversation_id(conversation_id)
        persist_workspace()
        return conversation_id

    def new_conversation() -> None:
        """Open an unsaved contextual composer; the first message persists it."""

        if state.get("loading"):
            return
        state["detail"] = None
        state["error"] = None
        state["message_draft"] = ""
        state["user_selected"] = True
        _persist_active_conversation_id(None)
        persist_workspace()
        render()

    def start_new_project() -> None:
        """Send the project-planning prompt in the same assistant surface."""

        if state.get("loading") or state.get("project_prompt_pending"):
            return
        state["project_prompt_pending"] = True
        render()
        background_tasks.create(
            send_prompt(NEW_PROJECT_PROMPT),
            name="learning-navigator-new-project-prompt",
        )

    def start_context_prompt(prompt: str) -> None:
        """Open a contextual thread and send one explicit user-approved prompt."""

        content = prompt.strip()
        if not content or state.get("loading"):
            return
        new_conversation()
        background_tasks.create(
            send_content(content),
            name="learning-navigator-context-prompt",
        )

    async def upload_pending_files() -> None:
        pending = state.get("pending_upload_files")
        if not isinstance(pending, list) or not pending or state.get("attachment_uploading"):
            return
        files = list(pending)
        pending.clear()
        state["attachment_uploading"] = True
        state["error"] = None
        render()
        failures: list[str] = []
        try:
            staged = state.get("staged_attachments")
            if not isinstance(staged, list):
                staged = []
                state["staged_attachments"] = staged
            for uploaded in files:
                filename = str(getattr(uploaded, "name", "") or "attachment")
                content_type = str(
                    getattr(uploaded, "content_type", "") or "application/octet-stream"
                )
                try:
                    raw = await client.upload(
                        "/ai/attachments",
                        filename=filename,
                        content_type=content_type,
                        chunks=uploaded.iterate(),
                    )
                except (UIAPIError, OSError):
                    failures.append(filename)
                    continue
                if isinstance(raw, dict):
                    staged.append(raw)
            persist_workspace()
            if failures:
                state["error"] = "以下文件未能上传：" + "、".join(failures[:5])
        finally:
            state["attachment_uploading"] = False
            render()

    def begin_attachment_upload(_event: Any) -> None:
        state["attachment_uploading"] = True

    def collect_attachment(event: events.UploadEventArguments) -> None:
        pending = state.get("pending_upload_files")
        if isinstance(pending, list):
            pending.append(event.file)

    def finish_attachment_upload(_event: Any) -> None:
        state["attachment_uploading"] = False
        background_tasks.create(
            upload_pending_files(),
            name="learning-navigator-ai-attachment-upload",
        )

    async def remove_staged_attachment(attachment_id: str) -> None:
        if not attachment_id or state.get("loading") or state.get("attachment_uploading"):
            return
        try:
            await client.delete(f"/ai/attachments/{attachment_id}")
        except UIAPIError as exc:
            state["error"] = f"无法移除附件：{exc}"
            render()
            return
        staged = state.get("staged_attachments")
        if isinstance(staged, list):
            staged[:] = [
                item
                for item in staged
                if not isinstance(item, dict) or str(item.get("id") or "") != attachment_id
            ]
        persist_workspace()
        render()

    def generate_path_from_attachments() -> None:
        staged = state.get("staged_attachments")
        if not isinstance(staged, list) or not staged:
            ui.notify("请先上传用于生成路径的文件。", type="warning")
            return
        if state.get("loading") or state.get("project_prompt_pending"):
            return
        state["project_prompt_pending"] = True
        render()

        async def generate() -> None:
            conversation = _conversation(state.get("detail"))
            purpose = str(conversation.get("purpose") or "")
            try:
                await send_content(
                    ATTACHMENT_PATH_PROMPT,
                    new_conversation_purpose=(
                        None if purpose in {"PLANNING", "PROJECT_ASSISTANT"} else MODE_NEW_PROJECT
                    ),
                    message_origin=ConversationMessageOrigin.USER_INPUT,
                )
            finally:
                state["project_prompt_pending"] = False
                render()

        background_tasks.create(
            generate(),
            name="learning-navigator-attachment-path-generation",
        )

    def toggle_fullscreen() -> None:
        state["fullscreen"] = not bool(state.get("fullscreen"))
        if state["fullscreen"]:
            drawer.classes(add="ln-ai-drawer-fullscreen")
            root.classes(add="ln-ai-assistant-fullscreen ln-ai-fullscreen")
        else:
            drawer.classes(remove="ln-ai-drawer-fullscreen")
            root.classes(remove="ln-ai-assistant-fullscreen ln-ai-fullscreen")
        render()

    async def send_content(
        content: str,
        *,
        new_conversation_purpose: str | None = None,
        message_origin: ConversationMessageOrigin = ConversationMessageOrigin.USER_INPUT,
    ) -> bool:
        content = content.strip()
        staged = state.get("staged_attachments")
        staged = staged if isinstance(staged, list) else []
        attachment_ids = [
            str(item.get("id") or "")
            for item in staged
            if isinstance(item, dict) and item.get("id")
        ]
        if (not content and not attachment_ids) or state.get("loading"):
            return False
        conversation = _conversation(state.get("detail"))
        conversation_id = (
            "" if new_conversation_purpose is not None else str(conversation.get("id") or "")
        )
        state["loading"] = True
        state["error"] = None
        render()
        sent = False
        try:
            if not conversation_id:
                if new_conversation_purpose is None:
                    conversation_id = str(await create(content) or "")
                else:
                    conversation_id = str(
                        await create(content, purpose=new_conversation_purpose) or ""
                    )
            if not conversation_id:
                return False
            conversation = _conversation(state.get("detail"))
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/messages",
                json={
                    "content": content,
                    "attachment_ids": attachment_ids,
                    "confirmed_external_ai": bool(is_external_provider()),
                    "message_origin": message_origin.value,
                    "page_context": _scoped_page_context(
                        conversation,
                        context.to_payload(),
                    ),
                },
            )
            remember_detail()
            if attachment_ids:
                state["staged_attachments"] = []
            persist_workspace()
            sent = True
        except UIAPIError as exc:
            state["error"] = f"发送失败：{exc}"
            with suppress(UIAPIError):
                await refresh_detail(conversation_id)
                remember_detail()
        finally:
            state["loading"] = False
            render()
        return sent

    async def send_prompt(content: str) -> None:
        """Start one planning thread and send its first prompt without changing surfaces."""

        try:
            await send_content(
                content,
                new_conversation_purpose=MODE_NEW_PROJECT,
                message_origin=ConversationMessageOrigin.PROJECT_CREATION_SHORTCUT,
            )
        finally:
            state["project_prompt_pending"] = False
            render()

    async def send() -> None:
        current_input = state.get("message_input")
        content = str(getattr(current_input, "value", "") or "").strip()
        staged = state.get("staged_attachments")
        if not content and not (isinstance(staged, list) and staged):
            return
        # Rendering the loading state rebuilds the composer.  Keep the user's
        # text until the server confirms the turn, so a network failure never
        # becomes lost work.
        state["message_draft"] = content
        persist_workspace()
        if await send_content(content):
            state["message_draft"] = ""
            persist_workspace()
            refreshed_input = state.get("message_input")
            if refreshed_input is not None:
                refreshed_input.set_value("")

    def retry_failed_message(content: str) -> None:
        """Retry the persisted user turn without asking the user to retype it."""

        if not content or state.get("loading") or state.get("retry_pending"):
            return
        state["retry_pending"] = True
        render()

        async def retry() -> None:
            state["retry_pending"] = False
            try:
                await send_content(content)
            finally:
                state["retry_pending"] = False
                render()

        background_tasks.create(retry(), name="learning-navigator-ai-retry")

    async def decide_tool_proposal(proposal_id: str, action: str) -> None:
        """Apply or reject exactly one reviewed proposal at the visible revision."""

        if action not in {"approve", "reject"} or state.get("loading"):
            return
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id or not proposal_id:
            return
        state["loading"] = True
        state["error"] = None
        render()
        try:
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/{action}",
                json={"expected_revision": _conversation_revision(detail)},
            )
            remember_detail()
            if action == "approve":
                ui.notify("已应用到草稿，正在刷新页面数据。", type="positive")
                ui.run_javascript("window.setTimeout(() => window.location.reload(), 500)")
            else:
                ui.notify("已拒绝这项改动。", type="positive")
        except UIAPIError as exc:
            state["error"] = f"无法处理这项改动：{exc}"
        finally:
            state["loading"] = False
            render()

    async def finalize_plan() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id or not isinstance(conversation.get("working_plan"), dict):
            ui.notify("先和 AI 形成一份完整方案。", type="warning")
            return
        state["loading"] = True
        render()
        try:
            state["detail"] = await client.post(
                f"/ai/conversations/{conversation_id}/finalize-plan",
                json={"expected_revision": _conversation_revision(detail)},
            )
            remember_detail()
            ui.notify("方案已锁定，请确认后建立项目。", type="positive")
        except UIAPIError as exc:
            state["error"] = f"无法锁定方案：{exc}"
        finally:
            state["loading"] = False
            render()

    async def activate_plan() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            return
        state["loading"] = True
        render()
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
            await refresh_detail(conversation_id)
            remember_detail()
            ui.notify("项目已建立，当前对话已继续关联该项目。", type="positive")
        except (UIAPIError, ValueError) as exc:
            state["error"] = f"无法建立项目：{exc}"
        finally:
            state["loading"] = False
            render()

    async def open_history(conversation_id: str) -> None:
        """History always opens in place; it never changes the current page URL."""

        state["user_selected"] = True
        await load(conversation_id)

    async def refresh_history() -> None:
        """Refresh both active and archived history from the durable source."""

        raw = await client.get(
            "/ai/conversations",
            params={"include_archived": True},
        )
        state["conversations"] = _conversation_items(raw)

    def set_history_view(view: str) -> None:
        """Switch history filters without navigating away from the current page."""

        if view not in {"active", "archived"} or state.get("loading"):
            return
        state["history_view"] = view
        state["history_query"] = ""
        persist_workspace()
        render()

    def set_history_kind(kind: str) -> None:
        """Separate project-creation threads from ordinary assistant conversations."""

        if kind not in {"chat", "project"} or state.get("loading"):
            return
        state["history_kind"] = kind
        state["history_query"] = ""
        persist_workspace()
        render()

    async def archive_conversation(item: dict[str, Any]) -> None:
        """Move one reviewed conversation out of normal history, preserving it locally."""

        conversation_id = str(item.get("id") or "")
        if not conversation_id or state.get("loading"):
            return
        state["loading"] = True
        state["error"] = None
        render()
        try:
            await client.post(
                f"/ai/conversations/{conversation_id}/archive",
                json={"expected_revision": _conversation_revision(item)},
            )
            await refresh_history()
            current_id = str(_conversation(state.get("detail")).get("id") or "")
            if current_id == conversation_id:
                state["detail"] = None
                state["message_draft"] = ""
                _persist_active_conversation_id(None)
            persist_workspace()
            ui.notify("对话已移到回收站，完整记录和上下文仍保存在本地。", type="positive")
        except UIAPIError as exc:
            state["error"] = f"无法归档对话：{exc}"
        finally:
            state["loading"] = False
            render()

    async def restore_conversation(item: dict[str, Any]) -> None:
        """Restore one archived conversation without changing the open page or thread."""

        conversation_id = str(item.get("id") or "")
        if not conversation_id or state.get("loading"):
            return
        state["loading"] = True
        state["error"] = None
        render()
        try:
            await client.post(
                f"/ai/conversations/{conversation_id}/restore",
                json={"expected_revision": _conversation_revision(item)},
            )
            await refresh_history()
            ui.notify("对话已恢复到历史记录。", type="positive")
        except UIAPIError as exc:
            state["error"] = f"无法恢复对话：{exc}"
        finally:
            state["loading"] = False
            render()

    async def permanently_delete_conversation(item: dict[str, Any], dialog: Any) -> None:
        """Destroy one trashed conversation after the server repeats every safety check."""

        conversation_id = str(item.get("id") or "")
        title = str(item.get("title") or "未命名对话")
        if not conversation_id or state.get("loading"):
            return
        state["loading"] = True
        state["error"] = None
        try:
            await client.delete(
                f"/ai/conversations/{conversation_id}",
                json={
                    "expected_revision": _conversation_revision(item),
                    "confirm_title": title,
                },
            )
            dialog.close()
            await refresh_history()
            current_id = str(_conversation(state.get("detail")).get("id") or "")
            if current_id == conversation_id:
                state["detail"] = None
                state["message_draft"] = ""
                _persist_active_conversation_id(None)
            persist_workspace()
            ui.notify("对话及其本地上下文已永久删除。", type="positive")
        except UIAPIError as exc:
            state["error"] = f"无法永久删除对话：{exc}"
            ui.notify("永久删除失败，对话仍保留在回收站。", type="negative")
        finally:
            state["loading"] = False
            render()

    def open_permanent_delete_confirmation(item: dict[str, Any]) -> None:
        """Require title confirmation for the irreversible conversation privacy action."""

        title = str(item.get("title") or "未命名对话")
        deleting = {"active": False}
        with ui.dialog() as dialog, ui.card().classes("ln-dialog-card max-w-lg gap-4 p-5"):
            with ui.row().classes("w-full items-start gap-3"):
                ui.icon("warning_amber", color="negative").classes("mt-0.5 text-2xl")
                with ui.column().classes("min-w-0 grow gap-1"):
                    ui.label("永久删除这段对话？").classes("text-xl font-black")
                    ui.label(title).classes("break-words font-bold")
            ui.label(
                "全部消息、页面或项目上下文、方案草稿和工具提案都会从本地永久删除，"
                "且无法恢复。已创建的项目以及已经批准执行的修改不会撤销。"
            ).classes("text-sm leading-6 text-gray-600")
            ui.label("请输入完整对话标题确认永久删除。").classes(
                "rounded-lg bg-red-50 px-3 py-2 text-xs font-bold text-red-800"
            )
            confirmation = (
                ui.input(
                    label=f"输入“{title}”确认永久删除",
                    placeholder=title,
                )
                .classes("w-full")
                .props("outlined autocomplete=off")
            )

            def sync_delete_button() -> None:
                if str(confirmation.value or "") == title:
                    delete_button.props(remove="disable")
                else:
                    delete_button.props("disable")

            async def confirm() -> None:
                if deleting["active"]:
                    return
                if str(confirmation.value or "") != title:
                    ui.notify("请输入完整对话标题后再永久删除。", type="warning")
                    return
                deleting["active"] = True
                delete_button.props("loading disable")
                await permanently_delete_conversation(item, dialog)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("flat no-caps")
                delete_button = ui.button(
                    "永久删除",
                    icon="delete_forever",
                    on_click=confirm,
                ).props("no-caps color=negative disable")
            confirmation.on_value_change(lambda _: sync_delete_button())
        dialog.props("aria-label='永久删除对话确认' role='alertdialog'")
        dialog.open()

    def history_items() -> list[dict[str, Any]]:
        conversations = state.get("conversations")
        items = conversations if isinstance(conversations, list) else []
        expected_status = "ARCHIVED" if state.get("history_view") == "archived" else "ACTIVE"
        items = [
            item for item in items if str(item.get("status") or "ACTIVE").upper() == expected_status
        ]
        expected_planning = state.get("history_kind") == "project"
        items = [
            item
            for item in items
            if (str(item.get("purpose") or "") == MODE_NEW_PROJECT) == expected_planning
        ]
        query = str(state.get("history_query") or "").strip().casefold()
        if not query:
            return items
        return [item for item in items if query in _conversation_history_label(item).casefold()]

    def render_history_action_items(item: dict[str, Any]) -> None:
        """Render the legal lifecycle actions for one history item.

        The same menu can be opened by right-click, long-press, or the standard
        keyboard context-menu shortcuts. Moving to trash is immediate and
        reversible; permanent deletion retains its explicit confirmation.
        """

        if str(item.get("status") or "ACTIVE").upper() == "ARCHIVED":
            ui.menu_item(
                "恢复对话",
                on_click=lambda item=item: restore_conversation(item),
            )
            ui.separator()
            ui.menu_item(
                "永久删除",
                on_click=lambda item=item: open_permanent_delete_confirmation(item),
            )
        else:
            ui.menu_item(
                "移到回收站",
                on_click=lambda item=item: archive_conversation(item),
            )

    def render_history_context_actions(item: dict[str, Any]) -> Any:
        """Attach right-click/long-press actions and return the keyboard-openable menu."""

        with ui.context_menu().classes("ln-ai-history-context-menu") as menu:
            render_history_action_items(item)
        return menu

    def bind_history_keyboard_menu(entry: Any, menu: Any) -> None:
        """Make the standard Menu key and Shift+F10 open the row's context menu."""

        entry.on(
            "keydown",
            menu.open,
            js_handler="""(event) => {
                if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
                    event.preventDefault();
                    emit();
                }
            }""",
        )

    def render_compact_history() -> None:
        items = history_items()
        with ui.menu().classes("ln-ai-history-menu"):
            with ui.row().classes("w-full items-center justify-between gap-2 px-3 pt-2"):
                ui.label(
                    "回收站" if state.get("history_view") == "archived" else "对话历史"
                ).classes("text-xs font-bold text-gray-500")
                ui.button(
                    "返回历史" if state.get("history_view") == "archived" else "回收站",
                    icon="history" if state.get("history_view") == "archived" else "delete_outline",
                    on_click=lambda: set_history_view(
                        "active" if state.get("history_view") == "archived" else "archived"
                    ),
                ).props("flat dense no-caps color=positive")
            with ui.row().classes("w-full gap-1 px-3 py-2"):
                for kind, label in (("chat", "对话"), ("project", "新建项目")):
                    selected = state.get("history_kind") == kind
                    ui.button(
                        label,
                        on_click=lambda kind=kind: set_history_kind(kind),
                    ).classes("min-w-0 grow").props(
                        ("unelevated" if selected else "flat") + " dense no-caps color=positive"
                    )
            if not items:
                ui.label(
                    "回收站为空" if state.get("history_view") == "archived" else "暂无记录"
                ).classes("px-4 py-3 text-sm text-gray-500")
            for item in items[:30]:
                conversation_id = str(item.get("id") or "")
                if conversation_id:
                    with (
                        ui.row()
                        .classes(
                            "ln-ai-history-entry ln-ai-compact-history-row "
                            "w-full items-center gap-1"
                        )
                        .props(
                            "tabindex=0 role=listitem aria-haspopup=menu "
                            "aria-label='对话历史项，右键或长按管理'"
                        )
                    ) as entry:
                        if state.get("history_view") == "archived":
                            ui.label(_conversation_history_label(item)).classes(
                                "min-w-0 grow truncate px-3 py-2 text-sm"
                            )
                        else:
                            history_item = (
                                ui.button(
                                    _conversation_history_label(item),
                                    on_click=lambda conversation_id=conversation_id: open_history(
                                        conversation_id
                                    ),
                                )
                                .classes("min-w-0 grow justify-start truncate")
                                .props(
                                    "flat dense no-caps align=left"
                                    + (" disable" if state.get("loading") else "")
                                )
                            )
                            history_item.tooltip(_conversation_history_label(item))
                        menu = render_history_context_actions(item)
                    bind_history_keyboard_menu(entry, menu)

    def render_history_header() -> None:
        history_slot.clear()
        with history_slot:
            with ui.row().classes("ln-ai-header-primary-action items-center"):
                ui.button("新对话", icon="edit_square", on_click=new_conversation).props(
                    "flat dense no-caps aria-label='新对话'"
                    + (" disable" if state.get("loading") else "")
                ).classes("ln-ai-new-chat-button")
            with ui.row().classes("ln-ai-header-icon-actions items-center gap-1"):
                with (
                    ui.button(icon="history")
                    .classes("ln-ai-history-trigger")
                    .props("flat round dense aria-label='切换 AI 对话历史'")
                    .tooltip("对话历史")
                ):
                    render_compact_history()
                ui.button(
                    icon="fullscreen_exit" if state.get("fullscreen") else "fullscreen",
                    on_click=toggle_fullscreen,
                ).props("flat round dense aria-label='切换 AI 全屏'").tooltip(
                    "退出全屏" if state.get("fullscreen") else "全屏"
                )
                ui.button(icon="close", on_click=drawer.hide).props(
                    "flat round dense aria-label='关闭 AI 工作区'"
                ).tooltip("关闭")

    def render_history_list(slot: Any, *, grouped: bool) -> None:
        slot.clear()
        items = history_items()
        active_id = str(_conversation(state.get("detail")).get("id") or "")
        with slot:
            if not items:
                ui.label("暂无匹配记录").classes("ln-empty w-full")
                return
            last_group = ""
            for item in items:
                if grouped:
                    group = _history_group_label(item.get("updated_at"))
                    if group != last_group:
                        ui.label(group).classes("ln-ai-history-group")
                        last_group = group
                conversation_id = str(item.get("id") or "")
                if not conversation_id:
                    continue
                classes = "ln-ai-history-item"
                if conversation_id == active_id:
                    classes += " ln-ai-history-item-active"
                with (
                    ui.row()
                    .classes("ln-ai-history-entry w-full items-center gap-1")
                    .props(
                        "tabindex=0 role=listitem aria-haspopup=menu "
                        "aria-label='对话历史项，右键或长按管理'"
                    )
                ) as entry:
                    if state.get("history_view") == "archived":
                        with ui.column().classes(f"{classes} min-w-0 grow items-start gap-0"):
                            ui.label(str(item.get("title") or "未命名对话")).classes(
                                "w-full truncate text-left text-sm font-bold"
                            )
                            ui.label("已在回收站 · 消息与上下文仍保存在本地").classes(
                                "text-left text-xs text-gray-500"
                            )
                    else:
                        with (
                            ui.button(
                                on_click=lambda conversation_id=conversation_id: open_history(
                                    conversation_id
                                )
                            )
                            .classes(f"{classes} min-w-0 grow")
                            .props(
                                "flat no-caps align=left"
                                + (" disable" if state.get("loading") else "")
                            )
                        ):
                            with ui.column().classes("min-w-0 items-start gap-0"):
                                ui.label(str(item.get("title") or "未命名对话")).classes(
                                    "w-full truncate text-left text-sm font-bold"
                                )
                                ui.label(
                                    {
                                        "PLANNING": "新建项目",
                                        "PROJECT_ASSISTANT": "项目协作",
                                        "PAGE_ASSISTANT": "页面问答",
                                    }.get(str(item.get("purpose") or ""), "AI 对话")
                                ).classes("text-xs text-gray-500")
                    menu = render_history_context_actions(item)
                bind_history_keyboard_menu(entry, menu)

    def render_fullscreen_history() -> None:
        with ui.element("aside").classes("ln-ai-history-rail"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.button("新对话", icon="edit_square", on_click=new_conversation).classes(
                    "min-w-0 grow"
                ).props(
                    "outline no-caps color=positive" + (" disable" if state.get("loading") else "")
                )
                ui.button(
                    icon="history" if state.get("history_view") == "archived" else "delete_outline",
                    on_click=lambda: set_history_view(
                        "active" if state.get("history_view") == "archived" else "archived"
                    ),
                ).props(
                    "flat round color=positive "
                    + (
                        "aria-label='返回对话历史'"
                        if state.get("history_view") == "archived"
                        else "aria-label='打开对话回收站'"
                    )
                ).tooltip("返回对话历史" if state.get("history_view") == "archived" else "回收站")

            with ui.row().classes("w-full gap-1"):
                for kind, label in (("chat", "对话"), ("project", "新建项目")):
                    selected = state.get("history_kind") == kind
                    ui.button(
                        label,
                        on_click=lambda kind=kind: set_history_kind(kind),
                    ).classes("min-w-0 grow").props(
                        ("unelevated" if selected else "flat") + " dense no-caps color=positive"
                    )

            if state.get("history_view") == "archived":
                ui.label("回收站中的对话可以恢复，也可以在确认标题后永久删除。").classes(
                    "text-xs leading-5 text-gray-500"
                )

            def search_changed(event: events.ValueChangeEventArguments[Any]) -> None:
                state["history_query"] = str(event.value or "")
                render_history_list(history_list_slot, grouped=True)

            ui.input(
                "搜索对话",
                value=str(state.get("history_query") or ""),
                on_change=search_changed,
            ).classes("w-full").props("outlined dense clearable aria-label='搜索对话历史'")
            history_list_slot = ui.column().classes("ln-ai-history-list min-h-0 w-full grow gap-1")
            render_history_list(history_list_slot, grouped=True)

    def render_plan_artifact(conversation: dict[str, Any]) -> None:
        final_plan = conversation.get("final_plan")
        working_plan = conversation.get("working_plan")
        plan = final_plan if isinstance(final_plan, dict) else working_plan
        if not isinstance(plan, dict):
            return
        with ui.element("article").classes("ln-plan-chat-card ln-ai-inline-plan"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon("account_tree").classes("text-xl text-green-700")
                ui.label("方案草稿").classes("font-black")
                ui.label("对话生成").classes("ln-ai-local-badge ml-auto")
            _render_plan_summary(plan, final=isinstance(final_plan, dict))
            goal_id = str(conversation.get("goal_id") or "")
            if goal_id:
                ui.link("打开已建立项目", f"/projects/{goal_id}/overview").classes(
                    "ln-action-button w-full justify-center no-underline"
                )
            elif isinstance(final_plan, dict):
                ui.button(
                    "确认并建立项目",
                    icon="check_circle",
                    on_click=activate_plan,
                ).classes("ln-action-button w-full").props(
                    "color=positive" + (" disable" if state.get("loading") else "")
                )
            else:
                ui.button(
                    "锁定当前方案",
                    icon="task_alt",
                    on_click=finalize_plan,
                ).classes("w-full").props(
                    "outline color=positive" + (" disable" if state.get("loading") else "")
                )
            ui.label("只有你确认后，方案才会成为正式项目。 ").classes("text-xs text-gray-500")

    def render_welcome() -> None:
        with ui.column().classes("ln-ai-welcome w-full gap-3 p-4"):
            ui.icon("forum").classes("text-2xl text-green-700")
            ui.label("开始一段对话").classes("font-black")
            ui.label(
                "描述想理解、学习或完成的事，也可以直接询问当前项目。"
                if context.goal_id
                else "描述想理解、学习或完成的事，也可以询问当前页面。"
            ).classes("text-sm text-gray-600")

    def render_attachment_card(
        attachment: dict[str, Any],
        *,
        staged: bool,
    ) -> None:
        attachment_id = str(attachment.get("id") or "")
        name = str(attachment.get("original_name") or "未命名附件")
        media_type = str(attachment.get("media_type") or "application/octet-stream")
        kind = str(attachment.get("kind") or "file")
        status = str(attachment.get("status") or "").upper()
        content_url = _attachment_browser_url(
            client,
            str(attachment.get("content_url") or ""),
        )
        with ui.row().classes("ln-ai-attachment-card w-full items-center gap-2"):
            if media_type.lower() in _SAFE_AI_PREVIEW_IMAGE_TYPES and content_url:
                ui.image(content_url).props("fit=cover loading=lazy").classes(
                    "ln-ai-attachment-thumbnail"
                )
            else:
                with ui.element("span").classes("ln-ai-attachment-file-icon"):
                    ui.icon(
                        "folder_zip" if kind == "archive" else "draft",
                        size="sm",
                    ).classes("text-green-700")
            with ui.column().classes("min-w-0 grow gap-0"):
                ui.label(name).classes("w-full truncate text-xs font-bold").tooltip(name)
                state_label = {
                    "INDEXED": "已提取内容",
                    "PARTIAL": "已提取部分内容",
                    "UNSUPPORTED": "原文件已保存",
                    "ERROR": "原文件已保存 · 解析失败",
                }.get(status, "已在本地保存")
                ui.label(
                    f"{_attachment_size_label(attachment.get('size_bytes'))} · {state_label}"
                ).classes("text-xs text-gray-500")
            if content_url:
                ui.link("查看", content_url, new_tab=True).classes(
                    "shrink-0 text-xs font-bold no-underline"
                )
            if staged and attachment_id:

                async def remove(item_id: str = attachment_id) -> None:
                    await remove_staged_attachment(item_id)

                ui.button(icon="close", on_click=remove).props(
                    "flat round dense color=negative aria-label='移除附件'"
                ).tooltip("移除附件")

    def render_message_attachments(item: dict[str, Any]) -> None:
        attachments = item.get("attachments")
        if not isinstance(attachments, list) or not attachments:
            return
        with ui.column().classes("ln-ai-message-attachments w-full gap-2"):
            for attachment in attachments:
                if isinstance(attachment, dict):
                    render_attachment_card(attachment, staged=False)

    def render_staged_attachments() -> None:
        staged = state.get("staged_attachments")
        if not isinstance(staged, list) or not staged:
            return
        with ui.column().classes("ln-ai-staged-attachments w-full gap-2"):
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label(f"待发送附件 · {len(staged)}").classes("text-xs font-black")
                ui.label("发送后会绑定到本轮对话").classes("text-xs text-gray-500")
            for attachment in staged:
                if isinstance(attachment, dict):
                    render_attachment_card(attachment, staged=True)

    def render_chat() -> None:
        detail = state.get("detail")
        conversation = _conversation(detail)
        messages = _conversation_messages(detail)
        with ui.column().classes("ln-ai-chat-pane min-h-0 min-w-0 grow gap-0"):
            with ui.column().classes("ln-ai-message-log min-h-0 w-full grow gap-3 p-4"):
                if messages:
                    proposal_decisions: dict[str, str] = {}
                    for candidate in messages:
                        structured = candidate.get("structured_content")
                        structured = structured if isinstance(structured, dict) else {}
                        reviewed_id = str(structured.get("proposal_tool_call_id") or "")
                        reviewed_status = str(structured.get("status") or "").upper()
                        if reviewed_id and reviewed_status in {
                            "SUCCEEDED",
                            "FAILED",
                            "REJECTED",
                        }:
                            proposal_decisions[reviewed_id] = reviewed_status
                    previous_user_content = ""
                    for item in messages:
                        if str(item.get("role") or "").upper() == "USER":
                            previous_user_content = str(item.get("content") or "").strip()
                        failure = _assistant_failure_view(item)
                        retry_callback = None
                        if (
                            failure is not None
                            and failure.get("retryable")
                            and previous_user_content
                            and not state.get("loading")
                            and not state.get("retry_pending")
                        ):

                            def retry_callback(content: str = previous_user_content) -> None:
                                retry_failed_message(content)

                        proposal = _tool_proposal_view(item)
                        proposal_decision = (
                            proposal_decisions.get(proposal["id"]) if proposal is not None else None
                        )
                        approve_callback = None
                        reject_callback = None
                        if (
                            proposal is not None
                            and proposal_decision is None
                            and not state.get("loading")
                        ):
                            proposal_id = proposal["id"]

                            async def approve(proposal_id: str = proposal_id) -> None:
                                await decide_tool_proposal(proposal_id, "approve")

                            async def reject(proposal_id: str = proposal_id) -> None:
                                await decide_tool_proposal(proposal_id, "reject")

                            approve_callback = approve
                            reject_callback = reject
                        _render_message(
                            item,
                            on_retry=retry_callback,
                            on_approve=approve_callback,
                            on_reject=reject_callback,
                            proposal_decision=proposal_decision,
                        )
                        render_message_attachments(item)
                    render_plan_artifact(conversation)
                elif state.get("loading"):
                    with ui.row().classes("w-full items-center justify-center gap-2 py-8"):
                        ui.spinner("dots", size="lg", color="positive")
                        loading_label = (
                            "正在创建项目讨论…"
                            if state.get("project_prompt_pending")
                            else "正在读取对话…"
                        )
                        ui.label(loading_label).classes("text-sm text-gray-500")
                else:
                    render_welcome()
                if state.get("error"):
                    ui.label(str(state["error"])).classes(
                        "ln-ai-inline-error w-full rounded-xl px-3 py-2 text-sm"
                    )
            with ui.column().classes("ln-ai-composer w-full gap-2 p-3"):
                render_staged_attachments()
                with ui.row().classes("ln-ai-quick-prompts w-full items-center gap-2"):
                    ui.button("新建项目", icon="account_tree", on_click=start_new_project).props(
                        "flat dense no-caps color=positive"
                        + (
                            " loading disable"
                            if state.get("project_prompt_pending")
                            else " disable"
                            if state.get("loading")
                            else ""
                        )
                    ).classes("ln-ai-project-prompt-button text-xs font-bold").tooltip(
                        "发送项目规划指令"
                    )
                    ui.button(
                        "依据附件生成路径",
                        icon="route",
                        on_click=generate_path_from_attachments,
                    ).props(
                        "flat dense no-caps color=positive"
                        + (
                            " loading disable"
                            if state.get("project_prompt_pending")
                            else " disable"
                            if state.get("loading") or not state.get("staged_attachments")
                            else ""
                        )
                    ).classes("ln-ai-project-prompt-button text-xs font-bold").tooltip(
                        "根据待发送附件生成新路径，或增量更新当前项目"
                    )
                    ui.upload(
                        multiple=True,
                        auto_upload=True,
                        on_begin_upload=begin_attachment_upload,
                        on_upload=collect_attachment,
                        on_multi_upload=finish_attachment_upload,
                        label="添加文件",
                    ).props("flat color=positive accept=*").classes("ln-ai-attachment-upload")
                    if state.get("attachment_uploading"):
                        with ui.row().classes("items-center gap-1 px-2"):
                            ui.spinner(size="sm", color="positive")
                            ui.label("正在保存…").classes("text-xs text-gray-500")
                ui.run_javascript(_AI_ATTACHMENT_PASTE_BOOTSTRAP)
                ui.label("支持多选、图片、文档和压缩包；也可直接 Ctrl+V 粘贴截图。 ").classes(
                    "ln-ai-attachment-hint text-xs text-gray-500"
                )
                with ui.row().classes("ln-ai-composer-row w-full items-end gap-2"):

                    def draft_changed(event: events.ValueChangeEventArguments[Any]) -> None:
                        state["message_draft"] = str(event.value or "")
                        persist_workspace()

                    state["message_input"] = (
                        ui.textarea(
                            "向 AI 提问",
                            value=str(state.get("message_draft") or ""),
                            placeholder="提问、解释，或要求调整当前方案…",
                            on_change=draft_changed,
                        )
                        .classes("ln-ai-composer-input min-w-0 grow")
                        .props("outlined autogrow maxlength=40000 rows=2 aria-label='向 AI 提问'")
                    )
                    ui.button("发送", icon="send", on_click=send).props(
                        "color=positive aria-label='发送给 AI'"
                        + (" loading disable" if state.get("loading") else "")
                    ).classes("ln-ai-send-button ln-action-button")
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    purpose = str(conversation.get("purpose") or context.purpose)
                    status_text = {
                        "PLANNING": "新建项目 · 方案只进入草稿",
                        "PROJECT_ASSISTANT": "项目协作 · 改动只进入草稿",
                        "PAGE_ASSISTANT": "页面问答",
                    }.get(purpose, "AI 对话")
                    ui.label(status_text).classes("text-xs text-gray-500")

    def render() -> None:
        render_history_header()
        body.clear()
        conversation = _conversation(state.get("detail"))
        context_label.set_text(
            _conversation_history_label(conversation)
            if conversation.get("id")
            else context.display_label
        )
        with body:
            with ui.row().classes("ln-ai-workspace min-h-0 w-full grow flex-nowrap gap-0"):
                if state.get("fullscreen"):
                    render_fullscreen_history()
                render_chat()

    async def initialize() -> None:
        cached_conversation_id = str(_conversation(state.get("detail")).get("id") or "")
        state["loading"] = not bool(cached_conversation_id)
        if state["loading"]:
            render()
        state["ai_status"] = await _get_ai_status(client)
        try:
            raw = await client.get(
                "/ai/conversations",
                params={"include_archived": True},
            )
            conversations = _conversation_items(raw)
            state["conversations"] = conversations
            stored_id = await _stored_active_conversation_id()
            stored = next(
                (
                    item
                    for item in conversations
                    if item.get("status") == "ACTIVE" and str(item.get("id") or "") == stored_id
                ),
                {},
            )
            preferred = next(
                (
                    item
                    for item in conversations
                    if item.get("status") == "ACTIVE" and matches_current_focus(item)
                ),
                {},
            )
            conversation_id = str((stored or preferred).get("id") or "")
            if stored_id and not stored:
                _persist_active_conversation_id(None)
            if conversation_id and not state.get("user_selected"):
                await refresh_detail(conversation_id)
                _persist_active_conversation_id(conversation_id)
        except UIAPIError as exc:
            state["error"] = f"无法读取对话记录：{exc}"
        finally:
            state["loading"] = False
            persist_workspace()
            render()

    handle = GlobalAssistantHandle(
        drawer=drawer,
        _start_chat=new_conversation,
        _start_new_project=start_new_project,
        _start_context_prompt=start_context_prompt,
        _toggle_fullscreen=toggle_fullscreen,
    )
    render()
    ui.timer(0.05, initialize, once=True)
    ui.timer(
        0.05,
        lambda: ui.run_javascript("window.LearningNavigatorAssistantLayout?.applyWidth()"),
        once=True,
    )
    return handle
