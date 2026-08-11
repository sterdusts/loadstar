"""Human framework editor; all saves go through validated API commands."""

from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError

NODE_KIND_OPTIONS = {
    "MODULE": "框架模块",
    "CONCEPT": "核心概念",
    "SKILL": "关键能力",
    "PROCEDURE": "方法步骤",
    "PROJECT": "综合成果",
    "ASSESSMENT": "验证节点",
    "QUESTION": "关键问题",
    "ENTITY": "关键对象",
    "MECHANISM": "作用机制",
    "EVIDENCE": "事实证据",
    "MILESTONE": "推进里程碑",
    "DECISION": "关键决策",
    "DELIVERABLE": "交付物",
    "RISK": "风险与未知",
}

RELATION_KIND_OPTIONS = {
    "CONTAINS": "包含",
    "PREREQUISITE": "硬性前置",
    "RELATED": "相关",
    "APPLIES_TO": "应用于",
    "EXTENDS": "扩展",
    "ALTERNATIVE_TO": "替代方案",
    "CAUSES": "导致",
    "SUPPORTS": "支持",
    "CONSTRAINS": "约束",
    "VALIDATES": "验证",
    "ENABLES": "促进",
}


def register(client: UIAPIClient) -> None:
    @ui.page("/maps/{space_id}/edit")
    async def editor_page(space_id: str) -> None:
        with page_shell("高级编辑", "直接修改框架结构；循环前置关系会被领域层拒绝并解释。"):
            graph = await client.get(f"/spaces/{space_id}/graph")
            active_nodes = [item for item in graph["nodes"] if item["status"] != "ARCHIVED"]
            active_edges = [item for item in graph["edges"] if item["status"] != "ARCHIVED"]
            node_options = {item["id"]: item["title"] for item in active_nodes}
            versions = await client.get(f"/spaces/{space_id}/versions")

            def refresh_page() -> None:
                ui.navigate.to(f"/maps/{space_id}/edit")

            async def add_node() -> None:
                try:
                    await client.post(
                        f"/spaces/{space_id}/nodes",
                        json={
                            "title": node_title.value,
                            "description": node_description.value,
                            "node_type": node_kind.value,
                            "difficulty": int(node_difficulty.value),
                            "depth_level": 0,
                            "learning_objectives": [],
                            "source_basis": [],
                        },
                    )
                    ui.notify("节点已保存；刷新页面可继续建立关系", type="positive")
                    refresh_page()
                except UIAPIError as exc:
                    error_notice(str(exc))

            async def add_edge() -> None:
                try:
                    await client.post(
                        f"/spaces/{space_id}/edges",
                        json={
                            "source_node_id": source.value,
                            "target_node_id": target.value,
                            "relation_type": relation.value,
                            "strength": 1.0,
                            "confidence": 1.0,
                            "required_mastery_level": 3 if relation.value == "PREREQUISITE" else 0,
                            "reason": edge_reason.value,
                            "source_reference": [],
                        },
                    )
                    ui.notify("关系已保存", type="positive")
                    refresh_page()
                except UIAPIError as exc:
                    error_notice(str(exc))

            async def publish_version() -> None:
                try:
                    await client.post(
                        f"/spaces/{space_id}/versions/publish",
                        json={"change_summary": version_summary.value},
                    )
                    ui.notify("框架版本已发布，并创建了新的可编辑草稿", type="positive")
                    refresh_page()
                except UIAPIError as exc:
                    error_notice(str(exc))

            async def restore_version() -> None:
                if not restore_source.value:
                    ui.notify("请先选择要恢复的历史版本", type="warning")
                    return
                try:
                    await client.post(
                        f"/spaces/{space_id}/versions/{restore_source.value}/restore",
                        json={"change_summary": f"从版本 {restore_source.value} 恢复"},
                    )
                    ui.notify("历史版本已复制为新的可编辑草稿", type="positive")
                    refresh_page()
                except UIAPIError as exc:
                    error_notice(str(exc))

            with ui.card().classes("ln-card w-full p-5"):
                ui.label("框架版本").classes("text-xl font-bold")
                ui.label(
                    "发布会冻结当前版本并创建内容相同的新草稿；恢复也只创建新草稿，不覆盖历史。"
                )
                with ui.row().classes("w-full items-end gap-3 max-md:flex-col"):
                    version_summary = ui.input("发布说明", value="发布已审核的框架地图").classes(
                        "grow"
                    )
                    ui.button("发布当前版本", on_click=publish_version).props("color=positive")
                restore_options = {
                    item["id"]: f"v{item['version_number']} · {item['status']}"
                    for item in versions
                    if item["id"] != graph["map_version_id"]
                }
                with ui.row().classes("w-full items-end gap-3 max-md:flex-col"):
                    restore_source = ui.select(
                        restore_options, label="恢复历史版本为新草稿"
                    ).classes("grow")
                    ui.button("恢复所选版本", on_click=restore_version).props("outline")
                ui.label(
                    " · ".join(f"v{item['version_number']} {item['status']}" for item in versions)
                ).classes("text-sm text-gray-600")

            with ui.grid(columns=2).classes("w-full gap-5 max-md:grid-cols-1"):
                with ui.card().classes("ln-card p-5"):
                    ui.label("创建节点").classes("text-xl font-bold")
                    node_title = ui.input("名称").classes("w-full")
                    node_description = ui.textarea("一句话定义").classes("w-full")
                    node_kind = ui.select(
                        NODE_KIND_OPTIONS,
                        value="CONCEPT",
                        label="类型",
                    ).classes("w-full")
                    node_difficulty = ui.slider(min=1, max=5, value=1).props("label-always")
                    with ui.row():
                        ui.button("保存节点", on_click=add_node).props("color=positive")
                        ui.button(
                            "撤销未保存",
                            on_click=lambda: (
                                node_title.set_value(""),
                                node_description.set_value(""),
                            ),
                        ).props("flat")
                with ui.card().classes("ln-card p-5"):
                    ui.label("建立关系").classes("text-xl font-bold")
                    source = ui.select(node_options, label="起点").classes("w-full")
                    target = ui.select(node_options, label="终点").classes("w-full")
                    relation = ui.select(
                        RELATION_KIND_OPTIONS,
                        value="PREREQUISITE",
                        label="关系类型",
                    ).classes("w-full")
                    edge_reason = ui.input("关系理由").classes("w-full")
                    ui.button("保存关系", on_click=add_edge).props("color=positive")
            ui.label("拖动只改变本次浏览布局，不会修改节点或关系。")
            ui.link("返回框架地图", f"/maps/{space_id}")

            ui.separator().classes("my-4")
            ui.label("现有节点").classes("text-xl font-bold")
            if not active_nodes:
                ui.label("暂无节点。")
            for node in active_nodes:
                with ui.card().classes("ln-card w-full p-4"):
                    title = ui.input("标题", value=node["title"]).classes("w-full")
                    description = ui.textarea("描述", value=node["description"] or "").classes(
                        "w-full"
                    )

                    async def save_node(
                        node_id: str = node["id"],
                        title_input: Any = title,
                        description_input: Any = description,
                    ) -> None:
                        try:
                            await client.patch(
                                f"/spaces/{space_id}/nodes/{node_id}",
                                json={
                                    "title": title_input.value,
                                    "description": description_input.value,
                                },
                            )
                            ui.notify("节点已更新。", type="positive")
                            refresh_page()
                        except UIAPIError as exc:
                            error_notice(str(exc))

                    async def archive_node(node_id: str = node["id"]) -> None:
                        try:
                            await client.delete(f"/spaces/{space_id}/nodes/{node_id}")
                            ui.notify("节点已归档。", type="positive")
                            refresh_page()
                        except UIAPIError as exc:
                            error_notice(str(exc))

                    with ui.row():
                        ui.button("保存修改", on_click=save_node).props("color=positive")
                        ui.button("归档节点", on_click=archive_node).props("color=negative flat")

            ui.label("现有关系").classes("text-xl font-bold mt-4")
            if not active_edges:
                ui.label("暂无关系。")
            for edge in active_edges:
                relation_label = RELATION_KIND_OPTIONS.get(
                    edge["relation_type"], edge["relation_type"]
                )
                with ui.card().classes("ln-card w-full p-4"):
                    ui.label(
                        f"{node_options.get(edge['source_node_id'], edge['source_node_id'])} "
                        f"— {relation_label} → "
                        f"{node_options.get(edge['target_node_id'], edge['target_node_id'])}"
                    ).classes("font-medium")
                    if edge["reason"]:
                        ui.label(edge["reason"]).classes("text-sm text-gray-600")

                    async def archive_edge(edge_id: str = edge["id"]) -> None:
                        try:
                            await client.delete(f"/spaces/{space_id}/edges/{edge_id}")
                            ui.notify("关系已归档。", type="positive")
                            refresh_page()
                        except UIAPIError as exc:
                            error_notice(str(exc))

                    ui.button("归档关系", on_click=archive_edge).props("color=negative flat")
