"""Unified project workspace for maps, paths, state and activity."""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from nicegui import events, ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.components.navigation import (
    build_full_map_options,
    full_map_height,
    group_framework_by_modules,
    group_route_by_modules,
)
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    build_parallel_dashboard_view_model,
    intent_action_label,
    intent_profile,
    intent_progress_label,
    intent_status_label,
    localize_route_reason,
)

PROJECT_SECTIONS = (
    ("overview", "概览", "space_dashboard"),
    ("map", "框架", "hub"),
    ("mindmap", "脑图", "account_tree"),
)

NODE_TYPE_OPTIONS = {
    "MODULE": "框架模块",
    "CONCEPT": "核心概念",
    "SKILL": "关键能力",
    "PROCEDURE": "方法步骤",
    "PROJECT": "综合成果",
    "ASSESSMENT": "验证节点",
    "QUESTION": "关键问题",
    "ENTITY": "关键对象",
    "MECHANISM": "作用机制",
    "EVIDENCE": "事实证据",
    "MILESTONE": "推进里程碑",
    "DECISION": "关键决策",
    "DELIVERABLE": "交付物",
    "RISK": "风险与未知",
}

RELATION_TYPE_OPTIONS = {
    "PREREQUISITE": "前置",
    "RELATED": "相关",
    "APPLIES_TO": "应用于",
    "EXTENDS": "扩展",
    "SUPPORTS": "支持",
    "CONSTRAINS": "约束",
    "VALIDATES": "验证",
    "ENABLES": "促进",
}


def project_href(project_id: str, section: str = "overview", *, node_id: str | None = None) -> str:
    href = f"/projects/{quote(project_id, safe='')}/{section}"
    if node_id:
        href += f"?node={quote(node_id, safe='')}"
    return href


def path_revision_href(
    project_id: str,
    revision_id: str | None = None,
    *,
    node_id: str | None = None,
) -> str:
    """Compatibility link into the unified framework and path editor."""

    params = [("edit", "structure")]
    if revision_id:
        params.append(("revision", revision_id))
    if node_id:
        params.append(("node", node_id))
    return f"{project_href(project_id, 'map')}?{urlencode(params)}"


def framework_editor_href(
    project_id: str,
    revision_id: str | None = None,
    *,
    node_id: str | None = None,
) -> str:
    return path_revision_href(project_id, revision_id, node_id=node_id)


def _active_path_revision(revisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in revisions
            if isinstance(item.get("path"), dict) and item["path"].get("status") == "ACTIVE"
        ),
        None,
    )


def _selected_edit_revision(
    revisions: list[dict[str, Any]],
    revision_id: str | None,
) -> dict[str, Any] | None:
    if revision_id:
        selected = next(
            (
                item
                for item in revisions
                if str((item.get("path") or {}).get("id") or "") == revision_id
            ),
            None,
        )
        if selected is not None:
            return selected
    return next(
        (
            item
            for item in revisions
            if isinstance(item.get("path"), dict) and item["path"].get("status") == "DRAFT"
        ),
        next(
            (
                item
                for item in revisions
                if isinstance(item.get("path"), dict) and item["path"].get("status") == "ACTIVE"
            ),
            revisions[0] if revisions else None,
        ),
    )


def _route_progress_state(item: dict[str, Any]) -> tuple[str, str, str]:
    """Return the display-only progress state, label and icon for one active-route step."""

    state = str(item.get("display_progress_state") or "").upper()
    if state == "COMPLETED":
        return "completed", "已完成", "check_circle"
    if state == "IN_PROGRESS":
        return "active", "进行中", "pending"
    if state in {"NOT_STARTED", "PENDING"}:
        return "pending", "未进行", "play_circle"

    score = item.get("progress_score")
    if isinstance(score, (int, float)):
        if score >= 10:
            return "completed", "已完成", "check_circle"
        if score > 0:
            return "active", "进行中", "pending"

    status = str(item.get("status") or "").upper()
    if status == "MASTERED":
        return "completed", "已完成", "check_circle"
    if status in {"IN_PROGRESS", "NEEDS_REVIEW"}:
        return "active", "进行中", "pending"
    return "pending", "未进行", "play_circle"


def _assistant_progress_status(item: dict[str, Any]) -> str:
    state = _route_progress_state(item)[0]
    return {
        "completed": "COMPLETED",
        "active": "IN_PROGRESS",
        "pending": "NOT_STARTED",
    }[state]


def _assistant_page_node(
    item: dict[str, Any],
    *,
    position: int | None = None,
) -> dict[str, Any]:
    node_id = str(item.get("node_id") or item.get("id") or "").strip()
    result: dict[str, Any] = {
        "name": str(item.get("title") or "未命名要素"),
        "status": _assistant_progress_status(item),
    }
    if node_id:
        result["node_id"] = node_id
    if position is not None:
        result["path_position"] = position
    score = item.get("progress_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        result["score"] = int(score)
    return result


def _build_assistant_page_state(
    project: dict[str, Any],
    selected_node: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project facts visible on this page, bounded later by AssistantPageContext."""

    route_items = _dict_items(project.get("route"))
    route_states = [_route_progress_state(item)[0] for item in route_items]
    completed = int(project.get("completed_count") or route_states.count("completed"))
    in_progress = int(project.get("in_progress_count") or route_states.count("active"))
    total = len(route_items)
    steps = [
        _assistant_page_node(item, position=index)
        for index, item in enumerate(route_items, start=1)
    ]

    current_source = selected_node
    if current_source is None:
        candidate = project.get("current_position") or project.get("next_step")
        current_source = candidate if isinstance(candidate, dict) else None
    current_node = None
    if isinstance(current_source, dict):
        current_id = str(current_source.get("node_id") or current_source.get("id") or "")
        position = next(
            (
                index
                for index, item in enumerate(route_items, start=1)
                if str(item.get("node_id") or item.get("id") or "") == current_id
            ),
            None,
        )
        route_source = next(
            (
                item
                for item in route_items
                if str(item.get("node_id") or item.get("id") or "") == current_id
            ),
            current_source,
        )
        current_node = _assistant_page_node(route_source, position=position)

    page_state: dict[str, Any] = {
        "project_title": str(project.get("goal_title") or "当前项目"),
        "path_summary": {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "not_started": max(total - completed - in_progress, 0),
            "steps": steps,
        },
        "progress_summary": {
            "percent": int(project.get("progress_percent") or 0),
            "completed": completed,
            "total": total,
        },
    }
    if current_node:
        page_state["current_node"] = current_node
    return page_state


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _project_overview_counts(
    nodes: list[dict[str, Any]],
    route: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Keep framework modules, content nodes, and route steps mutually distinct."""

    visible_nodes = [item for item in nodes if item.get("status") != "ARCHIVED"]
    module_count = sum(item.get("node_type") == "MODULE" for item in visible_nodes)
    knowledge_count = sum(item.get("node_type") != "MODULE" for item in visible_nodes)
    actionable_ids = {
        str(item.get("id") or "")
        for item in visible_nodes
        if item.get("node_type") != "MODULE" and item.get("id")
    }
    route_step_count = sum(str(item.get("node_id") or "") in actionable_ids for item in route)
    return module_count, knowledge_count, route_step_count


def _project_structure_diagnostics(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    route: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe persisted hierarchy defects without inventing module membership."""

    visible_nodes = [item for item in nodes if item.get("status") != "ARCHIVED"]
    module_ids = {
        str(item.get("id"))
        for item in visible_nodes
        if item.get("node_type") == "MODULE" and item.get("id")
    }
    content_ids = {
        str(item.get("id"))
        for item in visible_nodes
        if item.get("node_type") != "MODULE" and item.get("id")
    }
    children_by_module: dict[str, set[str]] = {module_id: set() for module_id in module_ids}
    parents_by_content: dict[str, set[str]] = {content_id: set() for content_id in content_ids}
    for edge in edges:
        if edge.get("status") == "ARCHIVED" or edge.get("relation_type") != "CONTAINS":
            continue
        source_id = str(edge.get("source_node_id") or "")
        target_id = str(edge.get("target_node_id") or "")
        if source_id in module_ids and target_id in content_ids:
            children_by_module[source_id].add(target_id)
            parents_by_content[target_id].add(source_id)
    empty_modules = sorted(
        module_id for module_id, children in children_by_module.items() if not children
    )
    ungrouped_content = sorted(
        content_id for content_id, parents in parents_by_content.items() if not parents
    )
    multiply_grouped_content = sorted(
        content_id for content_id, parents in parents_by_content.items() if len(parents) > 1
    )
    route_ids = {
        str(item.get("node_id") or "")
        for item in route
        if str(item.get("node_id") or "") in content_ids
    }
    modules_missing_from_route = sorted(
        module_id
        for module_id, children in children_by_module.items()
        if children and route_ids.isdisjoint(children)
    )
    return {
        "empty_module_count": len(empty_modules),
        "ungrouped_content_count": len(ungrouped_content),
        "multiply_grouped_content_count": len(multiply_grouped_content),
        "route_coverage_count": len(route_ids),
        "content_count": len(content_ids),
        "modules_missing_from_route_count": len(modules_missing_from_route),
        "malformed": bool(
            module_ids and (empty_modules or ungrouped_content or multiply_grouped_content)
        ),
    }


def _archived_project_items(value: Any) -> list[dict[str, str]]:
    """Normalize the recycle-bin projection without trusting transport shape."""

    source = value.get("items", value.get("goals", [])) if isinstance(value, dict) else value
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in _dict_items(source):
        goal_value = raw.get("goal")
        goal: dict[str, Any] = goal_value if isinstance(goal_value, dict) else raw
        project_id = str(goal.get("id") or raw.get("goal_id") or "").strip()
        status = str(goal.get("status") or raw.get("status") or "ARCHIVED").upper()
        if not project_id or project_id in seen or status != "ARCHIVED":
            continue
        seen.add(project_id)
        items.append(
            {
                "id": project_id,
                "title": str(goal.get("title") or raw.get("goal_title") or "未命名项目"),
                "archived_at": str(goal.get("archived_at") or raw.get("archived_at") or ""),
            }
        )
    items.sort(key=lambda item: item["archived_at"], reverse=True)
    return items


def _project_view(dashboard: Any, project_id: str) -> dict[str, Any] | None:
    view = build_parallel_dashboard_view_model(dashboard, focused_goal_id=project_id)
    for project in _dict_items(view.get("goals")):
        if project.get("goal_id") == project_id:
            return project
    return None


def _project_navigation(
    project_id: str,
    active_section: str,
    *,
    on_switch: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    tabs: dict[str, Any] = {}
    with ui.element("nav").classes("ln-project-tabs").props("aria-label='项目导航'"):
        for section, label, icon in PROJECT_SECTIONS:
            classes = "ln-project-tab"
            if section == active_section:
                classes += " ln-project-tab-active"
            tab: Any
            if on_switch is None:
                tab = ui.link("", project_href(project_id, section)).classes(classes)
            else:

                async def switch(target: str = section) -> None:
                    await on_switch(target)

                tab = ui.button(on_click=switch).classes(classes).props("flat no-caps")
            tabs[section] = tab
            with tab:
                if section == active_section:
                    tab.props("aria-current=page")
                with ui.row().classes("items-center gap-1.5 flex-nowrap"):
                    ui.icon(icon).classes("text-base")
                    ui.label(label)
    return tabs


def _render_project_archive_dialog(
    client: UIAPIClient,
    *,
    project_id: str,
    project_title: str,
) -> Any:
    archiving = {"active": False}
    with (
        ui.dialog() as dialog,
        ui.card()
        .classes("gap-5 p-6")
        .style("width:min(440px, calc(100vw - 24px));max-width:440px"),
    ):
        with ui.row().classes("w-full items-start gap-3 flex-nowrap"):
            ui.icon("inventory_2", color="warning").classes("mt-0.5 text-2xl")
            with ui.column().classes("min-w-0 gap-1"):
                ui.label(f"将“{project_title}”移到回收站？").classes("text-xl font-black")
                ui.label(
                    "它会从首页、项目列表和导航中隐藏；框架、路径、进度与对话都会保留，"
                    "之后可以从回收站恢复。"
                ).classes("text-sm leading-6 text-gray-600")
        ui.label("移入后不会丢失数据，可以恢复。").classes(
            "rounded-lg bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900"
        )

        async def archive_project() -> None:
            if archiving["active"]:
                return
            archiving["active"] = True
            archive_button.props("loading disable")
            try:
                await client.post(f"/goals/{project_id}/archive")
            except UIAPIError as exc:
                archiving["active"] = False
                archive_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            ui.notify(
                f"“{project_title}”已移到回收站，可随时恢复。",
                type="positive",
            )
            ui.navigate.to(f"/projects?{urlencode({'archived': project_title})}")

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat autofocus").classes(
                "max-sm:w-full"
            )
            archive_button = (
                ui.button(
                    "移到回收站",
                    icon="inventory_2",
                    on_click=archive_project,
                )
                .props("color=warning text-color=black")
                .classes("max-sm:w-full")
            )
    dialog.props("aria-label='移到回收站确认' role='alertdialog'")
    return dialog


def _render_permanent_delete_dialog(
    client: UIAPIClient,
    *,
    project_id: str,
    project_title: str,
) -> Any:
    """Render irreversible deletion only for an item already in the recycle bin."""

    deleting = {"active": False}
    with (
        ui.dialog() as dialog,
        ui.card()
        .classes("gap-5 p-6")
        .style("width:min(440px, calc(100vw - 24px));max-width:440px"),
    ):
        with ui.row().classes("w-full items-start gap-3 flex-nowrap"):
            ui.icon("warning_amber", color="negative").classes("mt-0.5 text-2xl")
            with ui.column().classes("min-w-0 gap-1"):
                ui.label(f"永久删除“{project_title}”？").classes("text-xl font-black")
                ui.label(
                    "项目及其专属框架、路径、进度记录和项目对话将被永久删除；"
                    "其他项目及其中的同名节点不会被删除。"
                ).classes("text-sm leading-6 text-gray-600")
        ui.label("此操作不可恢复。请输入完整项目名称确认。").classes(
            "rounded-lg bg-red-50 px-3 py-2 text-xs font-bold text-red-800"
        )
        confirmation = (
            ui.input(
                label=f"输入“{project_title}”确认永久删除",
                placeholder=project_title,
            )
            .classes("w-full")
            .props("outlined autocomplete=off")
        )

        def sync_delete_button() -> None:
            if str(confirmation.value or "") == project_title:
                delete_button.props(remove="disable")
            else:
                delete_button.props("disable")

        async def delete_project() -> None:
            if deleting["active"]:
                return
            if str(confirmation.value or "") != project_title:
                ui.notify("请输入完整项目名称后再永久删除。", type="warning")
                return
            deleting["active"] = True
            delete_button.props("loading disable")
            try:
                await client.delete(
                    f"/goals/{project_id}",
                    json={"confirm_title": project_title},
                )
            except UIAPIError as exc:
                deleting["active"] = False
                delete_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            ui.notify(f"“{project_title}”已永久删除。", type="positive")
            params = urlencode({"view": "trash", "deleted": project_title})
            ui.navigate.to(f"/projects?{params}")

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat autofocus").classes(
                "max-sm:w-full"
            )
            delete_button = (
                ui.button("永久删除", icon="delete_forever", on_click=delete_project)
                .props("color=negative disable")
                .classes("max-sm:w-full")
            )
        confirmation.on_value_change(lambda _: sync_delete_button())
    dialog.props("aria-label='永久删除项目确认' role='alertdialog'")
    return dialog


def _render_project_actions(
    client: UIAPIClient,
    *,
    project_id: str,
    project_title: str,
) -> None:
    dialog = _render_project_archive_dialog(
        client,
        project_id=project_id,
        project_title=project_title,
    )
    with (
        ui.button(icon="more_vert")
        .classes("h-10 w-10 shrink-0")
        .props("flat round dense aria-label='项目操作'")
    ):
        ui.tooltip("项目操作")
        with ui.menu():
            ui.menu_item("移到回收站", on_click=dialog.open)


def _project_summary(client: UIAPIClient, project: dict[str, Any]) -> None:
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    copy = intent_profile(goal)
    with ui.element("section").classes("ln-project-summary"):
        with ui.column().classes("min-w-0 gap-1"):
            ui.label(copy["mode_label"]).classes("ln-kicker")
            ui.label(project["goal_title"]).classes("line-clamp-2 text-lg font-black sm:text-xl")
            current = project.get("current_position")
            if isinstance(current, dict):
                ui.label(f"当前位置 · {current['title']}").classes("text-sm text-gray-600")
        with ui.column().classes("w-40 shrink-0 items-end gap-1 max-sm:w-32"):
            with ui.row().classes("w-full items-center justify-end gap-1 flex-nowrap"):
                ui.label(f"{project['progress_percent']}%").classes("text-xl font-black")
                _render_project_actions(
                    client,
                    project_id=str(project["goal_id"]),
                    project_title=str(project["goal_title"]),
                )
            ui.linear_progress(value=project["progress_percent"] / 100).classes("w-full").props(
                "rounded color=positive"
            )


def _node_link(project_id: str, section: str, node: dict[str, Any]) -> None:
    with ui.link("", project_href(project_id, section, node_id=str(node["id"]))).classes(
        "w-full no-underline"
    ):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("min-w-0 gap-0"):
                ui.label(str(node.get("title") or "未命名要素")).classes(
                    "truncate font-bold text-gray-900"
                )
                description = str(node.get("description") or "").strip()
                if description:
                    ui.label(description).classes("line-clamp-1 text-xs text-gray-500")
            status = str(node.get("computed_status") or "NOT_RELEVANT")
            ui.label(intent_status_label(status)).classes(
                f"ln-status-{status} shrink-0 rounded-full px-2 py-1 text-xs font-bold"
            )


def _render_overview(
    project: dict[str, Any],
    graph: dict[str, Any],
    *,
    project_id: str,
    on_select_node: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    copy = intent_profile(goal)
    next_step = project.get("next_step")
    nodes = [item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"]
    route = _dict_items(project.get("route"))
    route_groups = group_route_by_modules(graph, route)
    routed_module_count = sum(
        bool(group.get("module_id")) and bool(_dict_items(group.get("steps")))
        for group in route_groups
    )
    ungrouped_route_count = sum(
        len(_dict_items(group.get("steps"))) for group in route_groups if not group.get("module_id")
    )
    module_count, knowledge_count, route_step_count = _project_overview_counts(nodes, route)
    structure = _project_structure_diagnostics(nodes, _dict_items(graph.get("edges")), route)
    route_states = [_route_progress_state(item)[0] for item in route]
    completed_count = int(project.get("completed_count") or route_states.count("completed"))
    in_progress_count = int(project.get("in_progress_count") or route_states.count("active"))
    progress_percent = int(project.get("progress_percent") or 0)

    with ui.grid().classes(
        "w-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,.65fr)]"
    ):
        with ui.card().classes("ln-card ln-focus-card min-w-0 p-5 sm:p-6"):
            if isinstance(next_step, dict):
                ui.label(copy["next_kicker"]).classes("ln-kicker")
                ui.label(next_step["title"]).classes("mt-1 text-2xl font-black sm:text-3xl")
                ui.label(next_step["reason"]).classes(
                    "mt-2 max-w-3xl text-sm leading-6 text-gray-600"
                )
                with ui.row().classes("mt-4 flex-wrap gap-2"):

                    async def open_next_step() -> None:
                        if on_select_node is not None:
                            await on_select_node(str(next_step["node_id"]))

                    async def locate_next_step() -> None:
                        if on_select_node is not None:
                            await on_select_node(str(next_step["node_id"]))
                        await ui.run_javascript(
                            "document.getElementById('current-route')?.scrollIntoView({"
                            "behavior:'smooth',block:'start'});"
                        )

                    ui.button(
                        intent_action_label(next_step["status"], goal),
                        icon="play_arrow",
                        on_click=(
                            open_next_step
                            if on_select_node is not None
                            else lambda: ui.navigate.to(
                                project_href(
                                    project_id,
                                    "overview",
                                    node_id=next_step["node_id"],
                                )
                                + "&panel=action"
                            )
                        ),
                    ).classes("ln-action-button").props("color=positive")
                    ui.button(
                        "查看路径位置",
                        icon="route",
                        on_click=(
                            locate_next_step
                            if on_select_node is not None
                            else lambda: ui.navigate.to(
                                project_href(
                                    project_id,
                                    "overview",
                                    node_id=next_step["node_id"],
                                )
                                + "#current-route"
                            )
                        ),
                    ).props("outline color=positive")
            else:
                if route and completed_count == len(route):
                    ui.label("当前路径已完成").classes("text-xl font-black")
                    ui.label(
                        f"已完成全部 {len(route)} 个步骤。可以查看进展复盘，或继续完善框架。"
                    ).classes("mt-1 text-sm text-gray-600")
                    with ui.row().classes("mt-3 flex-wrap gap-2"):
                        ui.link("查看进展", "/growth").classes("font-bold no-underline")
                        ui.link("完善框架", project_href(project_id, "map")).classes(
                            "font-bold no-underline"
                        )
                else:
                    ui.label("当前没有可推进项").classes("text-xl font-black")
                    ui.label("检查当前路径，或进入编辑后调整步骤。 ").classes(
                        "mt-1 text-sm text-gray-600"
                    )
                    ui.link("编辑框架与路径", path_revision_href(project_id)).classes(
                        "mt-3 font-bold"
                    )

        with ui.card().classes("ln-card min-w-0 p-5"):
            ui.label("项目全貌").classes("text-lg font-black")
            with ui.grid().classes("mt-3 w-full grid-cols-3 gap-2"):
                for value, label in (
                    (module_count, f"{copy['module_label']}（结构）"),
                    (knowledge_count, f"{copy['node_label']}（不含模块）"),
                    (route_step_count, "路径步骤"),
                ):
                    with ui.column().classes("items-center gap-1 rounded-xl bg-green-50 p-3"):
                        ui.label(str(value)).classes("text-xl font-black text-green-800")
                        ui.label(label).classes("text-center text-xs text-gray-600")
            ui.link("打开完整框架", project_href(project_id, "map")).classes(
                "mt-4 block font-bold no-underline"
            )

    if structure["malformed"]:
        with ui.card().classes(
            "ln-card w-full border border-amber-400 bg-amber-50 p-4 text-amber-950"
        ):
            ui.label("当前项目使用旧版不完整结构").classes("font-black")
            ui.label(
                f"{structure['empty_module_count']} 个空模块、"
                f"{structure['ungrouped_content_count']} 个未归类{copy['node_label']}；"
                f"路径覆盖 {structure['route_coverage_count']}/"
                f"{structure['content_count']} 个{copy['node_label']}。"
            ).classes("text-sm")
            ui.label(
                f"上方的 {knowledge_count} 个{copy['node_label']}不包含 {module_count} 个模块；"
                "系统不会再猜测错误归属，修订后框架、脑图和路径会使用同一结构。"
            ).classes("text-xs text-amber-800")
            ui.link("修订框架与路径", path_revision_href(project_id)).classes(
                "mt-2 font-bold text-amber-900"
            )

    with ui.card().classes("ln-card mt-4 w-full p-4 sm:p-5").props("id=current-route"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("min-w-0 gap-0"):
                ui.label("当前路径").classes("text-lg font-black")
                route_summary = f"{routed_module_count} 个模块 · {len(route)} 个步骤"
                if ungrouped_route_count:
                    route_summary += f" · {ungrouped_route_count} 步未归类"
                ui.label(f"{route_summary}；按顺序推进，打卡后自动更新。").classes(
                    "text-xs text-gray-500"
                )
            ui.link("编辑框架与路径", path_revision_href(project_id)).classes(
                "shrink-0 text-sm font-bold no-underline"
            )

        if not route:
            with ui.column().classes("ln-empty mt-4 w-full items-start gap-3"):
                ui.label("尚未启用路径")
                ui.button(
                    "创建路径",
                    icon="route",
                    on_click=lambda: ui.navigate.to(path_revision_href(project_id)),
                ).props("outline color=positive")
            return

        with ui.grid().classes(
            "mt-4 w-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,.34fr)]"
        ):
            with ui.column().classes("min-w-0 gap-3"):
                for group in route_groups:
                    group_steps = _dict_items(group.get("steps"))
                    with ui.element("section").classes("ln-route-module w-full"):
                        with ui.row().classes("ln-route-module-header w-full items-center gap-3"):
                            module_sequence = group.get("module_sequence")
                            if module_sequence is not None:
                                ui.label(str(module_sequence)).classes("ln-route-module-number")
                            with ui.column().classes("min-w-0 grow gap-0"):
                                ui.label(str(group.get("title") or "未命名模块")).classes(
                                    "truncate font-black"
                                )
                                ui.label(
                                    f"{len(group_steps)} 步 · "
                                    f"{int(group.get('knowledge_count') or 0)} 个知识点"
                                ).classes("text-xs text-gray-500")

                        with ui.column().classes("ln-route-module-steps w-full gap-1"):
                            if not group_steps:
                                ui.label("当前路径尚未安排此模块的步骤").classes(
                                    "px-4 py-3 text-xs text-gray-500"
                                )
                            for item in group_steps:
                                index = int(item.get("route_position") or 0)
                                state, state_label, _ = _route_progress_state(item)
                                route_row: Any
                                if on_select_node is None:
                                    route_row = ui.link(
                                        "",
                                        project_href(
                                            project_id,
                                            "overview",
                                            node_id=str(item["node_id"]),
                                        ),
                                    )
                                else:

                                    async def select_route_node(
                                        target: str = str(item["node_id"]),
                                    ) -> None:
                                        await on_select_node(target)

                                    route_row = ui.button(on_click=select_route_node).props(
                                        "flat no-caps align=left"
                                    )
                                with route_row.classes(
                                    f"ln-route-row ln-route-state-{state} w-full no-underline"
                                ):
                                    ui.label(str(index)).classes("ln-route-number")
                                    with ui.column().classes("min-w-0 grow gap-0"):
                                        ui.label(str(item.get("title") or "未命名步骤")).classes(
                                            "ln-route-step-title truncate font-bold"
                                        )
                                        reason = str(item.get("reason") or "").strip()
                                        if reason:
                                            ui.label(reason).classes(
                                                "line-clamp-1 text-xs leading-5 text-gray-500"
                                            )
                                    with ui.row().classes(
                                        "ln-route-state-label shrink-0 items-center gap-1 "
                                        "flex-nowrap"
                                    ):
                                        ui.label(state_label).classes("text-xs font-bold")

            with ui.column().classes("ln-route-progress-summary min-w-0 gap-3"):
                with ui.row().classes("w-full items-end justify-between gap-3"):
                    with ui.column().classes("gap-0"):
                        ui.label("总体进度").classes("text-xs font-bold text-gray-500")
                        ui.label(f"{progress_percent}%").classes("text-3xl font-black")
                    ui.label(f"{completed_count}/{len(route)} 完成").classes(
                        "text-xs font-bold text-gray-600"
                    )
                ui.linear_progress(value=progress_percent / 100).classes("w-full").props(
                    "rounded color=positive"
                )
                with ui.row().classes("w-full flex-wrap gap-2"):
                    ui.label(f"{in_progress_count} 进行中").classes(
                        "ln-route-state-active ln-route-state-label text-xs font-bold"
                    )
                    ui.label(f"{len(route) - completed_count - in_progress_count} 未进行").classes(
                        "ln-route-state-pending ln-route-state-label text-xs font-bold"
                    )

                recent_check_ins = _dict_items(project.get("recent_check_ins"))
                if recent_check_ins:
                    ui.separator().classes("my-1")
                    ui.label("最近打卡").classes("text-sm font-black")
                    for check_in in recent_check_ins[:4]:
                        checked_at = str(check_in.get("checked_in_at") or "").replace("T", " ")[:16]
                        with ui.column().classes(
                            "gap-0 border-b border-gray-100 pb-2 last:border-0"
                        ):
                            check_in_title = str(check_in.get("title") or "路径步骤")
                            check_in_score = check_in.get("score", "-")
                            ui.label(f"{check_in_title} · {check_in_score} 分").classes(
                                "line-clamp-1 text-xs font-bold"
                            )
                            with ui.row().classes("w-full justify-between gap-2"):
                                note = str(check_in.get("note") or "").strip()
                                if note:
                                    ui.label(note).classes(
                                        "line-clamp-1 min-w-0 text-xs text-gray-500"
                                    )
                                ui.label(checked_at).classes(
                                    "ml-auto shrink-0 text-xs text-gray-500"
                                )


def _render_structure_remove_dialog(
    *,
    title: str,
    kind: str,
    impact: str,
    on_confirm: Any,
) -> Any:
    """Confirm one permanent, synchronized framework deletion."""

    with (
        ui.dialog() as dialog,
        ui.card()
        .classes("gap-4 p-6")
        .style("width:min(440px, calc(100vw - 24px));max-width:440px"),
    ):
        with ui.row().classes("w-full items-start gap-3 flex-nowrap"):
            ui.icon("delete_outline", color="warning").classes("mt-0.5 text-2xl")
            with ui.column().classes("min-w-0 gap-1"):
                ui.label(f"永久删除{kind}“{title}”？").classes("text-xl font-black")
                ui.label(impact).classes("text-sm leading-6 text-gray-600")
        ui.label("此操作不可撤销。").classes(
            "rounded-lg bg-red-50 px-3 py-2 text-sm font-bold text-red-900"
        )
        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat autofocus")
            ui.button(
                f"永久删除{kind}",
                icon="delete_forever",
                on_click=on_confirm,
            ).props("color=negative no-caps")
    dialog.props(f"aria-label='永久删除{kind}确认' role='alertdialog'")
    return dialog


def _render_graph_context_menu(
    *,
    project: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    chart: Any,
    count_label: Any,
    project_id: str,
    space_id: str,
    client: UIAPIClient,
) -> None:
    """Attach one graph-native edit surface to the ECharts canvas."""

    node_by_id = {str(item.get("id") or ""): item for item in nodes}
    state: dict[str, Any] = {
        "node_id": None,
        "title": "",
        "description": "",
        "node_type": "CONCEPT",
    }

    async def refresh_chart() -> None:
        try:
            graph = await client.get(f"/spaces/{space_id}/graph")
            dashboard = await client.get("/dashboard")
            refreshed_project = _project_view(dashboard, project_id) or project
            refreshed_nodes = _dict_items(graph.get("nodes"))
            refreshed_edges = _dict_items(graph.get("edges"))
            active_nodes = [item for item in refreshed_nodes if item.get("status") != "ARCHIVED"]
            active_edges = [item for item in refreshed_edges if item.get("status") != "ARCHIVED"]
            semantic_edges = [
                item for item in active_edges if item.get("relation_type") != "CONTAINS"
            ]
            module_count, element_count, _ = _project_overview_counts(active_nodes, [])
            count_label.set_text(
                f"{module_count} 个模块 · {element_count} 个要素 · {len(semantic_edges)} 条关系"
            )
            node_by_id.clear()
            node_by_id.update(
                {
                    str(item.get("id") or ""): item
                    for item in refreshed_nodes
                    if item.get("status") != "ARCHIVED"
                }
            )
            next_options = build_full_map_options(
                graph,
                refreshed_project.get("route", []),
                intent_context=refreshed_project.get("goal", {}),
                editable=True,
            )
            chart.options.clear()
            chart.options.update(next_options)
            chart.update()
        except UIAPIError as exc:
            error_notice(str(exc))

    async def save_inline_title() -> None:
        node_id = str(state.get("node_id") or "")
        # Read the live DOM value here. NiceGUI may not have propagated the
        # latest keystroke to ``title_input.value`` when the user immediately
        # clicks Save or presses Enter.
        live_title = await ui.run_javascript(
            "document.querySelector('[data-ln-node-title-input]')?.value ?? ''"
        )
        title = str(live_title or "").strip()
        if not node_id or not title:
            ui.notify("名称不能为空", type="warning")
            return
        try:
            await client.patch(
                f"/spaces/{space_id}/nodes/{node_id}",
                json={"title": title},
            )
            state["title"] = title
            edit_dialog.close()
            ui.notify("名称已同步到框架、路径与导航", type="positive")
            await refresh_chart()
        except UIAPIError as exc:
            error_notice(str(exc))

    async def archive_selected_node() -> None:
        node_id = str(state.get("node_id") or "")
        if not node_id:
            return
        try:
            await client.delete(f"/spaces/{space_id}/nodes/{node_id}")
            remove_dialog.close()
            ui.notify("节点、关系、路径引用和进度已永久删除并同步", type="positive")
            await refresh_chart()
        except UIAPIError as exc:
            error_notice(str(exc))

    def open_edit_dialog() -> None:
        node_action_popup.set_visibility(False)
        title_input.value = str(state.get("title") or "")
        edit_dialog.open()

    async def open_remove_dialog() -> None:
        node_action_popup.set_visibility(False)
        node_id = str(state.get("node_id") or "")
        kind = "模块" if state.get("node_type") == "MODULE" else "节点"
        remove_title.set_text(f"永久删除{kind}“{state.get('title') or '未命名节点'}”？")
        remove_message.set_text("正在核对受影响的关系、路径和学习记录……")
        remove_dialog.open()
        try:
            impact = await client.get(f"/spaces/{space_id}/nodes/{node_id}/delete-impact")
            child_count = int(impact.get("module_child_count") or 0)
            remove_message.set_text(
                f"将同步删除 {1 + child_count} 个框架要素、"
                f"{int(impact.get('relationship_count') or 0)} 条关系、"
                f"{int(impact.get('path_count') or 0)} 条路径中的引用和 "
                f"{int(impact.get('progress_record_count') or 0)} 条进度记录。"
            )
        except UIAPIError as exc:
            remove_dialog.close()
            error_notice(str(exc))

    with (
        ui.dialog() as edit_dialog,
        ui.card().classes("ln-inline-node-editor gap-3 p-4"),
    ):
        ui.label("编辑节点文字").classes("text-lg font-black")
        title_input = (
            ui.input("名称")
            .props("outlined autofocus clearable data-ln-node-title-input")
            .classes("w-full")
        )
        ui.label("只修改名称，不改变节点身份、关系或路径位置。").classes("text-xs text-gray-500")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=edit_dialog.close).props("flat no-caps")
            ui.button("保存", icon="check", on_click=save_inline_title).props(
                "color=positive no-caps"
            )

    title_input.on("keydown.enter", save_inline_title)

    with (
        ui.dialog() as remove_dialog,
        ui.card().classes("gap-3 p-5").style("width:min(440px,calc(100vw - 24px))"),
    ):
        remove_title = ui.label("永久删除节点？").classes("text-lg font-black")
        remove_message = ui.label("").classes("text-sm leading-6 text-gray-600")
        with ui.row().classes("w-full justify-end gap-2 max-sm:flex-col-reverse"):
            ui.button("取消", on_click=remove_dialog.close).props("flat no-caps")
            ui.button(
                "永久删除",
                icon="delete_forever",
                on_click=archive_selected_node,
            ).props("color=negative no-caps")

    def open_node_details() -> None:
        node_action_popup.set_visibility(False)
        node_id = str(state.get("node_id") or "")
        if node_id:
            ui.navigate.to(project_href(project_id, "map", node_id=node_id))

    def open_path_order_editor() -> None:
        node_action_popup.set_visibility(False)
        ui.navigate.to(path_revision_href(project_id))

    with (
        ui.card()
        .props("role=menu aria-label='节点操作'")
        .classes("ln-graph-node-menu gap-1 p-1") as node_action_popup
    ):
        ui.button("查看详情", icon="visibility", on_click=open_node_details).props(
            "flat dense no-caps align=left"
        ).classes("w-full justify-start")
        ui.button("编辑文字", icon="edit", on_click=open_edit_dialog).props(
            "flat dense no-caps align=left"
        ).classes("w-full justify-start")
        ui.button("编辑框架与路径", icon="route", on_click=open_path_order_editor).props(
            "flat dense no-caps align=left"
        ).classes("w-full justify-start")
        ui.separator()
        ui.button("删除节点", icon="delete_outline", on_click=open_remove_dialog).props(
            "flat dense no-caps align=left color=negative"
        ).classes("w-full justify-start")
    node_action_popup.set_visibility(False)

    def open_node_action_popup(event: events.GenericEventArguments) -> None:
        args = event.args if isinstance(event.args, dict) else {}
        data = args.get("data")
        node_id = data.get("nodeId") if isinstance(data, dict) else None
        if not isinstance(node_id, str) or node_id not in node_by_id:
            return
        node = node_by_id[node_id]
        state.update(
            {
                "node_id": node_id,
                "title": str(node.get("title") or "未命名节点"),
                "description": str(node.get("description") or ""),
                "node_type": str(node.get("node_type") or "CONCEPT"),
            }
        )
        pointer_x = max(8, int(args.get("pointerX") or 8))
        pointer_y = max(8, int(args.get("pointerY") or 8))
        node_action_popup.style(f"left:{pointer_x}px;top:{pointer_y}px")
        node_action_popup.set_visibility(True)

    chart.on(
        "chart:contextmenu",
        open_node_action_popup,
        js_handler=(
            "(e) => { e.event?.event?.preventDefault?.(); "
            "if (e.componentType !== 'series' || e.dataType !== 'node') return; "
            "const native = e.event?.event; "
            "const pointerX = Math.max(8, Math.min((native?.clientX ?? 8) + 8, "
            "window.innerWidth - 198)); "
            "const pointerY = Math.max(8, Math.min((native?.clientY ?? 8) + 8, "
            "window.innerHeight - 190)); "
            "emit({data: e.data, pointerX, pointerY}); }"
        ),
    )


def _render_structure_editor(
    project: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    selected_revision: dict[str, Any] | None,
    *,
    outline_revision: int,
    project_id: str,
    space_id: str,
    client: UIAPIClient,
) -> None:
    """Render one module-based editor for framework content and path order."""

    selected_path = (
        selected_revision.get("path")
        if isinstance(selected_revision, dict) and isinstance(selected_revision.get("path"), dict)
        else None
    )
    path_id = str(selected_path.get("id") or "") if selected_path else ""
    path_row_version = int(selected_path.get("row_version") or 1) if selected_path else 1
    path_is_draft = bool(selected_path and selected_path.get("status") == "DRAFT")
    selected_steps = (
        sorted(
            _dict_items(selected_revision.get("steps")),
            key=lambda item: int(item.get("preferred_order") or 0),
        )
        if selected_revision
        else []
    )
    node_names = {
        str(item.get("id") or ""): str(item.get("title") or "未命名要素") for item in nodes
    }
    grouped_nodes = group_framework_by_modules(
        {"nodes": nodes, "edges": edges},
        [{**item, "node_id": str(item.get("node_id") or "")} for item in selected_steps],
    )
    module_count, element_count, _ = _project_overview_counts(nodes, selected_steps)
    outline_state = {"revision": max(1, outline_revision), "saving": False}

    async def persist_outline(event: events.GenericEventArguments) -> None:
        """Persist one folder/layer drop as a complete atomic outline."""

        if outline_state["saving"]:
            ui.notify("正在保存上一次调整，请稍候", type="warning")
            return
        args = event.args if isinstance(event.args, dict) else {}
        raw_modules = args.get("modules")
        raw_ungrouped = args.get("ungroupedNodeIds")
        if not isinstance(raw_modules, list) or not isinstance(raw_ungrouped, list):
            ui.notify("拖动结果不完整，已保留原顺序", type="warning")
            ui.navigate.to(framework_editor_href(project_id, path_id or None))
            return
        modules: list[dict[str, Any]] = []
        for item in raw_modules:
            if not isinstance(item, dict):
                continue
            module_id = str(item.get("moduleId") or "")
            node_ids = item.get("nodeIds")
            if module_id and isinstance(node_ids, list):
                modules.append(
                    {
                        "module_id": module_id,
                        "node_ids": [str(node_id) for node_id in node_ids if node_id],
                    }
                )
        outline_node_order = [
            node_id for module in modules for node_id in [module["module_id"], *module["node_ids"]]
        ] + [str(node_id) for node_id in raw_ungrouped if node_id]
        step_id_by_node_id = {
            str(step.get("node_id") or ""): str(step.get("id") or "")
            for step in selected_steps
            if step.get("node_id") and step.get("id")
        }
        synced_path_step_ids = [
            step_id_by_node_id[node_id]
            for node_id in outline_node_order
            if node_id in step_id_by_node_id
        ]
        sync_path_order = bool(
            path_is_draft
            and path_id
            and len(synced_path_step_ids) == len(selected_steps)
            and set(synced_path_step_ids) == {str(step.get("id") or "") for step in selected_steps}
        )
        outline_state["saving"] = True
        try:
            payload: dict[str, Any] = {
                "expected_revision": outline_state["revision"],
                "modules": modules,
                "ungrouped_node_ids": [str(node_id) for node_id in raw_ungrouped if node_id],
            }
            if sync_path_order:
                payload.update(
                    {
                        "path_id": path_id,
                        "path_expected_revision": path_row_version,
                        "path_step_ids": synced_path_step_ids,
                    }
                )
            result = await client.put(f"/spaces/{space_id}/outline", json=payload)
            outline_state["revision"] = int(
                result.get("outline_revision") or outline_state["revision"] + 1
            )
            ui.notify("框架分组与顺序已同步；路径先后顺序保持不变", type="positive")
        except UIAPIError as exc:
            error_notice(str(exc))
            # Keep the visible editor on the persisted snapshot after an error.
        finally:
            ui.navigate.to(framework_editor_href(project_id, path_id or None))
            outline_state["saving"] = False

    async def clone_path_for_editing() -> None:
        if not selected_path:
            return
        try:
            payload = await client.post(
                f"/path-revisions/{path_id}/clone",
                json={
                    "expected_revision": path_row_version,
                    "change_summary": "从统一框架编辑器调整路径",
                },
            )
            cloned = payload.get("path", {}) if isinstance(payload, dict) else {}
            ui.notify("已创建安全草稿；应用前不会改变当前路径", type="positive")
            ui.navigate.to(framework_editor_href(project_id, str(cloned.get("id") or "")))
        except UIAPIError as exc:
            error_notice(str(exc))

    async def activate_path_draft() -> None:
        if not path_is_draft:
            return
        try:
            await client.post(
                f"/path-revisions/{path_id}/activate",
                json={"expected_revision": path_row_version},
            )
            ui.notify("路径已应用；概览、地图和进展已同步", type="positive")
            ui.navigate.to(project_href(project_id, "map"))
        except UIAPIError as exc:
            error_notice(str(exc))

    with ui.card().classes("ln-card ln-structure-editor w-full p-4 sm:p-5"):
        with ui.row().classes("w-full items-start justify-between gap-3 max-sm:flex-col"):
            with ui.column().classes("min-w-0 gap-1"):
                ui.label("编辑框架与路径").classes("text-xl font-black")
                ui.label("按模块管理要素，并在同一处调整路径内容和先后顺序。").classes(
                    "text-sm text-gray-600"
                )
            with ui.row().classes("items-center gap-2"):
                if selected_path and not path_is_draft:
                    ui.button(
                        "编辑路径草稿",
                        icon="edit_route",
                        on_click=clone_path_for_editing,
                    ).props("outline color=positive no-caps")
                if path_is_draft:
                    ui.button(
                        "保存并应用路径",
                        icon="check",
                        on_click=activate_path_draft,
                    ).props("color=positive no-caps")
                ui.button(
                    "完成编辑",
                    icon="close",
                    on_click=lambda: ui.navigate.to(project_href(project_id, "map")),
                ).props("flat color=positive no-caps")

        with ui.row().classes("mt-2 w-full flex-wrap gap-2"):
            add_node_button = ui.button("添加要素", icon="add").props("color=positive no-caps")
            add_module_button = ui.button("添加模块", icon="create_new_folder").props(
                "outline color=positive no-caps"
            )
            add_edge_button = ui.button("添加关系", icon="add_link").props(
                "outline color=positive no-caps"
            )
            ui.label(f"{module_count} 个模块 · {element_count} 个要素").classes(
                "self-center text-sm font-bold text-gray-600"
            )
            if path_is_draft:
                ui.label(f"路径草稿 · {len(selected_steps)} 步").classes(
                    "self-center rounded-full bg-green-50 px-3 py-1 text-xs "
                    "font-bold text-green-800"
                )
            elif selected_path:
                ui.label(f"当前路径 · {len(selected_steps)} 步").classes(
                    "self-center rounded-full bg-green-50 px-3 py-1 text-xs "
                    "font-bold text-green-800"
                )

        with (
            ui.dialog() as add_node_dialog,
            ui.card()
            .classes("gap-4 p-5")
            .style("width:min(560px, calc(100vw - 24px));max-width:560px"),
        ):
            ui.label("添加框架要素").classes("text-xl font-black")
            new_title = ui.input("名称").props("outlined autofocus").classes("w-full")
            new_description = ui.textarea("一句话说明").props("outlined autogrow").classes("w-full")
            new_type = (
                ui.select(NODE_TYPE_OPTIONS, value="CONCEPT", label="类型")
                .props("outlined dense")
                .classes("w-full")
            )

            async def create_node() -> None:
                title_value = str(new_title.value or "").strip()
                if not title_value:
                    ui.notify("请填写名称", type="warning")
                    return
                try:
                    await client.post(
                        f"/spaces/{space_id}/nodes",
                        json={
                            "title": title_value,
                            "description": str(new_description.value or "").strip(),
                            "node_type": new_type.value,
                            "difficulty": 1,
                            "depth_level": 0,
                            "learning_objectives": [],
                            "source_basis": [],
                        },
                    )
                    add_node_dialog.close()
                    ui.notify("要素已添加", type="positive")
                    ui.navigate.to(project_href(project_id, "map") + "?edit=structure")
                except UIAPIError as exc:
                    error_notice(str(exc))

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=add_node_dialog.close).props("flat")
                ui.button("添加", icon="add", on_click=create_node).props("color=positive")
        add_node_button.on("click", add_node_dialog.open)

        def open_module_dialog() -> None:
            new_type.value = "MODULE"
            add_node_dialog.open()

        add_module_button.on("click", open_module_dialog)

        with (
            ui.dialog() as add_edge_dialog,
            ui.card()
            .classes("gap-4 p-5")
            .style("width:min(560px, calc(100vw - 24px));max-width:560px"),
        ):
            ui.label("添加关系").classes("text-xl font-black")
            source = ui.select(node_names, label="从").props("outlined dense").classes("w-full")
            relation = (
                ui.select(
                    RELATION_TYPE_OPTIONS,
                    value="RELATED",
                    label="关系",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            target = ui.select(node_names, label="到").props("outlined dense").classes("w-full")
            edge_reason = ui.input("为什么有关联（可选）").props("outlined").classes("w-full")

            async def create_edge() -> None:
                if not source.value or not target.value:
                    ui.notify("请选择关系两端的要素", type="warning")
                    return
                if source.value == target.value:
                    ui.notify("关系两端不能是同一个要素", type="warning")
                    return
                try:
                    await client.post(
                        f"/spaces/{space_id}/edges",
                        json={
                            "source_node_id": source.value,
                            "target_node_id": target.value,
                            "relation_type": relation.value,
                            "strength": 1.0,
                            "confidence": 1.0,
                            "required_mastery_level": (
                                3 if relation.value == "PREREQUISITE" else 0
                            ),
                            "reason": str(edge_reason.value or "").strip(),
                            "source_reference": [],
                        },
                    )
                    add_edge_dialog.close()
                    ui.notify("关系已添加", type="positive")
                    ui.navigate.to(project_href(project_id, "map") + "?edit=structure")
                except UIAPIError as exc:
                    error_notice(str(exc))

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=add_edge_dialog.close).props("flat")
                ui.button("添加关系", icon="add_link", on_click=create_edge).props("color=positive")
        add_edge_button.on("click", add_edge_dialog.open)

        def render_framework_item(
            node: dict[str, Any],
            *,
            path_step: dict[str, Any] | None,
            module: bool = False,
            summary: str | None = None,
        ) -> None:
            node_id = str(node.get("id") or "")
            node_title = str(node.get("title") or "未命名要素")
            route_position = int(path_step.get("route_position") or 0) if path_step else 0
            item_element = ui.element("article").classes(
                "ln-structure-item ln-structure-module-item" if module else "ln-structure-item"
            )
            if not module:
                item_element.props(
                    f'draggable=true data-outline-kind="node" data-outline-node-id="{node_id}"'
                )
            with item_element:
                ui.icon("drag_indicator").classes("ln-outline-drag-handle shrink-0")
                if route_position:
                    ui.label(str(route_position)).classes("ln-route-number shrink-0")
                with ui.column().classes("min-w-0 grow gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(
                            NODE_TYPE_OPTIONS.get(str(node.get("node_type")), "框架要素")
                        ).classes("ln-kicker")
                        if path_step:
                            ui.label("路径中").classes("ln-path-membership")
                    ui.label(node_title).classes("line-clamp-1 font-black")
                    description = str(node.get("description") or "").strip()
                    if description:
                        ui.label(description).classes(
                            "line-clamp-2 text-xs leading-5 text-gray-500"
                        )
                    if summary:
                        ui.label(summary).classes("text-xs font-bold text-gray-500")
                with ui.row().classes("shrink-0 flex-nowrap items-center gap-0"):
                    if not module and path_is_draft:
                        if path_step:
                            step_id = str(path_step.get("id") or "")

                            async def move_step(
                                destination: int,
                                step_id: str = step_id,
                            ) -> None:
                                try:
                                    await client.patch(
                                        f"/path-revisions/{path_id}/steps/{step_id}",
                                        json={
                                            "expected_revision": path_row_version,
                                            "preferred_order": destination,
                                        },
                                    )
                                    ui.navigate.to(framework_editor_href(project_id, path_id))
                                except UIAPIError as exc:
                                    error_notice(str(exc))

                            ui.button(
                                icon="arrow_upward",
                                on_click=lambda handler=move_step, position=route_position: handler(
                                    position - 2
                                ),
                            ).props(
                                f"flat round dense {'disable' if route_position <= 1 else ''} "
                                "aria-label='路径前移一步'"
                            )
                            ui.button(
                                icon="arrow_downward",
                                on_click=lambda handler=move_step, position=route_position: handler(
                                    position
                                ),
                            ).props(
                                f"flat round dense "
                                f"{'disable' if route_position >= len(selected_steps) else ''} "
                                "aria-label='路径后移一步'"
                            )

                            async def remove_from_path(step_id: str = step_id) -> None:
                                try:
                                    await client.delete(
                                        f"/path-revisions/{path_id}/steps/{step_id}",
                                        params={"expected_revision": path_row_version},
                                    )
                                    ui.notify("已从路径草稿移除；框架要素仍保留", type="positive")
                                    ui.navigate.to(framework_editor_href(project_id, path_id))
                                except UIAPIError as exc:
                                    error_notice(str(exc))

                            remove_path_dialog = _render_path_step_remove_dialog(
                                title=node_title,
                                on_confirm=remove_from_path,
                            )
                            ui.button(
                                icon="remove_circle_outline",
                                on_click=remove_path_dialog.open,
                            ).props("flat round dense color=negative aria-label='从路径移除'")
                        else:

                            async def add_to_path(node_id: str = node_id) -> None:
                                action_kind = {
                                    "LEARN": "LEARN",
                                    "UNDERSTAND": "EXPLORE",
                                    "DO": "EXECUTE",
                                }.get(str(project.get("intent_mode")), "LEARN")
                                try:
                                    await client.post(
                                        f"/path-revisions/{path_id}/steps",
                                        json={
                                            "expected_revision": path_row_version,
                                            "node_id": node_id,
                                            "preferred_order": len(selected_steps),
                                            "required_mastery_level": 3,
                                            "recommendation_reason": "用户从框架加入路径",
                                            "is_required": True,
                                            "action_kind": action_kind,
                                        },
                                    )
                                    ui.notify("已加入路径草稿", type="positive")
                                    ui.navigate.to(framework_editor_href(project_id, path_id))
                                except UIAPIError as exc:
                                    error_notice(str(exc))

                            ui.button(icon="add_road", on_click=add_to_path).props(
                                "flat round dense color=positive aria-label='加入路径'"
                            )

                    edit_button = ui.button(icon="edit").props(
                        "flat round dense color=positive aria-label='编辑要素'"
                    )
                    with (
                        ui.dialog() as edit_dialog,
                        ui.card()
                        .classes("gap-4 p-5")
                        .style("width:min(560px, calc(100vw - 24px));max-width:560px"),
                    ):
                        ui.label(f"编辑“{node_title}”").classes("text-xl font-black")
                        edit_title = (
                            ui.input("名称", value=node_title).props("outlined").classes("w-full")
                        )
                        edit_description = (
                            ui.textarea(
                                "一句话说明",
                                value=str(node.get("description") or ""),
                            )
                            .props("outlined autogrow")
                            .classes("w-full")
                        )
                        edit_type = (
                            ui.select(
                                NODE_TYPE_OPTIONS,
                                value=str(node.get("node_type") or "CONCEPT"),
                                label="类型",
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )

                        async def save_node(
                            node_id: str = node_id,
                            title_input: Any = edit_title,
                            description_input: Any = edit_description,
                            type_input: Any = edit_type,
                            dialog: Any = edit_dialog,
                        ) -> None:
                            value = str(title_input.value or "").strip()
                            if not value:
                                ui.notify("名称不能为空", type="warning")
                                return
                            try:
                                await client.patch(
                                    f"/spaces/{space_id}/nodes/{node_id}",
                                    json={
                                        "title": value,
                                        "description": str(description_input.value or "").strip(),
                                        "node_type": type_input.value,
                                    },
                                )
                                dialog.close()
                                ui.notify("要素已同步更新", type="positive")
                                ui.navigate.to(framework_editor_href(project_id, path_id or None))
                            except UIAPIError as exc:
                                error_notice(str(exc))

                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("取消", on_click=edit_dialog.close).props("flat")
                            ui.button("保存", icon="save", on_click=save_node).props(
                                "color=positive"
                            )
                    edit_button.on("click", edit_dialog.open)

                    async def delete_node(node_id: str = node_id) -> None:
                        try:
                            await client.delete(f"/spaces/{space_id}/nodes/{node_id}")
                            ui.notify("要素、关系、路径引用和进度已永久删除", type="positive")
                            ui.navigate.to(framework_editor_href(project_id, path_id or None))
                        except UIAPIError as exc:
                            error_notice(str(exc))

                    remove_dialog = _render_structure_remove_dialog(
                        title=node_title,
                        kind="模块" if module else "要素",
                        impact=(
                            "模块及其直接包含的要素会永久删除；相关关系、所有路径引用与进度记录会同步清理。"
                            if module
                            else "要素会永久删除；相关关系、所有路径引用与进度记录会同步清理。"
                        ),
                        on_confirm=delete_node,
                    )
                    ui.button(icon="delete_outline", on_click=remove_dialog.open).props(
                        "flat round dense color=negative aria-label='移除要素'"
                    )

        with ui.expansion(
            f"框架 · {module_count} 个模块 · {element_count} 个要素",
            icon="category",
            value=True,
        ).classes("ln-structure-section mt-3 w-full"):
            if not nodes:
                ui.label("还没有框架要素。").classes("ln-empty w-full")
            outline_root = ui.column().classes("ln-framework-outline w-full gap-0")
            outline_root.on(
                "dragstart",
                js_handler=(
                    "e => { const item=e.target.closest('[data-outline-kind]'); if(!item)return; "
                    "e.dataTransfer.effectAllowed='move'; "
                    "e.dataTransfer.setData('text/plain', item.dataset.outlineKind + ':' + "
                    "(item.dataset.outlineModuleId || item.dataset.outlineNodeId)); "
                    "item.classList.add('ln-outline-dragging'); }"
                ),
            )
            outline_root.on(
                "dragend",
                js_handler=(
                    "e => { e.currentTarget.querySelectorAll('.ln-outline-dragging')"
                    ".forEach(el=>el.classList.remove('ln-outline-dragging')); }"
                ),
            )
            outline_root.on(
                "dragover",
                js_handler=(
                    "e => { const root=e.currentTarget; "
                    "const dragged=root.querySelector('.ln-outline-dragging'); "
                    "if(!dragged)return; e.preventDefault(); "
                    "if(dragged.dataset.outlineKind==='module'){ "
                    "const target=e.target.closest('[data-outline-kind=module]'); "
                    "if(!target||target===dragged)return; const r=target.getBoundingClientRect(); "
                    "root.insertBefore(dragged,e.clientY<r.top+r.height/2?"
                    "target:target.nextSibling); return;} "
                    "const list=e.target.closest('[data-outline-list]'); if(!list)return; "
                    "const target=e.target.closest('[data-outline-kind=node]'); "
                    "if(target&&target!==dragged){const r=target.getBoundingClientRect();"
                    "list.insertBefore(dragged,e.clientY<r.top+r.height/2?target:target.nextSibling);}"
                    "else if(!target){list.appendChild(dragged);} }"
                ),
            )
            outline_root.on(
                "drop",
                persist_outline,
                js_handler=(
                    "e => { e.preventDefault(); const root=e.currentTarget; "
                    "const modules=[...root.querySelectorAll("
                    "':scope > [data-outline-kind=module]')].map(m=>({"
                    "moduleId:m.dataset.outlineModuleId,nodeIds:[...m.querySelectorAll("
                    "'[data-outline-list] > [data-outline-kind=node]')].map("
                    "n=>n.dataset.outlineNodeId)})); "
                    "const loose=root.querySelector("
                    "':scope > [data-outline-kind=ungrouped] [data-outline-list]'); "
                    "emit({modules,ungroupedNodeIds:loose?[...loose.querySelectorAll("
                    "':scope > [data-outline-kind=node]')].map(n=>n.dataset.outlineNodeId):[]}); }"
                ),
            )
            with outline_root:
                for group in grouped_nodes:
                    module_id = str(group.get("module_id") or "")
                    module_node = next(
                        (item for item in nodes if str(item.get("id") or "") == module_id),
                        None,
                    )
                    module_props = (
                        f'draggable=true data-outline-kind="module" '
                        f'data-outline-module-id="{module_id}"'
                        if module_id
                        else 'data-outline-kind="ungrouped"'
                    )
                    with ui.element("section").props(module_props).classes("ln-framework-module"):
                        if module_node is not None:
                            render_framework_item(
                                module_node,
                                path_step=None,
                                module=True,
                                summary=(
                                    f"{int(group.get('knowledge_count') or 0)} 个要素 · "
                                    f"路径 {int(group.get('path_step_count') or 0)} 步"
                                ),
                            )
                        else:
                            ui.label(str(group.get("title") or "未归类要素")).classes(
                                "ln-framework-module-title"
                            )
                        items = _dict_items(group.get("items"))
                        with (
                            ui.column()
                            .props(f'data-outline-list data-outline-parent-id="{module_id}"')
                            .classes("ln-framework-module-items w-full gap-2")
                        ):
                            if not items:
                                ui.label("拖动要素到这里。").classes(
                                    "px-3 py-3 text-xs text-gray-500"
                                )
                            for item in items:
                                path_step = item.get("path_step")
                                render_framework_item(
                                    item,
                                    path_step=(path_step if isinstance(path_step, dict) else None),
                                )

        semantic_edges = [item for item in edges if item.get("relation_type") != "CONTAINS"]
        with ui.expansion(f"关系 · {len(semantic_edges)}", icon="lan").classes(
            "ln-structure-section mt-2 w-full"
        ):
            if not semantic_edges:
                ui.label("还没有关系。").classes("ln-empty w-full")
            with ui.column().classes("w-full gap-2"):
                for edge in semantic_edges:
                    edge_id = str(edge.get("id") or "")
                    source_name = node_names.get(str(edge.get("source_node_id") or ""), "未知要素")
                    target_name = node_names.get(str(edge.get("target_node_id") or ""), "未知要素")
                    relation_label = RELATION_TYPE_OPTIONS.get(
                        str(edge.get("relation_type") or ""), "关联"
                    )
                    relation_title = f"{source_name} → {target_name}"
                    with ui.element("article").classes("ln-structure-item"):
                        with ui.column().classes("min-w-0 grow gap-1"):
                            ui.label(relation_label).classes("ln-kicker")
                            ui.label(relation_title).classes("line-clamp-2 font-bold")
                            reason = str(edge.get("reason") or "").strip()
                            if reason:
                                ui.label(reason).classes("line-clamp-2 text-xs text-gray-500")

                        async def archive_edge(edge_id: str = edge_id) -> None:
                            try:
                                await client.delete(f"/spaces/{space_id}/edges/{edge_id}")
                                ui.notify("关系已移除", type="positive")
                                ui.navigate.to(project_href(project_id, "map") + "?edit=structure")
                            except UIAPIError as exc:
                                error_notice(str(exc))

                        remove_edge_dialog = _render_structure_remove_dialog(
                            title=relation_title,
                            kind="关系",
                            impact="这条连线会从当前框架移除，历史版本仍然保留。",
                            on_confirm=archive_edge,
                        )
                        ui.button(
                            "移除",
                            icon="delete_outline",
                            on_click=remove_edge_dialog.open,
                        ).props("flat dense no-caps color=negative")


def _render_map(
    project: dict[str, Any],
    graph: dict[str, Any],
    selected_revision: dict[str, Any] | None,
    *,
    project_id: str,
    edit: str | None,
    client: UIAPIClient,
) -> None:
    space_id = str(project["space_id"])
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    nodes = [item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"]
    edges = [item for item in _dict_items(graph.get("edges")) if item.get("status") != "ARCHIVED"]
    semantic_edges = [item for item in edges if item.get("relation_type") != "CONTAINS"]

    if edit == "structure":
        _render_structure_editor(
            project,
            nodes,
            edges,
            selected_revision,
            outline_revision=int(graph.get("outline_revision") or 1),
            project_id=project_id,
            space_id=space_id,
            client=client,
        )
        return

    with ui.row().classes("w-full items-center justify-between gap-3"):
        module_count, element_count, _ = _project_overview_counts(nodes, [])
        count_label = ui.label(
            f"{module_count} 个模块 · {element_count} 个要素 · {len(semantic_edges)} 条关系"
        ).classes("text-sm text-gray-600")
        with ui.row().classes("items-center gap-2"):
            ui.button(
                "添加要素",
                icon="add",
                on_click=lambda: ui.navigate.to(
                    project_href(project_id, "map") + "?edit=structure"
                ),
            ).props("flat color=positive no-caps")
            ui.button(
                "编辑框架与路径",
                icon="route",
                on_click=lambda: ui.navigate.to(path_revision_href(project_id)),
            ).props("flat color=positive no-caps")

    if not nodes:
        ui.label("框架中还没有要素。 ").classes("ln-empty w-full")
        return

    with ui.card().classes("ln-card w-full overflow-hidden p-3 sm:p-4"):
        ui.label("右键节点可查看、编辑或删除；菜单会在点击处打开。拖动和缩放不改变结构。 ").classes(
            "px-2 text-sm text-gray-600"
        )
        with ui.element("div").classes("w-full overflow-x-auto"):
            chart = (
                ui.echart(
                    build_full_map_options(
                        graph,
                        project["route"],
                        intent_context=goal,
                        editable=True,
                    )
                )
                .classes("w-full")
                .style(f"min-width:1120px;height:{full_map_height(graph, project['route'])}px")
            )

        _render_graph_context_menu(
            project=project,
            nodes=nodes,
            edges=semantic_edges,
            chart=chart,
            count_label=count_label,
            project_id=project_id,
            space_id=space_id,
            client=client,
        )


def _render_path_step_remove_dialog(*, title: str, on_confirm: Any) -> Any:
    with (
        ui.dialog() as dialog,
        ui.card()
        .classes("gap-4 p-6")
        .style("width:min(420px, calc(100vw - 24px));max-width:420px"),
    ):
        ui.label(f"从路径中移除“{title}”？").classes("text-xl font-black")
        ui.label("只从当前路径草稿移除；框架节点及其他项目不会被删除。").classes(
            "text-sm leading-6 text-gray-600"
        )
        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat autofocus")
            ui.button("移除步骤", icon="remove_circle_outline", on_click=on_confirm).props(
                "color=negative no-caps"
            )
    dialog.props("aria-label='移除路径步骤确认' role='alertdialog'")
    return dialog


def _render_path(
    client: UIAPIClient,
    project: dict[str, Any],
    graph: dict[str, Any],
    revisions: list[dict[str, Any]],
    selected_revision: dict[str, Any] | None,
    *,
    project_id: str,
) -> None:
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    selected_path = (
        selected_revision.get("path")
        if isinstance(selected_revision, dict) and isinstance(selected_revision.get("path"), dict)
        else None
    )

    path_id = str(selected_path.get("id") or "") if selected_path else ""
    is_draft = bool(selected_path and selected_path.get("status") == "DRAFT")
    row_version = int(selected_path.get("row_version") or 1) if selected_path else 1
    steps = (
        sorted(
            _dict_items(selected_revision.get("steps")),
            key=lambda item: int(item.get("preferred_order") or 0),
        )
        if selected_revision
        else []
    )
    active_route = _dict_items(project.get("route"))
    active_by_node = {str(item.get("node_id") or ""): item for item in active_route}
    graph_nodes = [
        item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"
    ]
    node_by_id = {str(item["id"]): item for item in graph_nodes}

    with ui.row().classes("w-full items-start justify-between gap-3"):
        with ui.column().classes("gap-0"):
            ui.label("编辑路径").classes("text-xl font-black")
            ui.label("调整顺序、添加或移除步骤；保存后导航和进度会一起更新。").classes(
                "text-sm text-gray-600"
            )
        if selected_path:
            status_label = {
                "DRAFT": "编辑草稿",
                "ACTIVE": "当前路径",
                "SUPERSEDED": "历史版本",
                "ARCHIVED": "已归档",
            }.get(str(selected_path.get("status")), str(selected_path.get("status")))
            ui.label(f"{status_label} · v{row_version}").classes(
                "rounded-full bg-green-50 px-3 py-1 text-xs font-bold text-green-800"
            )

    async def generate_candidate() -> None:
        try:
            payload = await client.post(
                f"/goals/{project_id}/path-revisions",
                json={"change_summary": "AI 生成的可编辑候选"},
            )
            created_path = payload.get("path", {}) if isinstance(payload, dict) else {}
            ui.notify("AI 候选已保存为草稿，当前路径未被覆盖", type="positive")
            ui.navigate.to(path_revision_href(project_id, str(created_path.get("id") or "")))
        except UIAPIError as exc:
            error_notice(str(exc))

    async def clone_revision() -> None:
        if not selected_path:
            return
        try:
            payload = await client.post(
                f"/path-revisions/{path_id}/clone",
                json={
                    "expected_revision": row_version,
                    "change_summary": "用户可持续编辑的路径副本",
                },
            )
            cloned = payload.get("path", {}) if isinstance(payload, dict) else {}
            ui.notify("已创建可编辑副本，原路径保持不变", type="positive")
            ui.navigate.to(path_revision_href(project_id, str(cloned.get("id") or "")))
        except UIAPIError as exc:
            error_notice(str(exc))

    async def validate_revision() -> None:
        try:
            result = await client.post(
                f"/path-revisions/{path_id}/validate",
                json={"expected_revision": row_version},
            )
            issues = _dict_items(result.get("issues")) if isinstance(result, dict) else []
            if not issues:
                ui.notify("校验通过，可以激活", type="positive")
                return
            labels = {
                "PREREQUISITE_ORDER": "硬前置顺序冲突",
                "MISSING_PREREQUISITE": "缺少必要前置",
                "MISSING_TARGET": "缺少目标要素",
                "NODE_NOT_IN_MAP_VERSION": "要素不在当前框架版本",
            }
            first_code = str(issues[0].get("code") or "")
            ui.notify(
                f"发现 {len(issues)} 个问题：{labels.get(first_code, '路径需要调整')}",
                type="warning",
            )
        except UIAPIError as exc:
            error_notice(str(exc))

    async def activate_revision() -> None:
        try:
            await client.post(
                f"/path-revisions/{path_id}/activate",
                json={"expected_revision": row_version},
            )
            ui.notify("新路径已激活；导航、地图和进展已同步", type="positive")
            ui.navigate.to(project_href(project_id, "overview"))
        except UIAPIError as exc:
            error_notice(str(exc))

    async def save_total_order() -> None:
        if not is_draft:
            return
        ordered_ids = await ui.run_javascript(
            f"""
            (() => {{
              const root = document.getElementById('c{order_list.id}');
              return root ? [...root.querySelectorAll('[data-step-id]')]
                .map(el => el.dataset.stepId) : [];
            }})()
            """
        )
        ordered_ids = (
            [str(step_id) for step_id in ordered_ids] if isinstance(ordered_ids, list) else []
        )
        if not all(ordered_ids):
            ui.notify("路径步骤数据不完整，请刷新后重试", type="warning")
            return
        try:
            await client.put(
                f"/path-revisions/{path_id}/order",
                json={
                    "expected_revision": row_version,
                    "step_ids": ordered_ids,
                },
            )
            ui.notify("先后顺序已保存到草稿", type="positive")
            ui.navigate.to(path_revision_href(project_id, path_id))
        except UIAPIError as exc:
            error_notice(str(exc))

    with ui.row().classes("w-full flex-wrap gap-2"):
        if selected_path and not is_draft:
            ui.button("开始编辑", icon="edit", on_click=clone_revision).props(
                "color=positive no-caps"
            )
        if is_draft:
            ui.button("保存并应用", icon="check", on_click=activate_revision).props(
                "color=positive no-caps"
            )
            ui.button("检查路径", icon="rule", on_click=validate_revision).props(
                "outline color=positive no-caps"
            )

    if selected_path and not is_draft:
        ui.label("开始编辑会创建安全草稿，当前路径在保存前不会改变。").classes(
            "text-xs text-gray-500"
        )

    with ui.expansion("版本与 AI 建议（高级）", icon="tune").classes("ln-structure-section w-full"):
        ui.button("让 AI 生成候选", icon="auto_awesome", on_click=generate_candidate).props(
            "outline color=positive no-caps"
        )
        if revisions:
            revision_options = {
                str(item["path"]["id"]): (
                    f"{item['path']['status']} · v{item['path'].get('row_version', 1)} · "
                    f"{item['path'].get('change_summary') or '路径修订'}"
                )
                for item in revisions
                if isinstance(item.get("path"), dict)
            }
            revision_select = (
                ui.select(
                    revision_options,
                    value=path_id or None,
                    label="历史版本",
                )
                .props("outlined dense options-dense")
                .classes("w-full max-w-xl")
            )
            revision_select.on(
                "update:model-value",
                lambda _: ui.navigate.to(
                    path_revision_href(project_id, str(revision_select.value or ""))
                ),
            )

    if is_draft:
        with ui.card().classes("ln-soft-card w-full gap-3 p-3 sm:p-4"):
            with ui.row().classes("w-full items-start justify-between gap-3 max-sm:flex-col"):
                with ui.column().classes("gap-0"):
                    ui.label("单独编辑先后顺序").classes("font-black")
                    ui.label("拖动步骤后保存；框架关系不会被改变。").classes(
                        "text-xs text-gray-500"
                    )
                ui.button("保存顺序", icon="save", on_click=save_total_order).props(
                    "outline color=positive no-caps"
                )
            order_list = ui.list().props("separator").classes("ln-path-order-list w-full")
            with order_list:
                for order_index, step in enumerate(steps, start=1):
                    step_id = str(step.get("id") or "")
                    order_item = (
                        ui.item()
                        .props(f'draggable=true data-step-id="{step_id}"')
                        .classes("ln-path-order-item")
                    )
                    order_item.on(
                        "dragstart",
                        js_handler=(
                            "e => { e.dataTransfer.effectAllowed = 'move'; "
                            "e.dataTransfer.setData('text/plain', e.currentTarget.dataset.stepId); "
                            "e.currentTarget.classList.add('ln-path-order-dragging'); }"
                        ),
                    )
                    order_item.on(
                        "dragend",
                        js_handler=(
                            "e => e.currentTarget.classList.remove('ln-path-order-dragging')"
                        ),
                    )
                    order_item.on("dragover", js_handler="e => e.preventDefault()")
                    order_item.on(
                        "drop",
                        js_handler=(
                            "e => { e.preventDefault(); "
                            "const root = e.currentTarget.parentElement; "
                            "const id = e.dataTransfer.getData('text/plain'); "
                            "const dragged = [...root.querySelectorAll('[data-step-id]')]"
                            ".find(el => el.dataset.stepId === id); if (!dragged) return; "
                            "const rect = e.currentTarget.getBoundingClientRect(); "
                            "root.insertBefore(dragged, e.clientY < rect.top + rect.height / 2 "
                            "? e.currentTarget : e.currentTarget.nextSibling); "
                            "[...root.querySelectorAll('[data-step-id]')].forEach((el, index) => { "
                            "const badge = el.querySelector('.ln-order-index'); "
                            "if (badge) badge.textContent = String(index + 1); }); }"
                        ),
                    )
                    with order_item:
                        ui.item_section().props("avatar")
                        ui.icon("drag_indicator").classes("ln-path-order-handle")
                        with ui.item_section():
                            ui.item_label(str(step.get("title") or f"步骤 {order_index}")).classes(
                                "font-bold"
                            )
                        ui.item_section().props("side")
                        ui.badge(str(order_index)).props("outline color=positive").classes(
                            "ln-order-index"
                        )

        existing_ids = {str(step.get("node_id") or "") for step in steps}
        available_nodes = {
            str(node["id"]): str(node.get("title") or "未命名要素")
            for node in graph_nodes
            if str(node["id"]) not in existing_ids and node.get("node_type") != "MODULE"
        }
        if available_nodes:
            with ui.card().classes("ln-soft-card w-full gap-3 p-3 sm:p-4"):
                ui.label("添加步骤").classes("font-black")
                with ui.row().classes("w-full items-end gap-2 max-sm:flex-col"):
                    add_node = (
                        ui.select(available_nodes, label="选择要素")
                        .props("outlined dense options-dense")
                        .classes("min-w-0 grow max-sm:w-full")
                    )
                    add_optional = ui.checkbox("可选", value=True).classes("shrink-0")

                async def add_step() -> None:
                    if not add_node.value:
                        ui.notify("请先选择要素", type="warning")
                        return
                    action_kind = {
                        "LEARN": "LEARN",
                        "UNDERSTAND": "EXPLORE",
                        "DO": "EXECUTE",
                    }.get(str(project.get("intent_mode")), "LEARN")
                    try:
                        await client.post(
                            f"/path-revisions/{path_id}/steps",
                            json={
                                "expected_revision": row_version,
                                "node_id": add_node.value,
                                "preferred_order": len(steps),
                                "required_mastery_level": 3,
                                "recommendation_reason": "用户从框架加入路径",
                                "is_required": not bool(add_optional.value),
                                "action_kind": action_kind,
                            },
                        )
                        ui.notify("要素已加入路径草稿", type="positive")
                        ui.navigate.to(path_revision_href(project_id, path_id))
                    except UIAPIError as exc:
                        error_notice(str(exc))

                    ui.button("添加", icon="add", on_click=add_step).props(
                        "color=positive no-caps"
                    ).classes("shrink-0 max-sm:w-full")

    if not steps:
        ui.label("当前版本还没有路径步骤。 ").classes("ln-empty w-full")
        return

    with ui.column().classes("w-full gap-2"):
        for index, item in enumerate(steps, start=1):
            node_id = str(item.get("node_id") or "")
            node = node_by_id.get(node_id, {})
            active_item = active_by_node.get(node_id, {})
            status = str(active_item.get("status") or node.get("computed_status") or "NOT_RELEVANT")
            classes = "ln-path-step"
            if status in {"AVAILABLE", "IN_PROGRESS", "NEEDS_REVIEW"}:
                classes += " ln-path-step-active"
            with ui.element("article").classes(classes):
                ui.label(str(index)).classes("ln-route-number")
                with ui.column().classes("min-w-0 gap-1"):
                    ui.link(
                        str(item.get("title") or node.get("title") or "未命名要素"),
                        path_revision_href(project_id, path_id, node_id=node_id),
                    ).classes("font-black no-underline")
                    ui.label(
                        localize_route_reason(
                            item.get("recommendation_reason") or active_item.get("reason"),
                            status=status,
                            intent_mode=goal,
                        )
                    ).classes("line-clamp-2 text-xs leading-5 text-gray-500")
                with ui.column().classes("items-end gap-1"):
                    ui.label(intent_status_label(status, goal)).classes(
                        f"ln-status-{status} rounded-full px-2 py-1 text-xs font-bold"
                    )
                    if is_draft:
                        with ui.row().classes("flex-nowrap gap-0"):

                            async def move_step(
                                destination: int,
                                step_id: str = str(item["id"]),
                            ) -> None:
                                try:
                                    await client.patch(
                                        f"/path-revisions/{path_id}/steps/{step_id}",
                                        json={
                                            "expected_revision": row_version,
                                            "preferred_order": destination,
                                        },
                                    )
                                    ui.navigate.to(path_revision_href(project_id, path_id))
                                except UIAPIError as exc:
                                    error_notice(str(exc))

                            ui.button(
                                icon="arrow_upward",
                                on_click=lambda destination=index - 2, handler=move_step: handler(
                                    destination
                                ),
                            ).props(
                                f"flat round dense {'disable' if index == 1 else ''} "
                                "aria-label='前移一步'"
                            )
                            ui.button(
                                icon="arrow_downward",
                                on_click=lambda destination=index, handler=move_step: handler(
                                    destination
                                ),
                            ).props(
                                f"flat round dense {'disable' if index == len(steps) else ''} "
                                "aria-label='后移一步'"
                            )

                            async def remove_step(step_id: str = str(item["id"])) -> None:
                                try:
                                    await client.delete(
                                        f"/path-revisions/{path_id}/steps/{step_id}",
                                        params={"expected_revision": row_version},
                                    )
                                    ui.notify("步骤已从草稿移除", type="positive")
                                    ui.navigate.to(path_revision_href(project_id, path_id))
                                except UIAPIError as exc:
                                    error_notice(str(exc))

                            remove_dialog = _render_path_step_remove_dialog(
                                title=str(item.get("title") or node.get("title") or "未命名要素"),
                                on_confirm=remove_step,
                            )
                            ui.button(icon="delete_outline", on_click=remove_dialog.open).props(
                                "flat round dense color=negative aria-label='移除步骤'"
                            )


def _ordered_mind_map_groups(
    graph: dict[str, Any],
    route: list[dict[str, Any]],
    module_order: list[str] | None,
) -> list[dict[str, Any]]:
    groups = group_framework_by_modules(graph, route)
    order = {str(value): index for index, value in enumerate(module_order or [])}
    groups.sort(
        key=lambda item: (
            order.get(str(item.get("module_id")), 10_000),
            int(item.get("module_sequence") or 10_000),
        )
    )
    return groups


def _mind_map_options(
    graph: dict[str, Any],
    route: list[dict[str, Any]],
    *,
    root_title: str = "项目脑图",
    focus_node_ids: list[str] | None = None,
    module_order: list[str] | None = None,
    show_relationships: bool = True,
) -> dict[str, Any]:
    """Render a MindMaster-style radial map from the live framework projection."""
    active_nodes = [
        item
        for item in _dict_items(graph.get("nodes"))
        if item.get("status") != "ARCHIVED" and item.get("id")
    ]
    node_ids = {str(item["id"]) for item in active_nodes}
    groups = _ordered_mind_map_groups(graph, route, module_order)
    focus = {str(value) for value in focus_node_ids or []}
    data: list[dict[str, Any]] = [
        {
            "id": "__mind_root__",
            "name": root_title,
            "x": 0,
            "y": 0,
            "symbol": "roundRect",
            "symbolSize": [190, 64],
            "itemStyle": {"color": "#126b4d", "borderColor": "#8be0bd", "borderWidth": 3},
            "label": {"show": True, "color": "#ffffff", "fontSize": 16, "fontWeight": "bold"},
        }
    ]
    positions: dict[str, tuple[int, int]] = {"__mind_root__": (0, 0)}
    links: list[dict[str, Any]] = []
    branch_colors = ["#59c79a", "#72a8f3", "#e4a64e", "#c88cf0", "#ef8375"]
    module_y_by_index, _ = _mind_map_branch_layout(groups)
    for branch_index, group in enumerate(groups):
        side = -1 if branch_index % 2 == 0 else 1
        module_id = str(group.get("module_id") or f"__mind_module_{branch_index}")
        if module_id not in node_ids:
            module_id = f"__mind_module_{branch_index}"
        module_y = module_y_by_index[branch_index]
        module_x = side * 430
        positions[module_id] = (module_x, int(module_y))
        color = branch_colors[branch_index % len(branch_colors)]
        data.append(
            {
                "id": module_id,
                "name": str(group.get("title") or "未归类要素"),
                "x": module_x,
                "y": int(module_y),
                "symbol": "roundRect",
                "symbolSize": [155, 48],
                "itemStyle": {"color": color, "borderColor": "#ffffff", "borderWidth": 2},
                "label": {"show": True, "color": "#10251c", "fontWeight": "bold"},
            }
        )
        links.append(
            {
                "source": "__mind_root__",
                "target": module_id,
                "lineStyle": {"color": color, "width": 4, "curveness": 0.28},
            }
        )
        items = [
            item
            for item in _dict_items(group.get("items"))
            if str(item.get("id") or "") in node_ids
        ]
        item_gap = 96
        for row, item in enumerate(items):
            item_id = str(item["id"])
            if item_id in positions:
                continue
            item_y = module_y + (row - (len(items) - 1) / 2) * item_gap
            item_x = side * 760
            positions[item_id] = (item_x, int(item_y))
            highlighted = item_id in focus
            path_step = item.get("path_step")
            path_position = path_step.get("route_position") if isinstance(path_step, dict) else None
            name = str(item.get("title") or item_id)
            if path_position is not None:
                name = f"{path_position} · {name}"
            data.append(
                {
                    "id": item_id,
                    "name": name,
                    "x": item_x,
                    "y": int(item_y),
                    "symbol": "circle",
                    "symbolSize": 48 if highlighted else 34,
                    "itemStyle": {
                        "color": "#f0a33a" if highlighted else "#e7f5ed",
                        "borderColor": color,
                        "borderWidth": 3 if highlighted else 2,
                    },
                    "label": {
                        "show": True,
                        # Labels face away from their module.  Inward-facing
                        # labels used to occupy the same corridor as the
                        # branch card and adjacent module, especially after
                        # ECharts fitted a dense map to the viewport.
                        "position": "right" if side > 0 else "left",
                        "color": "#e8f4ed",
                        "width": 190,
                        "overflow": "truncate",
                    },
                }
            )
            links.append(
                {
                    "source": module_id,
                    "target": item_id,
                    "lineStyle": {"color": color, "width": 2.5, "curveness": 0.2},
                }
            )
    if show_relationships:
        for edge in _dict_items(graph.get("edges")):
            source = str(edge.get("source_node_id") or "")
            target = str(edge.get("target_node_id") or "")
            if source not in positions or target not in positions:
                continue
            if str(edge.get("relation_type") or "") == "CONTAINS":
                continue
            links.append(
                {
                    "source": source,
                    "target": target,
                    "lineStyle": {
                        "color": "#79958a",
                        "opacity": 0.35,
                        "width": 1,
                        "type": "dashed",
                    },
                }
            )
    return {
        "backgroundColor": "transparent",
        "animationDuration": 250,
        "tooltip": {"trigger": "item", "confine": True},
        "toolbox": {"show": True, "right": 12, "top": 8, "feature": {"restore": {}}},
        "series": [
            {
                "type": "graph",
                "layout": "none",
                "left": 230,
                "right": 230,
                "top": 80,
                "bottom": 80,
                "preserveAspect": True,
                "roam": True,
                "draggable": True,
                "data": data,
                "links": links,
                "edgeSymbol": ["none", "arrow"],
                "edgeSymbolSize": [0, 8],
                "label": {"color": "#e8f4ed", "fontSize": 12},
                "lineStyle": {"curveness": 0.22},
                "emphasis": {"focus": "adjacency", "lineStyle": {"width": 3}},
            }
        ],
    }


def _mind_map_branch_layout(
    groups: list[dict[str, Any]],
) -> tuple[dict[int, int], int]:
    """Pack each side by its real child span instead of a global branch gap.

    Module order still determines which side and vertical order a branch uses.
    The height of a five-item branch is materially larger than a one-item
    branch, so reserving an interval per branch is the only stable way to keep
    neighbouring endpoint circles and labels separate.
    """

    item_gap = 96
    item_diameter = 48
    branch_gutter = 88
    bias_step = 12
    positions: dict[int, int] = {}
    top = 0.0
    bottom = 0.0
    for side in (-1, 1):
        entries: list[tuple[int, float]] = []
        for branch_index, group in enumerate(groups):
            if (-1 if branch_index % 2 == 0 else 1) != side:
                continue
            item_count = len(_dict_items(group.get("items")))
            span = max(48.0, (max(1, item_count) - 1) * item_gap + item_diameter)
            entries.append((branch_index, span))
        if not entries:
            continue
        total_span = sum(span for _, span in entries) + branch_gutter * (len(entries) - 1)
        cursor = -total_span / 2
        for branch_index, span in entries:
            global_bias = (branch_index - (len(groups) - 1) / 2) * bias_step
            center = cursor + span / 2 + global_bias
            positions[branch_index] = round(center)
            top = min(top, center - span / 2)
            bottom = max(bottom, center + span / 2)
            cursor += span + branch_gutter
    height = max(760, math.ceil(bottom - top + 240))
    return positions, height


def _mind_map_suggestion_matches_revision(
    graph: dict[str, Any],
    active_revision: dict[str, Any] | None,
    suggestion: dict[str, Any] | None,
) -> bool:
    """Compare an AI mind-map suggestion with the authoritative live revisions."""

    if not isinstance(suggestion, dict):
        return False
    proposed = suggestion.get("proposed_changes")
    if not isinstance(proposed, dict):
        return False
    if int(proposed.get("source_outline_revision") or 0) != int(graph.get("outline_revision") or 1):
        return False
    source_path_revision = proposed.get("source_path_revision")
    if source_path_revision is None:
        return True
    path = active_revision.get("path") if isinstance(active_revision, dict) else None
    if not isinstance(path, dict) or path.get("row_version") is None:
        return False
    return int(source_path_revision or 0) == int(path.get("row_version") or 0)


def _render_mindmap(
    project: dict[str, Any],
    graph: dict[str, Any],
    *,
    project_id: str,
    active_revision: dict[str, Any] | None,
    suggestion: dict[str, Any] | None,
    client: UIAPIClient,
) -> None:
    route = _dict_items(project.get("route"))
    proposed = suggestion.get("proposed_changes") if isinstance(suggestion, dict) else {}
    proposed = proposed if isinstance(proposed, dict) else {}
    revision = int(graph.get("outline_revision") or 1)
    path_payload = active_revision.get("path") if isinstance(active_revision, dict) else None
    path_payload = path_payload if isinstance(path_payload, dict) else {}
    current_path_revision = path_payload.get("row_version")
    same_revision = _mind_map_suggestion_matches_revision(graph, active_revision, suggestion)
    focus = [str(value) for value in proposed.get("focus_node_ids", [])] if same_revision else []
    module_order = (
        [str(value) for value in proposed.get("module_order", [])] if same_revision else []
    )
    mind_map_groups = _ordered_mind_map_groups(graph, route, module_order)
    _, mind_map_height = _mind_map_branch_layout(mind_map_groups)
    running = {"value": False}
    show_relationships = {"value": True}

    with ui.row().classes("w-full items-start justify-between gap-3"):
        with ui.column().classes("min-w-0 gap-1"):
            ui.label("AI脑图").classes("text-xl font-black")
            ui.label("框架是事实源，脑图帮助你理解整体结构、模块关系和下一步重点。").classes(
                "text-sm text-gray-500"
            )
        with ui.column().classes("items-end gap-1"):
            with ui.row().classes("items-center gap-2"):
                ui.button(
                    "添加模块",
                    icon="create_new_folder",
                    on_click=lambda: ui.navigate.to(
                        project_href(project_id, "map") + "?edit=structure"
                    ),
                ).props("outline color=positive no-caps")

            async def generate() -> None:
                if running["value"]:
                    return
                running["value"] = True
                generate_button.props("loading disable")
                try:
                    await client.post(
                        f"/ai/goals/{project_id}/mind-map/generate",
                        json={"confirmed_external_ai": True},
                    )
                    ui.notify("AI脑图建议已生成。", type="positive")
                    ui.navigate.to(project_href(project_id, "mindmap"))
                except UIAPIError as exc:
                    error_notice(str(exc))
                finally:
                    running["value"] = False
                    generate_button.props(remove="loading disable")

            generate_button = ui.button(
                "让 AI 生成脑图", icon="auto_awesome", on_click=generate
            ).props("color=positive no-caps")
            ui.label("会发送当前节点、关系和路径摘要；点击即表示确认发送。\n").classes(
                "text-right text-xs text-gray-500"
            )
    if suggestion and same_revision:
        with ui.card().classes("ln-card w-full gap-1 p-4"):
            ui.label("AI视图建议（待人工确认）").classes("font-bold text-green-700")
            summary = str(proposed.get("summary") or "").strip()
            if summary:
                ui.label(summary).classes("text-sm leading-6")
            path_version_label = (
                f"、路径版本 v{current_path_revision}" if current_path_revision else ""
            )
            ui.label(
                f"基于框架版本 v{revision}{path_version_label}；节点、关系和路径仍以项目数据为准。"
            ).classes("text-xs text-gray-500")
    elif suggestion:
        ui.label("框架已更新，上一版 AI 脑图建议已过期，请重新生成。").classes("ln-empty w-full")
    with ui.card().classes("ln-card w-full overflow-hidden p-3 sm:p-4"):
        ui.label(
            "中心主题向左右展开模块与知识点；数字表示路径顺序，橙色节点是 AI 建议优先关注的内容。"
        ).classes("px-2 text-sm text-gray-500")
        with ui.element("div").classes("w-full overflow-x-auto"):
            with (
                ui.element("div")
                .classes("relative")
                .style(f"min-width:1400px;height:{mind_map_height}px")
            ):
                chart = ui.echart(
                    _mind_map_options(
                        graph,
                        route,
                        root_title=str(project.get("title") or "项目脑图"),
                        focus_node_ids=focus,
                        module_order=module_order,
                        show_relationships=True,
                    )
                ).classes("w-full h-full")

                def toggle_relationships() -> None:
                    show_relationships["value"] = not show_relationships["value"]
                    chart.options.clear()
                    chart.options.update(
                        _mind_map_options(
                            graph,
                            route,
                            root_title=str(project.get("title") or "项目脑图"),
                            focus_node_ids=focus,
                            module_order=module_order,
                            show_relationships=show_relationships["value"],
                        )
                    )
                    chart.update()
                    toggle_button.set_text(
                        "隐藏关联线" if show_relationships["value"] else "显示关联线"
                    )
                    toggle_button.props(
                        add="color=primary" if show_relationships["value"] else "color=grey-7",
                        remove="color=primary color=grey-7",
                    )

                toggle_button = ui.button(
                    "隐藏关联线", icon="account_tree", on_click=toggle_relationships
                ).props("flat dense no-caps")
                toggle_button.classes("absolute right-3 top-12 z-10 bg-slate-900/80")
                toggle_button.tooltip("仅隐藏知识点之间的关联线，模块主干仍保留")


def _render_legacy_inspector(
    client: UIAPIClient,
    project: dict[str, Any],
    graph: dict[str, Any],
    node: dict[str, Any],
    selected_revision: dict[str, Any] | None,
    *,
    project_id: str,
    section: str,
    panel: str | None,
) -> None:
    space_id = str(project["space_id"])
    node_id = str(node["id"])
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    copy = intent_profile(goal)
    route = _dict_items(project.get("route"))
    route_item = next((item for item in route if item.get("node_id") == node_id), None)
    selected_path = (
        selected_revision.get("path")
        if isinstance(selected_revision, dict) and isinstance(selected_revision.get("path"), dict)
        else None
    )
    revision_steps = (
        _dict_items(selected_revision.get("steps")) if isinstance(selected_revision, dict) else []
    )
    path_step = next(
        (item for item in revision_steps if str(item.get("node_id") or "") == node_id),
        None,
    )
    path_id = str(selected_path.get("id") or "") if selected_path else ""
    path_row_version = int(selected_path.get("row_version") or 1) if selected_path else 1
    path_is_draft = bool(selected_path and selected_path.get("status") == "DRAFT")
    edges = [item for item in _dict_items(graph.get("edges")) if item.get("status") != "ARCHIVED"]
    names = {
        str(item["id"]): str(item.get("title") or "未命名")
        for item in _dict_items(graph.get("nodes"))
    }
    related_edges = [
        edge
        for edge in edges
        if edge.get("source_node_id") == node_id or edge.get("target_node_id") == node_id
    ]
    return_href = (
        path_revision_href(project_id, path_id)
        if section == "path"
        else project_href(project_id, section)
    )
    current_href = (
        path_revision_href(project_id, path_id, node_id=node_id)
        if section == "path"
        else project_href(project_id, section, node_id=node_id)
    )

    with ui.element("aside").classes("ln-node-inspector"):
        with ui.row().classes("w-full flex-nowrap items-start justify-between gap-2"):
            with ui.column().classes("min-w-0 gap-1"):
                ui.label(NODE_TYPE_OPTIONS.get(str(node.get("node_type")), "框架要素")).classes(
                    "ln-kicker"
                )
                ui.label(str(node.get("title") or "未命名要素")).classes(
                    "line-clamp-2 text-xl font-black"
                )
            ui.button(icon="close", on_click=lambda: ui.navigate.to(return_href)).props(
                "flat round dense aria-label='关闭要素面板'"
            )

        with ui.expansion("框架属性", icon="schema", value=panel != "action").classes(
            "mt-3 w-full rounded-xl border border-gray-200"
        ):
            title = (
                ui.input("名称", value=str(node.get("title") or ""))
                .props("outlined dense")
                .classes("w-full")
            )
            description = (
                ui.textarea(
                    "定义",
                    value=str(node.get("description") or ""),
                )
                .props("outlined autogrow")
                .classes("w-full")
            )
            node_type = (
                ui.select(
                    NODE_TYPE_OPTIONS,
                    value=str(node.get("node_type") or "CONCEPT"),
                    label="类型",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            difficulty = ui.slider(
                min=1,
                max=5,
                value=int(node.get("difficulty") or 1),
            ).props("label-always")
            objectives = (
                ui.textarea(
                    "目标或验收标准（每行一项）",
                    value="\n".join(
                        str(item)
                        for item in node.get("learning_objectives", [])
                        if str(item).strip()
                    ),
                )
                .props("outlined autogrow")
                .classes("w-full")
            )

            async def save_node() -> None:
                if not str(title.value or "").strip():
                    ui.notify("名称不能为空", type="warning")
                    return
                try:
                    await client.patch(
                        f"/spaces/{space_id}/nodes/{node_id}",
                        json={
                            "title": str(title.value).strip(),
                            "description": str(description.value or "").strip(),
                            "node_type": node_type.value,
                            "difficulty": int(difficulty.value),
                            "learning_objectives": [
                                line.strip()
                                for line in str(objectives.value or "").splitlines()
                                if line.strip()
                            ],
                        },
                    )
                    ui.notify("框架属性已更新，所有视图将使用同一节点", type="positive")
                    ui.navigate.to(current_href)
                except UIAPIError as exc:
                    error_notice(str(exc))

            ui.button("保存框架属性", icon="save", on_click=save_node).props("color=positive")

        with ui.expansion("路径设置", icon="route", value=section == "path").classes(
            "mt-2 w-full rounded-xl border border-gray-200"
        ):
            if selected_path is None:
                ui.label("还没有可编辑的路径版本。 ").classes("text-sm text-gray-600")
                ui.link("打开框架与路径", path_revision_href(project_id)).classes(
                    "text-sm font-bold no-underline"
                )
            elif path_step is None:
                ui.label("这个要素不在当前路径中。 ").classes("text-sm text-gray-600")
                ui.link("在框架中加入路径", path_revision_href(project_id, path_id)).classes(
                    "text-sm font-bold no-underline"
                )
            elif not path_is_draft:
                sequence = next(
                    (
                        index
                        for index, item in enumerate(revision_steps, start=1)
                        if item is path_step
                    ),
                    0,
                )
                ui.label(f"当前第 {sequence} 步").classes("font-black")
                ui.label(
                    localize_route_reason(
                        path_step.get("recommendation_reason") or (route_item or {}).get("reason"),
                        status=str(
                            node.get("computed_status")
                            or (route_item or {}).get("status")
                            or "NOT_RELEVANT"
                        ),
                        intent_mode=goal,
                    )
                ).classes("text-sm leading-6 text-gray-600")
                status = str(
                    node.get("computed_status")
                    or (route_item or {}).get("status")
                    or "NOT_RELEVANT"
                )
                ui.label(intent_status_label(status, goal)).classes(
                    f"ln-status-{status} self-start rounded-full px-3 py-1 text-xs font-bold"
                )
                ui.label("当前路径不可原地修改。 ").classes("text-xs text-gray-500")
                ui.link("创建编辑副本", path_revision_href(project_id, path_id)).classes(
                    "text-sm font-bold no-underline"
                )
            else:
                action_kind = (
                    ui.select(
                        {
                            "LEARN": "学习 / 建立理解",
                            "EXPLORE": "探索 / 收集信息",
                            "EXECUTE": "执行 / 推进行动",
                            "PRACTICE": "练习 / 应用",
                            "REVIEW": "复查 / 复习",
                            "VERIFY": "验证 / 验收",
                        },
                        value=str(path_step.get("action_kind") or "LEARN"),
                        label="本次动作",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                stage = (
                    ui.input(
                        "阶段（可选）",
                        value=str(path_step.get("stage") or ""),
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                priority = ui.slider(
                    min=0,
                    max=100,
                    value=int(path_step.get("priority") or 50),
                ).props("label-always")
                estimated_minutes = (
                    ui.number(
                        "预计分钟",
                        value=path_step.get("estimated_minutes"),
                        min=0,
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                is_required = ui.checkbox("必需步骤", value=bool(path_step.get("is_required")))
                is_pinned = ui.checkbox("固定在路径中", value=bool(path_step.get("is_pinned")))
                is_deferred = ui.checkbox("暂缓", value=bool(path_step.get("is_deferred")))
                user_note = (
                    ui.textarea(
                        "路径备注",
                        value=str(path_step.get("user_note") or ""),
                    )
                    .props("outlined autogrow")
                    .classes("w-full")
                )

                async def save_path_step() -> None:
                    try:
                        await client.patch(
                            f"/path-revisions/{path_id}/steps/{path_step['id']}",
                            json={
                                "expected_revision": path_row_version,
                                "action_kind": action_kind.value,
                                "stage": str(stage.value or "").strip() or None,
                                "priority": int(priority.value),
                                "estimated_minutes": (
                                    int(estimated_minutes.value)
                                    if estimated_minutes.value is not None
                                    else None
                                ),
                                "is_required": bool(is_required.value),
                                "is_pinned": bool(is_pinned.value),
                                "is_deferred": bool(is_deferred.value),
                                "user_note": str(user_note.value or "").strip() or None,
                            },
                        )
                        ui.notify("路径设置已保存到草稿", type="positive")
                        ui.navigate.to(current_href)
                    except UIAPIError as exc:
                        error_notice(str(exc))

                ui.button("保存路径设置", icon="save", on_click=save_path_step).props(
                    "color=positive"
                ).classes("w-full")
                ui.label("发布前会校验硬依赖；路径顺序不会反写到框架关系。 ").classes(
                    "text-xs text-gray-500"
                )

        with ui.expansion("状态与记录", icon="fact_check", value=panel == "action").classes(
            "mt-2 w-full rounded-xl border border-gray-200"
        ):
            status = str(
                node.get("computed_status") or (route_item or {}).get("status") or "NOT_RELEVANT"
            )
            ui.label(intent_status_label(status, goal)).classes(
                f"ln-status-{status} self-start rounded-full px-3 py-1 text-xs font-bold"
            )
            started_at = datetime.now(UTC)
            note = (
                ui.textarea(copy["workbench_result"]).props("outlined autogrow").classes("w-full")
            )
            self_rating = ui.slider(min=1, max=5, value=3).props("label-always")
            with ui.expansion("补充", icon="edit_note").classes("w-full"):
                difficulties = ui.input("阻碍或疑问").props("outlined dense").classes("w-full")
                next_step = ui.input("下次从哪里继续").props("outlined dense").classes("w-full")

            async def save_session() -> None:
                try:
                    await client.post(
                        "/learning-sessions",
                        json={
                            "node_id": node_id,
                            "started_at": started_at.isoformat(),
                            "ended_at": datetime.now(UTC).isoformat(),
                            "resource_ids": [],
                            "note": note.value or None,
                            "difficulties": difficulties.value or None,
                            "self_rating": int(self_rating.value),
                            "next_step": next_step.value or None,
                            "evidence": [],
                        },
                    )
                    ui.notify(f"{copy['record_label']}已保存", type="positive")
                    ui.navigate.to(project_href(project_id, "overview", node_id=node_id))
                except UIAPIError as exc:
                    error_notice(str(exc))

            ui.button(copy["finish_action"], icon="check_circle", on_click=save_session).props(
                "color=positive"
            ).classes("ln-action-button w-full")

        with ui.expansion(f"关系 · {len(related_edges)}", icon="lan").classes(
            "mt-2 w-full rounded-xl border border-gray-200"
        ):
            for edge in related_edges:
                source = str(edge.get("source_node_id") or "")
                edge_target = str(edge.get("target_node_id") or "")
                other = edge_target if source == node_id else source
                arrow = "→" if source == node_id else "←"
                ui.label(
                    f"{arrow} {names.get(other, other)} · "
                    f"{RELATION_TYPE_OPTIONS.get(str(edge.get('relation_type')), '关联')}"
                ).classes("text-xs leading-5 text-gray-600")
            other_nodes = {key: value for key, value in names.items() if key != node_id}
            if other_nodes:
                target = (
                    ui.select(other_nodes, label="关联要素")
                    .props("outlined dense")
                    .classes("w-full")
                )
                relation = (
                    ui.select(
                        RELATION_TYPE_OPTIONS,
                        value="RELATED",
                        label="关系",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                direction = (
                    ui.toggle({"OUT": "当前 → 对方", "IN": "对方 → 当前"}, value="OUT")
                    .props("no-caps spread")
                    .classes("w-full")
                )

                async def add_relation() -> None:
                    if not target.value:
                        ui.notify("请选择关联要素", type="warning")
                        return
                    source_id, target_id = (
                        (node_id, target.value)
                        if direction.value == "OUT"
                        else (target.value, node_id)
                    )
                    try:
                        await client.post(
                            f"/spaces/{space_id}/edges",
                            json={
                                "source_node_id": source_id,
                                "target_node_id": target_id,
                                "relation_type": relation.value,
                                "strength": 1.0,
                                "confidence": 1.0,
                                "required_mastery_level": 3
                                if relation.value == "PREREQUISITE"
                                else 0,
                                "reason": "用户在项目工作区添加",
                                "source_reference": [],
                            },
                        )
                        ui.notify("关系已加入框架草稿", type="positive")
                        ui.navigate.to(current_href)
                    except UIAPIError as exc:
                        error_notice(str(exc))

                ui.button("添加关系", icon="add_link", on_click=add_relation).props(
                    "outline color=positive"
                ).classes("w-full")


def _checkin_time_label(value: Any) -> str:
    """Format one server timestamp in the viewer's local timezone."""

    raw = str(value or "").strip()
    if not raw:
        return "时间未知"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone()
        return parsed.strftime("%m月%d日 %H:%M")
    except ValueError:
        return raw.replace("T", " ")[:16]


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


_SAFE_PREVIEW_IMAGE_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

_CHECKIN_CLIPBOARD_PASTE_BOOTSTRAP = r"""
(() => {
  if (window.LearningNavigatorCheckinPaste) return;

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
    document.querySelectorAll('.ln-checkin-upload')
  ).find(element => element.offsetParent !== null);

  document.addEventListener('paste', event => {
    const uploader = visibleUploader();
    if (!uploader) return;
    const images = Array.from(event.clipboardData?.files || [])
      .filter(file => String(file.type || '').toLowerCase().startsWith('image/'));
    if (!images.length) return;

    const input = uploader.querySelector('input[type="file"]');
    if (!input || typeof DataTransfer === 'undefined') return;
    const transfer = new DataTransfer();
    const stamp = timestamp();
    images.forEach((image, index) => {
      const type = image.type || 'image/png';
      const originalName = String(image.name || '').trim();
      const genericName = !originalName || /^image\.(png|jpe?g|gif|webp|avif)$/i.test(originalName);
      const name = genericName
        ? `截图-${stamp}${images.length > 1 ? `-${index + 1}` : ''}.${extensionFor(type)}`
        : originalName;
      transfer.items.add(new File([image], name, {type, lastModified: Date.now()}));
    });
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
    event.preventDefault();
  });

  window.LearningNavigatorCheckinPaste = {enabled: true};
})();
"""


def _attachment_browser_url(client: UIAPIClient, raw_url: str) -> str:
    """Turn an API-relative attachment URL into a browser-safe absolute URL."""

    if raw_url.startswith("/api/"):
        return f"{client.base_url.rstrip('/')}/{raw_url.removeprefix('/api/')}"
    return raw_url


async def _upload_checkin_files(
    client: UIAPIClient,
    checkin_id: str,
    files: list[Any],
) -> list[str]:
    """Stream selected NiceGUI uploads to one durable check-in."""

    failures: list[str] = []
    for uploaded in files:
        filename = str(getattr(uploaded, "name", "") or "attachment")
        content_type = str(getattr(uploaded, "content_type", "") or "application/octet-stream")
        try:
            await client.upload(
                f"/progress-check-ins/{checkin_id}/attachments",
                filename=filename,
                content_type=content_type,
                chunks=uploaded.iterate(),
            )
        except (UIAPIError, OSError):
            failures.append(filename)
    return failures


async def _refresh_preserving_scroll(href: str) -> None:
    """Refresh a project projection without sending the learner back to the top."""

    await ui.run_javascript(
        "sessionStorage.setItem('ln-preserved-scroll-y', String(window.scrollY || 0));"
    )
    ui.navigate.to(href)


async def _refresh_checkin_surface(
    on_refresh: Callable[[], Awaitable[None]] | None,
    current_href: str,
) -> None:
    """Refresh only the mounted check-in inspector when the page provides one."""

    if on_refresh is not None:
        await on_refresh()
        return
    await _refresh_preserving_scroll(current_href)


async def _refresh_checkin_ai_evaluation(client: UIAPIClient, checkin_id: str) -> bool:
    if not checkin_id:
        return False
    try:
        await client.post(
            f"/progress-check-ins/{checkin_id}/ai-evaluation",
            json={"confirmed_external_ai": True},
        )
    except UIAPIError:
        return False
    return True


def _render_attachment_uploader(
    pending_files: list[Any],
    uploading: dict[str, bool],
) -> None:
    """Render an unlimited multi-file picker backed by NiceGUI's disk spooling."""

    def begin_upload(_event: Any) -> None:
        uploading["active"] = True

    def collect_file(event: events.UploadEventArguments) -> None:
        pending_files.append(event.file)

    def finish_upload(_event: Any) -> None:
        uploading["active"] = False

    ui.label("图片与文件（可多选）").classes("text-sm font-black")
    ui.upload(
        multiple=True,
        auto_upload=True,
        on_begin_upload=begin_upload,
        on_upload=collect_file,
        on_multi_upload=finish_upload,
        label="选择图片或文件",
    ).props("flat bordered color=positive").classes("ln-checkin-upload w-full")
    ui.run_javascript(_CHECKIN_CLIPBOARD_PASTE_BOOTSTRAP)
    ui.label("也可以在这个窗口直接按 Ctrl+V 粘贴截图。 ").classes(
        "text-xs font-bold text-green-800"
    )
    ui.label("不限制文件大小；实际可用容量取决于本机磁盘空间。").classes("text-xs text-gray-500")


def _render_checkin_attachments(
    client: UIAPIClient,
    attachments: list[dict[str, Any]],
    *,
    current_href: str,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> None:
    if not attachments:
        return

    with ui.column().classes("ln-checkin-attachments w-full gap-2"):
        for attachment in attachments:
            attachment_id = str(attachment.get("id") or "")
            filename = str(attachment.get("original_name") or "附件")
            media_type = str(attachment.get("media_type") or "application/octet-stream")
            content_url = _attachment_browser_url(
                client,
                str(attachment.get("content_url") or ""),
            )
            download_url = _attachment_browser_url(
                client,
                str(attachment.get("download_url") or content_url),
            )
            with ui.row().classes("ln-checkin-attachment w-full items-center gap-2"):
                if media_type.lower() in _SAFE_PREVIEW_IMAGE_TYPES and content_url:
                    ui.image(content_url).props("fit=cover loading=lazy").classes(
                        "ln-checkin-attachment-preview"
                    )
                else:
                    with ui.element("span").classes("ln-checkin-attachment-file-icon"):
                        ui.icon("draft", size="sm").classes("text-green-700")
                with ui.column().classes("ln-checkin-attachment-body min-w-0 grow gap-1"):
                    ui.label(filename).classes("break-all text-xs font-bold leading-5")
                    ui.label(_attachment_size_label(attachment.get("size_bytes"))).classes(
                        "text-xs text-gray-500"
                    )

                    async def delete_attachment(
                        item_id: str = attachment_id,
                        item_name: str = filename,
                    ) -> None:
                        try:
                            await client.delete(f"/progress-check-in-attachments/{item_id}")
                        except UIAPIError as exc:
                            error_notice(str(exc))
                            return
                        ui.notify(f"已删除附件：{item_name}", type="positive")
                        await _refresh_checkin_surface(on_refresh, current_href)

                    with (
                        ui.dialog() as delete_dialog,
                        ui.card().classes("ln-checkin-dialog gap-4 p-5"),
                    ):
                        ui.label("删除这个附件？").classes("text-lg font-black")
                        ui.label(filename).classes("break-all text-sm text-gray-600")
                        ui.label("文件将从本机永久删除，打卡记录本身会保留。").classes(
                            "text-xs font-bold text-red-800"
                        )
                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("取消", on_click=delete_dialog.close).props("flat")
                            ui.button("确认删除", on_click=delete_attachment).props(
                                "color=negative"
                            )
                    with ui.row().classes("ln-checkin-attachment-actions items-center gap-1"):
                        if content_url:
                            ui.link("查看大图", content_url, new_tab=True).classes(
                                "text-xs font-bold text-green-700"
                            )
                        if download_url:
                            ui.link("下载", download_url, new_tab=True).classes(
                                "text-xs font-bold text-green-700"
                            )
                        ui.button(icon="delete", on_click=delete_dialog.open).props(
                            f"flat round dense color=negative aria-label='删除附件 {filename}'"
                        )


def _render_checkin_edit_dialog(
    client: UIAPIClient,
    checkin: dict[str, Any],
    *,
    current_href: str,
    goal: dict[str, Any] | None = None,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> Any:
    """Render the only flow that may lower a recorded progress score."""

    checkin_id = str(checkin.get("id") or "")
    raw_original_score = checkin.get("score")
    original_score = int(raw_original_score) if raw_original_score is not None else 1
    progress_label = intent_progress_label(original_score * 10, goal or {})
    saving = {"active": False}
    uploading = {"active": False}
    pending_files: list[Any] = []
    with ui.dialog() as dialog, ui.card().classes("ln-checkin-dialog gap-5 p-5 sm:p-6"):
        with ui.column().classes("w-full gap-1"):
            ui.label("修改打卡").classes("text-xl font-black")
            ui.label(_checkin_time_label(checkin.get("checked_in_at"))).classes(
                "text-xs text-gray-500"
            )
            ui.label(progress_label).classes("text-xs font-bold text-green-800")
            ui.label("修改模式允许纠正为更低的分数，原打卡日期不会改变。").classes(
                "text-sm leading-6 text-gray-600"
            )
        edit_score = (
            ui.slider(
                min=1,
                max=10,
                step=1,
                value=max(1, original_score),
            )
            .props("snap markers label-always aria-label='修改总体进度评分，满分十分'")
            .classes("w-full")
        )
        edit_note = (
            ui.textarea("备注（可选）", value=str(checkin.get("note") or ""))
            .props("outlined autogrow maxlength=2000")
            .classes("w-full")
        )
        edit_duration = (
            ui.number(
                "投入时间（分钟）",
                value=int(checkin.get("duration_minutes") or 0),
                min=0,
                max=1440,
                step=5,
            )
            .props("outlined suffix='分钟' aria-label='本次投入时间，分钟'")
            .classes("w-full")
        )
        _render_checkin_attachments(
            client,
            _dict_items(checkin.get("attachments")),
            current_href=current_href,
            on_refresh=on_refresh,
        )
        _render_attachment_uploader(pending_files, uploading)

        async def save_edit() -> None:
            if saving["active"]:
                return
            if uploading["active"]:
                ui.notify("文件仍在读取，请稍候再保存。", type="warning")
                return
            saving["active"] = True
            save_button.props("loading disable")
            try:
                await client.patch(
                    f"/progress-check-ins/{checkin_id}",
                    json={
                        "expected_revision": int(checkin.get("row_version") or 1),
                        "score": int(edit_score.value),
                        "note": str(edit_note.value or "").strip() or None,
                        "duration_minutes": int(edit_duration.value or 0),
                    },
                )
                failed_files = await _upload_checkin_files(
                    client,
                    checkin_id,
                    pending_files,
                )
                evaluation_ready = await _refresh_checkin_ai_evaluation(client, checkin_id)
            except UIAPIError as exc:
                saving["active"] = False
                save_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            change = f"{original_score} → {int(edit_score.value)}"
            if failed_files:
                ui.notify(
                    f"打卡已修改，但 {len(failed_files)} 个附件上传失败，可重新打开修改后重试。",
                    type="warning",
                )
            else:
                ui.notify(f"打卡已修改：{change}", type="positive")
            if not evaluation_ready:
                ui.notify("打卡已保存，AI 评语暂未生成，可稍后再次修改触发。", type="warning")
            await _refresh_checkin_surface(on_refresh, current_href)

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat").classes("max-sm:w-full")
            save_button = (
                ui.button("保存修改", icon="save", on_click=save_edit)
                .props("color=positive")
                .classes("max-sm:w-full")
            )
    dialog.props("aria-label='修改进度打卡'")
    return dialog


def _render_checkin_clear_dialog(
    client: UIAPIClient,
    latest_checkin: dict[str, Any],
    *,
    project_id: str,
    node_id: str,
    current_href: str,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> Any:
    """Render a destructive clear action with an explicit second confirmation."""

    clearing = {"active": False}
    latest_checkin_id = str(latest_checkin.get("id") or "")
    latest_revision = int(latest_checkin.get("row_version") or 1)
    with (
        ui.dialog() as dialog,
        ui.card().classes("ln-checkin-dialog ln-checkin-reset-dialog gap-5 p-5 sm:p-6"),
    ):
        with ui.column().classes("w-full gap-2"):
            ui.label("删除这个节点的全部进度？").classes("text-xl font-black")
            ui.label("全部打卡、备注、AI 评语和附件会从进度、统计与时间线中移除。").classes(
                "text-sm leading-6 text-gray-600"
            )
            ui.label(
                "系统会在本地回收站保留一份恢复副本；确认后当前页面将像从未打卡一样。"
            ).classes("text-xs font-bold text-red-800")

        async def clear_progress() -> None:
            if clearing["active"]:
                return
            clearing["active"] = True
            clear_button.props("loading disable")
            try:
                await client.post(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins/clear",
                    json={
                        "expected_check_in_id": latest_checkin_id,
                        "expected_revision": latest_revision,
                    },
                )
            except UIAPIError as exc:
                clearing["active"] = False
                clear_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            ui.notify("进度已移到回收站", type="positive")
            await _refresh_checkin_surface(on_refresh, current_href)

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat").classes("max-sm:w-full")
            clear_button = (
                ui.button("确认删除全部进度", icon="delete_sweep", on_click=clear_progress)
                .props("outline color=negative")
                .classes("ln-checkin-reset max-sm:w-full")
            )
    dialog.props("aria-label='确认删除节点全部进度'")
    return dialog


def _render_checkin_timeline(
    client: UIAPIClient,
    checkins: list[dict[str, Any]],
    *,
    current_href: str,
    detail_href: str,
    goal: dict[str, Any] | None = None,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Render a stable newest-first progress chain."""

    ui.label("进度记录").classes("mt-1 text-sm font-black")
    if not checkins:
        ui.label("还没有记录，完成第一次打卡后会从这里开始。 ").classes(
            "ln-checkin-empty text-sm leading-6 text-gray-600"
        )
        return

    with ui.element("ol").classes("ln-checkin-timeline"):
        for checkin in checkins:
            index = checkins.index(checkin)
            raw_score = checkin.get("score")
            score = int(raw_score) if raw_score is not None else 1
            previous = checkins[index + 1] if index + 1 < len(checkins) else None
            previous_raw_score = previous.get("score") if previous else None
            previous_score = int(previous_raw_score) if previous_raw_score is not None else None
            if previous_score is None:
                movement = "首次"
            elif score > previous_score:
                movement = f"+{score - previous_score}"
            elif score == previous_score:
                movement = "保持"
            else:
                movement = f"已修正 {score - previous_score}"
            edit_dialog = _render_checkin_edit_dialog(
                client,
                checkin,
                current_href=current_href,
                goal=goal,
                on_refresh=on_refresh,
            )
            checked_in_at = str(checkin.get("checked_in_at") or "")
            check_in_id = str(checkin.get("id") or "")
            check_in_detail_href = detail_href
            if check_in_id:
                separator = "&" if "?" in detail_href else "?"
                check_in_detail_href = (
                    f"{detail_href}{separator}{urlencode({'check_in_id': check_in_id})}"
                )
            attachments = _dict_items(checkin.get("attachments"))
            detail_label = movement
            if attachments:
                detail_label = f"{movement} · {len(attachments)} 个附件"
            with ui.element("li").classes("ln-checkin-entry"):
                ui.element("span").classes("ln-checkin-dot").props("aria-hidden=true")
                with ui.column().classes("min-w-0 grow gap-1"):
                    with ui.row().classes("w-full flex-nowrap items-center gap-2"):
                        with (
                            ui.element("time")
                            .props(f"datetime='{checked_in_at}'")
                            .classes("min-w-0 grow text-xs font-bold text-gray-600")
                        ):
                            ui.link(
                                _checkin_time_label(checked_in_at),
                                check_in_detail_href,
                            ).props(
                                f"aria-label='查看{_checkin_time_label(checked_in_at)}"
                                "这次打卡的 AI 学习评语'"
                            ).classes(
                                "ln-checkin-evaluation-link w-fit text-xs font-bold no-underline"
                            )
                        ui.label(
                            f"{score}/10 · {intent_progress_label(score * 10, goal or {})}"
                        ).classes("ln-checkin-score")
                    note = str(checkin.get("note") or "").strip()
                    with ui.row().classes("w-full flex-nowrap items-start gap-2"):
                        ui.label(note or "无备注").classes(
                            "min-w-0 grow whitespace-pre-wrap break-words text-sm leading-5 "
                            "text-gray-600"
                        )
                        ui.button("修改", on_click=edit_dialog.open).props(
                            f"flat dense color=positive aria-label='修改"
                            f"{_checkin_time_label(checked_in_at)}的打卡'"
                        ).classes("ln-checkin-edit shrink-0")
                    if checkin.get("corrected_at"):
                        ui.label("已修改").classes("ln-checkin-corrected")
                    if attachments:
                        with (
                            ui.expansion(
                                detail_label,
                                icon="attachment",
                                value=False,
                            )
                            .props("dense expand-separator aria-label='展开或收起打卡附件'")
                            .classes("ln-checkin-details w-full")
                        ):
                            _render_checkin_attachments(
                                client,
                                attachments,
                                current_href=current_href,
                                on_refresh=on_refresh,
                            )
                    else:
                        ui.label(movement).classes("text-xs font-bold text-gray-500")


def _render_checkin_panel(
    client: UIAPIClient,
    node: dict[str, Any],
    checkins_payload: dict[str, Any],
    *,
    project_id: str,
    space_id: str,
    current_href: str,
    goal: dict[str, Any] | None = None,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Render the focused current-score action and its dated history."""

    node_id = str(node["id"])
    checkins = _dict_items(checkins_payload.get("items"))
    raw_current_score = checkins_payload.get("current_score")
    current_score = int(raw_current_score) if raw_current_score is not None else 0
    create_score = max(1, current_score)
    today_check_in = (
        checkins_payload.get("today_check_in")
        if isinstance(checkins_payload.get("today_check_in"), dict)
        else None
    )
    copy = intent_profile(goal or {})
    current_progress_label = intent_progress_label(current_score * 10, goal or {})

    with (
        ui.element("section")
        .classes("ln-checkin-summary")
        .props("aria-label='当前节点进度' aria-live='polite'")
    ):
        with ui.column().classes("ln-checkin-summary-main min-w-0 gap-1"):
            ui.label("当前进度").classes("text-xs font-bold text-gray-500")
            if raw_current_score is None:
                ui.label("未评分").classes("text-2xl font-black")
            else:
                with ui.row().classes("items-baseline gap-1"):
                    ui.label(str(raw_current_score)).classes("text-4xl font-black")
                    ui.label("/ 10").classes("text-sm font-bold text-gray-500")
        with ui.row().classes(
            "ln-checkin-summary-footer w-full items-center justify-between gap-3"
        ):
            ui.label(current_progress_label).classes("text-xs font-bold text-green-800")
            recent_label = (
                f"最近打卡 · {_checkin_time_label(checkins[0].get('checked_in_at'))}"
                if checkins
                else "暂无打卡记录"
            )
            ui.label(recent_label).classes("text-right text-xs text-gray-500")

    creating = {"active": False}
    uploading = {"active": False}
    pending_files: list[Any] = []
    with ui.dialog() as checkin_dialog, ui.card().classes("ln-checkin-dialog gap-5 p-5 sm:p-6"):
        ui.label(f"今日{copy['record_label']}").classes("text-xl font-black")
        ui.label(
            f"记录今天推进到哪里。1 到 10 分对应“{copy['progress_levels'][0]['label']}”"
            f"到“{copy['progress_levels'][-1]['label']}”，评分可以保持或提高。"
        ).classes("text-sm leading-6 text-gray-600")
        if create_score == 10:
            score = (
                ui.slider(min=1, max=10, step=1, value=10)
                .props("disable snap markers label-always aria-label='本次总体进度评分，满分十分'")
                .classes("w-full")
            )
        else:
            score = (
                ui.slider(
                    min=create_score,
                    max=10,
                    step=1,
                    value=create_score,
                )
                .props("snap markers label-always aria-label='本次总体进度评分，满分十分'")
                .classes("w-full")
            )
        note = (
            ui.textarea("备注（可选）", placeholder="今天推进了什么？")
            .props("outlined autogrow maxlength=2000")
            .classes("w-full")
        )
        duration = (
            ui.number("投入时间（分钟）", value=60, min=0, max=1440, step=5)
            .props("outlined suffix='分钟' aria-label='本次投入时间，默认六十分钟'")
            .classes("w-full")
        )
        _render_attachment_uploader(pending_files, uploading)

        async def create_checkin() -> None:
            if creating["active"]:
                return
            if uploading["active"]:
                ui.notify("文件仍在读取，请稍候再打卡。", type="warning")
                return
            creating["active"] = True
            checkin_button.props("loading disable")
            try:
                created = await client.post(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins",
                    json={
                        "score": int(score.value),
                        "note": str(note.value or "").strip() or None,
                        "duration_minutes": int(duration.value or 60),
                    },
                )
                checkin_id = str(created.get("id") or "") if isinstance(created, dict) else ""
                failed_files = await _upload_checkin_files(
                    client,
                    checkin_id,
                    pending_files,
                )
                evaluation_ready = await _refresh_checkin_ai_evaluation(client, checkin_id)
            except UIAPIError as exc:
                creating["active"] = False
                checkin_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            checkin_dialog.close()
            if failed_files:
                ui.notify(
                    f"进度已记录，但 {len(failed_files)} 个附件上传失败；可在修改打卡中重试。",
                    type="warning",
                )
            else:
                ui.notify("今日进度已记录", type="positive")
            if not evaluation_ready:
                ui.notify("进度已保存，AI 评语暂未生成，可稍后再次修改触发。", type="warning")
            await _refresh_checkin_surface(on_refresh, current_href)

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=checkin_dialog.close).props("flat").classes("max-sm:w-full")
            checkin_button = (
                ui.button("打卡", icon="check_circle", on_click=create_checkin)
                .props("color=positive")
                .classes("ln-action-button max-sm:w-full")
            )
    checkin_dialog.props("aria-label='新增进度打卡'")

    if today_check_in is None:
        ui.button("打卡", icon="check_circle", on_click=checkin_dialog.open).props(
            "color=positive aria-label='记录今日进度'"
        ).classes("ln-action-button w-full")
    else:
        today_dialog = _render_checkin_edit_dialog(
            client,
            today_check_in,
            current_href=current_href,
            goal=goal,
            on_refresh=on_refresh,
        )
        ui.button("修改今日打卡", icon="edit", on_click=today_dialog.open).props(
            "outline color=positive aria-label='修改今日打卡'"
        ).classes("ln-action-button w-full")

    if checkins:
        clear_dialog = _render_checkin_clear_dialog(
            client,
            checkins[0],
            project_id=project_id,
            node_id=node_id,
            current_href=current_href,
            on_refresh=on_refresh,
        )
        ui.button("删除全部进度", icon="delete_sweep", on_click=clear_dialog.open).props(
            "flat color=negative aria-label='删除当前节点全部进度'"
        ).classes("ln-checkin-reset w-full")

    clear_recovery = (
        checkins_payload.get("clear_recovery")
        if isinstance(checkins_payload.get("clear_recovery"), dict)
        else None
    )
    if not checkins and clear_recovery:
        restoring = {"active": False}
        deleting_recovery = {"active": False}

        async def restore_cleared_progress() -> None:
            if restoring["active"]:
                return
            batch_id = str(clear_recovery.get("id") or "")
            if not batch_id:
                error_notice("恢复记录无效，请刷新后重试。")
                return
            restoring["active"] = True
            restore_button.props("loading disable")
            try:
                await client.post(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins/"
                    f"clear-recovery/{batch_id}/restore",
                )
            except UIAPIError as exc:
                restoring["active"] = False
                restore_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            ui.notify("已恢复删除前的全部进度", type="positive")
            await _refresh_checkin_surface(on_refresh, current_href)

        record_count = int(clear_recovery.get("record_count") or 0)
        attachment_count = int(clear_recovery.get("attachment_count") or 0)
        restore_button = (
            ui.button(
                f"恢复已删除进度（{record_count} 次打卡 · {attachment_count} 个附件）",
                icon="restore_from_trash",
                on_click=restore_cleared_progress,
            )
            .props("outline color=positive aria-label='从回收站恢复节点全部进度'")
            .classes("ln-action-button w-full")
        )

        async def delete_cleared_progress_permanently() -> None:
            if deleting_recovery["active"]:
                return
            batch_id = str(clear_recovery.get("id") or "")
            if not batch_id:
                error_notice("回收记录无效，请刷新后重试。")
                return
            deleting_recovery["active"] = True
            permanent_delete_button.props("loading disable")
            try:
                await client.delete(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins/clear-recovery/{batch_id}",
                )
            except UIAPIError as exc:
                deleting_recovery["active"] = False
                permanent_delete_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            permanent_delete_dialog.close()
            ui.notify("已彻底删除回收的进度和附件", type="positive")
            await _refresh_checkin_surface(on_refresh, current_href)

        with (
            ui.dialog() as permanent_delete_dialog,
            ui.card().classes("ln-checkin-dialog gap-5 p-5 sm:p-6"),
        ):
            with ui.row().classes("w-full items-start gap-3 flex-nowrap"):
                ui.icon("warning_amber", color="negative").classes("mt-0.5 text-2xl")
                with ui.column().classes("min-w-0 gap-1"):
                    ui.label("彻底删除已回收进度？").classes("text-lg font-black")
                    ui.label(
                        f"将永久删除 {record_count} 次打卡和 {attachment_count} 个附件，"
                        "且无法恢复。框架、路径及其他节点不会被修改。"
                    ).classes("text-sm leading-6 text-gray-600")
            with ui.row().classes(
                "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
            ):
                ui.button("取消", on_click=permanent_delete_dialog.close).props("flat")
                permanent_delete_button = (
                    ui.button(
                        "确认彻底删除",
                        icon="delete_forever",
                        on_click=delete_cleared_progress_permanently,
                    )
                    .props("color=negative")
                    .classes("max-sm:w-full")
                )
        permanent_delete_dialog.props("aria-label='彻底删除已回收进度确认' role='alertdialog'")
        ui.button(
            "彻底删除",
            icon="delete_forever",
            on_click=permanent_delete_dialog.open,
        ).props("flat color=negative aria-label='彻底删除回收站中的节点进度和附件'").classes(
            "ln-checkin-reset w-full"
        )

    if checkins_payload.get("load_error"):
        ui.label(str(checkins_payload["load_error"])).classes(
            "rounded-lg bg-red-50 px-3 py-2 text-xs font-bold text-red-800"
        )

    detail_href = (
        f"/maps/{quote(space_id, safe='')}/nodes/{quote(node_id, safe='')}?"
        f"{urlencode({'goal_id': project_id})}"
    )
    _render_checkin_timeline(
        client,
        checkins,
        current_href=current_href,
        detail_href=detail_href,
        goal=goal,
        on_refresh=on_refresh,
    )


def _render_inspector(
    client: UIAPIClient,
    project: dict[str, Any],
    graph: dict[str, Any],
    node: dict[str, Any],
    selected_revision: dict[str, Any] | None,
    checkins: dict[str, Any],
    *,
    project_id: str,
    section: str,
    panel: str | None,
    edit: str | None,
    on_close: Callable[[], Awaitable[None]] | None = None,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Keep the persistent side rail focused on one user decision: log progress."""

    _ = panel
    selected_path = (
        selected_revision.get("path")
        if isinstance(selected_revision, dict) and isinstance(selected_revision.get("path"), dict)
        else None
    )
    path_id = str(selected_path.get("id") or "") if selected_path else ""
    editing_path = edit in {"path", "structure"}
    return_href = (
        path_revision_href(project_id, path_id)
        if editing_path
        else project_href(project_id, section)
    )
    current_href = (
        path_revision_href(project_id, path_id, node_id=str(node["id"]))
        if editing_path
        else project_href(project_id, section, node_id=str(node["id"]))
    )
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    route = _dict_items(project.get("route"))
    route_position = next(
        (
            index
            for index, item in enumerate(route, start=1)
            if str(item.get("node_id") or "") == str(node["id"])
        ),
        None,
    )
    node_type_label = NODE_TYPE_OPTIONS.get(str(node.get("node_type")), "框架要素")
    position_label = (
        f"路径 {route_position}/{len(route)} · {node_type_label}"
        if route_position is not None
        else f"未加入当前路径 · {node_type_label}"
    )

    with (
        ui.element("aside")
        .classes("ln-node-inspector ln-checkin-panel")
        .props(f"aria-label='当前路径位置：{position_label}'")
    ):
        with ui.row().classes("w-full flex-nowrap items-start justify-between gap-2"):
            with ui.column().classes("min-w-0 grow gap-1"):
                ui.label(position_label).classes("ln-kicker")
                ui.label(str(node.get("title") or "未命名要素")).classes(
                    "line-clamp-2 text-xl font-black"
                )
            with ui.row().classes("shrink-0 flex-nowrap gap-0"):
                with ui.button(icon="more_vert").props(
                    "flat round dense aria-label='节点更多操作'"
                ):
                    with ui.menu():
                        ui.menu_item(
                            "编辑框架",
                            on_click=lambda: ui.navigate.to(
                                project_href(project_id, "map") + "?edit=structure"
                            ),
                        )
                        ui.menu_item(
                            "调整项目路径",
                            on_click=lambda: ui.navigate.to(path_revision_href(project_id)),
                        )
                ui.button(
                    icon="close",
                    on_click=(
                        on_close if on_close is not None else lambda: ui.navigate.to(return_href)
                    ),
                ).props("flat round dense aria-label='关闭节点进度面板'")
        ui.separator().classes("my-3")
        _render_checkin_panel(
            client,
            node,
            checkins,
            project_id=project_id,
            space_id=str(project["space_id"]),
            current_href=current_href,
            goal=goal,
            on_refresh=on_refresh,
        )


async def _render_project_page(
    client: UIAPIClient,
    project_id: str,
    section: str,
    *,
    node_id: str | None,
    panel: str | None,
    edit: str | None,
    revision_id: str | None,
    open_assistant: bool = False,
) -> None:
    try:
        dashboard = await client.get("/dashboard")
    except UIAPIError as exc:
        with page_shell("项目不可用", active_path="/projects"):
            error_notice(str(exc))
        return
    project = _project_view(dashboard, project_id)
    if project is None:
        with page_shell("未找到项目", "这个项目可能已归档或删除。", active_path="/projects"):
            with ui.row().classes("items-center gap-4"):
                ui.link("返回项目", "/projects").classes("font-bold no-underline")
                ui.link("查看回收站", "/projects?view=trash").classes("font-bold no-underline")
        return
    graph_error: str | None
    try:
        graph = await client.get(f"/spaces/{project['space_id']}/graph")
    except UIAPIError as exc:
        graph = {"nodes": [], "edges": []}
        graph_error = str(exc)
    else:
        graph_error = None

    try:
        raw_revisions = await client.get(f"/goals/{project_id}/path-revisions")
        revisions = _dict_items(raw_revisions)
    except UIAPIError:
        revisions = []
    active_revision = _active_path_revision(revisions)
    editing_path = edit in {"path", "structure"}
    selected_revision = (
        _selected_edit_revision(revisions, revision_id) if editing_path else active_revision
    )

    nodes = [item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"]
    selected_node = next((item for item in nodes if str(item.get("id")) == node_id), None)
    if node_id and selected_node is None:
        node_id = None

    checkins: dict[str, Any] = {
        "items": [],
        "total": 0,
        "current_score": None,
        "today_check_in": None,
    }
    if selected_node is not None:
        try:
            payload = await client.get(
                f"/goals/{project_id}/nodes/{selected_node['id']}/check-ins",
                params={"limit": 30, "offset": 0},
            )
            if isinstance(payload, dict):
                checkins = payload
        except UIAPIError as exc:
            checkins["load_error"] = str(exc)

    selected_path: dict[str, Any] = {}
    if isinstance(selected_revision, dict):
        candidate_path = selected_revision.get("path")
        if isinstance(candidate_path, dict):
            selected_path = candidate_path

    mind_map_suggestion: dict[str, Any] | None = None
    try:
        raw_suggestions = await client.get(
            "/ai/suggestions",
            params={"space_id": str(project["space_id"])},
        )
        candidates = [
            item
            for item in _dict_items(raw_suggestions)
            if str(item.get("suggestion_type") or "") == "MIND_MAP"
            and str(item.get("target_id") or "") == project_id
        ]
        if candidates:
            mind_map_suggestion = candidates[0]
    except UIAPIError:
        mind_map_suggestion = None

    with page_shell(
        project["goal_title"],
        "一处查看框架、路径、位置与记录。",
        kicker="导航项目",
        active_path="/projects",
        assistant_context=AssistantPageContext.project(
            goal_id=project_id,
            space_id=str(project["space_id"]),
            page_title=str(project["goal_title"]),
            section=section,
            node_id=node_id,
            path_revision_id=str(selected_path.get("id") or "") or None,
            page_state=_build_assistant_page_state(project, selected_node),
        ),
    ) as assistant_handle:
        if open_assistant and assistant_handle is not None:
            ui.timer(0.05, assistant_handle.show, once=True)
        _project_summary(client, project)
        if graph_error:
            error_notice(f"框架暂时不可用：{graph_error}")
        active_section = {"value": section}
        selected_node_state: dict[str, dict[str, Any] | None] = {"value": selected_node}
        content_slot: Any = None
        inspector_slot: Any = None
        workspace: Any = None
        tabs: dict[str, Any] = {}

        def section_href(target: str, target_node_id: str | None = None) -> str:
            return project_href(project_id, target, node_id=target_node_id)

        def render_section(target: str) -> None:
            content_slot.clear()
            with content_slot:
                with ui.element("div").classes("ln-project-view-panel w-full"):
                    if target == "overview":
                        _render_overview(
                            project,
                            graph,
                            project_id=project_id,
                            on_select_node=select_node,
                        )
                    elif target == "map":
                        _render_map(
                            project,
                            graph,
                            selected_revision,
                            project_id=project_id,
                            edit=edit,
                            client=client,
                        )
                    elif target == "mindmap":
                        _render_mindmap(
                            project,
                            graph,
                            project_id=project_id,
                            active_revision=active_revision,
                            suggestion=mind_map_suggestion,
                            client=client,
                        )

        async def replace_project_url(target: str, target_node_id: str | None) -> None:
            href = section_href(target, target_node_id)
            await ui.run_javascript(
                "(() => {"
                "const mount = document.location.pathname.startsWith('/ui/') ? '/ui' : '';"
                f"history.replaceState({{}}, '', mount + {json.dumps(href, ensure_ascii=False)});"
                "})();"
            )

        async def render_inspector_for(node: dict[str, Any]) -> None:
            payload: dict[str, Any] = {
                "items": [],
                "total": 0,
                "current_score": None,
                "today_check_in": None,
            }
            try:
                raw_checkins = await client.get(
                    f"/goals/{project_id}/nodes/{node['id']}/check-ins",
                    params={"limit": 30, "offset": 0},
                )
                if isinstance(raw_checkins, dict):
                    payload = raw_checkins
            except UIAPIError as exc:
                payload["load_error"] = str(exc)
            inspector_slot.clear()
            with inspector_slot:
                _render_inspector(
                    client,
                    project,
                    graph,
                    node,
                    selected_revision,
                    payload,
                    project_id=project_id,
                    section=active_section["value"],
                    panel=panel,
                    edit=edit,
                    on_close=close_inspector,
                    on_refresh=lambda: render_inspector_for(node),
                )

        async def select_node(target_node_id: str) -> None:
            target = next(
                (item for item in nodes if str(item.get("id")) == target_node_id),
                None,
            )
            if target is None:
                return
            selected_node_state["value"] = target
            workspace.classes(add="ln-project-workspace-has-inspector")
            await render_inspector_for(target)
            await replace_project_url(active_section["value"], target_node_id)

        async def close_inspector() -> None:
            selected_node_state["value"] = None
            inspector_slot.clear()
            workspace.classes(remove="ln-project-workspace-has-inspector")
            await replace_project_url(active_section["value"], None)

        async def switch_section(target: str) -> None:
            if target not in {item[0] for item in PROJECT_SECTIONS}:
                return
            active_section["value"] = target
            for tab_section, tab in tabs.items():
                if tab_section == target:
                    tab.classes(add="ln-project-tab-active")
                    tab.props("aria-current=page")
                else:
                    tab.classes(remove="ln-project-tab-active")
                    tab.props(remove="aria-current")
            render_section(target)
            current_node = selected_node_state["value"]
            if current_node is not None:
                await render_inspector_for(current_node)
            await replace_project_url(
                target,
                str(current_node["id"]) if current_node is not None else None,
            )

        tabs = _project_navigation(project_id, section, on_switch=switch_section)
        workspace_classes = "ln-project-workspace"
        if selected_node is not None:
            workspace_classes += " ln-project-workspace-has-inspector"
        workspace = ui.element("div").classes(workspace_classes)
        with workspace:
            content_slot = ui.element("main").classes("ln-project-main flex flex-col gap-4")
            inspector_slot = ui.element("div").classes("ln-project-inspector-slot")
        render_section(section)
        if selected_node is not None:
            inspector_slot.clear()
            with inspector_slot:
                _render_inspector(
                    client,
                    project,
                    graph,
                    selected_node,
                    selected_revision,
                    checkins,
                    project_id=project_id,
                    section=section,
                    panel=panel,
                    edit=edit,
                    on_close=close_inspector,
                    on_refresh=lambda: render_inspector_for(selected_node),
                )


def register(client: UIAPIClient) -> None:
    @ui.page("/projects")
    async def projects_page(
        view: str | None = None,
        archived: str | None = None,
        restored: str | None = None,
        deleted: str | None = None,
    ) -> None:
        recycle_bin = view == "trash"
        with page_shell(
            "项目回收站" if recycle_bin else "项目",
            (
                "已移入的项目会保留框架、路径、进度与对话。"
                if recycle_bin
                else "每个项目共享同一套框架、路径与状态。"
            ),
            active_path="/projects",
        ) as assistant_handle:
            notice = ""
            if archived:
                notice = f"“{archived}”已移到回收站，可随时恢复；首页与项目列表已同步。"
            elif restored:
                notice = f"“{restored}”已恢复；首页与项目列表已同步。"
            elif deleted:
                notice = f"“{deleted}”已永久删除；首页与项目列表已同步。"
            if notice:
                with (
                    ui.element("div")
                    .classes(
                        "w-full rounded-xl border border-green-300 bg-green-50 px-4 py-3 "
                        "text-sm font-bold text-green-900"
                    )
                    .props("role='status' aria-live='polite'")
                ):
                    ui.label(notice)

            if recycle_bin:
                with ui.row().classes("w-full items-center justify-between gap-3"):
                    ui.label("已移入的项目").classes("ln-section-title")
                    ui.link("返回项目", "/projects").classes(
                        "font-bold text-green-700 no-underline"
                    )
                try:
                    archived_payload = await client.get("/goals/archived")
                except UIAPIError as exc:
                    error_notice(str(exc))
                    with ui.card().classes("ln-card w-full items-start gap-3 p-6"):
                        ui.label("回收站暂时不可用").classes("text-xl font-black")
                        ui.label("没有执行任何删除操作，请稍后重试。").classes(
                            "text-sm text-gray-600"
                        )
                        ui.link("重新加载", "/projects?view=trash").classes(
                            "font-bold text-green-700 no-underline"
                        )
                    return
                archived_projects = _archived_project_items(archived_payload)
                if not archived_projects:
                    with ui.card().classes("ln-card w-full items-center gap-2 p-7 text-center"):
                        ui.icon("inventory_2").classes("text-4xl text-gray-400")
                        ui.label("回收站为空").classes("text-xl font-black")
                        ui.label("移入回收站的项目会显示在这里。").classes("text-sm text-gray-600")
                    return
                with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"):
                    for item in archived_projects:
                        project_id = item["id"]
                        project_title = item["title"]
                        permanent_dialog = _render_permanent_delete_dialog(
                            client,
                            project_id=project_id,
                            project_title=project_title,
                        )
                        restore_state: dict[str, Any] = {"active": False, "button": None}

                        async def restore_project(
                            project_id: str = project_id,
                            project_title: str = project_title,
                            restore_state: dict[str, Any] = restore_state,
                        ) -> None:
                            if restore_state["active"]:
                                return
                            restore_state["active"] = True
                            restore_button = restore_state.get("button")
                            if restore_button is not None:
                                restore_button.props("loading disable")
                            try:
                                await client.post(f"/goals/{project_id}/restore")
                            except UIAPIError as exc:
                                restore_state["active"] = False
                                if restore_button is not None:
                                    restore_button.props(remove="loading disable")
                                error_notice(str(exc))
                                return
                            ui.notify(f"“{project_title}”已恢复。", type="positive")
                            ui.navigate.to(f"/projects?{urlencode({'restored': project_title})}")

                        with ui.card().classes("ln-card min-w-0 gap-4 p-5"):
                            ui.label(project_title).classes("line-clamp-2 text-lg font-black")
                            if item["archived_at"]:
                                ui.label(
                                    f"移入时间 · {item['archived_at'][:16].replace('T', ' ')}"
                                ).classes("text-xs text-gray-500")
                            ui.label("框架、路径、进度和项目对话仍保存在本地。").classes(
                                "text-sm text-gray-600"
                            )
                            with ui.row().classes("mt-auto w-full items-center gap-2"):
                                restore_state["button"] = ui.button(
                                    "恢复项目",
                                    icon="restore",
                                    on_click=restore_project,
                                ).props("color=positive no-caps")
                                ui.button(
                                    "永久删除",
                                    icon="delete_forever",
                                    on_click=permanent_dialog.open,
                                ).props("flat color=negative no-caps")
                return

            try:
                dashboard = await client.get("/dashboard")
            except UIAPIError as exc:
                error_notice(str(exc))
                return
            dashboard_view = build_parallel_dashboard_view_model(dashboard)
            with ui.row().classes("w-full items-center justify-between gap-3"):
                ui.label("进行中的项目").classes("ln-section-title")
                ui.link("回收站", "/projects?view=trash").classes(
                    "font-bold text-green-700 no-underline"
                )
            if not dashboard_view["has_goals"]:
                with ui.card().classes("ln-card w-full items-center p-7 text-center"):
                    ui.label("还没有项目").classes("text-2xl font-black")
                    ui.label("从一个目标或问题开始，先建立可编辑框架。 ").classes(
                        "text-sm text-gray-600"
                    )
                    ui.button(
                        "新建项目",
                        icon="add",
                        on_click=(
                            assistant_handle.start_new_project
                            if assistant_handle is not None
                            else None
                        ),
                    ).props("color=positive")
                return
            with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"):
                for project in dashboard_view["goals"]:
                    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
                    copy = intent_profile(goal)
                    with ui.card().classes("ln-card ln-interactive-card min-w-0 p-5"):
                        with ui.row().classes("w-full items-start gap-3 flex-nowrap"):
                            with ui.column().classes("min-w-0 grow gap-1"):
                                ui.label(copy["mode_label"]).classes("ln-kicker")
                                ui.link(
                                    project["goal_title"],
                                    project_href(project["goal_id"]),
                                ).classes("line-clamp-2 text-xl font-black no-underline")
                            _render_project_actions(
                                client,
                                project_id=str(project["goal_id"]),
                                project_title=str(project["goal_title"]),
                            )
                        next_step = project.get("next_step")
                        ui.label(
                            f"下一路径节点：{next_step['title']}"
                            if isinstance(next_step, dict)
                            else "当前暂无下一路径节点"
                        ).classes("mt-2 line-clamp-1 text-sm text-gray-600")
                        ui.linear_progress(value=project["progress_percent"] / 100).classes(
                            "mt-4"
                        ).props("rounded color=positive")
                        with ui.row().classes("mt-2 w-full justify-between text-xs text-gray-500"):
                            ui.label(f"{project['progress_percent']}%")
                            ui.label(f"{project['total_count']} 步")

    @ui.page("/projects/{project_id}")
    async def project_root(project_id: str) -> None:
        ui.navigate.to(project_href(project_id))

    @ui.page("/projects/{project_id}/overview")
    async def project_overview(
        project_id: str,
        node: str | None = None,
        panel: str | None = None,
        edit: str | None = None,
        revision: str | None = None,
        ai: str | None = None,
    ) -> None:
        await _render_project_page(
            client,
            project_id,
            "overview",
            node_id=node,
            panel=panel,
            edit=edit,
            revision_id=revision,
            open_assistant=ai == "open",
        )

    @ui.page("/projects/{project_id}/map")
    async def project_map(
        project_id: str,
        node: str | None = None,
        edit: str | None = None,
        revision: str | None = None,
    ) -> None:
        await _render_project_page(
            client,
            project_id,
            "map",
            node_id=node,
            panel=None,
            edit=edit,
            revision_id=revision,
        )

    @ui.page("/projects/{project_id}/mindmap")
    async def project_mindmap(
        project_id: str,
        node: str | None = None,
        ai: str | None = None,
    ) -> None:
        await _render_project_page(
            client,
            project_id,
            "mindmap",
            node_id=node,
            panel=None,
            edit=None,
            revision_id=None,
            open_assistant=ai == "open",
        )

    @ui.page("/projects/{project_id}/collaboration")
    async def project_collaboration(project_id: str) -> None:
        ui.navigate.to(project_href(project_id, "overview") + "?ai=open")

    @ui.page("/projects/{project_id}/path")
    async def project_path(
        project_id: str,
        node: str | None = None,
        revision: str | None = None,
    ) -> None:
        ui.navigate.to(path_revision_href(project_id, revision, node_id=node))

    @ui.page("/projects/{project_id}/progress")
    async def project_progress(project_id: str, node: str | None = None) -> None:
        ui.navigate.to(project_href(project_id, "overview", node_id=node) + "#current-route")
