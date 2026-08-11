"""Product contracts for the shared contextual AI assistant panel."""

from __future__ import annotations

import inspect

from learning_navigator.ui import app
from learning_navigator.ui.components import ai_collaboration, global_ai_assistant, layout
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
    assert "width=400 breakpoint=1320" in panel_source
    assert ".ln-ai-drawer" in css_source
    assert "background:var(--ln-surface)" in css_source
    assert "color:var(--ln-ink)" in css_source
    assert 'html[data-ln-theme="dark"]' in css_source
    assert "var(--ln-scrollbar-width,0px)" in css_source
    assert "env(safe-area-inset-bottom)" in css_source

    for marker in (
        'ui.button(icon="close"',
        'ui.button(icon="history")',
        'ui.button(icon="add_comment"',
        "ui.textarea(",
        'ui.button("发送"',
    ):
        assert "aria-label=" in _window(panel_source, marker)
    assert "aria-label=" in _window(shell_source, 'ui.button(\n                        "AI"')


def test_project_pages_pass_live_project_and_selection_context() -> None:
    source = inspect.getsource(projects._render_project_page)

    assert "assistant_context=AssistantPageContext.project(" in source
    assert "goal_id=project_id" in source
    assert 'space_id=str(project["space_id"])' in source
    assert "section=section" in source
    assert "node_id=node_id" in source
    assert "path_revision_id=" in source


def test_full_page_composers_disable_the_shared_drawer_to_avoid_duplicates() -> None:
    onboarding_source = inspect.getsource(onboarding.register)
    project_source = inspect.getsource(projects._render_project_page)

    assert "assistant_enabled=False" in onboarding_source
    assert 'assistant_enabled=section != "collaboration"' in project_source
    assert "await render_new_project_collaboration(" in onboarding_source
    assert "await render_project_collaboration(" in project_source


def test_global_assistant_uses_one_history_with_focus_specific_creation() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert 'return "PLANNING", context.context_key' in source
    assert 'return "PROJECT_ASSISTANT", context.context_key' in source
    assert '"context_snapshot": context.to_payload()' in source
    assert 'await client.get("/ai/conversations")' in source
    assert "matches_current_focus(item)" in source
    assert "_conversation_history_label(item)" in source
    assert "_conversation_focus_href(conversation)" in source
    assert "ui.navigate.to(target)" in source
    assert 'f"/ai/conversations/{conversation_id}/messages"' in source
    assert '"page_context": page_context_for(conversation)' in source
    assert '"confirmed_external_ai": bool(external)' in source


def test_global_assistant_always_sends_the_live_page_not_an_old_conversation_snapshot() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    page_context_source = source[
        source.index("    def page_context_for(") : source.index("    def matches_current_focus(")
    ]

    assert "return context.to_payload()" in page_context_source
    assert "context_snapshot" not in page_context_source


def test_global_assistant_does_not_send_a_history_item_through_the_wrong_scope() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    send_source = source[
        source.index("    async def send()") : source.index("    def render_history()")
    ]
    history_source = source[
        source.index("    def render_history()") : source.index("    def render()")
    ]

    assert "conversation_id and not matches_current_focus(conversation)" in send_source
    assert 'state["detail"] = None' in send_source
    assert 'conversation_id = str(await create() or "")' in send_source
    assert "if matches_current_focus(item):" in history_source
    assert "target = _conversation_focus_href(item)" in history_source
    assert "ui.navigate.to(target)" in history_source


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
        source.index("    def new_conversation()") : source.index("    async def send()")
    ]
    send_source = source[
        source.index("    async def send()") : source.index("    def render_history()")
    ]

    assert 'state["detail"] = None' in new_chat_source
    assert "await create(" not in new_chat_source
    assert "await create()" in send_source


def test_global_assistant_drawer_stays_above_mobile_backdrop() -> None:
    source = inspect.getsource(layout.install_theme)

    assert ".q-drawer:has(> .ln-ai-drawer) { z-index:3200!important; }" in source


def test_full_project_collaboration_uses_the_same_project_assistant_scope() -> None:
    source = inspect.getsource(ai_collaboration.render_project_collaboration)

    assert source.count('"purpose": "PROJECT_ASSISTANT"') >= 2
    assert source.count('"context_key": f"project:{project_id}"') >= 2
    assert '"context_snapshot": {' in source
    assert '"page_context": {' in source


def test_global_assistant_has_one_inline_consent_free_composer() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    send_source = source[
        source.index("    async def send()") : source.index("    def render_history()")
    ]
    render_source = source[
        source.index("    def render()") : source.index("    async def initialize()")
    ]

    assert "external_confirm" not in source
    assert "ui.checkbox(" not in render_source
    assert "发送前请确认外部 AI 数据授权" not in send_source
    assert '"confirmed_external_ai": bool(external)' in send_source

    composer = render_source[render_source.index('with ui.row().classes("ln-ai-composer-row') :]
    assert "ui.textarea(" in composer
    assert '"向 AI 提问"' in composer
    assert 'ui.button("发送", icon="send", on_click=send)' in composer
