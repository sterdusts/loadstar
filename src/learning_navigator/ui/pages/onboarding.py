"""Conversation-first project creation."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient


def _activation_is_valid(payload: Any) -> bool:
    """Keep the activation response contract explicit for UI regression tests."""

    if not isinstance(payload, dict):
        return False
    route = payload.get("route")
    return (
        isinstance(payload.get("space"), dict)
        and isinstance(payload.get("goal"), dict)
        and isinstance(route, dict)
        and isinstance(route.get("items"), list)
    )


def _plan_activation_state(item: Any, current_goal_id: str | None) -> str:
    if not isinstance(item, dict):
        return "draft"
    activation = item.get("activation")
    if not isinstance(activation, dict):
        return "draft"
    goal_id = activation.get("goal_id")
    if isinstance(goal_id, str) and goal_id and goal_id == current_goal_id:
        return "current"
    return "activated" if isinstance(goal_id, str) and goal_id else "draft"


def _plan_action_label(state: str) -> str:
    return {
        "current": "查看当前地图",
        "activated": "切换到此方案",
    }.get(state, "启用")


def _plan_can_delete(item: Any) -> bool:
    return isinstance(item, dict) and item.get("review_status") not in {
        "ACCEPTED",
        "MODIFIED_ACCEPTED",
    }


def register(client: UIAPIClient) -> None:
    @ui.page("/projects/new")
    @ui.page("/onboarding")
    async def onboarding_page(conversation: str | None = None) -> None:
        """Keep old creation links working while the shared assistant owns creation."""

        ui.navigate.to("/?ai=new-project")
