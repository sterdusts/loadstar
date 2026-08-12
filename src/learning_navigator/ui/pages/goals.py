"""Goal creation and explainable path generation."""

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell, status_badge
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError


def register(client: UIAPIClient) -> None:
    @ui.page("/goals")
    async def goals_page() -> None:
        with page_shell("目标与路径", "从框架中选择终点，生成一条可解释的推进路径。"):
            spaces = await client.get("/spaces")
            space_options = {item["id"]: item["title"] for item in spaces}
            space_select = ui.select(space_options, label="框架空间").classes("w-full")
            target_select = ui.select({}, label="目标节点").classes("w-full")

            async def load_nodes() -> None:
                if not space_select.value:
                    return
                graph = await client.get(f"/spaces/{space_select.value}/graph")
                target_select.options = {
                    item["id"]: item["title"]
                    for item in graph["nodes"]
                    if item["status"] != "ARCHIVED"
                }
                target_select.update()

            space_select.on("update:model-value", lambda _: load_nodes())
            preference = ui.select(
                {
                    "FOUNDATION_COMPLETE": "前置完整",
                    "SHORTEST_FEASIBLE": "最短可行",
                    "PROJECT_FIRST": "结果优先",
                    "THEORY_FIRST": "原理优先",
                    "MANUAL": "人工自定义",
                },
                value="FOUNDATION_COMPLETE",
                label="路径偏好",
            ).classes("w-full")
            title = ui.input("目标名称").classes("w-full")
            ui.label("目标达成等级").classes("text-sm text-gray-600")
            target_level = ui.slider(min=1, max=5, value=3).props("label-always")
            route_container = ui.column().classes("w-full")

            async def create_and_route() -> None:
                try:
                    goal = await client.post(
                        "/goals",
                        json={
                            "space_id": space_select.value,
                            "target_node_id": target_select.value,
                            "title": title.value,
                            "target_mastery_level": int(target_level.value),
                            "route_preference": preference.value,
                            "deadline": None,
                            "load_preference": None,
                        },
                    )
                    result = await client.post(f"/goals/{goal['id']}/paths")
                    route_container.clear()
                    with route_container:
                        for index, item in enumerate(result["items"], start=1):
                            with ui.card().classes("ln-card w-full p-4"):
                                with ui.row().classes("items-center gap-3"):
                                    ui.label(str(index)).classes("font-mono text-gray-400")
                                    ui.label(item["title"]).classes("font-bold")
                                    status_badge(item["status"])
                                ui.label(item["reason"]).classes("text-sm text-gray-600")
                except UIAPIError as exc:
                    error_notice(str(exc))

            ui.button("生成推进路径", on_click=create_and_route).props("color=positive")
