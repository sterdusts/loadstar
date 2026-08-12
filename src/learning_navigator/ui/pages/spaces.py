"""Framework-space list and creation."""

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError


def register(client: UIAPIClient) -> None:
    @ui.page("/spaces")
    async def spaces_page() -> None:
        with page_shell("框架空间", "集中管理目标、领域或事项的完整框架。"):
            container = ui.column().classes("w-full gap-3")

            async def refresh() -> None:
                container.clear()
                try:
                    spaces = await client.get("/spaces")
                except UIAPIError as exc:
                    error_notice(str(exc))
                    return
                with container:
                    if not spaces:
                        ui.label("暂无框架空间。")
                    for item in spaces:
                        with ui.card().classes("ln-card w-full p-5"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.column().classes("gap-1"):
                                    ui.label(item["title"]).classes("text-xl font-bold")
                                    ui.label(item["description"] or "尚未填写范围说明").classes(
                                        "text-gray-600"
                                    )
                                with ui.row():
                                    ui.link("打开地图", f"/maps/{item['id']}")
                                    ui.link("高级编辑", f"/maps/{item['id']}/edit")

            async def create() -> None:
                try:
                    await client.post(
                        "/spaces",
                        json={"title": title.value, "description": description.value},
                    )
                    title.value = ""
                    description.value = ""
                    ui.notify("框架空间已创建", type="positive")
                    await refresh()
                except UIAPIError as exc:
                    error_notice(str(exc))

            with ui.expansion("新建框架空间", icon="add").classes("ln-card w-full p-2"):
                title = ui.input("名称", placeholder="例如：理解生成式 AI 行业").classes("w-full")
                description = ui.textarea("范围说明").classes("w-full")
                ui.button("创建", on_click=create).props("color=positive")
            await refresh()
