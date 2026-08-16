"""Cross-page product contracts for the learner-facing UI system."""

from __future__ import annotations

import ast
import inspect
from types import ModuleType

import pytest

from learning_navigator.ui.components import global_ai_assistant, layout
from learning_navigator.ui.pages import (
    ai_review,
    current_map,
    growth,
    home,
    node_detail,
    onboarding,
    projects,
    records,
    spaces,
    workbench,
)
from learning_navigator.ui.view_models import intent_profile

LEARNER_PAGES = (home, current_map, node_detail, workbench, growth, projects)


def _source(module: ModuleType) -> str:
    return inspect.getsource(module)


def _window(source: str, marker: str, *, before: int = 80, after: int = 520) -> str:
    index = source.index(marker)
    return source[max(0, index - before) : index + after]


def _string_literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_string_literals(node.left), *_string_literals(node.right)]
    return []


def _learner_facing_literals(module: ModuleType) -> list[str]:
    """Collect only text passed to learner-facing UI calls, not internal payload keys."""

    methods = {
        "button",
        "checkbox",
        "expansion",
        "input",
        "label",
        "link",
        "menu_item",
        "notify",
        "select",
        "tab",
        "textarea",
        "tooltip",
    }
    texts: list[str] = []
    tree = ast.parse(_source(module))
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        function = call.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr in methods
            and (
                (isinstance(function.value, ast.Name) and function.value.id == "ui")
                or isinstance(function.value, ast.Call)
            )
        ):
            continue
        for argument in call.args:
            texts.extend(_string_literals(argument))
        for keyword in call.keywords:
            if keyword.arg in {"label", "placeholder"}:
                texts.extend(_string_literals(keyword.value))
    return texts


def test_primary_navigation_is_small_consistent_and_shared_by_every_page() -> None:
    assert layout.PRIMARY_NAV == (
        ("导航", "/", "explore"),
        ("项目", "/projects", "view_quilt"),
        ("动态", "/activity", "timeline"),
    )
    for module in LEARNER_PAGES:
        source = _source(module)
        assert "page_shell(" in source
        assert "ui.header(" not in source
    assert 'ui.navigate.to("/?ai=new-project")' in _source(onboarding)


def test_navigation_supports_keyboard_named_controls_without_legacy_advanced_menu() -> None:
    source = _source(layout)

    assert "aria-label='主导航'" in source
    assert "aria-label='高级功能'" not in source
    assert all(label not in source for label in ("框架库", "AI 审核中心", "数据与记录"))
    assert "aria-label='更多设置'" in source
    assert "aria-label='AI 与数据设置'" in source
    assert ".ln-mobile-nav { display:none!important; }" in source
    assert "@media (max-width: 767px)" in source
    assert ".ln-mobile-nav { display:inline-flex!important; }" in source
    assert ".ln-action-button { min-height:46px" in source


def test_retired_advanced_pages_redirect_into_the_canonical_product_flow() -> None:
    assert 'ui.navigate.to("/projects")' in _source(spaces)
    assert 'ui.navigate.to("/projects")' in _source(ai_review)
    assert 'ui.navigate.to("/activity")' in _source(records)
    for module in (spaces, ai_review, records):
        source = _source(module)
        assert "page_shell(" not in source
        assert "client.get(" not in source
        assert "client.post(" not in source


@pytest.mark.parametrize(
    ("module", "marker"),
    [
        (home, 'primary["action_label"]'),
        (current_map, 'mode_copy["action_labels"].get'),
        (node_detail, "primary_label,"),
        (projects, 'copy["finish_action"]'),
        (global_ai_assistant, '"发送"'),
        (growth, 'intent_action_label("AVAILABLE"'),
    ],
)
def test_each_core_page_gives_its_main_action_consistent_visual_priority(
    module: ModuleType,
    marker: str,
) -> None:
    action_source = _window(_source(module), marker, after=800)

    assert "ln-action-button" in action_source
    assert "color=positive" in action_source or "color=white" in action_source


def test_secondary_node_actions_do_not_compete_with_start_progress() -> None:
    source = _source(node_detail)

    update_window = _window(source, 'mode_copy["update_state"]')
    assert "outline color=positive" in update_window
    assert "ln-action-button" not in update_window


def test_growth_metrics_stack_on_small_screens() -> None:
    assert "grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" in _source(growth)


def test_detail_and_project_workspace_use_one_mobile_safe_layout() -> None:
    detail_source = _source(node_detail)
    workbench_source = _source(workbench)
    project_source = _source(projects)

    assert "max-sm:flex-col" in detail_source
    assert "grid-cols-1 gap-4 md:grid-cols-2" in detail_source
    assert "ui.grid(columns=" not in detail_source
    assert "focus_mode" not in workbench_source
    assert "ln-project-workspace-has-inspector" in project_source
    assert "/projects/{project_id}/overview" in project_source


def test_goal_creation_and_switching_hide_secondary_complexity() -> None:
    assistant_source = _source(global_ai_assistant)
    assert '"/ai/conversations"' in assistant_source
    assert 'params={"include_archived": True}' in assistant_source
    assert "pre_project_only" not in assistant_source
    assert "goal_input" not in assistant_source
    assert "requirements_input" not in assistant_source
    assert "ln-goal-switcher" in _source(home)


def test_goal_creation_is_general_and_conversation_first() -> None:
    source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)

    assert "描述想理解、学习或完成的事" in source
    assert 'ui.button("开始讨论"' not in source
    assert '"/ai/conversations"' in source
    assert 'f"/ai/conversations/{conversation_id}/messages"' in source
    assert "/finalize-plan" in source
    assert "/activate-plan" in source
    assert "ln-ai-inline-plan" in source


def test_detail_project_workspace_and_growth_use_intent_aware_progress_language() -> None:
    assert 'mode_copy["detail_title"]' in _source(node_detail)
    assert 'mode_copy["state_heading"]' in _source(node_detail)
    assert 'copy["workbench_result"]' in _source(projects)
    assert 'copy["finish_action"]' in _source(projects)
    assert '"进展"' in _source(growth)
    assert 'mode_copy["timeline"]' in _source(growth)
    assert intent_profile("LEARN")["workbench_title"] == "专注学习"
    assert intent_profile("UNDERSTAND")["workbench_title"] == "专注探索"
    assert intent_profile("DO")["workbench_title"] == "专注执行"


def test_icon_only_assessment_close_control_has_an_accessible_name() -> None:
    close_control = _window(
        _source(node_detail),
        'ui.button(icon="close"',
        before=0,
        after=240,
    )
    assert "aria-label='关闭评估'" in close_control


def test_workbench_self_rating_control_has_an_accessible_name() -> None:
    project_source = _source(projects)
    if "self_rating = ui.slider" in project_source:
        self_rating_control = _window(
            project_source,
            "self_rating = ui.slider",
            before=0,
            after=260,
        )
        assert "label-always" in self_rating_control


def test_next_step_stays_inside_the_project_workspace_and_saves_progress() -> None:
    actions = home._build_today_actions(
        [
            {
                "goal_id": "goal-1",
                "goal_title": "掌握函数",
                "space_id": "space-1",
                "map_href": "/maps/space-1",
                "next_step": {
                    "node_id": "node-functions",
                    "title": "函数图像",
                    "status": "AVAILABLE",
                    "reason": "这是进入导数前的下一步。",
                },
            }
        ]
    )

    assert actions[0]["action_href"] == (
        "/projects/goal-1/overview?node=node-functions&panel=action"
    )

    project_source = _source(projects)
    assert '"/learning-sessions"' in project_source
    assert 'project_href(project_id, "overview", node_id=node_id)' in project_source
    assert 'project_href(project_id, "progress", node_id=node_id)' not in project_source
    assert "focus_mode" not in project_source


def test_workbench_resolves_mode_from_the_goal_that_owns_the_node() -> None:
    dashboard = {
        "goal_overviews": [
            {
                "goal": {
                    "space_id": "space-learn",
                    "intent_mode": "LEARN",
                },
                "route_overview": [{"node_id": "lesson"}],
            },
            {
                "goal": {
                    "space_id": "space-do",
                    "intent_mode": "DO",
                },
                "route_overview": [{"node_id": "deliver"}],
            },
        ]
    }

    assert (
        workbench._intent_mode_for_node(
            dashboard,
            node_id="deliver",
            space_id="space-do",
        )
        == "DO"
    )
    assert workbench._intent_mode_for_node({}, node_id="legacy", space_id="legacy-space") == "LEARN"


def test_growth_uses_specific_copy_only_for_one_consistent_goal_mode() -> None:
    one_mode = {
        "goal_overviews": [
            {"goal": {"intent_mode": "UNDERSTAND"}},
            {"goal": {"intent_mode": "UNDERSTAND"}},
        ]
    }
    mixed = {
        "goal_overviews": [
            {"goal": {"intent_mode": "LEARN"}},
            {"goal": {"intent_mode": "DO"}},
        ]
    }

    assert growth._consensus_intent_mode(one_mode) == "UNDERSTAND"
    assert growth._consensus_intent_mode(mixed) is None
    assert growth._growth_copy("UNDERSTAND")["timeline"] == "探索记录时间线"
    assert growth._growth_copy(None)["timeline"] == "推进时间线"
    assert growth._growth_copy(None)["progress"] == "整体进度"
    assert growth._growth_copy(None)["coverage_trend"] == "整体进度"
    assert growth._growth_copy(None)["activity"] == "累计活跃天数"
    assert growth._growth_copy("LEARN")["progress"] == "学习进度"
    assert growth._growth_copy("LEARN")["coverage_trend"] == "学习进度"


def test_growth_metrics_explain_score_and_every_source_of_invested_time() -> None:
    assert growth._time_record_label(sessions=0, check_ins=2) == "2 次打卡"
    assert growth._time_record_label(sessions=1, check_ins=2) == "1 次学习会话 · 2 次打卡"
    assert growth._time_record_label(sessions=0, check_ins=0) == "暂无投入记录"


@pytest.mark.parametrize("module", LEARNER_PAGES)
def test_learner_facing_text_does_not_expose_internal_schema_terms(module: ModuleType) -> None:
    visible_text = "\n".join(_learner_facing_literals(module))

    for internal_term in (
        "CONCEPT",
        "CONTAINS",
        "PREREQUISITE",
        "SELF_REPORT",
        "depth_level",
        "evidence_confidence",
        "mastery_level",
        "node_type",
        "prompt_version",
        "provider",
        "suggestion_id",
    ):
        assert internal_term not in visible_text
