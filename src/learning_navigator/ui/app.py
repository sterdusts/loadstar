"""NiceGUI registration and FastAPI mounting."""

from fastapi import FastAPI
from nicegui import ui

from learning_navigator.config import Settings
from learning_navigator.ui.components.layout import configure_global_ai_assistant
from learning_navigator.ui.pages import (
    ai_review,
    current_map,
    goals,
    growth,
    home,
    map_browser,
    map_editor,
    node_detail,
    onboarding,
    projects,
    records,
    settings,
    spaces,
    workbench,
)
from learning_navigator.ui.state.api_client import UIAPIClient


def mount_ui(app: FastAPI, settings_value: Settings) -> None:
    client = UIAPIClient(settings_value.internal_api_url)
    configure_global_ai_assistant(client)
    home.register(client)
    onboarding.register(client)
    projects.register(client)
    current_map.register(client)
    growth.register(client)
    spaces.register(client)
    map_browser.register(client)
    map_editor.register(client)
    node_detail.register(client)
    goals.register(client)
    workbench.register(client)
    ai_review.register(client)
    records.register(client)
    settings.register(client)
    ui.run_with(
        app,
        mount_path="/ui",
        storage_secret=settings_value.storage_secret.get_secret_value(),
        title=settings_value.app_name,
        favicon="🧭",
    )
