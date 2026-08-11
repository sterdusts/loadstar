"""Unified project workspace for maps, paths, state and activity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from nicegui import events, ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.components.navigation import (
    build_full_map_options,
    full_map_height,
)
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    build_parallel_dashboard_view_model,
    intent_action_label,
    intent_profile,
    intent_status_label,
    localize_route_reason,
)

PROJECT_SECTIONS = (
    ("overview", "概览", "space_dashboard"),
    ("map", "框架", "hub"),
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
    params = [("edit", "path")]
    if revision_id:
        params.append(("revision", revision_id))
    if node_id:
        params.append(("node", node_id))
    return f"{project_href(project_id, 'overview')}?{urlencode(params)}"


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


def _project_navigation(project_id: str, active_section: str) -> None:
    with ui.element("nav").classes("ln-project-tabs").props("aria-label='项目导航'"):
        for section, label, icon in PROJECT_SECTIONS:
            classes = "ln-project-tab"
            if section == active_section:
                classes += " ln-project-tab-active"
            with ui.link("", project_href(project_id, section)).classes(classes) as link:
                if section == active_section:
                    link.props("aria-current=page")
                with ui.row().classes("items-center gap-1.5 flex-nowrap"):
                    ui.icon(icon).classes("text-base")
                    ui.label(label)


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
) -> None:
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    copy = intent_profile(goal)
    next_step = project.get("next_step")
    nodes = [item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"]
    modules = [item for item in nodes if item.get("node_type") == "MODULE"]
    route = _dict_items(project.get("route"))
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
                    ui.button(
                        intent_action_label(next_step["status"], goal),
                        icon="play_arrow",
                        on_click=lambda: ui.navigate.to(
                            project_href(project_id, "overview", node_id=next_step["node_id"])
                            + "&panel=action"
                        ),
                    ).classes("ln-action-button").props("color=positive")
                    ui.button(
                        "查看路径位置",
                        icon="route",
                        on_click=lambda: ui.navigate.to(
                            project_href(project_id, "overview", node_id=next_step["node_id"])
                            + "#current-route"
                        ),
                    ).props("outline color=positive")
            else:
                ui.label("当前没有可推进项").classes("text-xl font-black")
                ui.label("检查当前路径，或进入编辑后调整步骤。 ").classes(
                    "mt-1 text-sm text-gray-600"
                )
                ui.link("编辑路径", path_revision_href(project_id)).classes("mt-3 font-bold")

        with ui.card().classes("ln-card min-w-0 p-5"):
            ui.label("项目全貌").classes("text-lg font-black")
            with ui.grid().classes("mt-3 w-full grid-cols-3 gap-2"):
                for value, label in (
                    (len(modules), copy["module_label"]),
                    (len(nodes), copy["node_label"]),
                    (project["total_count"], copy["route_label"]),
                ):
                    with ui.column().classes("items-center gap-1 rounded-xl bg-green-50 p-3"):
                        ui.label(str(value)).classes("text-xl font-black text-green-800")
                        ui.label(label).classes("text-center text-xs text-gray-600")
            ui.link("打开完整框架", project_href(project_id, "map")).classes(
                "mt-4 block font-bold no-underline"
            )

    with ui.card().classes("ln-card w-full p-4 sm:p-5").props("id=current-route"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("min-w-0 gap-0"):
                ui.label("当前路径").classes("text-lg font-black")
                ui.label("按顺序推进，打卡后自动更新。 ").classes("text-xs text-gray-500")
            ui.link("编辑路径", path_revision_href(project_id)).classes(
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
            with ui.column().classes("min-w-0 gap-2"):
                for index, item in enumerate(route, start=1):
                    state, state_label, _ = _route_progress_state(item)
                    with ui.link(
                        "",
                        project_href(project_id, "overview", node_id=str(item["node_id"])),
                    ).classes(f"ln-route-row ln-route-state-{state} w-full no-underline"):
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
                            "ln-route-state-label shrink-0 items-center gap-1 flex-nowrap"
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


def _render_map(
    project: dict[str, Any],
    graph: dict[str, Any],
    *,
    project_id: str,
    edit: str | None,
    client: UIAPIClient,
) -> None:
    space_id = str(project["space_id"])
    goal = project.get("goal") if isinstance(project.get("goal"), dict) else {}
    nodes = [item for item in _dict_items(graph.get("nodes")) if item.get("status") != "ARCHIVED"]
    edges = [item for item in _dict_items(graph.get("edges")) if item.get("status") != "ARCHIVED"]

    with ui.row().classes("w-full items-center justify-between gap-3"):
        ui.label(f"{len(nodes)} 个要素 · {len(edges)} 条关系").classes("text-sm text-gray-600")
        ui.button(
            "收起编辑" if edit == "structure" else "编辑结构",
            icon="close" if edit == "structure" else "edit",
            on_click=lambda: ui.navigate.to(
                project_href(project_id, "map")
                if edit == "structure"
                else project_href(project_id, "map") + "?edit=structure"
            ),
        ).props("flat color=positive")

    if edit == "structure":
        with ui.card().classes("ln-card ln-soft-card w-full p-4 sm:p-5"):
            ui.label("添加框架要素").classes("text-lg font-black")
            with ui.grid().classes("mt-2 w-full grid-cols-1 gap-3 md:grid-cols-[1fr_1.4fr_auto]"):
                title = ui.input("名称").props("outlined dense").classes("w-full")
                description = ui.input("一句话定义").props("outlined dense").classes("w-full")
                node_type = ui.select(NODE_TYPE_OPTIONS, value="CONCEPT", label="类型").props(
                    "outlined dense"
                )

            async def create_node() -> None:
                if not str(title.value or "").strip():
                    ui.notify("请填写名称", type="warning")
                    return
                try:
                    created = await client.post(
                        f"/spaces/{space_id}/nodes",
                        json={
                            "title": str(title.value).strip(),
                            "description": str(description.value or "").strip(),
                            "node_type": node_type.value,
                            "difficulty": 1,
                            "depth_level": 0,
                            "learning_objectives": [],
                            "source_basis": [],
                        },
                    )
                    node_id = str(created.get("id") or "") if isinstance(created, dict) else ""
                    ui.notify("要素已加入框架草稿", type="positive")
                    ui.navigate.to(
                        project_href(project_id, "map", node_id=node_id)
                        if node_id
                        else project_href(project_id, "map")
                    )
                except UIAPIError as exc:
                    error_notice(str(exc))

            ui.button("添加", icon="add", on_click=create_node).props("color=positive")

    if not nodes:
        ui.label("框架中还没有要素。 ").classes("ln-empty w-full")
        return

    with ui.card().classes("ln-card w-full overflow-hidden p-3 sm:p-4"):
        ui.label("点击要素即可查看与编辑；拖动和缩放只改变当前浏览视图。 ").classes(
            "px-2 text-sm text-gray-600"
        )
        with ui.element("div").classes("w-full overflow-x-auto"):
            chart = (
                ui.echart(build_full_map_options(graph, project["route"], intent_context=goal))
                .classes("w-full")
                .style(f"min-width:920px;height:{full_map_height(graph, project['route'])}px")
            )

        def open_node(event: events.GenericEventArguments) -> None:
            args = event.args if isinstance(event.args, dict) else {}
            data = args.get("data")
            node_id = data.get("nodeId") if isinstance(data, dict) else None
            if isinstance(node_id, str) and node_id:
                ui.navigate.to(project_href(project_id, "map", node_id=node_id))

        chart.on("click", open_node)


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
    copy = intent_profile(goal)
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
            ui.label(copy["route_label"]).classes("text-xl font-black")
            ui.label("路径引用框架要素；改名会同步，调整路径不会改写框架依赖。 ").classes(
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
                label="查看路径版本",
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

    with ui.row().classes("w-full flex-wrap gap-2"):
        ui.button("AI 生成候选", icon="auto_awesome", on_click=generate_candidate).props(
            "outline color=positive"
        )
        if selected_path and not is_draft:
            ui.button("创建可编辑副本", icon="content_copy", on_click=clone_revision).props(
                "color=positive"
            )
        if is_draft:
            ui.button("校验", icon="rule", on_click=validate_revision).props(
                "outline color=positive"
            )
            ui.button("确认并激活", icon="publish", on_click=activate_revision).props(
                "color=positive"
            )

    if selected_path and not is_draft:
        ui.label("已激活版本不可原地修改；创建副本后编辑。 ").classes("text-xs text-gray-500")

    if is_draft:
        existing_ids = {str(step.get("node_id") or "") for step in steps}
        available_nodes = {
            str(node["id"]): str(node.get("title") or "未命名要素")
            for node in graph_nodes
            if str(node["id"]) not in existing_ids and node.get("node_type") != "MODULE"
        }
        if available_nodes:
            with ui.expansion("加入框架中的其他要素", icon="playlist_add").classes(
                "ln-card w-full rounded-xl px-2"
            ):
                add_node = (
                    ui.select(available_nodes, label="选择要素")
                    .props("outlined dense options-dense")
                    .classes("w-full")
                )
                add_optional = ui.checkbox("设为可选项", value=True)

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

                ui.button("加入草稿", icon="add", on_click=add_step).props("color=positive")

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
                ui.link("打开路径", path_revision_href(project_id)).classes(
                    "text-sm font-bold no-underline"
                )
            elif path_step is None:
                ui.label("这个要素不在当前路径中。 ").classes("text-sm text-gray-600")
                ui.link("在路径页加入", path_revision_href(project_id, path_id)).classes(
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


def _render_checkin_edit_dialog(
    client: UIAPIClient,
    checkin: dict[str, Any],
    *,
    current_href: str,
) -> Any:
    """Render the only flow that may lower a recorded progress score."""

    checkin_id = str(checkin.get("id") or "")
    raw_original_score = checkin.get("score")
    original_score = int(raw_original_score) if raw_original_score is not None else 1
    is_reset_record = original_score == 0
    saving = {"active": False}
    with ui.dialog() as dialog, ui.card().classes("ln-checkin-dialog gap-5 p-5 sm:p-6"):
        with ui.column().classes("w-full gap-1"):
            ui.label("恢复打卡" if is_reset_record else "修改打卡").classes("text-xl font-black")
            ui.label(_checkin_time_label(checkin.get("checked_in_at"))).classes(
                "text-xs text-gray-500"
            )
            edit_hint = (
                "这是一条清零记录。保存后会从所选分数恢复进度，原打卡日期不会改变。"
                if is_reset_record
                else "修改模式允许纠正为更低的分数，原打卡日期不会改变。"
            )
            ui.label(edit_hint).classes("text-sm leading-6 text-gray-600")
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

        async def save_edit() -> None:
            if saving["active"]:
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
                    },
                )
            except UIAPIError as exc:
                saving["active"] = False
                save_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            change = f"{original_score} → {int(edit_score.value)}"
            ui.notify(f"打卡已修改：{change}", type="positive")
            ui.navigate.to(current_href)

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


def _render_checkin_reset_dialog(
    client: UIAPIClient,
    latest_checkin: dict[str, Any],
    *,
    project_id: str,
    node_id: str,
    current_href: str,
) -> Any:
    """Render an explicit, concurrency-safe reset confirmation."""

    resetting = {"active": False}
    latest_checkin_id = str(latest_checkin.get("id") or "")
    latest_revision = int(latest_checkin.get("row_version") or 1)
    with (
        ui.dialog() as dialog,
        ui.card().classes("ln-checkin-dialog ln-checkin-reset-dialog gap-5 p-5 sm:p-6"),
    ):
        with ui.column().classes("w-full gap-2"):
            ui.label("清零当前进度？").classes("text-xl font-black")
            ui.label(
                "确认后，当前进度将回到 0/10，路径状态变为未进行，并保留一条清零记录。"
            ).classes("text-sm leading-6 text-gray-600")
            ui.label("此操作不会删除以往的进度记录。 ").classes("text-xs font-bold text-red-800")

        async def reset_progress() -> None:
            if resetting["active"]:
                return
            resetting["active"] = True
            reset_button.props("loading disable")
            try:
                await client.post(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins/reset",
                    json={
                        "expected_check_in_id": latest_checkin_id,
                        "expected_revision": latest_revision,
                    },
                )
            except UIAPIError as exc:
                resetting["active"] = False
                reset_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            dialog.close()
            ui.notify("当前进度已清零", type="positive")
            ui.navigate.to(current_href)

        with ui.row().classes(
            "w-full justify-end gap-2 max-sm:flex-col-reverse max-sm:items-stretch"
        ):
            ui.button("取消", on_click=dialog.close).props("flat").classes("max-sm:w-full")
            reset_button = (
                ui.button("确认清零", icon="restart_alt", on_click=reset_progress)
                .props("outline color=negative")
                .classes("ln-checkin-reset max-sm:w-full")
            )
    dialog.props("aria-label='确认清零当前进度'")
    return dialog


def _render_checkin_timeline(
    client: UIAPIClient,
    checkins: list[dict[str, Any]],
    *,
    current_href: str,
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
            if score == 0:
                movement = "已清零"
            elif previous_score is None:
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
            )
            checked_in_at = str(checkin.get("checked_in_at") or "")
            with ui.element("li").classes("ln-checkin-entry"):
                ui.element("span").classes("ln-checkin-dot").props("aria-hidden=true")
                with ui.column().classes("min-w-0 grow gap-1"):
                    with ui.row().classes("w-full flex-nowrap items-center gap-2"):
                        with (
                            ui.element("time")
                            .props(f"datetime='{checked_in_at}'")
                            .classes("min-w-0 grow text-xs font-bold text-gray-600")
                        ):
                            ui.label(_checkin_time_label(checked_in_at))
                        ui.label(f"{score}/10").classes("ln-checkin-score")
                    with ui.row().classes("w-full flex-nowrap items-start gap-2"):
                        note = str(checkin.get("note") or "").strip()
                        ui.label(note or "无备注").classes(
                            "min-w-0 grow whitespace-pre-wrap break-words text-sm leading-5 "
                            "text-gray-600"
                        )
                        edit_label = "恢复" if score == 0 else "修改"
                        ui.button(edit_label, on_click=edit_dialog.open).props(
                            f"flat dense color=positive aria-label='{edit_label}"
                            f"{_checkin_time_label(checked_in_at)}的打卡'"
                        ).classes("ln-checkin-edit shrink-0")
                    with ui.row().classes("items-center gap-2"):
                        ui.label(movement).classes("text-xs font-bold text-gray-500")
                        if checkin.get("corrected_at"):
                            ui.label("已修改").classes("ln-checkin-corrected")


def _render_checkin_panel(
    client: UIAPIClient,
    node: dict[str, Any],
    checkins_payload: dict[str, Any],
    *,
    project_id: str,
    current_href: str,
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

    with (
        ui.element("section")
        .classes("ln-checkin-summary")
        .props("aria-label='当前节点进度' aria-live='polite'")
    ):
        with ui.column().classes("min-w-0 gap-1"):
            ui.label("当前进度").classes("text-xs font-bold text-gray-500")
            if raw_current_score is None:
                ui.label("未评分").classes("text-2xl font-black")
            else:
                with ui.row().classes("items-baseline gap-1"):
                    ui.label(str(raw_current_score)).classes("text-4xl font-black")
                    ui.label("/ 10").classes("text-sm font-bold text-gray-500")
        if checkins:
            ui.label(f"最近 · {_checkin_time_label(checkins[0].get('checked_in_at'))}").classes(
                "text-xs text-gray-500"
            )

    creating = {"active": False}
    with ui.dialog() as checkin_dialog, ui.card().classes("ln-checkin-dialog gap-5 p-5 sm:p-6"):
        ui.label("今日打卡").classes("text-xl font-black")
        ui.label("记录今天推进到哪里。评分可以保持或提高。 ").classes(
            "text-sm leading-6 text-gray-600"
        )
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

        async def create_checkin() -> None:
            if creating["active"]:
                return
            creating["active"] = True
            checkin_button.props("loading disable")
            try:
                await client.post(
                    f"/goals/{project_id}/nodes/{node_id}/check-ins",
                    json={
                        "score": int(score.value),
                        "note": str(note.value or "").strip() or None,
                    },
                )
            except UIAPIError as exc:
                creating["active"] = False
                checkin_button.props(remove="loading disable")
                error_notice(str(exc))
                return
            checkin_dialog.close()
            ui.notify("今日进度已记录", type="positive")
            ui.navigate.to(current_href)

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
        )
        today_action = "恢复今日进度" if current_score == 0 else "修改今日打卡"
        ui.button(today_action, icon="edit", on_click=today_dialog.open).props(
            f"outline color=positive aria-label='{today_action}'"
        ).classes("ln-action-button w-full")

    if current_score > 0 and checkins:
        reset_dialog = _render_checkin_reset_dialog(
            client,
            checkins[0],
            project_id=project_id,
            node_id=node_id,
            current_href=current_href,
        )
        ui.button("清零当前进度", icon="restart_alt", on_click=reset_dialog.open).props(
            "flat color=negative aria-label='清零当前节点进度'"
        ).classes("ln-checkin-reset w-full")

    if checkins_payload.get("load_error"):
        ui.label(str(checkins_payload["load_error"])).classes(
            "rounded-lg bg-red-50 px-3 py-2 text-xs font-bold text-red-800"
        )

    _render_checkin_timeline(client, checkins, current_href=current_href)


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
) -> None:
    """Keep the persistent side rail focused on one user decision: log progress."""

    _ = panel
    selected_path = (
        selected_revision.get("path")
        if isinstance(selected_revision, dict) and isinstance(selected_revision.get("path"), dict)
        else None
    )
    path_id = str(selected_path.get("id") or "") if selected_path else ""
    editing_path = section == "overview" and edit == "path"
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
    space_id = str(project["space_id"])
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
                            "编辑框架与关系",
                            on_click=lambda: ui.navigate.to(f"/maps/{space_id}/edit"),
                        )
                        ui.menu_item(
                            "调整项目路径",
                            on_click=lambda: ui.navigate.to(path_revision_href(project_id)),
                        )
                ui.button(icon="close", on_click=lambda: ui.navigate.to(return_href)).props(
                    "flat round dense aria-label='关闭节点进度面板'"
                )
        ui.separator().classes("my-3")
        _render_checkin_panel(
            client,
            node,
            checkins,
            project_id=project_id,
            current_href=current_href,
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
    editing_path = section == "overview" and edit == "path"
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
        _project_navigation(project_id, section)
        if graph_error:
            error_notice(f"框架暂时不可用：{graph_error}")
        workspace_classes = "ln-project-workspace"
        if selected_node is not None:
            workspace_classes += " ln-project-workspace-has-inspector"
        with ui.element("div").classes(workspace_classes):
            with ui.element("main").classes("ln-project-main flex flex-col gap-4"):
                if section == "overview":
                    if editing_path:
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.column().classes("gap-0"):
                                ui.label("编辑当前路径").classes("text-xl font-black")
                                ui.label(
                                    "草稿确认启用后，概览、进展和打卡位置会同时更新。 "
                                ).classes("text-sm text-gray-600")
                            ui.link(
                                "返回概览",
                                project_href(project_id, "overview", node_id=node_id),
                            ).classes("shrink-0 font-bold no-underline")
                        _render_path(
                            client,
                            project,
                            graph,
                            revisions,
                            selected_revision,
                            project_id=project_id,
                        )
                    else:
                        _render_overview(project, graph, project_id=project_id)
                elif section == "map":
                    _render_map(
                        project,
                        graph,
                        project_id=project_id,
                        edit=edit,
                        client=client,
                    )
            if selected_node is not None:
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
    ) -> None:
        await _render_project_page(
            client,
            project_id,
            "map",
            node_id=node,
            panel=None,
            edit=edit,
            revision_id=None,
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
