"""Compatibility redirect for the retired standalone goal/path creator."""

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient


def register(client: UIAPIClient) -> None:
    del client

    @ui.page("/goals")
    async def goals_page() -> None:
        ui.navigate.to("/projects")
