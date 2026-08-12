"""Visual framework graph and staged navigation for goal-facing plans."""

import math
from html import escape
from itertools import pairwise
from typing import Any

from nicegui import ui

NODE_TYPE_LABELS = {
    "MODULE": "框架模块",
    "CONCEPT": "核心概念",
    "SKILL": "关键能力",
    "PROCEDURE": "方法步骤",
    "PROJECT": "交付结果",
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

NODE_TYPE_COLORS = {
    "MODULE": "#1f6b4f",
    "CONCEPT": "#46a36f",
    "SKILL": "#4776bd",
    "PROCEDURE": "#c48a32",
    "PROJECT": "#c95f45",
    "ASSESSMENT": "#7950a3",
    "QUESTION": "#2f7f91",
    "ENTITY": "#6b7f3b",
    "MECHANISM": "#8d6c3f",
    "EVIDENCE": "#6574a8",
    "MILESTONE": "#3c8c82",
    "DECISION": "#9a6b34",
    "DELIVERABLE": "#b05d4e",
    "RISK": "#9c4f6f",
}

RELATION_LABELS = {
    "CONTAINS": "包含",
    "PREREQUISITE": "前置",
    "RELATED": "相关",
    "APPLIES_TO": "应用于",
    "EXTENDS": "扩展",
    "ALTERNATIVE_TO": "可替代",
    "CAUSES": "导致",
    "SUPPORTS": "支持",
    "CONSTRAINS": "约束",
    "VALIDATES": "验证",
    "ENABLES": "促进",
}

RELATION_EXPLANATION_TEMPLATES = {
    "CONTAINS": "「{target}」属于「{source}」的组成部分。",
    "PREREQUISITE": "建议先完成「{source}」，再推进「{target}」。",
    "RELATED": "「{source}」与「{target}」存在主题关联，可结合理解。",
    "APPLIES_TO": "「{source}」可用于处理「{target}」。",
    "EXTENDS": "「{target}」在「{source}」的基础上进一步扩展。",
    "ALTERNATIVE_TO": "「{source}」与「{target}」是可对照选择的不同路径。",
    "CAUSES": "「{source}」会导致或推动「{target}」。",
    "SUPPORTS": "「{source}」为「{target}」提供依据或支撑。",
    "CONSTRAINS": "「{source}」限制了「{target}」的可选范围。",
    "VALIDATES": "「{source}」可用于验证「{target}」。",
    "ENABLES": "「{source}」能促进「{target}」，但不是硬性前置。",
}

STAGE_ACCENTS = (
    "#1f6b4f",
    "#4776bd",
    "#c48a32",
    "#7950a3",
    "#c95f45",
    "#26828e",
    "#8c6d31",
    "#5f6caf",
    "#b45f93",
    "#4c956c",
    "#9c6644",
    "#577590",
)

GRAPH_CELL_WIDTH = 560
GRAPH_CELL_HEIGHT = 500
GRAPH_EXTRA_RING_WIDTH = 300
GRAPH_EXTRA_RING_HEIGHT = 180
GRAPH_MIN_FAN_OFFSET = 105
GRAPH_RING_CAPACITY = 4
GRAPH_BASE_RING_RADIUS = 150
GRAPH_FAN_HALF_ANGLE = 55
GRAPH_MIN_WRAPPED_COLUMNS = 3
GRAPH_MAX_COLUMNS = 4
GRAPH_COORDINATE_PADDING = 96
GRAPH_CHART_BOTTOM_PADDING = 120


def _stable_jitter(value: str, span: int) -> tuple[int, int]:
    """Return repeatable, process-independent offsets for a less mechanical layout."""

    seed = sum((index + 1) * ord(character) for index, character in enumerate(value))
    width = span * 2 + 1
    return seed % width - span, (seed // width) % width - span


def _stable_curve(source_key: str, target_key: str, relation: str) -> float:
    if relation != "PREREQUISITE":
        return 0
    seed = sum(
        (index + 1) * ord(character)
        for index, character in enumerate(f"{source_key}>{target_key}:{relation}")
    )
    magnitude = (0.08, 0.12, 0.16)[seed % 3]
    return magnitude if (seed // 3) % 2 == 0 else -magnitude


def _stage_marker(sequence: int) -> str:
    markers = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    if 1 <= sequence <= len(markers):
        return markers[sequence - 1]
    return f"S{sequence}"


def _edge_explanation(
    edge: dict[str, Any], relation: str, source_title: str, target_title: str
) -> str:
    """Prefer the generated rationale and provide a safe fallback for old plans."""

    reason = edge.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    template = RELATION_EXPLANATION_TEMPLATES.get(relation, "「{source}」与「{target}」存在关联。")
    return template.format(source=source_title, target=target_title)


def _edge_tooltip(
    source_title: str, target_title: str, relation_label: str, explanation: str
) -> dict[str, str]:
    title = f"{escape(source_title)} → {escape(target_title)}"
    safe_explanation = escape(explanation).replace("\n", "<br/>")
    return {
        "formatter": (
            f"<strong>{title}</strong><br/>"
            f"关系：{escape(relation_label)}<br/>"
            f"关联说明：{safe_explanation}"
        ),
        "extraCssText": "max-width:360px; white-space:normal; line-height:1.55;",
    }


def _ordered_navigation_stages(
    plan: dict[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    """Return valid navigation stages in their explicit learning order."""

    navigation = plan.get("navigation", {})
    raw_stages = navigation.get("stages", []) if isinstance(navigation, dict) else []
    prepared: list[tuple[int, int, dict[str, Any]]] = []
    for original_index, stage in enumerate(raw_stages):
        if not isinstance(stage, dict):
            continue
        raw_sequence = stage.get("sequence")
        sequence = (
            raw_sequence
            if isinstance(raw_sequence, int) and not isinstance(raw_sequence, bool)
            else original_index + 1
        )
        prepared.append((sequence, original_index, stage))
    prepared.sort(key=lambda item: (item[0], item[1], str(item[2].get("title", ""))))
    return [(sequence, stage) for sequence, _, stage in prepared]


def _stage_graph_model(plan: dict[str, Any], lanes: list[list[int]]) -> list[dict[str, Any]]:
    """Map ordered learning stages to stable anchors in the existing graph."""

    nodes = plan.get("nodes", [])
    node_index_by_key = {str(node.get("temp_id")): index for index, node in enumerate(nodes)}
    used_anchors: set[int] = set()
    model: list[dict[str, Any]] = []

    for stage_index, (sequence, stage) in enumerate(_ordered_navigation_stages(plan)):
        node_indices: list[int] = []
        seen_indices: set[int] = set()
        for node_key in stage.get("node_temp_ids", []):
            node_index = node_index_by_key.get(str(node_key))
            if node_index is not None and node_index not in seen_indices:
                node_indices.append(node_index)
                seen_indices.add(node_index)

        stage_nodes = set(node_indices)
        module_candidates: list[tuple[int, int, int]] = []
        for lane_index, lane in enumerate(lanes):
            overlap = sum(node_index in stage_nodes for node_index in lane)
            if overlap == 0:
                continue
            module_index = next(
                (
                    node_index
                    for node_index in lane
                    if nodes[node_index].get("node_type") == "MODULE"
                    and node_index not in used_anchors
                ),
                None,
            )
            if module_index is not None:
                module_candidates.append((-overlap, lane_index, module_index))

        anchor_index = None
        if module_candidates:
            anchor_index = min(module_candidates)[2]
        else:
            anchor_index = next(
                (node_index for node_index in node_indices if node_index not in used_anchors),
                None,
            )
        if anchor_index is not None:
            used_anchors.add(anchor_index)

        model.append(
            {
                "sequence": sequence,
                "title": str(stage.get("title", f"阶段 {sequence}")),
                "anchor_index": anchor_index,
                "node_indices": node_indices,
                "accent": STAGE_ACCENTS[stage_index % len(STAGE_ACCENTS)],
            }
        )
    return model


def _graph_lanes(plan: dict[str, Any]) -> list[list[int]]:
    """Group nodes into stable module/stage lanes for a readable directed graph."""

    nodes = plan.get("nodes", [])
    if not nodes:
        return []

    node_index_by_key = {str(node.get("temp_id")): index for index, node in enumerate(nodes)}
    stages = _ordered_navigation_stages(plan)
    stage_slot_by_key: dict[str, tuple[int, int]] = {}
    for stage_rank, (_, stage) in enumerate(stages):
        for position, node_key in enumerate(stage.get("node_temp_ids", [])):
            stage_slot_by_key.setdefault(str(node_key), (stage_rank, position))

    type_order = {node_type: index for index, node_type in enumerate(NODE_TYPE_LABELS)}

    def stable_node_key(index: int) -> tuple[int, int, int, str, str]:
        node = nodes[index]
        stage_rank, stage_position = stage_slot_by_key.get(
            str(node.get("temp_id")),
            (len(stages) + 1, len(nodes) + 1),
        )
        return (
            stage_rank,
            stage_position,
            type_order.get(str(node.get("node_type", "OTHER")), len(type_order)),
            str(node.get("title", "")).casefold(),
            str(node.get("temp_id", "")),
        )

    children_by_module: dict[int, set[int]] = {}
    for edge in plan.get("edges", []):
        if edge.get("relation_type") != "CONTAINS":
            continue
        source = node_index_by_key.get(str(edge.get("source_temp_id")))
        target = node_index_by_key.get(str(edge.get("target_temp_id")))
        if source is None or target is None or nodes[source].get("node_type") != "MODULE":
            continue
        children_by_module.setdefault(source, set()).add(target)

    module_indices = [
        index for index, node in enumerate(nodes) if node.get("node_type") == "MODULE"
    ]
    module_indices.sort(
        key=lambda index: (
            min(
                (
                    stage_slot_by_key.get(str(nodes[child].get("temp_id")), (len(stages), 0))[0]
                    for child in children_by_module.get(index, set())
                ),
                default=len(stages),
            ),
            stable_node_key(index),
        )
    )

    lanes: list[list[int]] = []
    claimed: set[int] = set()
    for module_index in module_indices:
        children = sorted(
            (
                child
                for child in children_by_module.get(module_index, set())
                if child not in claimed
            ),
            key=stable_node_key,
        )
        lanes.append([module_index, *children])
        claimed.update((module_index, *children))

    if not lanes:
        lane_count = len(stages) or min(6, max(1, math.ceil(len(nodes) / 5)))
        lanes = [[] for _ in range(lane_count)]

    unclaimed = sorted(
        (index for index in range(len(nodes)) if index not in claimed), key=stable_node_key
    )
    for index in unclaimed:
        stage_slot = stage_slot_by_key.get(str(nodes[index].get("temp_id")))
        if stage_slot is not None and stage_slot[0] < len(lanes):
            lane_index = stage_slot[0]
        else:
            lane_index = min(range(len(lanes)), key=lambda value: (len(lanes[value]), value))
        lanes[lane_index].append(index)

    return [lane for lane in lanes if lane]


def _graph_positions(
    plan: dict[str, Any],
) -> tuple[dict[int, tuple[int, int]], dict[int, str], list[list[int]]]:
    """Place every module cluster inside a deterministic, non-overlapping cell.

    The cells provide the hard readability guarantee.  Alternating fans,
    stable jitter and a serpentine stage order keep the result from becoming a
    rigid table without allowing one module's labels or children to invade the
    next module's visual territory.
    """

    lanes = _graph_lanes(plan)
    nodes = plan.get("nodes", [])
    positions: dict[int, tuple[int, int]] = {}
    label_positions: dict[int, str] = {}
    max_children = max(
        (sum(nodes[index].get("node_type") != "MODULE" for index in lane) for lane in lanes),
        default=0,
    )
    lane_count = len(lanes)
    grid_columns = (
        lane_count
        if lane_count <= 4
        else min(
            GRAPH_MAX_COLUMNS,
            max(
                GRAPH_MIN_WRAPPED_COLUMNS,
                math.ceil(math.sqrt(lane_count * 1.5)),
            ),
        )
    )
    extra_rings = max(0, math.ceil(max_children / GRAPH_RING_CAPACITY) - 1)
    cell_width = GRAPH_CELL_WIDTH + extra_rings * GRAPH_EXTRA_RING_WIDTH
    cell_height = GRAPH_CELL_HEIGHT + extra_rings * GRAPH_EXTRA_RING_HEIGHT
    outer_radius = GRAPH_BASE_RING_RADIUS + extra_rings * 90 + 18
    fan_offset = min(
        cell_height // 3,
        max(GRAPH_MIN_FAN_OFFSET, round(outer_radius * 0.68)),
    )

    for lane_index, lane in enumerate(lanes):
        module_index = next(
            (index for index in lane if nodes[index].get("node_type") == "MODULE"),
            None,
        )
        anchor_key = (
            str(nodes[module_index].get("temp_id"))
            if module_index is not None
            else f"lane-{lane_index}"
        )
        jitter_x, jitter_y = _stable_jitter(anchor_key, 4)
        row_index, row_slot = divmod(lane_index, max(1, grid_columns))
        display_column = row_slot if row_index % 2 == 0 else grid_columns - 1 - row_slot
        cell_center_x = (display_column + 0.5) * cell_width
        cell_center_y = (row_index + 0.5) * cell_height
        opens_down = display_column % 2 == 1
        if row_index > 0 and row_slot == 0:
            # At a wrapped-row turn, put the entering module at the top of its
            # cell and fan its children away from the previous row.  This
            # preserves a clean visual turn instead of threading the path
            # through the next cluster.
            opens_down = True
        anchor_x = round(cell_center_x + jitter_x)
        anchor_y = round(cell_center_y + (-fan_offset if opens_down else fan_offset) + jitter_y)

        if module_index is not None:
            positions[module_index] = (anchor_x, anchor_y)
            label_positions[module_index] = "top" if opens_down else "bottom"

        content_indices = [index for index in lane if index != module_index]
        for content_order, node_index in enumerate(content_indices):
            ring_index = content_order // GRAPH_RING_CAPACITY
            position_in_ring = content_order % GRAPH_RING_CAPACITY
            ring_size = min(
                GRAPH_RING_CAPACITY,
                len(content_indices) - ring_index * GRAPH_RING_CAPACITY,
            )
            angle_offset = (
                0
                if ring_size == 1
                else -GRAPH_FAN_HALF_ANGLE
                + position_in_ring * (2 * GRAPH_FAN_HALF_ANGLE / (ring_size - 1))
            )
            if ring_index % 2:
                angle_offset += 7
            center_angle = 90 if opens_down else -90
            angle = math.radians(center_angle + angle_offset)
            radius = GRAPH_BASE_RING_RADIUS + ring_index * 90 + (0, 18, 4, 14)[position_in_ring]
            child_key = str(nodes[node_index].get("temp_id"))
            child_jitter_x, child_jitter_y = _stable_jitter(child_key, 6)
            x = round(anchor_x + radius * math.cos(angle)) + child_jitter_x
            y = round(anchor_y + radius * math.sin(angle)) + child_jitter_y
            positions[node_index] = (x, y)

            vertical = math.sin(angle)
            outward_label = "bottom" if vertical >= 0 else "top"
            inward_label = "top" if vertical >= 0 else "bottom"
            # Left/right labels consume a complete label width outside the
            # cluster.  Keeping labels vertical preserves the cell boundary;
            # alternating inward/outward positions then separates neighbours
            # inside the same fan.  The two outer nodes face inward so their
            # text cannot leak into the adjacent module cell.
            if ring_size == 1:
                label_positions[node_index] = outward_label
            elif position_in_ring in {0, ring_size - 1} or position_in_ring % 2 == 0:
                label_positions[node_index] = inward_label
            else:
                label_positions[node_index] = outward_label

    if positions:
        min_x = min(position[0] for position in positions.values())
        min_y = min(position[1] for position in positions.values())
        shift_x = max(0, GRAPH_COORDINATE_PADDING - min_x)
        shift_y = max(0, GRAPH_COORDINATE_PADDING - min_y)
        if shift_x or shift_y:
            positions = {
                index: (round(x + shift_x), round(y + shift_y))
                for index, (x, y) in positions.items()
            }

    return positions, label_positions, lanes


def graph_chart_height(plan: dict[str, Any]) -> int:
    """Keep enough vertical room for labels instead of shrinking dense lanes."""

    positions, _, _ = _graph_positions(plan)
    if not positions:
        return 620
    max_y = max(position[1] for position in positions.values())
    return max(620, math.ceil(max_y + GRAPH_CHART_BOTTOM_PADDING))


def build_graph_options(plan: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic ECharts graph options without exposing temporary identifiers."""

    nodes = plan.get("nodes", [])
    edges = plan.get("edges", [])
    present_types = [
        node_type
        for node_type in NODE_TYPE_LABELS
        if any(node.get("node_type") == node_type for node in nodes)
    ]
    unknown_types = sorted(
        {str(node.get("node_type", "OTHER")) for node in nodes} - set(present_types)
    )
    category_types = [*present_types, *unknown_types]
    category_index = {node_type: index for index, node_type in enumerate(category_types)}
    chart_id_by_key = {
        str(node.get("temp_id")): f"node-{index}" for index, node in enumerate(nodes)
    }
    node_index_by_key = {str(node.get("temp_id")): index for index, node in enumerate(nodes)}
    positions, label_positions, lanes = _graph_positions(plan)
    graph_margin = 64 if len(lanes) > 4 else 88
    lane_by_node = {
        node_index: lane_index for lane_index, lane in enumerate(lanes) for node_index in lane
    }
    stage_graph_model = _stage_graph_model(plan, lanes)
    stage_by_node_index: dict[int, dict[str, Any]] = {}
    anchor_stage_by_index: dict[int, dict[str, Any]] = {}
    for stage_entry in stage_graph_model:
        for node_index in stage_entry["node_indices"]:
            stage_by_node_index.setdefault(node_index, stage_entry)
        anchor_index = stage_entry["anchor_index"]
        if anchor_index is not None:
            stage_by_node_index.setdefault(anchor_index, stage_entry)
            anchor_stage_by_index[anchor_index] = stage_entry

    graph_nodes: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        node_type = str(node.get("node_type", "OTHER"))
        node_stage = stage_by_node_index.get(index)
        anchor_stage = anchor_stage_by_index.get(index)
        difficulty = node.get("difficulty", 1)
        size = (
            64
            if node_type == "MODULE"
            else 52
            if node_type == "PROJECT"
            else min(36 + 4 * difficulty, 50)
            if isinstance(difficulty, int)
            else 40
        )
        x, y = positions[index]
        node_label = {
            "position": label_positions[index],
            "distance": 13 if node_type == "MODULE" else 9,
            **(
                {
                    "fontWeight": "bold",
                    "width": 184,
                    "overflow": "truncate",
                    "ellipsis": "…",
                }
                if node_type == "MODULE"
                else {
                    "width": 112,
                    "overflow": "truncate",
                    "ellipsis": "…",
                }
            ),
        }
        if anchor_stage is not None:
            node_label["formatter"] = (
                f"{_stage_marker(anchor_stage['sequence'])} {node.get('title', '未命名节点')!s}"
            )
        item_style = {
            "color": NODE_TYPE_COLORS.get(node_type, "#718078"),
            "borderColor": node_stage["accent"] if node_stage is not None else "#ffffff",
            "borderWidth": 5 if anchor_stage is not None else 4 if node_stage is not None else 2,
        }
        if node_type == "MODULE":
            item_style.update(
                {
                    "shadowBlur": 18 if anchor_stage is not None else 12,
                    "shadowColor": (
                        f"{anchor_stage['accent']}55"
                        if anchor_stage is not None
                        else "rgba(31,107,79,0.18)"
                    ),
                }
            )
        description = str(node.get("description") or "暂无简介")
        graph_node = {
            "id": f"node-{index}",
            "name": str(node.get("title", "未命名节点")),
            "category": category_index[node_type],
            "symbolSize": size,
            "value": (
                f"第 {node_stage['sequence']} 阶段 · {node_stage['title']}\n{description}"
                if node_stage is not None
                else description
            ),
            "x": x,
            "y": y,
            "itemStyle": item_style,
            "label": node_label,
        }
        if node_stage is not None:
            graph_node["stageSequence"] = node_stage["sequence"]
            graph_node["stageTitle"] = node_stage["title"]
            graph_node["stageAccent"] = node_stage["accent"]
        if anchor_stage is not None:
            graph_node["stageBadge"] = _stage_marker(anchor_stage["sequence"])
        graph_nodes.append(graph_node)
    graph_links: list[dict[str, Any]] = []
    for edge in edges:
        source_key = str(edge.get("source_temp_id"))
        target_key = str(edge.get("target_temp_id"))
        source = chart_id_by_key.get(source_key)
        target = chart_id_by_key.get(target_key)
        if source is None or target is None:
            continue
        relation = str(edge.get("relation_type", "RELATED"))
        source_index = node_index_by_key[source_key]
        target_index = node_index_by_key[target_key]
        source_title = str(nodes[source_index].get("title", "未命名节点"))
        target_title = str(nodes[target_index].get("title", "未命名节点"))
        relation_label = RELATION_LABELS.get(relation, relation)
        explanation = _edge_explanation(edge, relation, source_title, target_title)
        same_cluster = lane_by_node.get(source_index) == lane_by_node.get(target_index)
        curveness = _stable_curve(source_key, target_key, relation)
        if same_cluster and relation == "PREREQUISITE":
            curveness = 0.06 if curveness >= 0 else -0.06
        if relation == "CONTAINS":
            edge_color = "#81968a"
            edge_width = 1.0
            edge_opacity = 0.2
            edge_type = "dashed"
            edge_symbol = ["none", "none"]
            edge_symbol_size = [0, 0]
        elif relation == "PREREQUISITE":
            edge_color = "#71877b"
            edge_width = 1.8
            edge_opacity = 0.52
            edge_type = "solid"
            edge_symbol = ["none", "arrow"]
            edge_symbol_size = [0, 8]
        else:
            edge_color = "#8fa198"
            edge_width = 1.1
            edge_opacity = 0.28
            edge_type = "dashed"
            edge_symbol = (
                ["none", "none"] if relation in {"RELATED", "ALTERNATIVE_TO"} else ["none", "arrow"]
            )
            edge_symbol_size = [0, 7]
        graph_links.append(
            {
                "source": source,
                "target": target,
                "name": f"{source_title} → {target_title}",
                "value": relation_label,
                "kind": "knowledge",
                "relationType": relation,
                "sourceTitle": source_title,
                "targetTitle": target_title,
                "associationExplanation": explanation,
                "tooltip": _edge_tooltip(source_title, target_title, relation_label, explanation),
                "symbol": edge_symbol,
                "symbolSize": edge_symbol_size,
                "lineStyle": {
                    "color": edge_color,
                    "width": edge_width,
                    "curveness": curveness,
                    "type": edge_type,
                    "opacity": edge_opacity,
                },
            }
        )

    for progress_index, (source_stage, target_stage) in enumerate(pairwise(stage_graph_model)):
        source_index = source_stage["anchor_index"]
        target_index = target_stage["anchor_index"]
        if source_index is None or target_index is None or source_index == target_index:
            continue
        progress_path = (
            f"第 {source_stage['sequence']} 阶段 {source_stage['title']}"
            f" → 第 {target_stage['sequence']} 阶段 {target_stage['title']}"
        )
        progress_text = f"建议推进顺序：{progress_path}"
        graph_links.append(
            {
                "source": f"node-{source_index}",
                "target": f"node-{target_index}",
                "value": progress_text,
                "name": progress_path,
                "kind": "stage_progress",
                "fromStage": source_stage["sequence"],
                "toStage": target_stage["sequence"],
                "symbol": ["none", "arrow"],
                "symbolSize": [0, 15],
                "lineStyle": {
                    "color": "#2f9e77",
                    "width": 5,
                    "curveness": 0.1 if progress_index % 2 == 0 else -0.1,
                    "type": "solid",
                    "opacity": 0.9,
                    "shadowBlur": 7,
                    "shadowColor": "rgba(47,158,119,0.28)",
                },
                # Sequence badges live on their module nodes.  A second label on
                # a curved edge is laid out independently by ECharts and can
                # appear detached after the graph is fitted, zoomed or dragged.
                "tooltip": {
                    "formatter": (
                        f"<strong>建议推进路径</strong><br/>"
                        f"{escape(progress_path)}<br/>"
                        "完成前一阶段后，再进入后一阶段。"
                    ),
                    "extraCssText": ("max-width:360px; white-space:normal; line-height:1.55;"),
                },
            }
        )
    categories = [
        {
            "name": NODE_TYPE_LABELS.get(node_type, "其他内容"),
            "itemStyle": {"color": NODE_TYPE_COLORS.get(node_type, "#718078")},
        }
        for node_type in category_types
    ]
    return {
        "backgroundColor": "transparent",
        "animationDuration": 500,
        "animationDurationUpdate": 320,
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}<br/>{c}",
            "confine": True,
        },
        "legend": [
            {
                "data": [category["name"] for category in categories],
                "bottom": 0,
                "textStyle": {"color": "#405047"},
            }
        ],
        "series": [
            {
                "type": "graph",
                "layout": "none",
                "preserveAspect": True,
                "left": graph_margin,
                "right": graph_margin,
                "top": 80,
                "bottom": 80,
                "roam": True,
                "scaleLimit": {"min": 0.55, "max": 3},
                "draggable": False,
                "data": graph_nodes,
                "links": graph_links,
                "categories": categories,
                "label": {
                    "show": True,
                    "position": "bottom",
                    "distance": 9,
                    "color": "#17211b",
                    "fontSize": 12,
                    "width": 136,
                    "overflow": "truncate",
                    "ellipsis": "…",
                    "textBorderColor": "rgba(255,255,255,0.96)",
                    "textBorderWidth": 3,
                },
                "labelLayout": {"hideOverlap": True},
                "edgeSymbol": ["none", "arrow"],
                "edgeSymbolSize": [0, 9],
                "emphasis": {
                    # Adjacency focus applies ECharts' global blur state and
                    # makes the rest of a dense map almost disappear. Keep
                    # the surrounding framework readable while the hovered
                    # node and its tooltip provide the local emphasis.
                    "focus": "none",
                    "label": {
                        "show": True,
                        "width": 190,
                        "overflow": "break",
                        "backgroundColor": "rgba(255,255,255,0.96)",
                        "padding": [4, 6],
                    },
                    "lineStyle": {"width": 3, "opacity": 1},
                },
            }
        ],
    }


def build_stage_visual_model(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve stage node references into presentation-ready, identifier-free cards."""

    nodes = plan.get("nodes", [])
    node_by_key = {str(node.get("temp_id")): node for node in nodes}
    model = []
    for index, (sequence, stage) in enumerate(_ordered_navigation_stages(plan)):
        stage_nodes = [
            node_by_key[str(node_key)]
            for node_key in stage.get("node_temp_ids", [])
            if str(node_key) in node_by_key
        ]
        model.append(
            {
                "sequence": sequence,
                "title": str(stage.get("title", f"阶段 {sequence}")),
                "objective": str(stage.get("objective", "")),
                "node_titles": [str(node.get("title", "未命名节点")) for node in stage_nodes],
                "nodes": stage_nodes,
                "completion_criteria": list(stage.get("completion_criteria", [])),
                "deliverable": stage.get("deliverable"),
                "estimated_effort": stage.get("estimated_effort"),
                "accent": STAGE_ACCENTS[index % len(STAGE_ACCENTS)],
            }
        )
    return model


def _render_node_detail(node: dict[str, Any]) -> None:
    with ui.column().classes("w-full gap-1 border-l-2 border-green-200 pl-3"):
        ui.label(node.get("title", "未命名节点")).classes("font-medium")
        if node.get("description"):
            ui.label(node["description"]).classes("text-sm text-gray-600")
        for objective in node.get("learning_objectives", []):
            ui.label(f"· {objective}").classes("text-sm text-gray-700")


def render_learning_plan(plan: dict[str, Any]) -> None:
    """Render the visual overview first and keep accessible text details available."""

    space = plan["space"]
    navigation = plan["navigation"]
    stage_model = build_stage_visual_model(plan)
    nodes = plan.get("nodes", [])
    module_count = sum(node.get("node_type") == "MODULE" for node in nodes)

    with ui.column().classes("w-full gap-6"):
        with ui.card().classes("ln-card w-full p-6"):
            ui.label("框架预览").classes("ln-kicker")
            ui.label(space["title"]).classes("text-2xl font-black")
            if space.get("description"):
                ui.label(space["description"]).classes("text-gray-600")
            with ui.row().classes("mt-2 gap-2"):
                for value, label in (
                    (module_count, "模块"),
                    (len(nodes), "节点"),
                    (len(stage_model), "阶段"),
                ):
                    ui.label(f"{value} 个{label}").classes(
                        "rounded-full bg-green-50 px-3 py-1 text-sm font-bold text-green-900"
                    )
            if stage_model:
                with ui.row().classes(
                    "mt-4 w-full flex-nowrap items-center gap-2 overflow-x-auto "
                    "rounded-xl bg-green-50 px-4 py-3"
                ):
                    ui.label("建议路径").classes("mr-1 shrink-0 text-sm font-black text-green-900")
                    for stage_index, stage in enumerate(stage_model):
                        with ui.row().classes("shrink-0 flex-nowrap items-center gap-2"):
                            ui.label(str(stage["sequence"])).classes(
                                "flex h-7 w-7 items-center justify-center rounded-full "
                                "text-xs font-black text-white"
                            ).style(f"background:{stage['accent']}")
                            ui.label(stage["title"]).classes(
                                "max-w-40 truncate text-sm font-bold text-gray-700"
                            )
                        if stage_index < len(stage_model) - 1:
                            ui.icon("arrow_forward").classes("shrink-0 text-base text-green-700")
            ui.label("滚轮缩放，拖动查看；粗线表示建议路径，悬停连线查看关系。").classes(
                "mt-2 text-sm text-green-800"
            )
            if plan.get("nodes"):
                ui.echart(build_graph_options(plan)).classes("w-full").style(
                    f"height: {graph_chart_height(plan)}px"
                )
                with ui.expansion("查看节点清单").classes("mt-2 w-full"):
                    for node_type, type_label in NODE_TYPE_LABELS.items():
                        typed_nodes = [node for node in nodes if node.get("node_type") == node_type]
                        if not typed_nodes:
                            continue
                        ui.label(type_label).classes("mt-3 font-bold text-green-800")
                        for node in typed_nodes:
                            _render_node_detail(node)
            else:
                ui.label("当前框架没有可展示的节点。").classes(
                    "rounded-lg bg-amber-50 p-3 text-amber-800"
                )

        ui.label("推进路径").classes("text-2xl font-black")
        with ui.card().classes("ln-card w-full p-5 border-l-4 border-green-700"):
            ui.label(navigation["goal_title"]).classes("text-xl font-bold text-green-800")
            ui.label(f"完成标准：{navigation['success_definition']}").classes("text-gray-600")

        with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-2"):
            for stage in stage_model:
                with ui.card().classes("ln-card relative overflow-hidden p-5"):
                    ui.element("div").classes("absolute left-0 top-0 h-full w-2").style(
                        f"background:{stage['accent']}"
                    )
                    with ui.row().classes("items-center gap-3 pl-2"):
                        ui.label(str(stage["sequence"])).classes(
                            "flex h-10 w-10 items-center justify-center rounded-full "
                            "font-black text-white"
                        ).style(f"background:{stage['accent']}")
                        with ui.column().classes("gap-0"):
                            ui.label(stage["title"]).classes("text-xl font-bold")
                            if stage["estimated_effort"]:
                                ui.label(f"建议投入：{stage['estimated_effort']}").classes(
                                    "text-sm text-gray-500"
                                )
                    ui.label(stage["objective"]).classes("mt-3 text-gray-700")
                    if stage["node_titles"]:
                        with ui.row().classes("mt-3 gap-2"):
                            for title in stage["node_titles"]:
                                ui.label(title).classes(
                                    "rounded-full bg-green-50 px-3 py-1 text-sm text-green-900"
                                )
                    with ui.expansion("阶段详情").classes("mt-3 w-full"):
                        for node in stage["nodes"]:
                            _render_node_detail(node)
                        ui.label("怎样算完成").classes("mt-3 text-sm font-bold")
                        for criterion in stage["completion_criteria"]:
                            ui.label(f"· {criterion}").classes("text-sm text-gray-600")
                        if stage["deliverable"]:
                            ui.label("阶段产出").classes("mt-3 text-sm font-bold")
                            ui.label(stage["deliverable"]).classes("text-sm text-gray-600")

        notes = [*plan.get("warnings", []), *plan.get("uncertain_items", [])]
        if notes:
            with ui.expansion("假设与提醒").classes("ln-card w-full p-2"):
                for note in notes:
                    ui.label(f"· {note}").classes("text-sm text-gray-600")
