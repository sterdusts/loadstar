"""Contracts for the single project workspace and editable path flow."""

import inspect

from learning_navigator.ui.components import layout
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
        == "/projects/goal-1/overview?edit=path&revision=path-2&node=node-3"
    )


def test_project_workspace_has_one_small_navigation_hierarchy() -> None:
    assert projects.PROJECT_SECTIONS == (
        ("overview", "概览", "space_dashboard"),
        ("map", "框架", "hub"),
    )


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
    assert "for index, item in enumerate(route, start=1)" in overview_source
    assert "route[:" not in overview_source
    assert all(label in overview_source for label in ("当前路径", "总体进度", "最近打卡"))
    assert "recent_check_ins" in overview_source
    assert "path_revision_href(project_id)" in overview_source

    assert 'editing_path = section == "overview" and edit == "path"' in page_source
    revision_selection = (
        "_selected_edit_revision(revisions, revision_id) if editing_path else active_revision"
    )
    assert revision_selection in page_source
    assert 'elif section == "path"' not in page_source
    assert 'elif section == "progress"' not in page_source
    assert not hasattr(projects, "_render_progress")


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


def test_structural_archive_and_path_removal_require_confirmation() -> None:
    map_source = inspect.getsource(map_editor.register)
    project_source = inspect.getsource(projects._render_path)

    assert "_render_archive_confirmation" in map_source
    assert "归档后不会出现在当前框架" in inspect.getsource(map_editor._render_archive_confirmation)
    assert "node_archive_dialog.open" in map_source
    assert "edge_archive_dialog.open" in map_source
    assert "_render_path_step_remove_dialog" in project_source
    assert "只从当前路径草稿移除" in inspect.getsource(projects._render_path_step_remove_dialog)
