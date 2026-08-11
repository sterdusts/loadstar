"""Goal-facing route and formal framework-map presentation helpers."""

from __future__ import annotations

import math
from html import escape
from itertools import pairwise
from typing import Any

from nicegui import ui

from learning_navigator.ui.components.learning_plan import (
    build_graph_options,
    graph_chart_height,
)
from learning_navigator.ui.view_models import (
    DEFAULT_INTENT_MODE,
    STATUS_COLORS,
    intent_profile,
    intent_status_label,
)

ACTIVE_MAP_COLUMN_GAP = 280
ACTIVE_MAP_ROW_GAP = 230
FULL_MAP_CHILD_WIDTH = 130
FULL_MAP_CHILD_HEIGHT = 44
FULL_MAP_CHILD_FIRST_STEP = 128
FULL_MAP_CHILD_ROW_STEP = 108
FULL_MAP_CHILD_COLUMN_OFFSET = 122
FULL_MAP_CHILD_GROUP_GAP = 400


def _stable_offset(value: str, span: int = 16) -> int:
    seed = sum((index + 1) * ord(character) for index, character in enumerate(value))
    return seed % (span * 2 + 1) - span


def _active_map_columns(node_count: int) -> int:
    return min(6, max(3, math.ceil(math.sqrt(max(1, node_count)))))


def _formal_graph_payload(graph: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(graph, dict):
        return [], []
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    nodes = (
        [item for item in raw_nodes if isinstance(item, dict)]
        if isinstance(raw_nodes, list)
        else []
    )
    edges = (
        [item for item in raw_edges if isinstance(item, dict)]
        if isinstance(raw_edges, list)
        else []
    )
    return nodes, edges


def _formal_full_plan(
    graph: Any, route_items: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Adapt a persisted formal graph to the established module-cluster layout."""

    nodes, edges = _formal_graph_payload(graph)
    visible_nodes = [node for node in nodes if node.get("status") != "ARCHIVED"]
    visible_ids = {str(node.get("id")) for node in visible_nodes if node.get("id")}
    visible_edges = [
        edge
        for edge in edges
        if edge.get("status") != "ARCHIVED"
        and str(edge.get("source_node_id")) in visible_ids
        and str(edge.get("target_node_id")) in visible_ids
    ]
    node_by_id = {str(node["id"]): node for node in visible_nodes if node.get("id")}
    route_order = {
        str(item.get("node_id")): index
        for index, item in enumerate(route_items)
        if str(item.get("node_id")) in node_by_id
    }
    children_by_module: dict[str, set[str]] = {}
    for edge in visible_edges:
        source_id = str(edge.get("source_node_id") or "")
        target_id = str(edge.get("target_node_id") or "")
        if (
            edge.get("relation_type") == "CONTAINS"
            and node_by_id.get(source_id, {}).get("node_type") == "MODULE"
        ):
            children_by_module.setdefault(source_id, set()).add(target_id)

    module_ids = [
        node_id for node_id, node in node_by_id.items() if node.get("node_type") == "MODULE"
    ]
    module_ids.sort(
        key=lambda node_id: (
            min(
                (
                    route_order.get(child_id, len(route_order) + 1)
                    for child_id in children_by_module.get(node_id, set())
                ),
                default=len(route_order) + 1,
            ),
            str(node_by_id[node_id].get("title", "")).casefold(),
            node_id,
        )
    )
    stages: list[dict[str, Any]] = []
    for sequence, module_id in enumerate(module_ids, start=1):
        child_ids = sorted(
            children_by_module.get(module_id, set()),
            key=lambda child_id: (
                route_order.get(child_id, len(route_order) + 1),
                str(node_by_id.get(child_id, {}).get("title", "")).casefold(),
                child_id,
            ),
        )
        stages.append(
            {
                "sequence": sequence,
                "title": str(node_by_id[module_id].get("title") or f"模块 {sequence}"),
                "node_temp_ids": [module_id, *child_ids],
            }
        )

    plan = {
        "nodes": [
            {
                "temp_id": str(node.get("id")),
                "title": str(node.get("title") or "未命名节点"),
                "description": str(node.get("description") or "暂无说明"),
                "node_type": str(node.get("node_type") or "CONCEPT"),
                "difficulty": node.get("difficulty", 1),
            }
            for node in visible_nodes
        ],
        "edges": [
            {
                "source_temp_id": str(edge.get("source_node_id")),
                "target_temp_id": str(edge.get("target_node_id")),
                "relation_type": str(edge.get("relation_type") or "RELATED"),
                "reason": str(edge.get("reason") or "正式框架关系"),
            }
            for edge in visible_edges
        ],
        "navigation": {"stages": stages},
    }
    return plan, visible_nodes


def build_full_map_options(
    graph: Any,
    route_items: list[dict[str, Any]],
    *,
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> dict[str, Any]:
    """Render the complete framework as module clusters plus the real active route.

    ``_formal_full_plan`` uses module groups internally to obtain deterministic
    cluster coordinates.  Those groups are not learning stages, though.  This
    adapter deliberately removes the synthetic stage styling and rebuilds the
    highlighted backbone from ``route_items`` so module order, knowledge
    structure and action order remain three separate visual concepts.
    """

    copy = intent_profile(intent_context)
    plan, visible_nodes = _formal_full_plan(graph, route_items)
    options = build_graph_options(plan)
    options["toolbox"] = {
        "show": True,
        "right": 12,
        "top": 8,
        "feature": {"restore": {"title": "重置视图"}},
    }
    options["aria"] = {
        "enabled": True,
        "label": {
            "description": (
                f"完整{copy['mode_label']}框架图。可缩放、拖动，点击{copy['node_label']}查看详情。"
            )
        },
    }
    series = options["series"][0]
    series["symbol"] = "circle"
    series["preserveAspect"] = True
    series["draggable"] = False
    series["labelLayout"] = {"hideOverlap": False}
    series["emphasis"] = {
        "focus": "none",
        "label": {
            "show": True,
            "backgroundColor": "transparent",
            "padding": 0,
        },
        "lineStyle": {"opacity": 0.9, "width": 3},
    }
    module_members_by_id = {
        str(stage["node_temp_ids"][0]): [str(node_id) for node_id in stage["node_temp_ids"][1:]]
        for stage in plan.get("navigation", {}).get("stages", [])
        if stage.get("node_temp_ids")
    }
    module_sequence_by_id = {
        str(stage["node_temp_ids"][0]): int(stage["sequence"])
        for stage in plan.get("navigation", {}).get("stages", [])
        if stage.get("node_temp_ids")
    }
    module_by_node_id = {
        node_id: module_id
        for module_id, member_ids in module_members_by_id.items()
        for node_id in (module_id, *member_ids)
    }
    rendered_by_node_id: dict[str, dict[str, Any]] = {}
    for source, rendered in zip(visible_nodes, series["data"], strict=True):
        node_id = str(source.get("id"))
        node_type = str(source.get("node_type") or "CONCEPT")
        title = str(source.get("title") or "未命名节点")
        rendered["nodeId"] = node_id
        rendered["nodeType"] = node_type
        rendered["computedStatus"] = source.get("computed_status")
        rendered_by_node_id[node_id] = rendered
        for synthetic_stage_field in (
            "stageSequence",
            "stageTitle",
            "stageAccent",
            "stageBadge",
        ):
            rendered.pop(synthetic_stage_field, None)
        status = str(source.get("computed_status") or "NOT_RELEVANT")
        status_label = intent_status_label(status, intent_context)
        rendered["tooltip"] = {
            "formatter": (
                f"<strong>{escape(title)}</strong><br/>{escape(status_label)} · 点击查看详情"
            ),
            "extraCssText": "max-width:260px;white-space:normal;line-height:1.5;",
        }
        if node_type == "MODULE":
            module_sequence = module_sequence_by_id.get(node_id)
            rendered["moduleSequence"] = module_sequence
            rendered["moduleBadge"] = str(module_sequence) if module_sequence is not None else ""
            rendered["symbol"] = "roundRect"
            rendered["symbolSize"] = [184, 58]
            rendered["label"] = {
                "show": True,
                "position": "inside",
                "formatter": (
                    f"{module_sequence}  {title}" if module_sequence is not None else title
                ),
                "color": "#ffffff",
                "fontSize": 13,
                "fontWeight": "bold",
                "width": 150,
                "overflow": "truncate",
                "ellipsis": "…",
                "textBorderWidth": 0,
            }
            rendered["itemStyle"].update(
                {
                    "color": "#1f6b4f",
                    "borderColor": "#8fc4aa",
                    "borderWidth": 2,
                    "shadowBlur": 14,
                    "shadowColor": "rgba(31,107,79,.22)",
                }
            )
        else:
            rendered["symbol"] = "roundRect"
            rendered["symbolSize"] = [FULL_MAP_CHILD_WIDTH, FULL_MAP_CHILD_HEIGHT]
            rendered["label"] = {
                "show": True,
                "position": "inside",
                "formatter": title,
                "color": "#ffffff",
                "fontSize": 12,
                "fontWeight": 600,
                "width": FULL_MAP_CHILD_WIDTH - 16,
                "height": 34,
                "lineHeight": 16,
                "overflow": "break",
                "textBorderWidth": 0,
            }
            rendered["itemStyle"].update(
                {
                    "borderColor": "#d7e4dd",
                    "borderWidth": 2,
                    "shadowBlur": 0,
                }
            )

    # A module cell is a compact local map: one module header and a vertical
    # zig-zag of labelled knowledge cards.  Symbols and labels stay pixel-sized
    # while graph coordinates are fitted by ECharts, so explicit vertical
    # steps are required to keep labels readable at smaller desktop widths.
    for module_id, child_ids in module_members_by_id.items():
        module = rendered_by_node_id.get(module_id)
        children = [
            rendered_by_node_id[child_id]
            for child_id in child_ids
            if child_id in rendered_by_node_id
        ]
        if module is None or not children:
            continue
        opens_down = sum(float(child["y"]) for child in children) / len(children) > float(
            module["y"]
        )
        direction = 1 if opens_down else -1
        group_count = math.ceil(len(children) / 4)
        for child_order, child in enumerate(children):
            group_index, slot = divmod(child_order, 4)
            group_offset = (group_index - (group_count - 1) / 2) * FULL_MAP_CHILD_GROUP_GAP
            child["x"] = round(
                float(module["x"])
                + group_offset
                + (-FULL_MAP_CHILD_COLUMN_OFFSET if slot % 2 == 0 else FULL_MAP_CHILD_COLUMN_OFFSET)
            )
            child["y"] = round(
                float(module["y"])
                + direction * (FULL_MAP_CHILD_FIRST_STEP + (slot // 2) * FULL_MAP_CHILD_ROW_STEP)
            )

    # Remove the synthetic module-to-module stage backbone emitted by the
    # shared cluster builder.  The complete map highlights the user's actual
    # route nodes instead.
    knowledge_links = [link for link in series["links"] if link.get("kind") == "knowledge"]
    series["links"] = knowledge_links
    knowledge_link_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    chart_id_by_node_id = {
        node_id: str(rendered["id"]) for node_id, rendered in rendered_by_node_id.items()
    }
    node_id_by_chart_id = {chart_id: node_id for node_id, chart_id in chart_id_by_node_id.items()}
    for link in knowledge_links:
        if link.get("kind") == "knowledge" and link.get("relationType"):
            link["value"] = link["relationType"]
        source_node_id = node_id_by_chart_id.get(str(link.get("source")))
        target_node_id = node_id_by_chart_id.get(str(link.get("target")))
        if source_node_id is not None and target_node_id is not None:
            knowledge_link_by_pair.setdefault((source_node_id, target_node_id), link)

    route_ids: list[str] = []
    seen_route_ids: set[str] = set()
    for item in route_items:
        node_id = str(item.get("node_id") or "")
        if node_id not in rendered_by_node_id or node_id in seen_route_ids:
            continue
        route_ids.append(node_id)
        seen_route_ids.add(node_id)

    for route_sequence, node_id in enumerate(route_ids, start=1):
        rendered = rendered_by_node_id[node_id]
        rendered["routeSequence"] = route_sequence
        current_symbol_size = rendered.get("symbolSize", 40)
        if isinstance(current_symbol_size, (int, float)):
            rendered["symbolSize"] = max(48, int(current_symbol_size))
        rendered["label"].update(
            {
                "formatter": f"{route_sequence} · {rendered['name']}",
                "fontWeight": "bold",
            }
        )
        rendered["itemStyle"].update(
            {
                "borderColor": "#2f9e77",
                "borderWidth": 4,
                "shadowBlur": 18 if route_sequence == 1 else 9,
                "shadowColor": "rgba(47,158,119,.34)",
            }
        )

    for route_sequence, (source_id, target_id) in enumerate(pairwise(route_ids), start=1):
        existing = knowledge_link_by_pair.get((source_id, target_id))
        if (
            existing is None
            or existing.get("relationType") != "PREREQUISITE"
            or module_by_node_id.get(source_id) != module_by_node_id.get(target_id)
        ):
            continue
        route_line_style = {
            "color": "#2f9e77",
            "width": 3,
            "opacity": 0.72,
            "curveness": 0.08 if route_sequence % 2 else -0.08,
            "type": "solid",
            "shadowBlur": 0,
        }
        existing.update(
            {
                "kind": "route_knowledge",
                "routeSequence": route_sequence,
                "fromRoute": route_sequence,
                "toRoute": route_sequence + 1,
                "symbol": ["none", "arrow"],
                "symbolSize": [0, 13],
                "lineStyle": route_line_style,
            }
        )
        # Do not invent a line between consecutive route items when the graph
        # has no relationship for that pair.  Topological routes often switch
        # between parallel branches; synthetic chords turn the complete map
        # into a knot.  The numbered node labels carry the total order, while
        # lines remain reserved for real relationships.
    return options


def full_map_height(graph: Any, route_items: list[dict[str, Any]]) -> int:
    plan, _ = _formal_full_plan(graph, route_items)
    # The graph itself is zoomable. Keeping the canvas viewport-bounded avoids
    # turning a broad framework into a several-screen-tall page.
    return min(1080, max(620, graph_chart_height(plan)))


def build_active_map_options(
    graph: Any,
    route_items: list[dict[str, Any]],
    *,
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> dict[str, Any]:
    """Build a deterministic, route-first graph for a published knowledge map.

    The layout follows the active route in a gently meandering left-to-right
    path.  This makes order visible without turning the knowledge map into a
    rigid course table; prerequisite edges remain independently inspectable.
    """

    copy = intent_profile(intent_context)
    nodes, edges = _formal_graph_payload(graph)
    visible_nodes = [
        node
        for node in nodes
        if node.get("status") != "ARCHIVED" and node.get("computed_status") != "NOT_RELEVANT"
    ]
    node_by_id = {str(node.get("id")): node for node in visible_nodes if node.get("id")}
    route_order = {
        str(item.get("node_id")): index
        for index, item in enumerate(route_items)
        if item.get("node_id") in node_by_id
    }
    ordered_ids = sorted(
        node_by_id,
        key=lambda node_id: (
            route_order.get(node_id, len(route_order) + 1),
            str(node_by_id[node_id].get("title", "")).casefold(),
            node_id,
        ),
    )
    order_by_id = {node_id: index for index, node_id in enumerate(ordered_ids)}
    columns = _active_map_columns(len(ordered_ids))
    graph_nodes: list[dict[str, Any]] = []
    for index, node_id in enumerate(ordered_ids):
        node = node_by_id[node_id]
        row, slot = divmod(index, columns)
        column = slot if row % 2 == 0 else columns - 1 - slot
        route_index = route_order.get(node_id)
        status = str(node.get("computed_status") or "NOT_RELEVANT")
        x = column * ACTIVE_MAP_COLUMN_GAP + _stable_offset(node_id)
        y = (
            row * ACTIVE_MAP_ROW_GAP
            + 28 * math.sin((column + row) * 1.2)
            + _stable_offset(node_id, 10)
        )
        title = str(node.get("title") or "未命名节点")
        description = str(node.get("description") or "暂无说明")
        graph_nodes.append(
            {
                "id": f"formal-{index}",
                "name": title,
                "value": (
                    f"{copy['route_label']}第 {route_index + 1} 步\n{description}"
                    if route_index is not None
                    else description
                ),
                "x": round(x),
                "y": round(y),
                "symbolSize": 58 if route_index is not None else 42,
                "itemStyle": {
                    "color": STATUS_COLORS.get(status, "#9aa69f"),
                    "borderColor": "#ffffff",
                    "borderWidth": 4,
                    "shadowBlur": 13 if route_index is not None else 5,
                    "shadowColor": "rgba(24,84,58,.22)",
                },
                "label": {
                    "formatter": f"{route_index + 1}. {title}"
                    if route_index is not None
                    else title,
                    "fontWeight": "bold" if route_index is not None else "normal",
                },
                "nodeId": node_id,
                "routeSequence": route_index + 1 if route_index is not None else None,
            }
        )
    chart_id_by_node_id = {node_id: f"formal-{index}" for index, node_id in enumerate(ordered_ids)}

    graph_links: list[dict[str, Any]] = []
    prerequisite_link_by_pair: dict[tuple[str, str], int] = {}
    for edge in edges:
        source_id = str(edge.get("source_node_id") or "")
        target_id = str(edge.get("target_node_id") or "")
        if source_id not in chart_id_by_node_id or target_id not in chart_id_by_node_id:
            continue
        relation = str(edge.get("relation_type") or "RELATED")
        reason = str(edge.get("reason") or "框架中的关联关系")
        source_title = str(node_by_id[source_id].get("title") or source_id)
        target_title = str(node_by_id[target_id].get("title") or target_id)
        graph_links.append(
            {
                "source": chart_id_by_node_id[source_id],
                "target": chart_id_by_node_id[target_id],
                "kind": "knowledge",
                "value": relation,
                "lineStyle": {
                    "color": "#a8b8ae",
                    "width": 2 if relation == "PREREQUISITE" else 1.2,
                    "type": "solid" if relation == "PREREQUISITE" else "dashed",
                    "opacity": 0.38,
                    "curveness": 0.08 if order_by_id[source_id] % 2 == 0 else -0.08,
                },
                "tooltip": {
                    "formatter": (
                        f"<strong>{escape(source_title)} → {escape(target_title)}</strong><br/>"
                        f"关系：{escape(relation)}<br/>关联说明：{escape(reason)}"
                    ),
                    "extraCssText": "max-width:360px;white-space:normal;line-height:1.55;",
                },
            }
        )
        if relation == "PREREQUISITE":
            prerequisite_link_by_pair.setdefault((source_id, target_id), len(graph_links) - 1)

    # A separate visual backbone communicates recommended order even when two
    # consecutive route nodes do not have a direct graph edge.
    route_ids = [
        str(item.get("node_id"))
        for item in route_items
        if str(item.get("node_id")) in chart_id_by_node_id
    ]
    for sequence, (source_id, target_id) in enumerate(pairwise(route_ids), start=1):
        existing_index = prerequisite_link_by_pair.get((source_id, target_id))
        if existing_index is not None:
            existing = graph_links[existing_index]
            existing["kind"] = "route_knowledge"
            existing["routeSequence"] = sequence
            existing["symbol"] = ["none", "arrow"]
            existing["symbolSize"] = [0, 14]
            existing["lineStyle"].update(
                {
                    "color": "#1f7654",
                    "width": 4,
                    "opacity": 0.84,
                    "curveness": 0.1 if sequence % 2 else -0.1,
                }
            )
            existing_tooltip = existing.get("tooltip")
            if isinstance(existing_tooltip, dict):
                existing_tooltip["formatter"] = (
                    f"{existing_tooltip.get('formatter', '')}<br/>"
                    f"<strong>建议{copy['route_label']}："
                    f"第 {sequence} 步 → 第 {sequence + 1} 步</strong>"
                )
            continue
        graph_links.append(
            {
                "source": chart_id_by_node_id[source_id],
                "target": chart_id_by_node_id[target_id],
                "kind": "route",
                "value": f"第 {sequence} 步 → 第 {sequence + 1} 步",
                "symbol": ["none", "arrow"],
                "symbolSize": [0, 14],
                "lineStyle": {
                    "color": "#1f7654",
                    "width": 4,
                    "opacity": 0.82,
                    "curveness": 0.13 if sequence % 2 else -0.13,
                },
                "tooltip": {
                    "formatter": (
                        f"<strong>建议{copy['route_label']}</strong><br/>"
                        f"{escape(node_by_id[source_id].get('title', source_id))} → "
                        f"{escape(node_by_id[target_id].get('title', target_id))}"
                    )
                },
            }
        )

    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "item", "confine": True},
        "toolbox": {
            "show": True,
            "right": 12,
            "top": 8,
            "feature": {"restore": {"title": "重置视图"}},
        },
        "aria": {
            "enabled": True,
            "label": {
                "description": (
                    f"当前{copy['route_label']}。粗线表示建议顺序，"
                    f"点击{copy['node_label']}查看详情。"
                )
            },
        },
        "animationDuration": 450,
        "series": [
            {
                "type": "graph",
                "layout": "none",
                "symbol": "circle",
                "preserveAspect": True,
                "roam": True,
                "scaleLimit": {"min": 0.6, "max": 3},
                "draggable": False,
                "left": 48,
                "right": 48,
                "top": 65,
                "bottom": 70,
                "data": graph_nodes,
                "links": graph_links,
                "edgeSymbol": ["none", "arrow"],
                "edgeSymbolSize": [0, 9],
                "label": {
                    "show": True,
                    "position": "bottom",
                    "distance": 10,
                    "color": "#17211b",
                    "fontSize": 12,
                    "width": 150,
                    "overflow": "truncate",
                    "ellipsis": "…",
                    "textBorderColor": "rgba(255,255,255,.96)",
                    "textBorderWidth": 3,
                },
                "labelLayout": {"hideOverlap": True},
                "emphasis": {"focus": "none", "lineStyle": {"opacity": 1, "width": 4}},
            }
        ],
    }


def active_map_height(graph: Any) -> int:
    nodes, _ = _formal_graph_payload(graph)
    visible_count = sum(
        1
        for item in nodes
        if item.get("status") != "ARCHIVED" and item.get("computed_status") != "NOT_RELEVANT"
    )
    columns = _active_map_columns(visible_count)
    rows = max(1, math.ceil(visible_count / columns))
    data_width = max(ACTIVE_MAP_COLUMN_GAP, (columns - 1) * ACTIVE_MAP_COLUMN_GAP)
    data_height = max(ACTIVE_MAP_ROW_GAP, (rows - 1) * ACTIVE_MAP_ROW_GAP)
    fitted_height = 150 + math.ceil(960 * data_height / data_width)
    return min(860, max(560, fitted_height))


def render_route_strip(
    route_items: list[dict[str, Any]],
    *,
    space_id: str,
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> None:
    """Render an accessible route list alongside the richer graph."""

    copy = intent_profile(intent_context)
    if not route_items:
        ui.label(f"当前目标还没有可用{copy['route_label']}，请检查或更新框架。").classes(
            "ln-empty w-full"
        )
        return
    with ui.column().classes("w-full gap-0"):
        for sequence, item in enumerate(route_items, start=1):
            with ui.row().classes("ln-route-row w-full items-stretch gap-3"):
                with ui.column().classes("items-center gap-0"):
                    ui.label(str(sequence)).classes("ln-route-number")
                    if sequence < len(route_items):
                        ui.element("div").classes("ln-route-line grow")
                with ui.card().classes("ln-card mb-3 min-w-0 grow p-4"):
                    with ui.row().classes("w-full flex-nowrap items-start justify-between gap-3"):
                        with ui.column().classes("min-w-0 gap-1"):
                            ui.link(
                                item["title"],
                                f"/maps/{space_id}/nodes/{item['node_id']}",
                            ).classes("truncate text-base font-bold no-underline")
                            ui.label(item["reason"]).classes("text-sm text-gray-600")
                        ui.label(intent_status_label(item["status"], intent_context)).classes(
                            f"ln-status-{item['status']} rounded-full px-3 py-1 text-xs font-bold"
                        )
