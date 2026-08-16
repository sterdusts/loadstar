"""Compatibility redirect for the retired standalone AI review center."""

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient


def register(_client: UIAPIClient) -> None:
    @ui.page("/ai-review")
    async def review_page() -> None:
        ui.navigate.to("/projects")
