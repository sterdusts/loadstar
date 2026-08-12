"""Recent progress record page backed by the privacy export endpoint."""

from nicegui import ui

from learning_navigator.ui.components.layout import page_shell
from learning_navigator.ui.state.api_client import UIAPIClient


def register(client: UIAPIClient) -> None:
    @ui.page("/records")
    async def records_page() -> None:
        with page_shell("推进记录", "按时间查看行动、笔记与遇到的阻碍。"):
            export = await client.get("/data/export")
            sessions = sorted(
                export["learning_sessions"], key=lambda item: item["started_at"], reverse=True
            )
            if not sessions:
                ui.label("暂无推进记录。")
            for session in sessions:
                with ui.card().classes("ln-card w-full p-4"):
                    ui.label(session["started_at"]).classes("ln-kicker")
                    ui.label(session.get("note") or "未填写记录").classes("font-medium")
                    if session.get("difficulties"):
                        ui.label(f"阻碍：{session['difficulties']}").classes(
                            "text-sm text-gray-600"
                        )
