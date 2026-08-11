"""Current goal's framework map and active path."""

from __future__ import annotations

from typing import Any

from nicegui import events, ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.components.navigation import (
    active_map_height,
    build_active_map_options,
    build_full_map_options,
    full_map_height,
    render_route_strip,
)
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    DEFAULT_INTENT_MODE,
    STATUS_COLORS,
    build_dashboard_view_model,
    intent_status_label,
)

MAP_VIEW_LABELS = ("完整框架", "当前路径")
DEFAULT_MAP_VIEW = "full"


def _navigation_status_badge(
    status: str,
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> None:
    label = intent_status_label(status, intent_context)
    ui.label(label).classes(f"ln-status-{status} rounded-full px-3 py-1 text-xs font-bold")


def _active_node_count(graph: Any) -> int:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return 0
    return sum(
        isinstance(node, dict)
        and node.get("status") != "ARCHIVED"
        and node.get("computed_status") != "NOT_RELEVANT"
        for node in graph["nodes"]
    )


def _full_node_count(graph: Any) -> int:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return 0
    return sum(
        isinstance(node, dict) and node.get("status") != "ARCHIVED" for node in graph["nodes"]
    )


def _module_node_count(graph: Any) -> int:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return 0
    return sum(
        isinstance(node, dict)
        and node.get("status") != "ARCHIVED"
        and node.get("node_type") == "MODULE"
        for node in graph["nodes"]
    )


def _find_current_plan(plans: Any, current_goal_id: str | None) -> dict[str, Any] | None:
    if not isinstance(plans, list) or not current_goal_id:
        return None
    for item in plans:
        if not isinstance(item, dict):
            continue
        activation = item.get("activation")
        if isinstance(activation, dict) and activation.get("goal_id") == current_goal_id:
            return item
    return None


def register(client: UIAPIClient) -> None:
    @ui.page("/map")
    async def current_map_page() -> None:
        with page_shell(
            "框架地图",
            "在完整框架中看清结构，在当前路径中找到下一步。",
            active_path="/map",
        ):
            try:
                dashboard = await client.get("/dashboard")
            except UIAPIError as exc:
                error_notice(f"无法读取导航：{exc}")
                return
            view = build_dashboard_view_model(dashboard)
            if not view["has_goal"] or not view["space_id"]:
                with ui.card().classes("ln-hero-card w-full p-8"):
                    ui.label("还没有可展示的框架地图").classes("text-2xl font-black")
                    ui.label("先建立一个目标，系统会在这里展示框架、依赖和推进路径。").classes(
                        "text-green-50"
                    )
                    ui.button(
                        "建立新目标",
                        icon="add_circle_outline",
                        on_click=lambda: ui.navigate.to("/onboarding"),
                    ).classes("ln-action-button mt-3").props(
                        "unelevated color=white text-color=green-9"
                    )
                return

            intent_mode = view["intent_mode"]
            goal_context = view["goal"]
            mode_copy = view["intent_copy"]
            mode_tabs = {
                "LEARN": ("完整知识图", mode_copy["route_label"]),
                "UNDERSTAND": ("完整认知图", mode_copy["route_label"]),
                "DO": ("完整行动图", mode_copy["route_label"]),
            }[intent_mode]

            dashboard_goal = dashboard.get("current_goal") if isinstance(dashboard, dict) else None
            current_goal_id = (
                str(dashboard_goal.get("id"))
                if isinstance(dashboard_goal, dict) and dashboard_goal.get("id")
                else None
            )
            try:
                current_plan = _find_current_plan(
                    await client.get("/learning-plans"),
                    current_goal_id,
                )
            except UIAPIError:
                current_plan = None

            try:
                full_graph = await client.get(f"/spaces/{view['space_id']}/graph")
                focused_graph = (
                    await client.get(
                        f"/spaces/{view['space_id']}/graph",
                        params={"target_node_id": view["target_node_id"]},
                    )
                    if view["target_node_id"]
                    else full_graph
                )
            except UIAPIError as exc:
                error_notice(f"无法读取框架地图：{exc}")
                with ui.card().classes("ln-card w-full p-6"):
                    ui.label("路径仍然可用，但完整框架加载失败。").classes("font-bold")
                    render_route_strip(
                        view["route"],
                        space_id=view["space_id"],
                        intent_context=goal_context,
                    )
                return

            next_step = view["next_step"]
            with ui.grid().classes("w-full grid-cols-1 gap-4 lg:grid-cols-[1.5fr_.8fr]"):
                with ui.card().classes("ln-card ln-soft-card p-5 sm:p-6"):
                    ui.label("目标").classes("ln-kicker")
                    ui.label(view["goal_title"]).classes("mt-1 text-2xl font-black")
                    stage_text = (
                        f" · {current_plan['stage_count']} 个阶段"
                        if isinstance(current_plan, dict)
                        and isinstance(current_plan.get("stage_count"), int)
                        else ""
                    )
                    ui.label(
                        f"{_full_node_count(full_graph)} 个{mode_copy['node_label']}"
                        f" · {_module_node_count(full_graph)} 个{mode_copy['module_label']}"
                        f"{stage_text}"
                        f" · {mode_copy['route_label']} {view['total_count']} 步"
                    ).classes("mt-1 text-sm text-gray-600")
                    ui.button(
                        "切换目标",
                        icon="swap_horiz",
                        on_click=lambda: ui.navigate.to("/onboarding"),
                    ).classes("mt-2").props("flat dense color=positive")
                    ui.linear_progress(value=view["progress_percent"] / 100).classes("mt-4").props(
                        "color=positive rounded"
                    )
                with ui.card().classes("ln-card p-5 sm:p-6"):
                    ui.label(mode_copy["map_next_kicker"]).classes("ln-kicker")
                    if next_step:
                        with ui.row().classes("mt-1 items-center justify-between gap-2"):
                            ui.label(next_step["title"]).classes("text-xl font-black")
                            _navigation_status_badge(next_step["status"], goal_context)
                        ui.button(
                            mode_copy["action_labels"].get(
                                next_step["status"],
                                "查看下一步",
                            ),
                            icon="play_arrow",
                            on_click=lambda: ui.navigate.to(
                                f"/projects/{current_goal_id}/overview?"
                                f"node={next_step['node_id']}&panel=action"
                            ),
                        ).classes("ln-action-button mt-3 w-full").props("color=positive")
                    else:
                        ui.label(
                            f"{mode_copy['route_label']}暂无可继续的{mode_copy['node_label']}。"
                        ).classes("mt-1 text-gray-600")

            def open_node(event: events.GenericEventArguments) -> None:
                args = event.args if isinstance(event.args, dict) else {}
                data = args.get("data")
                node_id = data.get("nodeId") if isinstance(data, dict) else None
                if isinstance(node_id, str) and node_id:
                    ui.navigate.to(f"/projects/{current_goal_id}/map?node={node_id}")

            if _full_node_count(full_graph):
                with ui.card().classes("ln-card w-full p-4 sm:p-6"):
                    with ui.row().classes("w-full flex-wrap items-center justify-between gap-3"):
                        with ui.column().classes("gap-0"):
                            ui.label(f"框架与{mode_copy['route_label']}").classes(
                                "text-xl font-black"
                            )
                            ui.label(
                                f"编号是{mode_copy['route_label']}顺序；点击"
                                f"{mode_copy['node_label']}查看详情。"
                            ).classes("text-sm text-gray-600")
                        ui.link(
                            "大纲与高级浏览",
                            f"/maps/{view['space_id']}",
                        ).classes("font-bold no-underline")
                    with ui.tabs().classes("mt-3 w-full") as map_tabs:
                        full_tab = ui.tab(mode_tabs[0], icon="hub")
                        route_tab = ui.tab(mode_tabs[1], icon="route")
                    initial_tab = full_tab if DEFAULT_MAP_VIEW == "full" else route_tab
                    with ui.tab_panels(
                        map_tabs,
                        value=initial_tab,
                        animated=True,
                    ).classes("w-full bg-transparent"):
                        with ui.tab_panel(full_tab).classes("px-0"):
                            with ui.element("div").classes("w-full overflow-x-auto"):
                                full_chart = (
                                    ui.echart(
                                        build_full_map_options(
                                            full_graph,
                                            view["route"],
                                            intent_context=goal_context,
                                        )
                                    )
                                    .classes("w-full")
                                    .style(
                                        "min-width:1120px;"
                                        f"height:{full_map_height(full_graph, view['route'])}px"
                                    )
                                )
                            full_chart.on("click", open_node)
                        with ui.tab_panel(route_tab).classes("px-0"):
                            if view["route"] and _active_node_count(focused_graph):
                                with ui.row().classes("mb-2 flex-wrap gap-2"):
                                    for status in (
                                        "MASTERED",
                                        "IN_PROGRESS",
                                        "AVAILABLE",
                                        "NEEDS_REVIEW",
                                        "BLOCKED",
                                    ):
                                        with ui.row().classes("items-center gap-1"):
                                            ui.element("span").classes(
                                                "h-3 w-3 rounded-full"
                                            ).style(f"background:{STATUS_COLORS[status]}")
                                            ui.label(
                                                intent_status_label(status, goal_context)
                                            ).classes("text-xs text-gray-600")
                                route_chart = (
                                    ui.echart(
                                        build_active_map_options(
                                            focused_graph,
                                            view["route"],
                                            intent_context=goal_context,
                                        )
                                    )
                                    .classes("w-full")
                                    .style(f"height:{active_map_height(focused_graph)}px")
                                )
                                route_chart.on("click", open_node)
                            else:
                                ui.label(
                                    f"当前{mode_copy['route_label']}还没有可展示的"
                                    f"{mode_copy['node_label']}。"
                                ).classes("ln-empty w-full")
            else:
                with ui.card().classes("ln-card w-full p-6"):
                    ui.label(
                        f"框架地图已建立，但{mode_copy['route_label']}还没有"
                        f"{mode_copy['node_label']}。"
                    ).classes("text-lg font-bold")
                    ui.label("可以更新路径，或切换到其他目标。").classes("text-gray-600")
                    with ui.row().classes("mt-3 gap-2"):
                        ui.button(
                            "检查目标路径",
                            icon="route",
                            on_click=lambda: ui.navigate.to("/goals"),
                        ).props("color=positive")
                        ui.button(
                            "切换目标",
                            icon="history",
                            on_click=lambda: ui.navigate.to("/onboarding"),
                        ).props("outline color=positive")

            with ui.card().classes("ln-card w-full overflow-hidden p-0"):
                with ui.expansion(
                    f"{mode_copy['route_label']}清单 · {len(view['route'])} 步",
                    icon="format_list_numbered",
                ).classes("w-full"):
                    with ui.column().classes("w-full px-2 pb-3"):
                        render_route_strip(
                            view["route"],
                            space_id=view["space_id"],
                            intent_context=goal_context,
                        )
