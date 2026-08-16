"""Compatibility redirect for the retired standalone framework library."""

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient


def register(_client: UIAPIClient) -> None:
    @ui.page("/spaces")
    async def spaces_page() -> None:
        ui.navigate.to("/projects")
