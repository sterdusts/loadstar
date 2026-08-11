"""Product contracts for the shared contextual AI assistant panel."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime

from learning_navigator.ui import app
from learning_navigator.ui.components import global_ai_assistant, layout
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.pages import home, onboarding, projects


def _window(source: str, marker: str, *, after: int = 420) -> str:
    index = source.index(marker)
    return source[index : index + after]


def test_page_and_project_conversation_scopes_are_stable_across_sections() -> None:
    page_overview = AssistantPageContext.page(
        page_key="activity",
        page_title="推进记录",
        section="overview",
    )
    page_detail = AssistantPageContext.page(
        page_key="activity",
        page_title="推进记录",
        section="detail",
    )
    project_overview = AssistantPageContext.project(
        goal_id="goal-1",
        space_id="space-1",
        page_title="系统数学",
        section="overview",
    )
    project_path = AssistantPageContext.project(
        goal_id="goal-1",
        space_id="space-1",
        page_title="系统数学",
        section="path",
        node_id="node-7",
        path_revision_id="revision-3",
    )

    assert page_overview.purpose == "PAGE_ASSISTANT"
    assert page_overview.context_key == page_detail.context_key == "page:activity"
    assert project_overview.purpose == "PROJECT_ASSISTANT"
    assert project_overview.context_key == project_path.context_key == "project:goal-1"
    assert page_overview.context_key != project_overview.context_key


def test_page_context_payload_is_explicit_bounded_and_whitelist_only() -> None:
    context = AssistantPageContext.project(
        goal_id="  goal-1  ",
        space_id="  space-1  ",
        page_title="  系统   数学  ",
        section="path",
        node_id="node-7",
        path_revision_id="revision-3",
    )

    assert context.to_payload() == {
        "page_key": "project",
        "page_kind": "PROJECT",
        "page_title": "系统 数学",
        "section": "path",
        "space_id": "space-1",
        "goal_id": "goal-1",
        "node_id": "node-7",
        "path_revision_id": "revision-3",
    }
    assert "context_key" not in context.to_payload()
    assert "purpose" not in context.to_payload()
    assert "form_values" not in context.to_payload()
    assert "dom" not in context.to_payload()

    bounded = AssistantPageContext.page(
        page_key="x" * 200,
        page_title="y" * 300,
        section="z" * 100,
    )
    assert len(bounded.page_key) == 120
    assert len(bounded.page_title) == 160
    assert len(str(bounded.section)) == 64


def test_page_context_payload_carries_a_bounded_project_route_snapshot() -> None:
    page_state = {
        "project_title": "建立系统数学体系并应用于 AI/量化",
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
    context = AssistantPageContext.project(
        goal_id="goal-math",
        space_id="space-math",
        page_title="项目",
        section="overview",
        node_id="node-functions",
        path_revision_id="path-active",
        page_state=page_state,
    )

    payload_state = context.to_payload()["page_state"]
    assert payload_state["project_title"] == page_state["project_title"]
    assert payload_state["current_node"] == page_state["current_node"]
    assert payload_state["path_summary"]["total"] == 13
    assert payload_state["path_summary"]["steps"][0] == page_state["path_summary"]["steps"][0]
    assert payload_state["path_summary"]["steps"][1] == {
        key: value
        for key, value in page_state["path_summary"]["steps"][1].items()
        if value is not None
    }
    assert payload_state["progress_summary"] == page_state["progress_summary"]

    untrusted = AssistantPageContext.project(
        goal_id="goal-math",
        space_id="space-math",
        page_title="项目",
        section="overview",
        page_state={
            **page_state,
            "dom": "<main>private browser content</main>",
            "form_values": {"api_key": "secret"},
            "tool_policy": {"enabled": True},
            "path_summary": {
                **page_state["path_summary"],
                "steps": [
                    {
                        "path_position": index + 1,
                        "node_id": f"node-{index}-" + "x" * 200,
                        "name": "节点" + "很长" * 200,
                        "status": "NOT_STARTED",
                    }
                    for index in range(80)
                ],
            },
        },
    ).to_payload()["page_state"]

    assert set(untrusted) == {
        "project_title",
        "current_node",
        "path_summary",
        "progress_summary",
    }
    assert len(untrusted["path_summary"]["steps"]) == 40
    assert all(len(step["node_id"]) <= 128 for step in untrusted["path_summary"]["steps"])
    assert all(len(step["name"]) <= 240 for step in untrusted["path_summary"]["steps"])
    assert "dom" not in untrusted
    assert "form_values" not in untrusted
    assert "tool_policy" not in untrusted


def test_page_shell_mounts_exactly_one_configured_shared_assistant() -> None:
    shell_source = inspect.getsource(layout.page_shell)
    app_source = inspect.getsource(app.mount_ui)

    assert shell_source.count("mount_global_ai_assistant(") == 1
    assert "assistant_enabled and _GLOBAL_AI_CLIENT is not None" in shell_source
    assert "assistant_context or AssistantPageContext.page(" in shell_source
    assert "configure_global_ai_assistant(client)" in app_source
    assert "on_click=assistant_handle.toggle" in shell_source


def test_assistant_drawer_is_responsive_theme_semantic_and_accessible() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    shell_source = inspect.getsource(layout.page_shell)
    css_source = inspect.getsource(layout.install_theme)

    assert "ui.right_drawer(value=None, fixed=True, bordered=True)" in panel_source
    assert "breakpoint=" in panel_source
    assert ".ln-ai-drawer" in css_source
    assert "background:var(--ln-surface)" in css_source
    assert "color:var(--ln-ink)" in css_source
    assert 'html[data-ln-theme="dark"]' in css_source
    assert "var(--ln-scrollbar-width,0px)" in css_source
    assert "env(safe-area-inset-bottom)" in css_source

    for marker in (
        'ui.button(icon="close"',
        'ui.button(icon="history")',
        'ui.button("发送"',
    ):
        assert "aria-label=" in _window(panel_source, marker)
    assert "ui.textarea(" in panel_source
    assert "aria-label='向 AI 提问'" in panel_source
    assert "aria-label=" in _window(shell_source, 'ui.button(\n                        "AI"')


def test_project_pages_pass_live_project_and_selection_context() -> None:
    source = inspect.getsource(projects._render_project_page)

    assert "assistant_context=AssistantPageContext.project(" in source
    assert "goal_id=project_id" in source
    assert 'space_id=str(project["space_id"])' in source
    assert "section=section" in source
    assert "node_id=node_id" in source
    assert "path_revision_id=" in source


def test_all_ai_entry_points_use_the_shared_assistant_instead_of_page_composers() -> None:
    onboarding_source = inspect.getsource(onboarding.register)
    project_source = inspect.getsource(projects._render_project_page)

    assert "render_new_project_collaboration" not in onboarding_source
    assert "render_project_collaboration" not in project_source
    assert "assistant_enabled=False" not in onboarding_source
    assert 'assistant_enabled=section != "collaboration"' not in project_source


def test_global_assistant_uses_one_history_without_history_driven_navigation() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert '"/ai/conversations"' in source
    assert 'params={"include_archived": True}' in source
    assert "_conversation_history_label(item)" in source
    assert 'f"/ai/conversations/{conversation_id}/messages"' in source
    assert "_scoped_page_context(" in source
    assert '"confirmed_external_ai": bool(is_external_provider())' in source
    assert "_conversation_focus_href" not in source
    assert "ui.navigate.to(" not in source


def test_fullscreen_history_groups_saved_conversations_by_recency() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    assert global_ai_assistant._history_group_label("2026-08-12T08:00:00+00:00", now=now) == (
        "今天"
    )
    assert global_ai_assistant._history_group_label("2026-08-11T08:00:00+00:00", now=now) == (
        "昨天"
    )
    assert global_ai_assistant._history_group_label("2026-08-06T08:00:00+00:00", now=now) == (
        "过去 7 天"
    )
    assert global_ai_assistant._history_group_label("2026-07-01T08:00:00+00:00", now=now) == (
        "更早"
    )


def test_scoped_page_context_uses_live_page_only_when_scope_matches() -> None:
    page_snapshot = {
        "page_key": "activity",
        "page_kind": "PAGE",
        "page_title": "动态",
    }
    page_conversation = {
        "purpose": "PAGE_ASSISTANT",
        "context_key": "page:activity",
        "context_snapshot": page_snapshot,
    }
    live_activity = {**page_snapshot, "section": "detail"}
    other_page = {"page_key": "home", "page_kind": "PAGE", "page_title": "导航"}

    assert global_ai_assistant._scoped_page_context(page_conversation, live_activity) is (
        live_activity
    )
    assert global_ai_assistant._scoped_page_context(page_conversation, other_page) is (
        page_snapshot
    )

    project_snapshot = {
        "page_key": "project",
        "page_kind": "PROJECT",
        "page_title": "系统数学",
        "space_id": "space-1",
        "goal_id": "goal-1",
    }
    project_conversation = {
        "purpose": "PROJECT_ASSISTANT",
        "space_id": "space-1",
        "goal_id": "goal-1",
        "context_snapshot": project_snapshot,
    }
    same_project = {**project_snapshot, "section": "map"}
    other_project = {**project_snapshot, "space_id": "space-2", "goal_id": "goal-2"}

    assert global_ai_assistant._scoped_page_context(project_conversation, same_project) is (
        same_project
    )
    assert global_ai_assistant._scoped_page_context(project_conversation, other_project) is (
        project_snapshot
    )


def test_scoped_page_context_falls_back_to_minimal_persisted_scope() -> None:
    planning = {
        "purpose": global_ai_assistant.MODE_NEW_PROJECT,
        "context_snapshot": {
            "page_key": "project",
            "space_id": "must-not-leak",
            "goal_id": "must-not-leak",
        },
    }
    planning_context = global_ai_assistant._scoped_page_context(
        planning,
        {
            "page_key": "project",
            "space_id": "space-current",
            "goal_id": "goal-current",
        },
    )
    assert planning_context == global_ai_assistant._planning_page_context()
    assert "space_id" not in planning_context
    assert "goal_id" not in planning_context

    project = {
        "purpose": "PROJECT_ASSISTANT",
        "title": "量化项目",
        "space_id": "space-1",
        "goal_id": "goal-1",
        "context_snapshot": {},
    }
    minimal = global_ai_assistant._scoped_page_context(
        project,
        {"page_key": "home", "page_kind": "PAGE", "page_title": "导航"},
    )
    assert minimal["space_id"] == "space-1"
    assert minimal["goal_id"] == "goal-1"
    assert minimal["page_kind"] == "PROJECT"


def test_global_assistant_continues_selected_history_without_replacing_its_id() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert "conversation_id and not matches_current_focus(conversation)" not in source
    assert 'conversation_id = str(await create(content) or "")' in source
    assert 'f"/ai/conversations/{conversation_id}/messages"' in source
    assert "_scoped_page_context(" in source
    assert "ui.navigate.to(" not in source


def test_next_page_and_project_overview_supply_visible_state_to_the_assistant() -> None:
    home_source = inspect.getsource(home.register)
    project_source = inspect.getsource(projects._render_project_page)
    home_state_source = inspect.getsource(home._build_home_assistant_page_state)
    project_state_source = inspect.getsource(projects._build_assistant_page_state)

    assert "assistant_context=AssistantPageContext.page(" in home_source
    assert "page_state=_build_home_assistant_page_state(" in home_source
    assert "assistant_context=AssistantPageContext.project(" in project_source
    assert "page_state=_build_assistant_page_state(" in project_source
    for marker in (
        '"project_title"',
        '"current_node"',
        '"path_summary"',
        '"progress_summary"',
    ):
        assert marker in home_state_source
        assert marker in project_state_source


def test_global_assistant_new_chat_is_local_until_the_first_message() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    new_chat_source = source[
        source.index("    def new_conversation()") : source.index("    def start_new_project()")
    ]

    assert 'state["detail"] = None' in new_chat_source
    assert 'client.post("/ai/conversations"' not in new_chat_source
    assert "await create(content)" in source


def test_active_conversation_pointer_is_persisted_and_cleared_in_place(monkeypatch) -> None:
    javascript_calls: list[str] = []
    monkeypatch.setattr(
        global_ai_assistant.ui,
        "run_javascript",
        lambda script: javascript_calls.append(script),
    )

    global_ai_assistant._persist_active_conversation_id("conversation-7")
    global_ai_assistant._persist_active_conversation_id(None)

    assert javascript_calls == [
        'window.localStorage.setItem("ln-ai-active-conversation-id", "conversation-7")',
        'window.localStorage.removeItem("ln-ai-active-conversation-id")',
    ]

    async def stored_value(script: str) -> str:
        assert script == ("window.localStorage.getItem(\"ln-ai-active-conversation-id\") || ''")
        return "conversation-7"

    monkeypatch.setattr(global_ai_assistant.ui, "run_javascript", stored_value)
    assert asyncio.run(global_ai_assistant._stored_active_conversation_id()) == "conversation-7"


def test_active_conversation_pointer_does_not_block_background_prompt_without_client(
    monkeypatch,
) -> None:
    def missing_client(_script: str) -> None:
        raise RuntimeError("no current NiceGUI client")

    monkeypatch.setattr(global_ai_assistant.ui, "run_javascript", missing_client)

    # Browser-local persistence is best effort. The durable conversation and
    # first message must continue even when a background task has no UI client.
    global_ai_assistant._persist_active_conversation_id("conversation-8")


def test_history_and_normal_new_chat_update_the_active_thread_pointer() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    load_source = source[
        source.index("    async def load(") : source.index("    def remember_detail()")
    ]
    create_source = source[
        source.index("    async def create(") : source.index("    def new_conversation()")
    ]
    new_chat_source = source[
        source.index("    def new_conversation()") : source.index("    def start_new_project()")
    ]
    open_history_source = source[
        source.index("    async def open_history(") : source.index(
            "    def render_compact_history()"
        )
    ]

    assert "await refresh_detail(conversation_id)" in load_source
    assert "_persist_active_conversation_id(conversation_id)" in load_source
    assert "_persist_active_conversation_id(conversation_id)" in create_source
    assert "await load(conversation_id)" in open_history_source
    assert "_persist_active_conversation_id(None)" in new_chat_source


def test_initialization_prefers_stored_thread_then_clears_invalid_pointer_and_falls_back() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    initialize_source = source[
        source.index("    async def initialize()") : source.index(
            "    handle = GlobalAssistantHandle("
        )
    ]

    assert "stored_id = await _stored_active_conversation_id()" in initialize_source
    assert 'str(item.get("id") or "") == stored_id' in initialize_source
    assert 'conversation_id = str((stored or preferred).get("id") or "")' in (initialize_source)
    assert "if stored_id and not stored:" in initialize_source
    invalid_pointer = initialize_source[
        initialize_source.index("if stored_id and not stored:") : initialize_source.index(
            "if conversation_id and not state.get"
        )
    ]
    assert "_persist_active_conversation_id(None)" in invalid_pointer
    assert "await refresh_detail(conversation_id)" in initialize_source
    assert "_persist_active_conversation_id(conversation_id)" in initialize_source


def test_assistant_handle_opens_chat_project_prompt_and_fullscreen_in_place() -> None:
    calls: list[str] = []

    class Drawer:
        def show(self) -> None:
            calls.append("show")

        def toggle(self) -> None:
            calls.append("toggle")

    handle = global_ai_assistant.GlobalAssistantHandle(
        drawer=Drawer(),
        _start_chat=lambda: calls.append("chat"),
        _start_new_project=lambda: calls.append("project"),
        _toggle_fullscreen=lambda: calls.append("fullscreen"),
    )

    handle.start_chat()
    handle.start_project()  # compatibility alias for the same prompt shortcut
    handle.start_new_project()
    handle.toggle_fullscreen()

    assert calls == [
        "chat",
        "show",
        "project",
        "show",
        "project",
        "show",
        "fullscreen",
        "show",
    ]


def test_normal_assistant_remains_the_primary_conversation_surface() -> None:
    page_context = AssistantPageContext.page(page_key="activity", page_title="动态")

    assert page_context.purpose == "PAGE_ASSISTANT"
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    assert '"向 AI 提问"' in source
    assert '"和 AI 讨论" if mode == MODE_NEW_PROJECT' not in source
    assert 'ui.button("新对话"' in source


def test_new_project_entry_points_use_the_shared_assistant_without_navigation() -> None:
    shell_source = inspect.getsource(layout.page_shell)
    mobile_source = inspect.getsource(layout._mobile_bottom_navigation)

    assert "start_new_project" in shell_source
    assert "start_new_project" in mobile_source
    assert "if href == CREATE_ACTION[1]" in mobile_source
    assert 'ui.link("", CREATE_ACTION[1])' not in shell_source
    assert 'ui.navigate.to("/projects/new")' not in shell_source
    assert 'ui.navigate.to("/projects/new")' not in mobile_source


def test_compact_and_fullscreen_surfaces_both_expose_normal_new_chat() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    header = source[
        source.index("    def render_history_header()") : source.index(
            "    def render_history_list("
        )
    ]
    fullscreen = source[
        source.index("    def render_fullscreen_history()") : source.index(
            "    def render_plan_artifact("
        )
    ]

    # A normal blank chat is a first-class action in both densities. It must not
    # disappear merely because project creation is also available as a shortcut.
    assert '"新对话"' in header
    assert "on_click=new_conversation" in header
    assert '"新对话"' in fullscreen
    assert "on_click=new_conversation" in fullscreen
    assert "aria-label='新对话'" in header


def test_new_project_is_a_prompt_shortcut_not_a_separate_chat_mode() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    shortcut = source[
        source.index("def start_new_project()") : source.index("def toggle_fullscreen()")
    ]

    assert "NEW_PROJECT_PROMPT" in shortcut
    assert "send" in shortcut
    assert 'state["detail"] = None' not in shortcut
    assert 'state["mode"] =' not in shortcut
    assert "_persist_active_conversation_id(None)" not in shortcut
    assert "_planning_page_context()" not in shortcut

    # The shortcut lives with the one composer; it is not a special welcome
    # screen, header mode, secondary dialog, or replacement chat surface.
    composer = source[source.index('with ui.column().classes("ln-ai-composer') :]
    assert 'ui.button("新建项目"' in composer
    assert "on_click=start_new_project" in composer
    welcome = source[
        source.index("    def render_welcome()") : source.index("    def render_chat()")
    ]
    assert "MODE_NEW_PROJECT" not in welcome
    assert "与 AI 共创新项目" not in welcome


def test_ai_composer_preserves_failed_draft_and_prevents_duplicate_project_prompts() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    send_source = source[
        source.index("    async def send_content(") : source.index("    async def finalize_plan()")
    ]
    shortcut = source[
        source.index("    def start_new_project()") : source.index("    def toggle_fullscreen()")
    ]
    composer = source[source.index('with ui.column().classes("ln-ai-composer') :]

    assert 'state["message_draft"] = content' in send_source
    assert 'state["message_draft"] = ""' in send_source
    assert "return sent" in send_source
    assert 'state["project_prompt_pending"] = True' in shortcut
    assert 'state.get("project_prompt_pending")' in shortcut
    assert 'value=str(state.get("message_draft") or "")' in composer
    assert "project_prompt_pending" in composer


def test_ai_history_selection_is_disabled_while_a_request_is_in_flight() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    load_source = source[
        source.index("    async def load(") : source.index("    def remember_detail()")
    ]
    new_chat_source = source[
        source.index("    def new_conversation()") : source.index("    def start_new_project()")
    ]
    history_source = source[
        source.index("    def render_compact_history()") : source.index(
            "    def render_plan_artifact("
        )
    ]

    assert 'if state.get("loading")' in load_source
    assert 'if state.get("loading")' in new_chat_source
    assert '" disable" if state.get("loading") else ""' in history_source


def test_ai_history_uses_recoverable_archive_then_confirmed_permanent_deletion() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    lifecycle = source[
        source.index("    async def refresh_history()") : source.index(
            "    def render_plan_artifact("
        )
    ]

    assert 'params={"include_archived": True}' in source
    assert 'f"/ai/conversations/{conversation_id}/archive"' in lifecycle
    assert 'f"/ai/conversations/{conversation_id}/restore"' in lifecycle
    assert 'f"/ai/conversations/{conversation_id}"' in lifecycle
    assert 'json={"expected_revision": _conversation_revision(item)}' in lifecycle
    assert '"confirm_title": title' in lifecycle
    assert "open_archive_confirmation" in lifecycle
    assert "open_permanent_delete_confirmation" in lifecycle
    assert "移到回收站" in lifecycle
    assert "完整消息、页面或项目上下文仍保存在本地" in lifecycle
    assert "之后可以从回收站恢复" in lifecycle
    assert "全部消息、页面或项目上下文、方案草稿和工具提案" in lifecycle
    assert "已经批准执行的修改不会撤销" in lifecycle
    assert "请输入完整对话标题确认永久删除" in lifecycle
    assert "aria-label='永久删除对话确认' role='alertdialog'" in lifecycle
    assert "aria-label='对话操作'" in lifecycle
    assert "aria-label='恢复对话'" in lifecycle
    assert "aria-label='回收站对话操作'" in lifecycle

    # Opening the conversation and lifecycle actions remain separate sibling controls.
    history = source[
        source.index("    def render_history_list(") : source.index(
            "    def render_fullscreen_history()"
        )
    ]
    assert "ln-ai-history-entry" in history
    assert "more_vert" in history
    assert "open_archive_confirmation(item)" in history
    archived_start = history.index('if state.get("history_view") == "archived":')
    active_start = history.index("\n                    else:", archived_start)
    assert "open_permanent_delete_confirmation" in history[archived_start:active_start]
    assert "open_permanent_delete_confirmation" not in history[active_start:]


def test_pending_ai_tool_changes_require_explicit_versioned_review() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    decision = source[
        source.index("    async def decide_tool_proposal(") : source.index(
            "    async def finalize_plan()"
        )
    ]

    assert (
        'f"/ai/conversations/{conversation_id}/tool-proposals/{proposal_id}/{action}"' in decision
    )
    assert 'json={"expected_revision": _conversation_revision(detail)}' in decision
    assert 'action not in {"approve", "reject"}' in decision
    assert "remember_detail()" in decision
    assert "window.location.reload()" in decision
    render_source = source[source.index("    def render_chat()") : source.index("    def render()")]
    assert 'structured.get("proposal_tool_call_id")' in render_source
    assert "proposal_decisions[reviewed_id] = reviewed_status" in render_source
    assert "proposal_decision is None" in render_source


def test_plan_draft_and_review_actions_are_inline_in_the_message_stream() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert "_render_plan_summary" in source
    assert "working_plan" in source
    assert "final_plan" in source
    assert "/finalize-plan" in source
    assert "/activate-plan" in source
    assert "ln-ai-inline-plan" in source
    assert source.index("_render_message(") < source.index("render_plan_artifact(conversation)")

    # The plan is a conversation item, not a second right-hand preview column.
    assert "ln-collaboration-plan" not in source
    assert "plan_panel" not in source


def test_assistant_can_resize_persist_width_and_expand_to_fullscreen_history_layout() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    css_source = inspect.getsource(layout.install_theme)
    bootstrap = layout._THEME_BOOTSTRAP

    for marker in (
        "ln-ai-resize-handle",
        "ln-ai-fullscreen",
        "ln-ai-history-rail",
    ):
        assert marker in panel_source or marker in css_source

    assert "ln-ai-drawer-width" in bootstrap
    assert "window.localStorage.getItem(assistantWidthKey)" in bootstrap
    assert "window.localStorage.setItem(assistantWidthKey, width)" in bootstrap
    assert "assistantMinWidth" in bootstrap
    assert "assistantMaxWidth" in bootstrap
    assert "clampAssistantWidth" in bootstrap
    assert "Math.min(" in bootstrap and "Math.max(" in bootstrap
    assert "window.LearningNavigatorAssistantLayout" in bootstrap
    assert "document.addEventListener('pointerdown'" in bootstrap
    assert "window.addEventListener('pointermove'" in bootstrap
    assert "window.innerWidth - event.clientX" in bootstrap
    assert "window.addEventListener('pointerup', finishAssistantResize" in bootstrap

    assert 'icon="fullscreen_exit"' in panel_source
    assert 'else "fullscreen"' in panel_source
    assert "aria-label='切换 AI 全屏'" in panel_source

    # Full screen follows the familiar chat layout: searchable, grouped history
    # stays on the left while the conversation remains the primary right pane.
    workspace = panel_source[panel_source.index('with ui.row().classes("ln-ai-workspace') :]
    assert workspace.index("render_fullscreen_history()") < workspace.index("render_chat()")
    assert 'with ui.element("aside").classes("ln-ai-history-rail")' in panel_source
    assert '"搜索对话"' in panel_source
    assert "render_history_list(history_list_slot, grouped=True)" in panel_source
    assert "ln-ai-history-item-active" in panel_source

    history_rail_css = css_source.split(".ln-ai-history-rail {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "border-right:1px solid var(--ln-line)" in history_rail_css
    assert "flex:0 0 280px" in history_rail_css
    fullscreen_chat_css = css_source.split(
        ".ln-ai-assistant-fullscreen .ln-ai-chat-pane {", maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "margin:0 auto" in fullscreen_chat_css
    assert "max-width:980px" in fullscreen_chat_css


def test_header_actions_are_grouped_and_do_not_compete_for_one_cramped_row() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    css_source = inspect.getsource(layout.install_theme)
    header = panel_source[
        panel_source.index('with ui.row().classes("ln-ai-panel-header') : panel_source.index(
            "            body = ui.column()"
        )
    ]
    actions = panel_source[
        panel_source.index("    def render_history_header()") : panel_source.index(
            "    def render_history_list("
        )
    ]

    assert "ln-ai-header-identity" in header
    assert "ln-ai-header-actions" in header
    assert "ln-ai-header-primary-action" in actions
    assert "ln-ai-header-icon-actions" in actions
    assert 'ui.button("新对话"' in actions
    assert 'ui.button(icon="history")' in actions
    assert 'icon="fullscreen_exit"' in actions
    assert 'ui.button(icon="close"' in actions
    assert ".ln-ai-header-actions" in css_source
    assert "flex-wrap:nowrap" in css_source


def test_one_composer_is_anchored_to_the_bottom_in_drawer_and_fullscreen() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    css_source = inspect.getsource(layout.install_theme)

    assert panel_source.count("ui.textarea(") == 1
    assert panel_source.count('classes("ln-ai-composer ') == 1
    chat = panel_source[
        panel_source.index("    def render_chat()") : panel_source.index("    def render()")
    ]
    assert chat.index("ln-ai-message-log") < chat.index("ln-ai-composer")

    chat_pane_css = css_source.split(".ln-ai-chat-pane {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    composer_css = css_source.split(".ln-ai-composer {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "display:flex" in chat_pane_css
    assert "flex-direction:column" in chat_pane_css
    assert "height:100%" in chat_pane_css
    assert "bottom:0" in composer_css
    assert "flex:0 0 auto" in composer_css
    assert "position:sticky" in composer_css
    assert "z-index:" in composer_css


def test_fullscreen_uses_chatgpt_style_history_chat_and_bottom_composer_shell() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    css_source = inspect.getsource(layout.install_theme)
    workspace = panel_source[panel_source.index('with ui.row().classes("ln-ai-workspace') :]

    assert workspace.index("render_fullscreen_history()") < workspace.index("render_chat()")
    assert 'with ui.element("aside").classes("ln-ai-history-rail")' in panel_source
    assert 'ui.button("新对话"' in panel_source
    assert '"搜索对话"' in panel_source
    assert "render_history_list(history_list_slot, grouped=True)" in panel_source
    assert "ln-ai-history-item-active" in panel_source
    assert "render_chat()" in workspace

    fullscreen_css = css_source.split(".ln-ai-assistant-fullscreen .ln-ai-chat-pane {", maxsplit=1)[
        1
    ].split("}", maxsplit=1)[0]
    composer_css = css_source.split(".ln-ai-composer {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "margin:0 auto" in fullscreen_css
    assert "max-width:" in fullscreen_css
    assert "position:sticky" in composer_css
    assert "bottom:0" in composer_css


def test_global_assistant_drawer_stays_above_mobile_backdrop() -> None:
    source = inspect.getsource(layout.install_theme)

    drawer_block = source.split(".q-drawer:has(> .ln-ai-drawer),", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "z-index:3200!important" in drawer_block


def test_legacy_project_collaboration_url_only_opens_shared_assistant() -> None:
    source = inspect.getsource(projects.register)
    marker = '@ui.page("/projects/{project_id}/collaboration")'
    handler = source[source.index(marker) : source.index('@ui.page("/projects/{project_id}/path")')]

    assert 'ui.navigate.to(project_href(project_id, "overview") + "?ai=open")' in handler
    assert "render_project_collaboration" not in handler


def test_global_assistant_has_one_inline_consent_free_composer() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert "external_confirm" not in source
    assert "ui.checkbox(" not in source
    assert "发送前请确认外部 AI 数据授权" not in source
    assert '"confirmed_external_ai": bool(is_external_provider())' in source

    composer = source[source.index('with ui.row().classes("ln-ai-composer-row') :]
    assert "ui.textarea(" in composer
    assert '"向 AI 提问"' in composer
    assert 'ui.button("发送", icon="send", on_click=send)' in composer
