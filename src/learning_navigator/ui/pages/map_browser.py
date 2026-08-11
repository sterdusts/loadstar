"""Complete framework outline and interactive relation browser."""

from nicegui import events, ui

from learning_navigator.ui.components.layout import error_notice, page_shell, status_badge
from learning_navigator.ui.components.navigation import build_full_map_options, full_map_height
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import STATUS_LABELS, build_dashboard_view_model

FRAMEWORK_NODE_TYPES = {
    "全部": "全部",
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

FRAMEWORK_STATUS_OPTIONS = {"全部": "全部", **STATUS_LABELS}


def register(client: UIAPIClient) -> None:
    @ui.page("/maps/{space_id}")
    async def map_page(space_id: str) -> None:
        with page_shell(
            "框架地图",
            "查看完整结构、关系与当前状态。",
            active_path="/map",
        ):
            try:
                dashboard = await client.get("/dashboard")
                dashboard_view = build_dashboard_view_model(dashboard)
                route_items = (
                    dashboard_view["route"] if dashboard_view.get("space_id") == space_id else []
                )
                graph = await client.get(f"/spaces/{space_id}/graph")
            except UIAPIError as exc:
                error_notice(str(exc))
                return
            nodes = [item for item in graph["nodes"] if item["status"] != "ARCHIVED"]
            visible_node_ids = {item["id"] for item in nodes}
            edges = [
                item
                for item in graph["edges"]
                if item["status"] != "ARCHIVED"
                and item["source_node_id"] in visible_node_ids
                and item["target_node_id"] in visible_node_ids
            ]
            with ui.row().classes("w-full justify-between"):
                ui.label(f"{len(nodes)} 个节点 · {len(edges)} 条关系")
                ui.link("高级编辑", f"/maps/{space_id}/edit")
            with ui.tabs().classes("w-full") as tabs:
                outline_tab = ui.tab("节点清单")
                graph_tab = ui.tab("关系图")
            with ui.tab_panels(tabs, value=graph_tab).classes("w-full bg-transparent"):
                with ui.tab_panel(outline_tab):
                    search = ui.input("搜索节点").classes("w-full")
                    node_type = ui.select(
                        FRAMEWORK_NODE_TYPES,
                        value="全部",
                        label="节点类型",
                    )
                    mastery_status = ui.select(
                        FRAMEWORK_STATUS_OPTIONS,
                        value="全部",
                        label="当前状态",
                    )
                    listing = ui.column().classes("w-full")

                    def render() -> None:
                        listing.clear()
                        term = (search.value or "").casefold()
                        with listing:
                            for node in nodes:
                                if term and term not in node["title"].casefold():
                                    continue
                                if (
                                    node_type.value != "全部"
                                    and node["node_type"] != node_type.value
                                ):
                                    continue
                                if (
                                    mastery_status.value != "全部"
                                    and node["computed_status"] != mastery_status.value
                                ):
                                    continue
                                with ui.card().classes("ln-card w-full p-4"):
                                    with ui.row().classes("w-full justify-between items-center"):
                                        ui.link(
                                            node["title"], f"/maps/{space_id}/nodes/{node['id']}"
                                        )
                                        if node["computed_status"]:
                                            status_badge(node["computed_status"])
                                    ui.label(node["description"] or "暂无说明").classes(
                                        "text-sm text-gray-600"
                                    )

                    search.on("update:model-value", lambda _: render())
                    node_type.on("update:model-value", lambda _: render())
                    mastery_status.on("update:model-value", lambda _: render())
                    render()
                with ui.tab_panel(graph_tab):
                    with ui.element("div").classes("w-full overflow-x-auto"):
                        chart = (
                            ui.echart(build_full_map_options(graph, route_items))
                            .classes("w-full")
                            .style(
                                f"min-width:1120px;height:{full_map_height(graph, route_items)}px"
                            )
                        )

                    def open_node(event: events.GenericEventArguments) -> None:
                        args = event.args if isinstance(event.args, dict) else {}
                        data = args.get("data")
                        node_id = data.get("nodeId") if isinstance(data, dict) else None
                        if isinstance(node_id, str) and node_id:
                            ui.navigate.to(f"/maps/{space_id}/nodes/{node_id}")

                    chart.on("click", open_node)
