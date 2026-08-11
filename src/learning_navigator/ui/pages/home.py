"""Cross-goal next-action dashboard for the framework navigator."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.page_context import AssistantPageContext
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    DEFAULT_INTENT_MODE,
    _extract_learning_plan,
    _saved_plan_date,
    _saved_plan_stats,
    _saved_plan_title,
    build_parallel_dashboard_view_model,
    intent_action_label,
    intent_priority_reason,
    intent_profile,
    normalize_intent_mode,
)
from learning_navigator.ui.view_models import (
    uses_mock_provider as _uses_mock_provider,
)

# The imported private helpers remain available for compatibility with existing
# UI tests and extensions. Plan creation lives on /projects/new.
__all__ = [
    "_extract_learning_plan",
    "_saved_plan_date",
    "_saved_plan_stats",
    "_saved_plan_title",
    "_uses_mock_provider",
    "register",
]

ACTION_PRIORITY = {
    "NEEDS_REVIEW": 0,
    "IN_PROGRESS": 1,
    "AVAILABLE": 2,
}


def _study_action_label(status: str, intent_mode: str = DEFAULT_INTENT_MODE) -> str:
    """Keep the legacy helper name while restoring goal-specific actions."""

    return intent_action_label(status, intent_mode)


def _priority_reason(status: str, intent_mode: str = DEFAULT_INTENT_MODE) -> str:
    return intent_priority_reason(status, intent_mode)


def _mixed_action_label(status: str) -> str:
    return {
        "NEEDS_REVIEW": "检查状态",
        "IN_PROGRESS": "继续推进",
        "AVAILABLE": "开始推进",
    }.get(status, "查看下一步")


def _mixed_priority_reason(status: str) -> str:
    return {
        "NEEDS_REVIEW": "关联目标需要重新确认状态",
        "IN_PROGRESS": "延续已有进度",
        "AVAILABLE": "关联目标的依赖均已满足",
    }.get(status, "现在可以继续")


def _build_today_actions(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Take at most one next action per goal and merge truly shared nodes."""

    actions_by_node: dict[str, dict[str, Any]] = {}
    for goal_index, goal in enumerate(goals):
        next_step = goal.get("next_step")
        if not isinstance(next_step, dict):
            continue
        node_id = str(next_step.get("node_id") or "").strip()
        if not node_id:
            continue
        raw_goal = goal.get("goal") if isinstance(goal.get("goal"), dict) else goal
        goal_copy = intent_profile(raw_goal)
        goal_ref = {
            "goal_id": str(goal.get("goal_id") or ""),
            "goal_title": str(goal.get("goal_title") or "目标"),
            "space_id": str(goal.get("space_id") or ""),
            "map_href": str(goal.get("map_href") or "/map"),
            "intent_mode": normalize_intent_mode(goal.get("intent_mode")),
        }
        goal_ref["project_href"] = f"/projects/{goal_ref['goal_id']}/overview"
        goal_ref["project_map_href"] = f"/projects/{goal_ref['goal_id']}/map"
        existing = actions_by_node.get(node_id)
        if existing is not None:
            existing["goal_refs"].append(goal_ref)
            if existing["intent_copy"] != goal_copy:
                existing["intent_mode"] = "MIXED"
                existing["action_label"] = _mixed_action_label(str(existing["status"]))
                existing["priority_reason"] = _mixed_priority_reason(str(existing["status"]))
            continue
        status = str(next_step.get("status") or "AVAILABLE")
        intent_mode = goal_ref["intent_mode"]
        actions_by_node[node_id] = {
            "node_id": node_id,
            "title": str(next_step.get("title") or "未命名节点"),
            "status": status,
            "reason": str(next_step.get("reason") or "这是该目标现在可以推进的一步。"),
            "priority_reason": _priority_reason(status, intent_mode),
            "action_label": intent_action_label(status, raw_goal),
            "intent_mode": intent_mode,
            "intent_copy": goal_copy,
            "action_href": f"{goal_ref['project_href']}?node={node_id}&panel=action",
            "node_href": f"{goal_ref['project_map_href']}?node={node_id}",
            "goal_refs": [goal_ref],
            "_goal_index": goal_index,
        }

    return sorted(
        actions_by_node.values(),
        key=lambda item: (
            ACTION_PRIORITY.get(str(item["status"]), 99),
            int(item["_goal_index"]),
        ),
    )


def _goal_attention_text(goal: dict[str, Any]) -> str:
    total = int(goal.get("total_count") or 0)
    completed = int(goal.get("completed_count") or 0)
    if total and completed >= total:
        return "已达到路线要求。"
    blocked = goal.get("blocked")
    if isinstance(blocked, list) and blocked:
        first = blocked[0] if isinstance(blocked[0], dict) else {}
        unmet = first.get("unmet_titles") if isinstance(first, dict) else []
        if isinstance(unmet, list) and unmet:
            return f"建议先处理“{unmet[0]}”，也可直接继续。"
        title = str(first.get("title") or "后续节点")
        return f"“{title}”有前置建议，不会限制继续。"
    return "路线暂无可执行节点，需要检查或更新。"


def _filter_label(title: str, *, limit: int = 16) -> str:
    return title if len(title) <= limit else f"{title[:limit]}…"


def _split_goal_filters(
    goals: list[dict[str, Any]],
    selected_goal_id: str | None,
    *,
    visible_limit: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the selected target visible without letting the filter row grow forever."""

    if len(goals) <= visible_limit:
        return goals, []

    visible = goals[:visible_limit]
    if selected_goal_id and all(goal["goal_id"] != selected_goal_id for goal in visible):
        selected = next(
            (goal for goal in goals if goal["goal_id"] == selected_goal_id),
            None,
        )
        if selected is not None:
            visible = [*visible[:-1], selected]

    visible_ids = {goal["goal_id"] for goal in visible}
    overflow = [goal for goal in goals if goal["goal_id"] not in visible_ids]
    return visible, overflow


def _action_goal_context(goal_refs: list[dict[str, Any]]) -> str:
    titles = [str(item["goal_title"]) for item in goal_refs]
    if len(titles) > 1:
        return f"所属项目 · {len(titles)} 个 · {' · '.join(titles)}"
    return f"所属项目 · {titles[0]}" if titles else "所属项目 · 未知"


def _goal_state_summary(goal: dict[str, Any]) -> str:
    next_step = goal.get("next_step")
    if isinstance(next_step, dict):
        return f"{goal['progress_percent']}% · {next_step.get('status_label') or '可推进'}"
    total = int(goal.get("total_count") or 0)
    completed = int(goal.get("completed_count") or 0)
    if total and completed >= total:
        return "已达成"
    return f"{goal['progress_percent']}% · 需检查"


def _navigation_status_badge(
    status: str,
    intent_mode: str = DEFAULT_INTENT_MODE,
    *,
    intent_copy: dict[str, Any] | None = None,
) -> None:
    if intent_mode == "MIXED":
        label = "跨目标"
    else:
        labels = (intent_copy or intent_profile(intent_mode))["status_labels"]
        label = str(labels.get(status, status.replace("_", " ")))
    ui.label(label).classes(f"ln-status-{status} rounded-full px-3 py-1 text-xs font-bold")


def _render_goal_selector(
    goals: list[dict[str, Any]],
    selected_goal_id: str | None,
    *,
    available_action_count: int,
) -> None:
    """Render a compact goal lens without repeating route details."""

    with ui.row().classes("w-full items-center justify-between gap-3"):
        ui.label("目标视角").classes("ln-section-title")
        ui.button(
            "新建",
            icon="add",
            on_click=lambda: ui.navigate.to("/projects/new"),
        ).props("flat dense color=positive no-caps")

    visible_goals, overflow_goals = _split_goal_filters(goals, selected_goal_id)
    with ui.element("div").classes("ln-goal-deck ln-goal-switcher"):
        all_classes = "ln-goal-card ln-goal-card-all"
        if selected_goal_id is None:
            all_classes += " ln-goal-card-active"
        with ui.link("", "/").classes(all_classes).style("min-height:92px"):
            with ui.row().classes("w-full items-start justify-between gap-2"):
                ui.icon("auto_awesome").classes("text-2xl text-green-700")
                ui.label(f"{available_action_count} 步").classes(
                    "ln-goal-count rounded-full px-2 py-1 text-xs font-bold"
                )
            ui.label("综合").classes("mt-2 text-lg font-black")
            ui.label("跨目标排序").classes("ln-goal-meta")

        for goal in visible_goals:
            target_id = goal["goal_id"]
            card_classes = "ln-goal-card"
            if target_id == selected_goal_id:
                card_classes += " ln-goal-card-active"
            with (
                ui.link("", f"/projects/{target_id}/overview")
                .classes(card_classes)
                .style("min-height:92px")
            ):
                ui.label(_filter_label(goal["goal_title"], limit=26)).classes(
                    "ln-goal-title line-clamp-2"
                )
                ui.label(_goal_state_summary(goal)).classes("ln-goal-meta mt-auto")

    if overflow_goals:
        with (
            ui.button(
                f"其他 {len(overflow_goals)} 个目标",
                icon="expand_more",
            )
            .classes("self-start")
            .props("flat color=positive no-caps")
        ):
            with ui.menu():
                for goal in overflow_goals:
                    target_id = goal["goal_id"]
                    ui.menu_item(
                        goal["goal_title"],
                        on_click=lambda target_id=target_id: ui.navigate.to(
                            f"/projects/{target_id}/overview"
                        ),
                    )


def _assistant_home_status(item: dict[str, Any]) -> str:
    display = str(item.get("display_progress_state") or "").upper()
    status = str(item.get("status") or "").upper()
    if display == "COMPLETED" or status == "MASTERED":
        return "COMPLETED"
    if display == "IN_PROGRESS" or status in {"IN_PROGRESS", "NEEDS_REVIEW"}:
        return "IN_PROGRESS"
    return "NOT_STARTED"


def _assistant_home_node(
    item: dict[str, Any],
    *,
    position: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": str(item.get("title") or "未命名步骤"),
        "status": _assistant_home_status(item),
    }
    node_id = str(item.get("node_id") or item.get("id") or "").strip()
    if node_id:
        result["node_id"] = node_id
    if position is not None:
        result["path_position"] = position
    score = item.get("progress_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        result["score"] = int(score)
    return result


def _build_home_assistant_page_state(
    view: dict[str, Any],
    focused_goal_id: str | None,
) -> dict[str, Any] | None:
    goals = [item for item in view.get("goals", []) if isinstance(item, dict)]
    if not goals:
        return None
    actions = _build_today_actions(goals)
    focused = next(
        (item for item in goals if item.get("goal_id") == focused_goal_id),
        None,
    )
    if focused is None and actions:
        first_goal_id = str((actions[0].get("goal_refs") or [{}])[0].get("goal_id") or "")
        focused = next((item for item in goals if item.get("goal_id") == first_goal_id), None)
    focused = focused or goals[0]

    route = [item for item in focused.get("route", []) if isinstance(item, dict)]
    steps = [
        _assistant_home_node(item, position=index) for index, item in enumerate(route, start=1)
    ]
    completed = int(focused.get("completed_count") or 0)
    in_progress = int(focused.get("in_progress_count") or 0)
    total = len(route)
    current_node = None
    next_step = focused.get("next_step")
    if isinstance(next_step, dict):
        next_id = str(next_step.get("node_id") or "")
        position = next(
            (
                index
                for index, item in enumerate(route, start=1)
                if str(item.get("node_id") or "") == next_id
            ),
            None,
        )
        route_item = next(
            (item for item in route if str(item.get("node_id") or "") == next_id),
            next_step,
        )
        current_node = _assistant_home_node(route_item, position=position)

    state: dict[str, Any] = {
        "project_title": str(focused.get("goal_title") or "当前目标"),
        "path_summary": {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "not_started": max(total - completed - in_progress, 0),
            "steps": steps,
        },
        "progress_summary": {
            "percent": int(focused.get("progress_percent") or 0),
            "completed": completed,
            "total": total,
        },
    }
    if current_node:
        state["current_node"] = current_node
    return state


def register(client: UIAPIClient) -> None:
    @ui.page("/")
    async def home_page(goal_id: str | None = None) -> None:
        dashboard_error: str | None = None
        try:
            dashboard = await client.get("/dashboard")
        except UIAPIError as exc:
            dashboard = {}
            dashboard_error = str(exc)
        view = build_parallel_dashboard_view_model(dashboard, focused_goal_id=goal_id)
        with page_shell(
            "下一步",
            "从所有目标中，找到现在最值得推进的一步。",
            active_path="/",
            assistant_context=AssistantPageContext.page(
                page_key="home",
                page_kind="DASHBOARD",
                page_title="下一步",
                page_state=_build_home_assistant_page_state(view, goal_id),
            ),
        ):
            if dashboard_error is not None:
                error_notice(f"无法读取导航：{dashboard_error}")
                with ui.card().classes("ln-card w-full p-6"):
                    ui.label("导航暂时不可用").classes("text-xl font-bold")
                    ui.label("请确认服务已启动，然后刷新页面。").classes("text-gray-600")
                    ui.button("刷新", icon="refresh", on_click=lambda: ui.navigate.to("/")).props(
                        "color=positive"
                    )
                return
            if not view["has_goals"]:
                with ui.card().classes("ln-hero-card w-full p-7 sm:p-10"):
                    with ui.row().classes(
                        "w-full items-center justify-between gap-6 max-md:flex-col"
                    ):
                        with ui.column().classes("max-w-2xl gap-3"):
                            ui.label("把复杂目标变成可推进的框架").classes(
                                "text-2xl font-black sm:text-3xl"
                            )
                            ui.label(
                                "输入想弄清、学会或完成的事，AI 会拆出框架、依赖和可验证的下一步。"
                            ).classes("text-base text-green-50 sm:text-lg")
                            ui.button(
                                "新建目标",
                                icon="add_circle_outline",
                                on_click=lambda: ui.navigate.to("/projects/new"),
                            ).classes("ln-action-button mt-2").props(
                                "unelevated color=white text-color=green-9"
                            )
                        ui.icon("explore").classes("text-8xl text-green-100 opacity-80")
                return

            goals = view["goals"]
            available_goal_ids = {item["goal_id"] for item in goals}
            selected_goal_id = goal_id if goal_id in available_goal_ids else None
            selected_goal = next(
                (item for item in goals if item["goal_id"] == selected_goal_id),
                None,
            )
            scoped_goals = [selected_goal] if selected_goal is not None else goals
            actions = _build_today_actions(scoped_goals)
            all_actions = _build_today_actions(goals)
            alternatives = actions[1:3]

            if actions:
                primary = actions[0]
                primary_mode = str(primary["intent_mode"])
                primary_copy = primary["intent_copy"] if primary_mode != "MIXED" else None
                with ui.card().classes("ln-today-hero w-full overflow-hidden p-7 sm:p-10"):
                    with ui.row().classes(
                        "relative z-10 w-full items-stretch justify-between gap-8 max-md:flex-col"
                    ):
                        with ui.column().classes("min-w-0 flex-1 justify-center gap-3"):
                            ui.label(
                                primary_copy["next_kicker"]
                                if primary_copy is not None
                                else "现在先推进"
                            ).classes("ln-kicker")
                            ui.link(primary["title"], primary["node_href"]).classes(
                                "ln-today-title font-black"
                            )
                            ui.label(_action_goal_context(primary["goal_refs"])).classes(
                                "text-sm font-bold text-green-100"
                            )
                            ui.label(primary["reason"]).classes("ln-today-reason")
                            ui.button(
                                primary["action_label"],
                                icon="play_arrow",
                                on_click=lambda href=primary["action_href"]: ui.navigate.to(href),
                            ).classes("ln-action-button ln-today-action mt-3 self-start").props(
                                "color=white text-color=green-10 unelevated no-caps"
                            )
                        with ui.column().classes("ln-today-side w-64 shrink-0 gap-4 p-5"):
                            with ui.row().classes("w-full items-center justify-between gap-2"):
                                ui.label("状态").classes(
                                    "text-xs font-bold uppercase tracking-wider text-green-100"
                                )
                                _navigation_status_badge(
                                    primary["status"],
                                    primary_mode,
                                    intent_copy=primary_copy,
                                )
                            with ui.column().classes("gap-1"):
                                ui.label("排在前面的原因").classes("text-sm font-black")
                                ui.label(primary["priority_reason"]).classes(
                                    "text-sm leading-relaxed text-green-50"
                                )
            else:
                selected_mode = (
                    str(selected_goal.get("intent_mode") or DEFAULT_INTENT_MODE)
                    if selected_goal is not None
                    else None
                )
                empty_titles = {
                    "LEARN": "这个目标暂无可学习知识点",
                    "UNDERSTAND": "这个目标暂无可探索问题",
                    "DO": "这个目标暂无可执行行动",
                }
                empty_details = {
                    "LEARN": "可能已完成学习路径，或前置知识尚未掌握。",
                    "UNDERSTAND": "可能已覆盖当前认知路径，或前置问题尚未厘清。",
                    "DO": "可能已完成行动路径，或前置条件尚未满足。",
                }
                empty_title = (
                    empty_titles.get(selected_mode, "这个视角暂无可推进项")
                    if selected_mode is not None
                    else "这个视角暂无可推进项"
                )
                empty_detail = (
                    empty_details.get(
                        selected_mode,
                        "可能是路线已达成、依赖尚未满足，或框架需要更新。",
                    )
                    if selected_mode is not None
                    else "可能是路线已达成、依赖尚未满足，或框架需要更新。"
                )
                with ui.card().classes("ln-card w-full p-6"):
                    ui.label(empty_title).classes("text-xl font-black")
                    ui.label(empty_detail).classes("text-gray-600")
                    href = (
                        f"/projects/{selected_goal['goal_id']}/map"
                        if selected_goal is not None
                        else "/projects"
                    )
                    ui.button(
                        "查看框架地图",
                        icon="account_tree",
                        on_click=lambda href=href: ui.navigate.to(href),
                    ).classes("mt-3").props("color=positive")

            support_grid_classes = "w-full grid-cols-1 gap-5"
            if alternatives:
                support_grid_classes += " lg:grid-cols-[1.25fr_.75fr]"
            with ui.grid().classes(support_grid_classes):
                if alternatives:
                    with ui.element("section").classes("ln-alternative-section w-full"):
                        ui.label("其他可推进项").classes("mb-4 ln-section-title")
                        with ui.element("div").classes("ln-alternative-grid"):
                            for action in alternatives:
                                with ui.card().classes(
                                    "ln-alternative-card ln-interactive-card w-full"
                                ):
                                    with ui.column().classes("h-full min-w-0 gap-2 pt-3"):
                                        ui.label(_action_goal_context(action["goal_refs"])).classes(
                                            "line-clamp-1 text-xs font-bold text-green-800"
                                        )
                                        ui.link(action["title"], action["node_href"]).classes(
                                            "line-clamp-2 text-xl font-black text-gray-950 "
                                            "no-underline"
                                        )
                                        ui.button(
                                            action["action_label"],
                                            icon="arrow_forward",
                                            on_click=lambda href=action["action_href"]: (
                                                ui.navigate.to(href)
                                            ),
                                        ).classes("mt-auto self-start").props(
                                            "flat color=positive no-caps"
                                        )
                with ui.card().classes("ln-card w-full p-5"):
                    _render_goal_selector(
                        goals,
                        selected_goal_id,
                        available_action_count=len(all_actions),
                    )
