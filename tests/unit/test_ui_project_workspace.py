"""Contracts for the single project workspace and editable path flow."""

import inspect
from itertools import pairwise

from learning_navigator.ui.components import layout
from learning_navigator.ui.components.navigation import (
    group_framework_by_modules,
    group_route_by_modules,
)
from learning_navigator.ui.pages import map_editor, onboarding, projects, workbench


def test_project_urls_keep_project_and_node_context_explicit() -> None:
    assert projects.project_href("goal one") == "/projects/goal%20one/overview"
    assert projects.project_href("goal-1", "map", node_id="node/1") == (
        "/projects/goal-1/map?node=node%2F1"
    )
    assert (
        projects.path_revision_href(
            "goal-1",
            "path-2",
            node_id="node-3",
        )
        == "/projects/goal-1/map?edit=structure&revision=path-2&node=node-3"
    )


def test_project_workspace_has_one_small_navigation_hierarchy() -> None:
    assert projects.PROJECT_SECTIONS == (
        ("overview", "概览", "space_dashboard"),
        ("map", "框架", "hub"),
        ("mindmap", "脑图", "account_tree"),
    )


def test_project_views_switch_in_place_with_accessible_transition() -> None:
    navigation_source = inspect.getsource(projects._project_navigation)
    page_source = inspect.getsource(projects._render_project_page)
    theme_source = inspect.getsource(layout.install_theme)

    assert "on_switch" in navigation_source
    assert "ui.button(on_click=switch)" in navigation_source
    assert "history.replaceState" in page_source
    assert "document.location.pathname.startsWith('/ui/')" in page_source
    assert "content_slot.clear()" in page_source
    assert "ln-project-view-panel" in page_source
    assert "ln-project-view-enter" in theme_source
    assert "prefers-reduced-motion" in theme_source


def test_route_node_selection_only_refreshes_the_inspector() -> None:
    overview_source = inspect.getsource(projects._render_overview)
    page_source = inspect.getsource(projects._render_project_page)
    inspector_source = inspect.getsource(projects._render_inspector)

    assert "on_select_node" in overview_source
    assert "ui.button(on_click=select_route_node)" in overview_source
    assert "await render_inspector_for(target)" in page_source
    assert "inspector_slot.clear()" in page_source
    assert 'workspace.classes(add="ln-project-workspace-has-inspector")' in page_source
    assert "on_close" in inspector_source


def test_mind_map_uses_live_nodes_and_edges_without_archived_duplicates() -> None:
    graph = {
        "nodes": [
            {"id": "module", "title": "基础", "node_type": "MODULE"},
            {"id": "concept", "title": "函数", "node_type": "CONCEPT"},
            {"id": "skill", "title": "应用", "node_type": "SKILL"},
            {"id": "archived", "title": "旧节点", "node_type": "CONCEPT", "status": "ARCHIVED"},
            {"id": "loose", "title": "补充", "node_type": "CONCEPT"},
        ],
        "edges": [
            {"source_node_id": "module", "target_node_id": "concept", "relation_type": "CONTAINS"},
            {
                "source_node_id": "concept",
                "target_node_id": "skill",
                "relation_type": "PREREQUISITE",
            },
            {"source_node_id": "module", "target_node_id": "archived", "relation_type": "CONTAINS"},
        ],
    }
    options = projects._mind_map_options(
        graph,
        [{"node_id": "concept"}, {"node_id": "skill"}],
        focus_node_ids=["skill"],
        module_order=["module"],
    )

    series = options["series"][0]
    ids = {item["id"] for item in series["data"]}
    assert ids == {"__mind_root__", "module", "concept", "skill", "__mind_module_1", "loose"}
    assert "archived" not in ids
    links = {(link["source"], link["target"]) for link in series["links"]}
    assert {("module", "concept"), ("concept", "skill")} <= links
    assert all("archived" not in pair for pair in links)
    highlighted = next(item for item in series["data"] if item["id"] == "skill")
    assert highlighted["symbolSize"] > 32

    hidden = projects._mind_map_options(
        graph,
        [{"node_id": "concept"}, {"node_id": "skill"}],
        focus_node_ids=["skill"],
        module_order=["module"],
        show_relationships=False,
    )
    hidden_links = {(link["source"], link["target"]) for link in hidden["series"][0]["links"]}
    assert ("concept", "skill") not in hidden_links
    assert ("module", "concept") in hidden_links


def test_mind_map_keeps_framework_as_source_of_truth_when_ai_order_is_partial() -> None:
    graph = {
        "nodes": [
            {"id": "module-a", "title": "A", "node_type": "MODULE"},
            {"id": "module-b", "title": "B", "node_type": "MODULE"},
            {"id": "a", "title": "a", "node_type": "CONCEPT"},
            {"id": "b", "title": "b", "node_type": "CONCEPT"},
        ],
        "edges": [
            {"source_node_id": "module-a", "target_node_id": "a", "relation_type": "CONTAINS"},
            {"source_node_id": "module-b", "target_node_id": "b", "relation_type": "CONTAINS"},
        ],
    }
    options = projects._mind_map_options(
        graph,
        [],
        module_order=["module-b"],
    )
    data = options["series"][0]["data"]
    positions = {item["id"]: (item["x"], item["y"]) for item in data}
    assert positions["module-a"][0] * positions["module-b"][0] < 0
    assert positions["module-b"][1] < positions["module-a"][1]
    assert {item["id"] for item in data} == {
        "__mind_root__",
        "module-a",
        "module-b",
        "a",
        "b",
    }


def test_dense_mind_map_reserves_each_branch_real_child_height() -> None:
    child_counts = [5, 5, 5, 4, 6, 6]
    nodes = []
    edges = []
    route = []
    for module_index, child_count in enumerate(child_counts, start=1):
        module_id = f"module-{module_index}"
        nodes.append(
            {
                "id": module_id,
                "title": f"Module {module_index}",
                "node_type": "MODULE",
                "outline_order": module_index,
            }
        )
        for child_index in range(1, child_count + 1):
            node_id = f"{module_id}-node-{child_index}"
            nodes.append(
                {
                    "id": node_id,
                    "title": f"Knowledge {module_index}-{child_index}",
                    "node_type": "CONCEPT",
                    "outline_order": child_index,
                }
            )
            edges.append(
                {
                    "source_node_id": module_id,
                    "target_node_id": node_id,
                    "relation_type": "CONTAINS",
                }
            )
            route.append({"node_id": node_id})

    graph = {"nodes": nodes, "edges": edges}
    groups = projects._ordered_mind_map_groups(graph, route, [])
    module_y, chart_height = projects._mind_map_branch_layout(groups)

    intervals_by_side: dict[int, list[tuple[float, float]]] = {-1: [], 1: []}
    for branch_index, group in enumerate(groups):
        item_count = len(group["items"])
        span = max(48, (max(1, item_count) - 1) * 96 + 48)
        center = module_y[branch_index]
        side = -1 if branch_index % 2 == 0 else 1
        intervals_by_side[side].append((center - span / 2, center + span / 2))
    for intervals in intervals_by_side.values():
        intervals.sort()
        assert all(
            lower_start - upper_end >= 88
            for (_, upper_end), (lower_start, _) in pairwise(intervals)
        )
    assert chart_height >= 1800

    series = projects._mind_map_options(graph, route)["series"][0]
    rendered = {str(item["id"]): item for item in series["data"]}
    for branch_index, group in enumerate(groups):
        module_id = str(group["module_id"])
        expected_label = "left" if branch_index % 2 == 0 else "right"
        for item in group["items"]:
            assert rendered[str(item["id"])]["label"]["position"] == expected_label
        assert rendered[module_id]["y"] == module_y[branch_index]


def test_mind_map_freshness_uses_the_active_path_revision_not_dashboard_route() -> None:
    graph = {"outline_revision": 4}
    active_revision = {"path": {"id": "path-1", "row_version": 7}}
    suggestion = {
        "proposed_changes": {
            "source_outline_revision": 4,
            "source_path_revision": 7,
        }
    }

    assert projects._mind_map_suggestion_matches_revision(graph, active_revision, suggestion)
    suggestion["proposed_changes"]["source_path_revision"] = 6
    assert not projects._mind_map_suggestion_matches_revision(graph, active_revision, suggestion)
    suggestion["proposed_changes"]["source_path_revision"] = 7
    graph["outline_revision"] = 5
    assert not projects._mind_map_suggestion_matches_revision(graph, active_revision, suggestion)


def test_active_and_editing_revisions_are_selected_independently() -> None:
    revisions = [
        {"path": {"id": "active", "status": "ACTIVE"}, "steps": []},
        {"path": {"id": "draft", "status": "DRAFT"}, "steps": []},
    ]

    assert projects._active_path_revision(revisions) == revisions[0]
    assert projects._selected_edit_revision(revisions, None) == revisions[1]
    assert projects._selected_edit_revision(revisions, "active") == revisions[0]


def test_overview_is_the_only_active_route_and_progress_surface() -> None:
    overview_source = inspect.getsource(projects._render_overview)
    page_source = inspect.getsource(projects._render_project_page)

    assert 'project.get("route")' in overview_source
    assert "group_route_by_modules(graph, route)" in overview_source
    assert "route[:" not in overview_source
    assert all(label in overview_source for label in ("当前路径", "总体进度", "最近打卡"))
    assert '"ln-card mt-4 w-full p-4 sm:p-5"' in overview_source
    assert "recent_check_ins" in overview_source
    assert "path_revision_href(project_id)" in overview_source

    assert 'editing_path = edit in {"path", "structure"}' in page_source
    revision_selection = (
        "_selected_edit_revision(revisions, revision_id) if editing_path else active_revision"
    )
    assert revision_selection in page_source
    assert 'elif section == "path"' not in page_source
    assert 'elif section == "progress"' not in page_source
    assert not hasattr(projects, "_render_progress")


def test_active_route_is_grouped_by_the_same_framework_modules_without_renumbering() -> None:
    graph = {
        "nodes": [
            {"id": "module-a", "title": "基础", "node_type": "MODULE"},
            {"id": "module-b", "title": "进阶", "node_type": "MODULE"},
            {"id": "a-1", "title": "概念一", "node_type": "CONCEPT"},
            {"id": "a-2", "title": "概念二", "node_type": "CONCEPT"},
            {"id": "a-extra", "title": "补充知识", "node_type": "CONCEPT"},
            {"id": "b-1", "title": "能力一", "node_type": "SKILL"},
            {"id": "loose", "title": "未分类", "node_type": "CONCEPT"},
        ],
        "edges": [
            {
                "source_node_id": "module-a",
                "target_node_id": target,
                "relation_type": "CONTAINS",
            }
            for target in ("a-1", "a-2", "a-extra")
        ]
        + [
            {
                "source_node_id": "module-b",
                "target_node_id": "b-1",
                "relation_type": "CONTAINS",
            }
        ],
    }
    route = [
        {"node_id": "a-1", "title": "概念一"},
        {"node_id": "a-2", "title": "概念二"},
        {"node_id": "b-1", "title": "能力一"},
        {"node_id": "loose", "title": "未分类"},
    ]

    groups = group_route_by_modules(graph, route)

    assert [group["title"] for group in groups] == ["基础", "进阶", "未归类步骤"]
    assert [group["knowledge_count"] for group in groups] == [3, 1, 1]
    assert [[step["route_position"] for step in group["steps"]] for group in groups] == [
        [1, 2],
        [3],
        [4],
    ]
    assert [step["node_id"] for group in groups for step in group["steps"]] == [
        item["node_id"] for item in route
    ]


def test_route_keeps_all_framework_modules_when_only_one_has_scheduled_steps() -> None:
    graph = {
        "nodes": [
            {"id": f"module-{index}", "title": f"模块 {index}", "node_type": "MODULE"}
            for index in range(1, 10)
        ]
        + [
            {"id": "step-1", "title": "概率", "node_type": "CONCEPT"},
            {"id": "step-2", "title": "随机变量", "node_type": "CONCEPT"},
        ],
        "edges": [
            {
                "source_node_id": "module-5",
                "target_node_id": step_id,
                "relation_type": "CONTAINS",
            }
            for step_id in ("step-1", "step-2")
        ],
    }
    route = [
        {"node_id": "step-1", "title": "概率"},
        {"node_id": "step-2", "title": "随机变量"},
    ]

    groups = group_route_by_modules(graph, route)

    assert len(groups) == 9
    assert {group["title"] for group in groups} == {f"模块 {index}" for index in range(1, 10)}
    assert sum(not group["steps"] for group in groups) == 8
    scheduled_group = next(group for group in groups if group["title"] == "模块 5")
    assert [item["node_id"] for item in scheduled_group["steps"]] == ["step-1", "step-2"]
    assert [item["node_id"] for group in groups for item in group["steps"]] == ["step-1", "step-2"]


def test_legacy_module_prerequisites_have_one_consistent_compatibility_projection() -> None:
    graph = {
        "nodes": [
            {"id": "module-a", "title": "基础", "node_type": "MODULE", "outline_order": 0},
            {"id": "module-b", "title": "进阶", "node_type": "MODULE", "outline_order": 0},
            {"id": "leading", "title": "损失函数", "node_type": "CONCEPT", "outline_order": 0},
            {"id": "concept", "title": "概率", "node_type": "CONCEPT", "outline_order": 0},
            {"id": "skill", "title": "分析", "node_type": "SKILL", "outline_order": 0},
        ],
        "edges": [
            {
                "source_node_id": "module-a",
                "target_node_id": "module-b",
                "relation_type": "PREREQUISITE",
            },
            {
                "source_node_id": "module-b",
                "target_node_id": "concept",
                "relation_type": "PREREQUISITE",
            },
            {
                "source_node_id": "leading",
                "target_node_id": "concept",
                "relation_type": "PREREQUISITE",
            },
            {
                "source_node_id": "concept",
                "target_node_id": "skill",
                "relation_type": "PREREQUISITE",
            },
        ],
    }
    legacy_route = [
        {"node_id": "module-a", "title": "基础"},
        {"node_id": "module-b", "title": "进阶"},
        {"node_id": "leading", "title": "损失函数"},
        {"node_id": "concept", "title": "概率"},
        {"node_id": "skill", "title": "分析"},
    ]

    framework_groups = group_framework_by_modules(graph, legacy_route)
    route_groups = group_route_by_modules(graph, legacy_route)

    grouped_framework_ids = [item["id"] for group in framework_groups for item in group["items"]]
    grouped_route_ids = [item["node_id"] for group in route_groups for item in group["steps"]]
    assert grouped_framework_ids == ["leading", "concept", "skill"]
    assert grouped_route_ids == ["leading", "concept", "skill"]
    assert [item["route_position"] for group in route_groups for item in group["steps"]] == [
        1,
        2,
        3,
    ]
    assert [group["title"] for group in route_groups] == ["基础", "进阶", "未归类步骤"]
    assert all(not group["steps"] for group in route_groups[:2])
    assert [item["node_id"] for item in route_groups[-1]["steps"]] == [
        "leading",
        "concept",
        "skill",
    ]


def test_route_module_groups_follow_framework_order_when_route_starts_later() -> None:
    """The overview must use the same module order as the framework editor."""

    graph = {
        "nodes": [
            {"id": "module-first", "title": "基础", "node_type": "MODULE", "outline_order": 1},
            {"id": "module-second", "title": "进阶", "node_type": "MODULE", "outline_order": 2},
            {"id": "first-step", "title": "代数", "node_type": "CONCEPT", "outline_order": 1},
            {"id": "second-step", "title": "函数", "node_type": "CONCEPT", "outline_order": 2},
        ],
        "edges": [
            {
                "source_node_id": "module-first",
                "target_node_id": "first-step",
                "relation_type": "CONTAINS",
            },
            {
                "source_node_id": "module-second",
                "target_node_id": "second-step",
                "relation_type": "CONTAINS",
            },
        ],
    }

    groups = group_route_by_modules(
        graph,
        [
            {"node_id": "second-step", "title": "函数"},
            {"node_id": "first-step", "title": "代数"},
        ],
    )

    assert [group["title"] for group in groups] == ["基础", "进阶"]
    assert [[step["node_id"] for step in group["steps"]] for group in groups] == [
        ["first-step"],
        ["second-step"],
    ]


def test_project_overview_does_not_count_modules_as_knowledge_points() -> None:
    nodes = [
        {"id": "module-1", "node_type": "MODULE"},
        {"id": "module-2", "node_type": "MODULE"},
        {"id": "knowledge-1", "node_type": "CONCEPT"},
        {"id": "knowledge-2", "node_type": "SKILL"},
        {"id": "knowledge-3", "node_type": "CONCEPT", "status": "ARCHIVED"},
    ]
    route = [
        {"node_id": "module-1"},
        {"node_id": "knowledge-1"},
        {"node_id": "knowledge-2"},
    ]

    assert projects._project_overview_counts(nodes, route) == (2, 2, 2)

    source = inspect.getsource(projects._render_overview)
    assert "（不含模块）" in source
    assert '(route_step_count, "路径步骤")' in source
    assert "ungrouped_route_count" in source
    assert "步未归类" in source


def test_project_structure_diagnostics_exposes_empty_modules_and_ungrouped_content() -> None:
    nodes = [
        {"id": "module-1", "node_type": "MODULE"},
        {"id": "module-2", "node_type": "MODULE"},
        {"id": "knowledge-1", "node_type": "CONCEPT"},
        {"id": "knowledge-2", "node_type": "SKILL"},
        {"id": "knowledge-3", "node_type": "CONCEPT"},
    ]
    edges = [
        {
            "source_node_id": "module-1",
            "target_node_id": "knowledge-1",
            "relation_type": "CONTAINS",
        }
    ]

    diagnostics = projects._project_structure_diagnostics(
        nodes,
        edges,
        [{"node_id": "knowledge-1"}],
    )

    assert diagnostics == {
        "empty_module_count": 1,
        "ungrouped_content_count": 2,
        "multiply_grouped_content_count": 0,
        "route_coverage_count": 1,
        "content_count": 3,
        "modules_missing_from_route_count": 0,
        "malformed": True,
    }


def test_project_structure_diagnostics_accepts_complete_hierarchy() -> None:
    nodes = [
        {"id": "module-1", "node_type": "MODULE"},
        {"id": "module-2", "node_type": "MODULE"},
        {"id": "knowledge-1", "node_type": "CONCEPT"},
        {"id": "knowledge-2", "node_type": "SKILL"},
    ]
    edges = [
        {
            "source_node_id": "module-1",
            "target_node_id": "knowledge-1",
            "relation_type": "CONTAINS",
        },
        {
            "source_node_id": "module-2",
            "target_node_id": "knowledge-2",
            "relation_type": "CONTAINS",
        },
    ]

    diagnostics = projects._project_structure_diagnostics(
        nodes,
        edges,
        [{"node_id": "knowledge-1"}, {"node_id": "knowledge-2"}],
    )

    assert diagnostics["malformed"] is False
    assert diagnostics["empty_module_count"] == 0
    assert diagnostics["ungrouped_content_count"] == 0
    assert diagnostics["route_coverage_count"] == 2


def test_legacy_path_and_progress_urls_only_redirect_to_overview() -> None:
    source = inspect.getsource(projects.register)
    path_marker = '@ui.page("/projects/{project_id}/path")'
    progress_marker = '@ui.page("/projects/{project_id}/progress")'
    path_handler = source[source.index(path_marker) : source.index(progress_marker)]
    progress_handler = source[source.index(progress_marker) :]

    assert "ui.navigate.to(path_revision_href(project_id, revision, node_id=node))" in path_handler
    assert "await _render_project_page" not in path_handler
    assert 'ui.navigate.to(project_href(project_id, "overview", node_id=node)' in progress_handler
    assert '"#current-route"' in progress_handler
    assert "await _render_project_page" not in progress_handler


def test_route_display_progress_has_stable_semantics_and_accessible_color_tokens() -> None:
    assert projects._route_progress_state({"progress_score": 10}) == (
        "completed",
        "已完成",
        "check_circle",
    )
    assert projects._route_progress_state({"progress_score": 6}) == (
        "active",
        "进行中",
        "pending",
    )
    assert projects._route_progress_state({}) == (
        "pending",
        "未进行",
        "play_circle",
    )
    assert projects._route_progress_state({"status": "MASTERED"})[0] == "completed"
    assert projects._route_progress_state({"status": "NEEDS_REVIEW"})[0] == "active"

    theme_source = inspect.getsource(layout.install_theme)
    completed_block = theme_source.split(".ln-route-state-completed {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    active_block = theme_source.split(".ln-route-state-active {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    pending_block = theme_source.split(".ln-route-state-pending {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "var(--ln-danger-text)" in completed_block
    assert "var(--ln-warning-text)" in active_block
    assert "var(--ln-positive-text)" in pending_block


def test_path_ui_only_uses_versioned_draft_endpoints() -> None:
    source = inspect.getsource(projects)

    assert 'f"/goals/{project_id}/path-revisions"' in source
    assert 'f"/path-revisions/{path_id}/clone"' in source
    assert 'f"/path-revisions/{path_id}/validate"' in source
    assert 'f"/path-revisions/{path_id}/activate"' in source
    assert 'f"/path-revisions/{path_id}/steps/{step_id}"' in source
    assert 'f"/goals/{project_id}/paths"' not in source
    assert "expected_revision" in source


def test_node_inspector_no_longer_mixes_framework_path_state_and_relations() -> None:
    source = inspect.getsource(projects._render_inspector)

    assert all(label not in source for label in ("框架属性", "路径设置", "状态与记录", "关系 ·"))
    assert 'f"/spaces/{space_id}/nodes/{node_id}"' not in source
    assert "f\"/path-revisions/{path_id}/steps/{path_step['id']}\"" not in source
    assert '"/learning-sessions"' not in source


def test_old_workbench_is_only_a_context_preserving_compatibility_redirect() -> None:
    source = inspect.getsource(workbench.register)

    assert "/projects/{target_goal['id']}/overview" in source
    assert "focus_mode" not in source
    assert '"/learning-sessions"' not in source


def test_new_project_route_redirects_to_shared_assistant_mode() -> None:
    source = inspect.getsource(onboarding.register)

    assert '@ui.page("/projects/new")' in source
    assert 'ui.navigate.to("/?ai=new-project")' in source
    assert 'active_path="/projects/new"' not in source
    assert "render_new_project_collaboration" not in source


def test_active_project_action_is_recoverable_and_reused_across_list_and_detail() -> None:
    dialog_source = inspect.getsource(projects._render_project_archive_dialog)
    actions_source = inspect.getsource(projects._render_project_actions)
    summary_source = inspect.getsource(projects._project_summary)
    register_source = inspect.getsource(projects.register)

    assert 'await client.post(f"/goals/{project_id}/archive")' in dialog_source
    assert "移到回收站" in dialog_source
    assert "可以恢复" in dialog_source
    assert "永久删除" not in dialog_source
    assert "urlencode({'archived': project_title})" in dialog_source
    assert "more_vert" in actions_source
    assert "aria-label='项目操作'" in actions_source
    assert "移到回收站" in actions_source
    assert "永久删除" not in actions_source
    assert "_render_project_actions(" in summary_source
    assert "_render_project_actions(" in register_source


def test_project_trash_is_the_only_surface_for_restore_and_permanent_delete() -> None:
    source = inspect.getsource(projects.register)
    permanent_source = inspect.getsource(projects._render_permanent_delete_dialog)

    assert "view: str | None = None" in source
    assert 'await client.get("/goals/archived")' in source
    assert 'await client.post(f"/goals/{project_id}/restore")' in source
    assert "回收站" in source
    assert "恢复项目" in source
    assert 'f"/goals/{project_id}",' in permanent_source
    assert 'json={"confirm_title": project_title}' in permanent_source
    assert "输入完整项目名称" in permanent_source
    assert "此操作不可恢复" in permanent_source
    assert '.props("color=negative disable")' in permanent_source


def test_project_list_acknowledges_archive_restore_and_permanent_deletion() -> None:
    source = inspect.getsource(projects.register)

    assert "archived: str | None = None" in source
    assert "restored: str | None = None" in source
    assert "deleted: str | None = None" in source
    assert 'dashboard = await client.get("/dashboard")' in source
    assert "首页与项目列表已同步" in source
    assert "已移到回收站" in source
    assert "已恢复" in source
    assert "aria-live='polite'" in source
    assert "下一路径节点：" in source
    assert "当前暂无下一路径节点" in source


def test_legacy_new_project_query_is_consumed_once_before_prompting() -> None:
    from learning_navigator.ui.pages import home

    source = inspect.getsource(home.register)
    assert "window.history.replaceState({}, '', '/')" in source
    assert "consume_new_project_intent" in source


def test_structural_delete_and_path_removal_require_confirmation() -> None:
    map_source = inspect.getsource(map_editor.register)
    project_source = inspect.getsource(projects._render_path)

    assert "_render_archive_confirmation" in map_source
    assert "归档后不会出现在当前框架" in inspect.getsource(map_editor._render_archive_confirmation)
    assert "node_delete_dialog.open" in map_source
    assert "永久删除节点" in inspect.getsource(
        map_editor._render_permanent_node_delete_confirmation
    )
    assert "路径引用、前置与解锁缓存、学习进度会同步清理" in inspect.getsource(
        map_editor._render_permanent_node_delete_confirmation
    )
    assert "edge_archive_dialog.open" in map_source
    assert "_render_path_step_remove_dialog" in project_source
    assert "只从当前路径草稿移除" in inspect.getsource(projects._render_path_step_remove_dialog)


def test_project_structure_editor_is_direct_and_supports_safe_removal() -> None:
    editor_source = inspect.getsource(projects._render_structure_editor)
    remove_source = inspect.getsource(projects._render_structure_remove_dialog)
    map_source = inspect.getsource(projects._render_map)

    assert "编辑框架与路径" in editor_source
    assert "按模块管理要素" in editor_source
    assert "添加要素" in editor_source
    assert "添加关系" in editor_source
    assert "group_framework_by_modules" in editor_source
    assert "add_module_button" in editor_source
    assert 'new_type.value = "MODULE"' in editor_source
    assert "保存并应用路径" in editor_source
    assert "加入路径" in editor_source
    assert "从路径移除" in editor_source
    assert "路径前移一步" in editor_source
    assert "路径后移一步" in editor_source
    assert "await client.patch(" in editor_source
    assert 'await client.delete(f"/spaces/{space_id}/nodes/{node_id}")' in editor_source
    assert 'await client.delete(f"/spaces/{space_id}/edges/{edge_id}")' in editor_source
    assert "永久删除" in remove_source
    assert "此操作不可撤销" in remove_source
    assert "先从路径移除" not in remove_source
    assert 'f"/spaces/{space_id}/outline"' in editor_source
    assert "data-outline-kind" in editor_source
    assert "dragstart" in editor_source
    assert "dragover" in editor_source
    assert "ungroupedNodeIds" in editor_source
    assert "路径先后顺序保持不变" in editor_source
    assert "_render_structure_editor(" in map_source
    assert "?edit=structure" in map_source


def test_framework_editor_groups_modules_and_keeps_path_order_as_projection() -> None:
    graph = {
        "nodes": [
            {"id": "module-a", "title": "基础", "node_type": "MODULE"},
            {"id": "module-b", "title": "进阶", "node_type": "MODULE"},
            {"id": "a-1", "title": "知识一", "node_type": "CONCEPT"},
            {"id": "a-2", "title": "知识二", "node_type": "SKILL"},
            {"id": "b-1", "title": "知识三", "node_type": "CONCEPT"},
        ],
        "edges": [
            {
                "source_node_id": "module-a",
                "target_node_id": child,
                "relation_type": "CONTAINS",
            }
            for child in ("a-1", "a-2")
        ]
        + [
            {
                "source_node_id": "module-b",
                "target_node_id": "b-1",
                "relation_type": "CONTAINS",
            }
        ],
    }
    route = [
        {"id": "step-b", "node_id": "b-1"},
        {"id": "step-a", "node_id": "a-2"},
    ]

    groups = group_framework_by_modules(graph, route)

    assert [group["title"] for group in groups] == ["进阶", "基础"]
    assert [group["knowledge_count"] for group in groups] == [1, 2]
    assert [group["path_step_count"] for group in groups] == [1, 1]
    by_id = {item["id"]: item for group in groups for item in group["items"]}
    assert by_id["a-1"]["path_step"] is None
    assert by_id["a-2"]["path_step"]["route_position"] == 2
    assert by_id["b-1"]["path_step"]["route_position"] == 1


def test_path_editor_prioritizes_common_actions_and_hides_versions_in_advanced_area() -> None:
    source = inspect.getsource(projects._render_path)

    assert "开始编辑" in source
    assert "添加步骤" in source
    assert "保存并应用" in source
    assert "移除步骤" in source
    assert "版本与 AI 建议（高级）" in source
    assert "历史版本" in source
    assert source.index("保存并应用") < source.index("版本与 AI 建议（高级）")


def test_node_menu_uses_the_same_simplified_structure_editor() -> None:
    source = inspect.getsource(projects._render_inspector)

    assert "编辑框架" in source
    assert 'project_href(project_id, "map") + "?edit=structure"' in source
    assert 'f"/maps/{space_id}/edit"' not in source


def test_framework_graph_uses_context_click_anchored_editing_and_live_sync() -> None:
    menu_source = inspect.getsource(projects._render_graph_context_menu)
    map_source = inspect.getsource(projects._render_map)

    assert '"chart:contextmenu"' in menu_source
    assert '"chart:click"' not in menu_source
    assert "preventDefault" in menu_source
    assert "pointerX" in menu_source
    assert "pointerY" in menu_source
    assert "ln-graph-node-menu" in menu_source
    assert "查看详情" in menu_source
    assert "编辑文字" in menu_source
    assert "编辑框架与路径" in menu_source
    assert "删除节点" in menu_source
    assert "data-ln-node-title-input" in menu_source
    assert "await ui.run_javascript(" in menu_source
    assert 'json={"title": title}' in menu_source
    assert "名称已同步到框架、路径与导航" in menu_source
    assert "count_label.set_text" in menu_source
    assert 'item.get("status") != "ARCHIVED"' in menu_source
    assert "右键节点可查看、编辑或删除" in map_source
    assert "editable=True" in map_source

    navigation_source = inspect.getsource(projects.build_full_map_options)
    assert '"context-menu" if editable else "pointer"' in navigation_source


def test_path_order_editor_saves_one_atomic_total_order() -> None:
    source = inspect.getsource(projects._render_path)

    assert "单独编辑先后顺序" in source
    assert "data-step-id" in source
    assert "dragstart" in source
    assert "保存顺序" in source
    assert "await client.put(" in source
    assert 'f"/path-revisions/{path_id}/order"' in source
