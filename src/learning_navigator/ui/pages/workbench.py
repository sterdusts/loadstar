"""Focused goal-session capture with intent-aware language."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import intent_mode_for_goal


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _goal_context_for_node(
    dashboard: Any,
    *,
    node_id: str | None,
    space_id: str | None,
) -> dict[str, Any] | None:
    """Resolve a node's owning goal without inventing context for the session."""

    if not isinstance(dashboard, dict):
        return None
    current_goal = dashboard.get("current_goal")
    if not space_id and isinstance(current_goal, dict):
        return current_goal
    overviews = _dict_items(dashboard.get("goal_overviews"))
    if not overviews and isinstance(dashboard.get("current_goal"), dict):
        overviews = [
            {
                "goal": dashboard["current_goal"],
                "route_overview": dashboard.get("route_overview"),
            }
        ]

    matching_goal: dict[str, Any] | None = None
    for overview in overviews:
        goal = overview.get("goal")
        if not isinstance(goal, dict) or str(goal.get("space_id") or "") != str(space_id or ""):
            continue
        matching_goal = matching_goal or goal
        route = _dict_items(overview.get("route_overview"))
        if node_id and any(str(item.get("node_id") or "") == node_id for item in route):
            return goal
    return matching_goal


def _intent_mode_for_node(
    dashboard: Any,
    *,
    node_id: str | None,
    space_id: str | None,
) -> str:
    return intent_mode_for_goal(
        _goal_context_for_node(
            dashboard,
            node_id=node_id,
            space_id=space_id,
        )
    )


def register(client: UIAPIClient) -> None:
    @ui.page("/workbench")
    async def workbench_page(node_id: str | None = None) -> None:
        try:
            dashboard = await client.get("/dashboard")
        except UIAPIError as exc:
            with page_shell("推进节点", active_path="/projects"):
                error_notice(str(exc))
            return

        overviews = (
            _dict_items(dashboard.get("goal_overviews")) if isinstance(dashboard, dict) else []
        )
        if (
            not overviews
            and isinstance(dashboard, dict)
            and isinstance(dashboard.get("current_goal"), dict)
        ):
            overviews = [
                {
                    "goal": dashboard["current_goal"],
                    "route_overview": dashboard.get("route_overview", []),
                }
            ]

        target_goal: dict[str, Any] | None = None
        if node_id:
            for overview in overviews:
                route = _dict_items(overview.get("route_overview"))
                if any(str(item.get("node_id") or "") == node_id for item in route):
                    goal = overview.get("goal")
                    if isinstance(goal, dict):
                        target_goal = goal
                        break
        if target_goal is None:
            current_goal = dashboard.get("current_goal") if isinstance(dashboard, dict) else None
            target_goal = current_goal if isinstance(current_goal, dict) else None

        if target_goal and target_goal.get("id"):
            href = f"/projects/{target_goal['id']}/overview"
            if node_id:
                href += f"?node={node_id}&panel=action"
            ui.navigate.to(href)
            return

        with page_shell(
            "选择项目",
            "推进记录现在保存在项目内，不再使用独立工作台。",
            active_path="/projects",
        ):
            ui.link("返回项目", "/projects").classes("font-bold no-underline")
