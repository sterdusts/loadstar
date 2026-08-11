"""Pure product contracts for parallel learning goals on Today's Navigation."""

from __future__ import annotations

import inspect
from typing import Any

from learning_navigator.ui.pages.home import (
    _action_goal_context,
    _build_today_actions,
    _split_goal_filters,
    _study_action_label,
    register,
)
from learning_navigator.ui.view_models import (
    build_parallel_dashboard_view_model,
    intent_profile,
    intent_progress_label,
    intent_status_label,
    normalize_intent_mode,
)


def _custom_semantic_profile() -> dict[str, Any]:
    return {
        "template_id": "LEARN_PRACTICE_V1",
        "node_label": "能力单元",
        "module_label": "能力模块",
        "route_label": "掌握路线",
        "record_label": "训练记录",
        "evidence_label": "能力证明",
        "status_labels": {
            "AVAILABLE": "可以学习",
            "BLOCKED": "前置知识未掌握",
            "MASTERED": "已学会",
            "IN_PROGRESS": "正在学习",
            "NEEDS_REVIEW": "待复习",
            "NOT_RELEVANT": "暂不学习",
        },
        "action_labels": {
            "AVAILABLE": "开始学习",
            "IN_PROGRESS": "继续学习",
            "NEEDS_REVIEW": "复习巩固",
        },
        "dimension_labels": {
            "concept_understanding": "原理理解",
            "procedural_skill": "实操能力",
            "application_skill": "独立应用",
            "memory_strength": "长期保持",
        },
        "progress_levels": [
            {"min_score": 0, "label": "未开始"},
            {"min_score": 20, "label": "初步接触"},
            {"min_score": 45, "label": "正在理解"},
            {"min_score": 70, "label": "能够应用"},
            {"min_score": 90, "label": "已经掌握"},
        ],
    }


def _route_item(
    node_id: str,
    title: str,
    status: str,
    *,
    unlocks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "title": title,
        "status": status,
        "reason": f"按当前目标安排学习：{title}",
        "unmet_prerequisites": [],
        "unlocks": unlocks or [],
    }


def _goal_overview(
    *,
    goal_id: str,
    goal_title: str,
    space_id: str,
    route: list[dict[str, Any]],
    next_node_id: str | None,
) -> dict[str, Any]:
    next_step = next((item for item in route if item["node_id"] == next_node_id), None)
    return {
        "goal": {
            "id": goal_id,
            "title": goal_title,
            "space_id": space_id,
            "target_node_id": route[-1]["node_id"] if route else None,
        },
        "current_position": next_step,
        "next_step": next_step,
        "blocked": [item for item in route if item["status"] == "BLOCKED"],
        "route_overview": route,
    }


def _parallel_payload() -> dict[str, Any]:
    python_route = [
        _route_item("python-basics", "Python 基础", "MASTERED", unlocks=["python-functions"]),
        _route_item("python-functions", "函数与模块", "IN_PROGRESS", unlocks=["python-project"]),
        _route_item("python-project", "自动化项目", "BLOCKED"),
    ]
    drawing_route = [
        _route_item("drawing-lines", "线条练习", "MASTERED", unlocks=["drawing-perspective"]),
        _route_item("drawing-perspective", "透视基础", "AVAILABLE"),
    ]
    python = _goal_overview(
        goal_id="goal-python",
        goal_title="用 Python 完成自动化项目",
        space_id="space-python",
        route=python_route,
        next_node_id="python-functions",
    )
    drawing = _goal_overview(
        goal_id="goal-drawing",
        goal_title="掌握角色插画基础",
        space_id="space-drawing",
        route=drawing_route,
        next_node_id="drawing-perspective",
    )
    return {
        # The legacy projection remains for old clients; the parallel model must
        # not mistake it for the only active learning goal.
        "current_goal": python["goal"],
        "current_position": python["current_position"],
        "next_step": python["next_step"],
        "blocked": python["blocked"],
        "route_overview": python["route_overview"],
        "goal_overviews": [python, drawing],
        "recent_sessions": [{"id": "session-1", "node_id": "python-functions"}],
    }


def test_parallel_dashboard_keeps_every_active_goal_and_its_own_navigation() -> None:
    view = build_parallel_dashboard_view_model(_parallel_payload())

    assert view["has_goals"] is True
    assert [goal["goal_id"] for goal in view["goals"]] == ["goal-python", "goal-drawing"]

    python, drawing = view["goals"]
    assert python["next_step"]["title"] == "函数与模块"
    assert python["progress_percent"] == 33
    assert python["completed_count"] == 1
    assert python["total_count"] == 3
    assert python["map_href"] == "/maps/space-python"

    assert drawing["next_step"]["title"] == "透视基础"
    assert drawing["progress_percent"] == 50
    assert drawing["completed_count"] == 1
    assert drawing["total_count"] == 2
    assert drawing["map_href"] == "/maps/space-drawing"


def test_parallel_dashboard_expands_only_one_focus_goal_by_default() -> None:
    view = build_parallel_dashboard_view_model(_parallel_payload())

    assert view["focused_goal_id"] == "goal-python"
    assert [goal["goal_id"] for goal in view["goals"] if goal["is_focused"]] == ["goal-python"]


def test_switching_focus_preserves_every_goal_route_and_map_entry() -> None:
    default_view = build_parallel_dashboard_view_model(_parallel_payload())
    switched_view = build_parallel_dashboard_view_model(
        _parallel_payload(), focused_goal_id="goal-drawing"
    )

    assert switched_view["focused_goal_id"] == "goal-drawing"
    assert [goal["goal_id"] for goal in switched_view["goals"] if goal["is_focused"]] == [
        "goal-drawing"
    ]
    assert [goal["goal_id"] for goal in switched_view["goals"]] == [
        "goal-python",
        "goal-drawing",
    ]
    assert [goal["route"] for goal in switched_view["goals"]] == [
        goal["route"] for goal in default_view["goals"]
    ]
    assert [goal["map_href"] for goal in switched_view["goals"]] == [
        "/maps/space-python",
        "/maps/space-drawing",
    ]


def test_parallel_dashboard_preserves_zero_goal_onboarding_state() -> None:
    view = build_parallel_dashboard_view_model(
        {
            "current_goal": None,
            "current_position": None,
            "next_step": None,
            "blocked": [],
            "route_overview": [],
            "goal_overviews": [],
            "recent_sessions": [],
        }
    )

    assert view == {
        "has_goals": False,
        "goals": [],
        "focused_goal_id": None,
        "recent_sessions": [],
    }


def test_parallel_dashboard_wraps_legacy_single_goal_payload() -> None:
    legacy = _parallel_payload()
    legacy.pop("goal_overviews")

    view = build_parallel_dashboard_view_model(legacy)

    assert view["has_goals"] is True
    assert view["focused_goal_id"] == "goal-python"
    assert len(view["goals"]) == 1
    assert view["goals"][0]["goal_id"] == "goal-python"
    assert view["goals"][0]["next_step"]["title"] == "函数与模块"
    assert view["goals"][0]["map_href"] == "/maps/space-python"
    assert view["goals"][0]["intent_mode"] == "LEARN"
    assert view["goals"][0]["next_step"]["status_label"] == "学习中"


def test_parallel_dashboard_preserves_valid_mode_and_defaults_invalid_mode_to_learning() -> None:
    payload = _parallel_payload()
    payload["goal_overviews"][0]["goal"]["intent_mode"] = "UNDERSTAND"
    payload["goal_overviews"][1]["goal"]["intent_mode"] = "unexpected"

    view = build_parallel_dashboard_view_model(payload)

    first, second = view["goals"]
    assert first["intent_mode"] == "UNDERSTAND"
    assert first["next_step"]["status_label"] == "理解中"
    assert second["intent_mode"] == "LEARN"
    assert second["next_step"]["status_label"] == "现在可学"


def test_today_actions_take_one_candidate_per_goal_and_prioritize_review() -> None:
    payload = _parallel_payload()
    drawing = payload["goal_overviews"][1]
    drawing["next_step"]["status"] = "NEEDS_REVIEW"
    drawing["current_position"]["status"] = "NEEDS_REVIEW"
    view = build_parallel_dashboard_view_model(payload)

    actions = _build_today_actions(view["goals"])

    assert [item["title"] for item in actions] == ["透视基础", "函数与模块"]
    assert actions[0]["action_label"] == "开始复习"
    assert [item["goal_refs"][0]["goal_id"] for item in actions] == [
        "goal-drawing",
        "goal-python",
    ]


def test_shared_node_is_one_action_that_advances_multiple_goals() -> None:
    goals = [
        {
            "goal_id": "goal-a",
            "goal_title": "目标 A",
            "space_id": "space-shared",
            "map_href": "/maps/space-shared",
            "next_step": _route_item("shared-node", "共享基础", "AVAILABLE"),
        },
        {
            "goal_id": "goal-b",
            "goal_title": "目标 B",
            "space_id": "space-shared",
            "map_href": "/maps/space-shared",
            "next_step": _route_item("shared-node", "共享基础", "AVAILABLE"),
        },
    ]

    actions = _build_today_actions(goals)

    assert len(actions) == 1
    assert [item["goal_id"] for item in actions[0]["goal_refs"]] == ["goal-a", "goal-b"]


def test_same_title_nodes_keep_distinct_project_scoped_actions() -> None:
    """Display-title collisions must not resurrect or merge another project."""

    goals = [
        {
            "goal_id": "goal-deleted-lookalike",
            "goal_title": "数学基础项目",
            "space_id": "space-a",
            "map_href": "/maps/space-a",
            "next_step": _route_item("node-a", "实数与代数式", "AVAILABLE"),
        },
        {
            "goal_id": "goal-retained",
            "goal_title": "量化数学项目",
            "space_id": "space-b",
            "map_href": "/maps/space-b",
            "next_step": _route_item("node-b", "实数与代数式", "AVAILABLE"),
        },
    ]

    actions = _build_today_actions(goals)

    assert len(actions) == 2
    assert {item["node_id"] for item in actions} == {"node-a", "node-b"}
    by_goal = {item["goal_refs"][0]["goal_id"]: item for item in actions}
    retained = by_goal["goal-retained"]
    assert retained["action_href"] == ("/projects/goal-retained/overview?node=node-b&panel=action")
    assert retained["node_href"] == "/projects/goal-retained/map?node=node-b"
    assert _action_goal_context(retained["goal_refs"]) == "所属项目 · 量化数学项目"


def test_today_page_limits_actions_and_keeps_full_routes_in_maps() -> None:
    source = inspect.getsource(register)

    assert "actions[1:3]" in source
    assert "其他可推进项" in source
    assert "目标概览" not in source
    assert "查看完整成长记录" not in source
    assert "render_route_strip" not in source


def test_goal_filters_show_at_most_three_and_keep_selected_goal_visible() -> None:
    goals = [{"goal_id": f"goal-{index}", "goal_title": f"目标 {index}"} for index in range(5)]

    visible, overflow = _split_goal_filters(goals, "goal-4")

    assert [item["goal_id"] for item in visible] == ["goal-0", "goal-1", "goal-4"]
    assert [item["goal_id"] for item in overflow] == ["goal-2", "goal-3"]


def test_today_page_uses_one_primary_action_and_linked_knowledge_titles() -> None:
    source = inspect.getsource(register)

    assert 'ui.link(primary["title"], primary["node_href"])' in source
    assert 'ui.button(\n                            "查看知识点"' not in source
    assert _action_goal_context([{"goal_title": "A"}, {"goal_title": "B"}]) == (
        "所属项目 · 2 个 · A · B"
    )


def test_next_action_page_keeps_general_shell_and_learning_first_legacy_copy() -> None:
    source = inspect.getsource(register)

    assert '"下一步"' in source
    assert _study_action_label("AVAILABLE") == "开始学习"
    assert "知识地图" not in source
    assert "学习导航" not in source


def test_today_actions_adapt_to_each_goal_intent_mode() -> None:
    goals = [
        {
            "goal_id": "goal-learn",
            "goal_title": "学习概率",
            "space_id": "space-learn",
            "intent_mode": "LEARN",
            "next_step": _route_item("learn-node", "随机变量", "AVAILABLE"),
        },
        {
            "goal_id": "goal-understand",
            "goal_title": "理解芯片行业",
            "space_id": "space-understand",
            "intent_mode": "UNDERSTAND",
            "next_step": _route_item("question-node", "产业链结构", "NEEDS_REVIEW"),
        },
        {
            "goal_id": "goal-do",
            "goal_title": "发布产品",
            "space_id": "space-do",
            "intent_mode": "DO",
            "next_step": _route_item("action-node", "完成验收", "IN_PROGRESS"),
        },
    ]

    actions = {item["node_id"]: item for item in _build_today_actions(goals)}

    assert actions["learn-node"]["action_label"] == "开始学习"
    assert actions["question-node"]["action_label"] == "重新核验"
    assert actions["action-node"]["action_label"] == "继续执行"


def test_shared_cross_mode_action_uses_truthful_mixed_language() -> None:
    goals = [
        {
            "goal_id": "goal-learn",
            "goal_title": "学习目标",
            "space_id": "shared",
            "intent_mode": "LEARN",
            "next_step": _route_item("shared-node", "共同基础", "AVAILABLE"),
        },
        {
            "goal_id": "goal-do",
            "goal_title": "行动目标",
            "space_id": "shared",
            "intent_mode": "DO",
            "next_step": _route_item("shared-node", "共同基础", "AVAILABLE"),
        },
    ]

    action = _build_today_actions(goals)[0]

    assert action["intent_mode"] == "MIXED"
    assert action["action_label"] == "开始推进"


def test_status_badges_cover_all_modes_and_protect_legacy_goals() -> None:
    assert intent_status_label("AVAILABLE", "LEARN") == "现在可学"
    assert intent_status_label("MASTERED", "UNDERSTAND") == "已理解"
    assert intent_status_label("BLOCKED", "DO") == "建议先处理前置"
    assert intent_status_label("NEEDS_REVIEW", "DO") == "待检查"
    assert normalize_intent_mode(None) == "LEARN"
    assert normalize_intent_mode("not-a-mode") == "LEARN"


def test_valid_goal_semantic_profile_overrides_display_copy_only() -> None:
    payload = _parallel_payload()
    payload["goal_overviews"] = [payload["goal_overviews"][0]]
    payload["goal_overviews"][0]["goal"]["semantic_profile"] = _custom_semantic_profile()
    payload["current_goal"] = payload["goal_overviews"][0]["goal"]

    view = build_parallel_dashboard_view_model(payload)
    goal = view["goals"][0]
    actions = _build_today_actions(view["goals"])

    assert goal["next_step"]["status"] == "IN_PROGRESS"
    assert goal["next_step"]["status_label"] == "正在学习"
    assert actions[0]["action_label"] == "继续学习"
    assert actions[0]["action_href"] == (
        "/projects/goal-python/overview?node=python-functions&panel=action"
    )
    assert intent_progress_label(82, goal["goal"]) == "能够应用"


def test_malformed_semantic_profile_falls_back_as_one_display_unit() -> None:
    malformed_whole = _custom_semantic_profile()
    malformed_whole["unexpected"] = "不允许"
    whole = intent_profile({"intent_mode": "LEARN", "semantic_profile": malformed_whole})
    assert whole["node_label"] == "知识点"
    assert whole["action_labels"]["AVAILABLE"] == "开始学习"

    malformed_field = _custom_semantic_profile()
    malformed_field["node_label"] = "<script>"
    malformed_field["action_labels"] = {"IN_PROGRESS": "继续训练"}
    malformed_field["progress_levels"] = [
        {"min_score": 0, "label": "起点"},
        {"min_score": 60, "label": "提升"},
        {"min_score": 50, "label": "倒退"},
    ]
    fields = intent_profile({"intent_mode": "LEARN", "semantic_profile": malformed_field})

    assert fields["node_label"] == "知识点"
    assert fields["module_label"] == "学习模块"
    assert fields["action_labels"]["AVAILABLE"] == "开始学习"
    assert fields["progress_levels"][0]["label"] == "尚未掌握"
