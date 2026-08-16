"""Compatibility redirect for the retired duplicate records page."""

from nicegui import ui

from learning_navigator.ui.state.api_client import UIAPIClient


def register(_client: UIAPIClient) -> None:
    @ui.page("/records")
    async def records_page() -> None:
        ui.navigate.to("/activity")
