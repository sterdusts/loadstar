"""Pure presentation contracts for the personal navigation UI."""

import inspect
from itertools import pairwise

import pytest

from learning_navigator.ui.components.navigation import (
    _active_map_columns,
    build_active_map_options,
    build_full_map_options,
    full_map_height,
)
from learning_navigator.ui.pages.current_map import (
    DEFAULT_MAP_VIEW,
    MAP_VIEW_LABELS,
    _module_node_count,
)
from learning_navigator.ui.pages.current_map import (
    register as register_current_map,
)
from learning_navigator.ui.pages.growth import build_growth_chart_options
from learning_navigator.ui.pages.onboarding import (
    _activation_is_valid,
    _plan_action_label,
    _plan_activation_state,
)
from learning_navigator.ui.view_models import (
    build_dashboard_view_model,
    build_growth_view_model,
    localize_route_reason,
)


def _dashboard() -> dict[str, object]:
    return {
        "current_goal": {
            "id": "goal-1",
            "title": "掌握函数基础",
            "space_id": "space-1",
            "target_node_id": "node-c",
        },
        "current_position": {
            "node_id": "node-b",
            "title": "函数图像",
            "status": "AVAILABLE",
            "reason": "导数学习前需要先理解函数图像。",
            "unmet_prerequisites": [],
            "unlocks": ["node-c"],
        },
        "next_step": {
            "node_id": "node-b",
            "title": "函数图像",
            "status": "AVAILABLE",
            "reason": "导数学习前需要先理解函数图像。",
            "unmet_prerequisites": [],
            "unlocks": ["node-c"],
        },
        "blocked": [
            {
                "node_id": "node-c",
                "title": "导数",
                "status": "BLOCKED",
                "reason": "函数图像尚未掌握。",
                "unmet_prerequisites": ["node-b"],
                "unlocks": [],
            }
        ],
        "route_overview": [
            {
                "node_id": "node-a",
                "title": "代数",
                "status": "MASTERED",
                "reason": "基础前置。",
                "unmet_prerequisites": [],
                "unlocks": ["node-b"],
            },
            {
                "node_id": "node-b",
                "title": "函数图像",
                "status": "AVAILABLE",
                "reason": "导数学习前需要先理解函数图像。",
                "unmet_prerequisites": [],
                "unlocks": ["node-c"],
            },
            {
                "node_id": "node-c",
                "title": "导数",
                "status": "BLOCKED",
                "reason": "函数图像尚未掌握。",
                "unmet_prerequisites": ["node-b"],
                "unlocks": [],
            },
        ],
        "recent_sessions": [],
    }


def _formal_graph_with_modules(
    module_count: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    route: list[dict[str, object]] = []
    child_types = ("CONCEPT", "SKILL", "PROCEDURE")

    for module_index in range(module_count):
        module_id = f"module-{module_index + 1:02d}"
        nodes.append(
            {
                "id": module_id,
                "title": f"模块 {module_index + 1}",
                "node_type": "MODULE",
                "difficulty": 2,
                "status": "ACTIVE",
                "computed_status": "NOT_RELEVANT",
            }
        )
        for child_index, node_type in enumerate(child_types, start=1):
            child_id = f"{module_id}-node-{child_index}"
            nodes.append(
                {
                    "id": child_id,
                    "title": f"模块 {module_index + 1} 内容 {child_index}",
                    "node_type": node_type,
                    "difficulty": child_index,
                    "status": "ACTIVE",
                    "computed_status": "AVAILABLE",
                }
            )
            edges.append(
                {
                    "source_node_id": module_id,
                    "target_node_id": child_id,
                    "relation_type": "CONTAINS",
                    "reason": f"{child_id} 属于 {module_id}",
                    "status": "ACTIVE",
                }
            )
        route.append(
            {
                "node_id": f"{module_id}-node-1",
                "title": f"模块 {module_index + 1} 内容 1",
            }
        )

    return {"nodes": nodes, "edges": edges}, route


@pytest.mark.parametrize(
    "builder",
    [build_full_map_options, build_active_map_options],
    ids=["complete-map", "active-route"],
)
def test_map_hover_emphasis_keeps_the_whole_framework_readable(builder) -> None:
    graph, route = _formal_graph_with_modules(6)

    series = builder(graph, route)["series"][0]
    emphasis = series["emphasis"]

    # Only the item under the pointer may enter emphasis.  adjacency/self/series
    # focus all blur unrelated nodes in ECharts and make the full map unreadable.
    assert emphasis.get("focus") == "none"
    assert emphasis.get("blurScope") != "global"
    assert "blur" not in series

    for item in [*series["data"], *series["links"]]:
        item_emphasis = item.get("emphasis", {})
        assert item_emphasis.get("focus", "none") == "none"
        assert item_emphasis.get("blurScope") != "global"
        assert "blur" not in item


def test_dashboard_view_model_answers_navigation_questions() -> None:
    view = build_dashboard_view_model(_dashboard())

    assert view["has_goal"] is True
    assert view["goal_title"] == "掌握函数基础"
    assert view["current_position"]["title"] == "函数图像"
    assert view["next_step"]["reason"] == "导数学习前需要先理解函数图像。"
    assert view["next_step"]["unlock_titles"] == ["导数"]
    assert view["blocked"][0]["unmet_titles"] == ["函数图像"]
    assert view["completed_count"] == 1
    assert view["total_count"] == 3
    assert view["progress_percent"] == 33
    assert view["map_href"] == "/maps/space-1"


def test_dashboard_view_model_projects_check_in_progress_without_overwriting_mastery() -> None:
    payload = _dashboard()
    route = payload["route_overview"]
    assert isinstance(route, list)
    route[1]["progress_score"] = 4
    route[1]["progress_checked_in_at"] = "2026-08-09T09:00:00+00:00"
    route[1]["display_progress_state"] = "IN_PROGRESS"
    route[2]["progress_score"] = 10
    route[2]["progress_checked_in_at"] = "2026-08-09T10:00:00+00:00"
    route[2]["display_progress_state"] = "COMPLETED"
    payload["recent_check_ins"] = [
        {
            "id": "check-in-2",
            "node_id": "node-c",
            "title": "撖潭",
            "score": 10,
            "note": "已完成",
            "checked_in_at": "2026-08-09T10:00:00+00:00",
            "check_in_date": "2026-08-09",
            "display_progress_state": "COMPLETED",
        }
    ]

    view = build_dashboard_view_model(payload)

    assert [item["display_progress_state"] for item in view["route"]] == [
        "COMPLETED",
        "IN_PROGRESS",
        "COMPLETED",
    ]
    assert view["route"][1]["progress_score"] == 4
    assert view["route"][1]["status"] == "AVAILABLE"
    assert view["completed_count"] == 2
    assert view["in_progress_count"] == 1
    assert view["progress_percent"] == 80
    assert view["recent_check_ins"] == [
        {
            "id": "check-in-2",
            "node_id": "node-c",
            "title": "撖潭",
            "score": 10,
            "note": "已完成",
            "checked_in_at": "2026-08-09T10:00:00+00:00",
            "check_in_date": "2026-08-09",
            "display_progress_state": "COMPLETED",
        }
    ]


def test_dashboard_view_model_preserves_explicit_zero_progress() -> None:
    payload = _dashboard()
    route = payload["route_overview"]
    assert isinstance(route, list)
    route[0]["progress_score"] = 0
    route[0]["display_progress_state"] = "NOT_STARTED"

    view = build_dashboard_view_model(payload)

    assert view["route"][0]["progress_score"] == 0
    assert view["route"][0]["display_progress_state"] == "NOT_STARTED"
    assert view["completed_count"] == 0
    assert view["progress_percent"] == 0


def test_empty_dashboard_routes_to_onboarding_state() -> None:
    view = build_dashboard_view_model(
        {
            "current_goal": None,
            "current_position": None,
            "next_step": None,
            "blocked": [],
            "recent_sessions": [],
            "route_overview": [],
        }
    )

    assert view["has_goal"] is False
    assert view["next_step"] is None
    assert view["route"] == []
    assert view["progress_percent"] == 0


def test_current_map_exposes_full_graph_and_route_views_with_full_graph_first() -> None:
    assert MAP_VIEW_LABELS == ("完整框架", "当前路径")
    assert DEFAULT_MAP_VIEW == "full"


def test_current_map_keeps_graph_contract_and_collapses_text_route() -> None:
    source = inspect.getsource(register_current_map)

    assert 'active_path="/map"' in source
    assert 'data.get("nodeId")' in source
    assert "build_full_map_options(" in source
    assert "intent_context=goal_context" in source
    assert '"min-width:1120px;"' in source
    assert "full_map_height(full_graph, view['route'])" in source
    expansion_index = source.index("f\"{mode_copy['route_label']}清单 · {len(view['route'])} 步\"")
    route_strip_index = source.rindex("render_route_strip(")
    assert route_strip_index > expansion_index


def test_current_map_uses_framework_navigation_language() -> None:
    source = inspect.getsource(register_current_map)

    assert '"框架地图"' in source
    assert "完整框架" in source
    assert "知识地图" not in source
    assert "学习路线" not in source


def test_current_map_uses_shared_new_project_mode_and_project_switcher() -> None:
    source = inspect.getsource(register_current_map)

    assert 'ui.navigate.to("/onboarding")' not in source
    assert ") as assistant_handle:" in source
    assert "assistant_handle.start_new_project()" in source
    assert '"建立新目标",' in source
    assert "on_click=start_new_project," in source
    assert source.count('"切换目标",') == 2
    assert source.count('ui.navigate.to("/projects")') == 3


def test_legacy_goal_creator_is_not_a_second_path_workflow() -> None:
    from learning_navigator.ui.pages.goals import register as register_goals

    goals_source = inspect.getsource(register_goals)

    assert 'ui.navigate.to("/projects")' in goals_source
    assert 'client.post("/goals"' not in goals_source
    assert 'client.post(f"/goals/' not in goals_source


@pytest.mark.parametrize(
    ("item", "current_goal_id", "expected_state", "expected_action"),
    [
        ({"activation": None}, None, "draft", "启用"),
        (
            {"activation": {"goal_id": "goal-current"}},
            "goal-current",
            "current",
            "查看当前地图",
        ),
        (
            {"activation": {"goal_id": "goal-other"}},
            "goal-current",
            "activated",
            "切换到此方案",
        ),
    ],
)
def test_saved_plan_cards_expose_draft_current_and_activated_actions(
    item: object,
    current_goal_id: str | None,
    expected_state: str,
    expected_action: str,
) -> None:
    state = _plan_activation_state(item, current_goal_id)

    assert state == expected_state
    assert _plan_action_label(state) == expected_action


def test_current_map_module_count_uses_every_non_archived_module() -> None:
    graph = {
        "nodes": [
            {"id": "module-a", "node_type": "MODULE", "status": "ACTIVE"},
            {"id": "module-b", "node_type": "MODULE", "status": "ACTIVE"},
            {"id": "concept-a", "node_type": "CONCEPT", "status": "ACTIVE"},
            {"id": "module-old", "node_type": "MODULE", "status": "ARCHIVED"},
        ]
    }

    assert _module_node_count(graph) == 2
    assert _module_node_count({}) == 0


def test_route_engine_explanations_follow_current_status_in_chinese() -> None:
    reason = (
        "All hard prerequisites are satisfied; this is the next foundational step "
        "toward required mastery level 3."
    )

    assert (
        localize_route_reason(
            reason,
            status="AVAILABLE",
            required_mastery_level=3,
        )
        == "前置知识已掌握，可以开始学习。"
    )
    assert (
        localize_route_reason(
            reason,
            status="MASTERED",
            required_mastery_level=3,
        )
        == "已有掌握证据达到当前学习路径要求。"
    )
    assert (
        localize_route_reason(
            "Complete unmet prerequisites first: 函数; then continue toward "
            "required mastery level 3.",
            status="BLOCKED",
            required_mastery_level=3,
            unmet_titles=["函数"],
        )
        == "建议先掌握：函数；也可以直接开始，过程中再补齐。"
    )
    assert (
        localize_route_reason(
            "Recommended prerequisites to review first: 函数.",
            status="AVAILABLE",
            unmet_titles=["函数"],
        )
        == "建议先掌握：函数；也可以直接开始，过程中再补齐。"
    )

    assert (
        localize_route_reason(reason, status="AVAILABLE", intent_mode="UNDERSTAND")
        == "前置问题已厘清，可以开始探索。"
    )
    assert (
        localize_route_reason(
            "Complete unmet prerequisites first: 验收标准; then continue.",
            status="BLOCKED",
            unmet_titles=["验收标准"],
            intent_mode="DO",
        )
        == "建议先完成：验收标准；也可以直接执行，并自行承担依赖风险。"
    )


def test_active_map_keeps_formal_relations_and_adds_order_backbone() -> None:
    graph = {
        "nodes": [
            {
                "id": "node-a",
                "title": "代数",
                "status": "ACTIVE",
                "computed_status": "MASTERED",
            },
            {
                "id": "node-b",
                "title": "函数图像",
                "status": "ACTIVE",
                "computed_status": "AVAILABLE",
            },
            {
                "id": "node-c",
                "title": "导数",
                "status": "ACTIVE",
                "computed_status": "BLOCKED",
            },
            {
                "id": "unrelated",
                "title": "无关节点",
                "status": "ACTIVE",
                "computed_status": "NOT_RELEVANT",
            },
        ],
        "edges": [
            {
                "source_node_id": "node-a",
                "target_node_id": "node-b",
                "relation_type": "PREREQUISITE",
                "reason": "代数是函数的表达基础。",
            },
            {
                "source_node_id": "node-b",
                "target_node_id": "node-c",
                "relation_type": "PREREQUISITE",
                "reason": "先理解函数变化再进入导数。",
            },
        ],
    }
    route = build_dashboard_view_model(_dashboard())["route"]

    series = build_active_map_options(graph, route)["series"][0]
    assert [node["name"] for node in series["data"]] == ["代数", "函数图像", "导数"]
    assert [node["routeSequence"] for node in series["data"]] == [1, 2, 3]
    assert len({(node["x"], node["y"]) for node in series["data"]}) == 3
    route_knowledge = [link for link in series["links"] if link["kind"] == "route_knowledge"]
    assert len(route_knowledge) == 2
    assert all(link["lineStyle"]["width"] >= 4 for link in route_knowledge)
    assert "代数" in route_knowledge[0]["tooltip"]["formatter"]
    assert "formal-" not in route_knowledge[0]["tooltip"]["formatter"]


def test_active_map_preserves_round_node_symbols_when_chart_aspect_changes() -> None:
    graph = {
        "nodes": [
            {
                "id": f"node-{index}",
                "title": f"知识点 {index}",
                "status": "ACTIVE",
                "computed_status": "AVAILABLE",
            }
            for index in range(16)
        ],
        "edges": [],
    }
    route = [
        {
            "node_id": f"node-{index}",
            "title": f"知识点 {index}",
            "status": "AVAILABLE",
            "reason": "按依赖顺序学习。",
        }
        for index in range(16)
    ]

    series = build_active_map_options(graph, route)["series"][0]

    # A graph with explicit x/y coordinates is fitted into the available chart
    # rectangle.  Without this ECharts contract, a wide graph rendered in a
    # tall card stretches otherwise round nodes into vertical ellipses.
    assert series["preserveAspect"] is True
    assert series["draggable"] is False
    assert series["symbol"] == "circle"
    assert all(
        isinstance(node["symbolSize"], (int, float)) and not isinstance(node["symbolSize"], bool)
        for node in series["data"]
    )
    assert _active_map_columns(16) == 4


def test_active_map_deduplicates_route_steps_that_are_formal_prerequisites() -> None:
    graph = {
        "nodes": [
            {
                "id": node_id,
                "title": title,
                "status": "ACTIVE",
                "computed_status": "AVAILABLE",
            }
            for node_id, title in (
                ("node-a", "代数"),
                ("node-b", "函数"),
                ("node-c", "导数"),
            )
        ],
        "edges": [
            {
                "source_node_id": "node-a",
                "target_node_id": "node-b",
                "relation_type": "PREREQUISITE",
                "reason": "代数是理解函数的前置知识。",
            }
        ],
    }
    route = [
        {
            "node_id": node_id,
            "title": title,
            "status": "AVAILABLE",
            "reason": "按依赖顺序学习。",
        }
        for node_id, title in (
            ("node-a", "代数"),
            ("node-b", "函数"),
            ("node-c", "导数"),
        )
    ]

    series = build_active_map_options(graph, route)["series"][0]
    chart_id = {node["nodeId"]: node["id"] for node in series["data"]}
    first_step_links = [
        link
        for link in series["links"]
        if link["source"] == chart_id["node-a"] and link["target"] == chart_id["node-b"]
    ]
    second_step_links = [
        link
        for link in series["links"]
        if link["source"] == chart_id["node-b"] and link["target"] == chart_id["node-c"]
    ]

    assert [link["kind"] for link in first_step_links] == ["route_knowledge"]
    assert [link["kind"] for link in second_step_links] == ["route"]


def test_full_map_keeps_module_hierarchy_and_every_non_archived_node() -> None:
    graph = {
        "nodes": [
            {
                "id": "module-math",
                "title": "数学基础",
                "node_type": "MODULE",
                "status": "ACTIVE",
                "computed_status": "NOT_RELEVANT",
            },
            {
                "id": "concept-algebra",
                "title": "代数",
                "node_type": "CONCEPT",
                "status": "ACTIVE",
                "computed_status": "MASTERED",
            },
            {
                "id": "skill-functions",
                "title": "函数建模",
                "node_type": "SKILL",
                "status": "ACTIVE",
                "computed_status": "NOT_RELEVANT",
            },
            {
                "id": "archived-node",
                "title": "过期知识点",
                "node_type": "CONCEPT",
                "status": "ARCHIVED",
                "computed_status": "AVAILABLE",
            },
        ],
        "edges": [
            {
                "source_node_id": "module-math",
                "target_node_id": "concept-algebra",
                "relation_type": "CONTAINS",
                "reason": "代数属于数学基础模块。",
                "status": "ACTIVE",
            },
            {
                "source_node_id": "concept-algebra",
                "target_node_id": "skill-functions",
                "relation_type": "PREREQUISITE",
                "reason": "代数支撑函数建模。",
                "status": "ACTIVE",
            },
            {
                "source_node_id": "concept-algebra",
                "target_node_id": "skill-functions",
                "relation_type": "RELATED",
                "reason": "已归档的旧关系。",
                "status": "ARCHIVED",
            },
            {
                "source_node_id": "module-math",
                "target_node_id": "archived-node",
                "relation_type": "CONTAINS",
                "reason": "指向归档节点。",
                "status": "ACTIVE",
            },
        ],
    }

    series = build_full_map_options(graph, [])["series"][0]

    assert {node["nodeId"] for node in series["data"]} == {
        "module-math",
        "concept-algebra",
        "skill-functions",
    }
    module = next(node for node in series["data"] if node["nodeId"] == "module-math")
    child = next(node for node in series["data"] if node["nodeId"] == "concept-algebra")
    assert series["categories"][module["category"]]["name"] == "框架模块"
    assert series["symbol"] == "circle"
    assert series["preserveAspect"] is True
    assert series["draggable"] is False
    assert module["symbol"] == "roundRect"
    assert module["symbolSize"][0] >= module["symbolSize"][1] * 2
    assert child["symbol"] == "roundRect"
    assert child["symbolSize"][0] >= child["symbolSize"][1] * 2
    assert child["label"]["position"] == "inside"

    links = series["links"]
    assert len(links) == 2
    contains = next(link for link in links if link["relationType"] == "CONTAINS")
    assert contains["symbol"] == ["none", "none"]
    assert contains["symbolSize"] == [0, 0]
    assert contains["lineStyle"]["opacity"] <= 0.2
    assert all(link["kind"] == "knowledge" for link in links)


@pytest.mark.parametrize(
    ("module_count", "expected_row_lengths"),
    [(7, [4, 3]), (12, [4, 4, 4])],
)
def test_full_map_adapts_module_grid_without_truncation_or_clipping(
    module_count: int,
    expected_row_lengths: list[int],
) -> None:
    graph, route = _formal_graph_with_modules(module_count)

    options = build_full_map_options(graph, route)
    series = options["series"][0]
    rendered_nodes = series["data"]
    module_nodes = [node for node in rendered_nodes if node["nodeType"] == "MODULE"]

    assert len(rendered_nodes) == module_count * 4
    assert len(module_nodes) == module_count
    assert {node["nodeId"] for node in rendered_nodes} == {
        str(node["id"]) for node in graph["nodes"]
    }
    assert len({(node["x"], node["y"]) for node in rendered_nodes}) == len(rendered_nodes)

    # Sequence chunks form explicit rows. Alternating fan directions introduce
    # intentional y variation inside a row, so a naive global y-gap detector
    # would incorrectly merge adjacent rows.
    ordered_modules = sorted(module_nodes, key=lambda node: node["moduleSequence"])
    row_centers: list[float] = []
    offset = 0
    for expected_length in expected_row_lengths:
        row = ordered_modules[offset : offset + expected_length]
        offset += expected_length
        assert len(row) == expected_length
        row_y = [node["y"] for node in row]
        assert max(row_y) - min(row_y) <= 280
        row_centers.append(sum(row_y) / len(row_y))
    assert all(lower - upper >= 400 for upper, lower in pairwise(row_centers))
    assert max(node["x"] for node in module_nodes) - min(node["x"] for node in module_nodes) >= 900

    # The canvas stays viewport-bounded even for a broad map. ECharts fits the
    # complete coordinate space without distorting circular nodes, and users
    # can zoom or pan for detail.
    chart_height = full_map_height(graph, route)
    assert 620 <= chart_height <= 1_080
    assert series["preserveAspect"] is True
    assert series["roam"] is True
    assert series["draggable"] is False
    for node in rendered_nodes:
        symbol_size = node["symbolSize"]
        if isinstance(symbol_size, (list, tuple)):
            half_width = symbol_size[0] / 2
            half_height = symbol_size[1] / 2
        else:
            half_width = half_height = symbol_size / 2
        assert node["x"] - half_width >= 0
        assert node["y"] - half_height >= 0

    knowledge_cards = [node for node in rendered_nodes if node["nodeType"] != "MODULE"]
    assert all(node["symbol"] == "roundRect" for node in knowledge_cards)
    assert all(node["label"]["position"] == "inside" for node in knowledge_cards)


def test_full_map_separates_module_badges_from_real_route_sequence() -> None:
    graph, route = _formal_graph_with_modules(7)

    options = build_full_map_options(graph, route)
    series = options["series"][0]
    nodes_by_node_id = {node["nodeId"]: node for node in series["data"]}
    modules = sorted(
        (node for node in series["data"] if "moduleBadge" in node),
        key=lambda node: node["moduleSequence"],
    )
    route_links = [link for link in series["links"] if link["kind"] == "route_knowledge"]

    assert len(modules) == 7
    assert all(node["nodeType"] == "MODULE" for node in modules)
    assert [node["moduleSequence"] for node in modules] == list(range(1, 8))
    assert [node["moduleBadge"] for node in modules] == [str(value) for value in range(1, 8)]
    assert all(node["moduleBadge"] in node["label"]["formatter"] for node in modules)
    assert all(
        not ({"stageSequence", "stageBadge", "stageTitle", "stageAccent"} & node.keys())
        for node in series["data"]
    )

    route_nodes = [nodes_by_node_id[item["node_id"]] for item in route]
    assert [node["routeSequence"] for node in route_nodes] == list(range(1, 8))
    assert all(
        node["label"]["formatter"].startswith(f"{sequence} · ")
        for sequence, node in enumerate(route_nodes, start=1)
    )
    assert not route_links
    assert all(link["kind"] not in {"route", "stage_progress"} for link in series["links"])

    assert not options.get("graphic")
    assert series.get("edgeLabel", {}).get("show", False) is False


def test_growth_view_model_normalizes_ratios_and_builds_timeline() -> None:
    growth = {
        "summary": {
            "total_nodes": 16,
            "touched_nodes": 6,
            "tracked_nodes": 8,
            "mastered_nodes": 2,
            "coverage_rate": 37.5,
            "average_mastery_score": 62.5,
            "overall_progress_rate": 31.25,
            "total_sessions": 2,
            "total_check_ins": 1,
            "total_evidence": 3,
            "total_learning_minutes": 75,
            "active_days": 2,
        },
        "series": [
            {
                "date": "2026-08-04",
                "coverage_rate": 37.5,
                "learning_minutes": 75,
                "session_count": 2,
                "check_in_count": 1,
            }
        ],
        "check_ins": [
            {
                "id": "check-in-1",
                "node_id": "node-c",
                "node": {"id": "node-c", "title": "连接查询", "space_id": "space-1"},
                "score": 10,
                "note": "完成 JOIN 练习",
                "checked_in_at": "2026-08-04T10:00:00+00:00",
            }
        ],
    }
    sessions = {
        "items": [
            {
                "id": "session-1",
                "node_id": "node-b",
                "node": {"id": "node-b", "title": "函数图像", "space_id": "space-1"},
                "started_at": "2026-08-04T09:00:00+00:00",
                "ended_at": "2026-08-04T09:45:00+00:00",
                "note": "完成图像变换练习",
                "evidence_count": 2,
            }
        ],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }

    view = build_growth_view_model(growth, sessions)
    assert view["summary"]["coverage_percent"] == 37.5
    assert view["summary"]["mastery_percent"] == 62.5
    assert view["summary"]["overall_progress_percent"] == 31.2
    assert view["summary"]["touched_nodes"] == 6
    assert view["summary"]["total_nodes"] == 16
    assert view["summary"]["active_days"] == 2
    assert view["summary"]["total_check_ins"] == 1
    assert view["timeline"][0]["event_kind"] == "check_in"
    assert view["timeline"][0]["score"] == 10
    assert view["timeline"][0]["node_title"] == "连接查询"
    assert view["timeline"][1]["node_title"] == "函数图像"
    assert view["timeline"][1]["minutes"] == 45
    assert view["timeline"][1]["evidence_count"] == 2
    assert build_growth_chart_options(view["series"])["series"][0]["data"] == [37.5]


def test_activation_contract_requires_formal_space_goal_and_route_items() -> None:
    assert _activation_is_valid(
        {"space": {}, "goal": {}, "route": {"path": {}, "items": []}, "activation": {}}
    )
    assert not _activation_is_valid({"space": {}, "goal": {}, "route": {}})
