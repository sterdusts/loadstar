"""Regression contracts for the goal-facing framework graph layout.

These tests deliberately treat a module and all of its contained nodes as one
visual cluster.  Circle-to-circle clearance alone is not enough: labels can
make two otherwise separate clusters read as one dense blob.
"""

from __future__ import annotations

from itertools import combinations, pairwise
from typing import Any

import pytest

from learning_navigator.ui.components.navigation import build_full_map_options

MINIMUM_MODULE_CLUSTER_GUTTER = 56
MINIMUM_INTERNAL_CARD_GUTTER = 12
LABEL_LINE_HEIGHT = 22
DEFAULT_NODE_LABEL_WIDTH = 136
DEFAULT_MODULE_LABEL_WIDTH = 160
MAXIMUM_ANCHOR_Y_SPREAD_WITHIN_ROW = 280
MINIMUM_ROW_CENTER_GAP = 400
MINIMUM_COLUMN_CENTER_GAP = 300
FIT_AWARE_VIEWPORTS = (
    (1280, 900),
    (1480, 900),
    (1480, 1080),
)


def _module_graph(
    module_count: int,
    *,
    children_per_module: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a realistic formal map with a variable number of nodes per module."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    route: list[dict[str, Any]] = []
    child_types = ("CONCEPT", "SKILL", "PROCEDURE", "ASSESSMENT")

    for module_number in range(1, module_count + 1):
        module_id = f"module-{module_number:02d}"
        nodes.append(
            {
                "id": module_id,
                "title": f"Module {module_number} framework foundation",
                "node_type": "MODULE",
                "difficulty": 2,
                "status": "ACTIVE",
                "computed_status": "NOT_RELEVANT",
            }
        )
        for child_number in range(1, children_per_module + 1):
            node_type = child_types[(child_number - 1) % len(child_types)]
            child_id = f"{module_id}-node-{child_number}"
            nodes.append(
                {
                    "id": child_id,
                    "title": (
                        f"Module {module_number} knowledge item {child_number} with readable label"
                    ),
                    "node_type": node_type,
                    "difficulty": child_number,
                    "status": "ACTIVE",
                    "computed_status": "AVAILABLE",
                }
            )
            edges.append(
                {
                    "source_node_id": module_id,
                    "target_node_id": child_id,
                    "relation_type": "CONTAINS",
                    "reason": "Module contains node",
                    "status": "ACTIVE",
                }
            )
        route.append(
            {
                "node_id": f"{module_id}-node-1",
                "title": f"Module {module_number} knowledge item 1",
            }
        )

    return {"nodes": nodes, "edges": edges}, route


def _visual_bounds(
    node: dict[str, Any],
    *,
    series_label: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Return circle-plus-label bounds using the configured label direction."""

    x = float(node["x"])
    y = float(node["y"])
    raw_size = node["symbolSize"]
    if isinstance(raw_size, (list, tuple)):
        half_width = float(raw_size[0]) / 2
        half_height = float(raw_size[1]) / 2
    else:
        half_width = half_height = float(raw_size) / 2
    symbol_bounds = (
        x - half_width,
        x + half_width,
        y - half_height,
        y + half_height,
    )

    label = {**series_label, **node.get("label", {})}
    position = str(label.get("position", "bottom"))
    distance = float(label.get("distance", 0))
    fallback_width = (
        DEFAULT_MODULE_LABEL_WIDTH if node.get("nodeType") == "MODULE" else DEFAULT_NODE_LABEL_WIDTH
    )
    label_width = float(label.get("width", fallback_width))
    label_height = LABEL_LINE_HEIGHT

    if position == "inside":
        label_bounds = symbol_bounds
    elif position == "top":
        label_bounds = (
            x - label_width / 2,
            x + label_width / 2,
            y - half_height - distance - label_height,
            y - half_height - distance,
        )
    elif position == "left":
        label_bounds = (
            x - half_width - distance - label_width,
            x - half_width - distance,
            y - label_height / 2,
            y + label_height / 2,
        )
    elif position == "right":
        label_bounds = (
            x + half_width + distance,
            x + half_width + distance + label_width,
            y - label_height / 2,
            y + label_height / 2,
        )
    else:
        label_bounds = (
            x - label_width / 2,
            x + label_width / 2,
            y + half_height + distance,
            y + half_height + distance + label_height,
        )

    return (
        min(symbol_bounds[0], label_bounds[0]),
        max(symbol_bounds[1], label_bounds[1]),
        min(symbol_bounds[2], label_bounds[2]),
        max(symbol_bounds[3], label_bounds[3]),
    )


def _fit_series_to_viewport(
    series: dict[str, Any],
    *,
    viewport_width: int,
    viewport_height: int,
) -> dict[str, Any]:
    """Apply the graph's preserve-aspect fit while keeping UI sizes in pixels.

    ECharts maps the fixed ``layout='none'`` node coordinates into the series
    rectangle.  Node symbols, label widths, distances and font sizes remain
    screen-pixel values, so raw-coordinate AABBs alone can miss collisions that
    appear after a broad graph is fitted into a finite viewport.
    """

    rendered_nodes = series.get("data", [])
    if not rendered_nodes:
        return {**series, "data": []}

    left = float(series.get("left", 0))
    right = float(series.get("right", 0))
    top = float(series.get("top", 0))
    bottom = float(series.get("bottom", 0))
    available_width = max(1.0, viewport_width - left - right)
    available_height = max(1.0, viewport_height - top - bottom)

    xs = [float(node["x"]) for node in rendered_nodes]
    ys = [float(node["y"]) for node in rendered_nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    data_width = max(1.0, max_x - min_x)
    data_height = max(1.0, max_y - min_y)
    scale = min(available_width / data_width, available_height / data_height)
    fitted_width = data_width * scale
    fitted_height = data_height * scale
    offset_x = left + (available_width - fitted_width) / 2 - min_x * scale
    offset_y = top + (available_height - fitted_height) / 2 - min_y * scale

    return {
        **series,
        "data": [
            {
                **node,
                "x": float(node["x"]) * scale + offset_x,
                "y": float(node["y"]) * scale + offset_y,
            }
            for node in rendered_nodes
        ],
    }


def _cluster_bounds_by_module(
    graph: dict[str, Any],
    series: dict[str, Any],
) -> dict[str, tuple[float, float, float, float]]:
    """Return conservative AABBs for every complete module cluster."""

    rendered_by_id = {str(node["nodeId"]): node for node in series["data"]}
    child_ids_by_module: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        if edge["relation_type"] == "CONTAINS":
            child_ids_by_module.setdefault(str(edge["source_node_id"]), set()).add(
                str(edge["target_node_id"])
            )

    result: dict[str, tuple[float, float, float, float]] = {}
    for module_id, child_ids in child_ids_by_module.items():
        member_ids = {module_id, *child_ids}
        member_bounds = [
            _visual_bounds(rendered_by_id[node_id], series_label=series["label"])
            for node_id in member_ids
        ]
        result[module_id] = (
            min(bounds[0] for bounds in member_bounds),
            max(bounds[1] for bounds in member_bounds),
            min(bounds[2] for bounds in member_bounds),
            max(bounds[3] for bounds in member_bounds),
        )
    return result


def _largest_axis_gap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """Return separation on the best axis; a negative result means overlap."""

    first_left, first_right, first_top, first_bottom = first
    second_left, second_right, second_top, second_bottom = second
    horizontal_gap = max(second_left - first_right, first_left - second_right)
    vertical_gap = max(second_top - first_bottom, first_top - second_bottom)
    return max(horizontal_gap, vertical_gap)


@pytest.mark.parametrize("module_count", [5, 6, 7, 8, 12])
@pytest.mark.parametrize("children_per_module", [3, 4])
def test_every_module_cluster_has_label_aware_clearance(
    module_count: int,
    children_per_module: int,
) -> None:
    graph, route = _module_graph(
        module_count,
        children_per_module=children_per_module,
    )
    series = build_full_map_options(graph, route)["series"][0]
    bounds_by_module = _cluster_bounds_by_module(graph, series)

    collisions: list[str] = []
    for first_id, second_id in pairwise(sorted(bounds_by_module)):
        # Keep the useful adjacent-pair message compact, but do not rely on it:
        # the exhaustive loop below catches wrapped-row pairs such as 2 and 6.
        gap = _largest_axis_gap(bounds_by_module[first_id], bounds_by_module[second_id])
        if gap < MINIMUM_MODULE_CLUSTER_GUTTER:
            collisions.append(f"{first_id}/{second_id}: {gap:.1f}px")
    module_ids = sorted(bounds_by_module)
    for first_index, first_id in enumerate(module_ids):
        for second_id in module_ids[first_index + 1 :]:
            if int(second_id.rsplit("-", 1)[1]) == int(first_id.rsplit("-", 1)[1]) + 1:
                continue
            gap = _largest_axis_gap(bounds_by_module[first_id], bounds_by_module[second_id])
            if gap < MINIMUM_MODULE_CLUSTER_GUTTER:
                collisions.append(f"{first_id}/{second_id}: {gap:.1f}px")

    assert not collisions, (
        "module clusters overlap or visually stick together after labels are included; "
        f"required gutter={MINIMUM_MODULE_CLUSTER_GUTTER}px; "
        f"collisions={', '.join(collisions)}"
    )


@pytest.mark.parametrize("viewport_width,viewport_height", FIT_AWARE_VIEWPORTS)
@pytest.mark.parametrize("module_count", range(5, 13))
def test_every_module_cluster_remains_separate_after_series_fit(
    module_count: int,
    viewport_width: int,
    viewport_height: int,
) -> None:
    graph, route = _module_graph(module_count, children_per_module=4)
    series = build_full_map_options(graph, route)["series"][0]
    fitted_series = _fit_series_to_viewport(
        series,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    bounds_by_module = _cluster_bounds_by_module(graph, fitted_series)

    collisions = [
        f"{first_id}/{second_id}: "
        f"{_largest_axis_gap(bounds_by_module[first_id], bounds_by_module[second_id]):.1f}px"
        for first_id, second_id in combinations(sorted(bounds_by_module), 2)
        if _largest_axis_gap(bounds_by_module[first_id], bounds_by_module[second_id])
        < MINIMUM_MODULE_CLUSTER_GUTTER
    ]

    assert not collisions, (
        "module clusters overlap after ECharts-style preserve-aspect fitting; "
        f"viewport={viewport_width}x{viewport_height}; "
        f"required gutter={MINIMUM_MODULE_CLUSTER_GUTTER}px; "
        f"collisions={', '.join(collisions)}"
    )


@pytest.mark.parametrize("viewport_width,viewport_height", FIT_AWARE_VIEWPORTS)
@pytest.mark.parametrize("module_count", [5, 8, 12])
def test_label_cards_remain_separate_inside_each_fitted_module(
    module_count: int,
    viewport_width: int,
    viewport_height: int,
) -> None:
    graph, route = _module_graph(module_count, children_per_module=4)
    series = build_full_map_options(graph, route)["series"][0]
    fitted_series = _fit_series_to_viewport(
        series,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    rendered_by_id = {str(node["nodeId"]): node for node in fitted_series["data"]}
    child_ids_by_module: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        if edge["relation_type"] == "CONTAINS":
            child_ids_by_module.setdefault(str(edge["source_node_id"]), []).append(
                str(edge["target_node_id"])
            )

    collisions: list[str] = []
    for module_id, child_ids in child_ids_by_module.items():
        member_ids = [module_id, *child_ids]
        bounds = {
            node_id: _visual_bounds(
                rendered_by_id[node_id],
                series_label=fitted_series["label"],
            )
            for node_id in member_ids
        }
        for first_id, second_id in combinations(member_ids, 2):
            gap = _largest_axis_gap(bounds[first_id], bounds[second_id])
            if gap < MINIMUM_INTERNAL_CARD_GUTTER:
                collisions.append(f"{first_id}/{second_id}: {gap:.1f}px")

    assert not collisions, (
        "knowledge cards overlap inside a fitted module; "
        f"viewport={viewport_width}x{viewport_height}; "
        f"required gutter={MINIMUM_INTERNAL_CARD_GUTTER}px; "
        f"collisions={', '.join(collisions)}"
    )


@pytest.mark.parametrize("children_per_module", [5, 6])
@pytest.mark.parametrize("viewport_width", [1120, 1280, 1480])
def test_dense_module_cards_expand_vertically_without_collisions(
    children_per_module: int,
    viewport_width: int,
) -> None:
    """Cover the six-module, five-to-six-card shape seen in real projects."""

    graph, route = _module_graph(6, children_per_module=children_per_module)
    series = build_full_map_options(graph, route)["series"][0]
    fitted_series = _fit_series_to_viewport(
        series,
        viewport_width=viewport_width,
        viewport_height=900,
    )
    bounds_by_module = _cluster_bounds_by_module(graph, fitted_series)
    assert all(
        _largest_axis_gap(first, second) >= MINIMUM_MODULE_CLUSTER_GUTTER
        for first, second in combinations(bounds_by_module.values(), 2)
    )

    rendered_by_id = {str(node["nodeId"]): node for node in fitted_series["data"]}
    child_ids_by_module: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        if edge["relation_type"] == "CONTAINS":
            child_ids_by_module.setdefault(str(edge["source_node_id"]), []).append(
                str(edge["target_node_id"])
            )
    for module_id, child_ids in child_ids_by_module.items():
        members = [module_id, *child_ids]
        bounds = {
            node_id: _visual_bounds(
                rendered_by_id[node_id],
                series_label=fitted_series["label"],
            )
            for node_id in members
        }
        assert all(
            _largest_axis_gap(bounds[first_id], bounds[second_id]) >= MINIMUM_INTERNAL_CARD_GUTTER
            for first_id, second_id in combinations(members, 2)
        )


@pytest.mark.parametrize(
    ("module_count", "expected_row_lengths"),
    [
        (6, [3, 3]),
        (7, [4, 3]),
        (8, [4, 4]),
        (12, [4, 4, 4]),
    ],
)
def test_module_grid_uses_readable_bounded_rows(
    module_count: int,
    expected_row_lengths: list[int],
) -> None:
    graph, route = _module_graph(module_count, children_per_module=4)
    series = build_full_map_options(graph, route)["series"][0]
    anchors = sorted(
        (node for node in series["data"] if "moduleBadge" in node),
        key=lambda node: int(node["moduleSequence"]),
    )
    rows: list[list[dict[str, Any]]] = []
    offset = 0
    for row_length in expected_row_lengths:
        rows.append(anchors[offset : offset + row_length])
        offset += row_length

    assert len(anchors) == sum(expected_row_lengths)
    assert [len(row) for row in rows] == expected_row_lengths
    row_centers: list[float] = []
    for row in rows:
        row_y = [float(node["y"]) for node in row]
        row_x = sorted(float(node["x"]) for node in row)
        assert max(row_y) - min(row_y) <= MAXIMUM_ANCHOR_Y_SPREAD_WITHIN_ROW
        assert all(right - left >= MINIMUM_COLUMN_CENTER_GAP for left, right in pairwise(row_x))
        row_centers.append(sum(row_y) / len(row_y))
    assert all(lower - upper >= MINIMUM_ROW_CENTER_GAP for upper, lower in pairwise(row_centers))


@pytest.mark.parametrize("module_count", [5, 6, 7, 8, 12])
@pytest.mark.parametrize("children_per_module", [3, 4])
def test_complete_map_keeps_nodes_modules_and_real_route_in_order(
    module_count: int,
    children_per_module: int,
) -> None:
    graph, route = _module_graph(
        module_count,
        children_per_module=children_per_module,
    )
    series = build_full_map_options(graph, route)["series"][0]
    rendered_nodes = series["data"]
    rendered_by_node_id = {str(node["nodeId"]): node for node in rendered_nodes}
    modules = sorted(
        (node for node in rendered_nodes if "moduleBadge" in node),
        key=lambda node: int(node["moduleSequence"]),
    )
    route_links = [link for link in series["links"] if link["kind"] == "route_knowledge"]

    assert len(rendered_nodes) == module_count * (children_per_module + 1)
    assert {str(node["nodeId"]) for node in rendered_nodes} == {
        str(node["id"]) for node in graph["nodes"]
    }
    assert [int(module["moduleSequence"]) for module in modules] == list(range(1, module_count + 1))
    assert [str(module["nodeId"]) for module in modules] == [
        f"module-{sequence:02d}" for sequence in range(1, module_count + 1)
    ]
    assert all(module["moduleBadge"] in module["label"]["formatter"] for module in modules)
    assert all(
        not ({"stageSequence", "stageBadge", "stageTitle", "stageAccent"} & node.keys())
        for node in rendered_nodes
    )
    route_nodes = [rendered_by_node_id[str(item["node_id"])] for item in route]
    assert [node["routeSequence"] for node in route_nodes] == list(range(1, module_count + 1))
    assert all(
        node["label"]["formatter"].startswith(f"{sequence} · ")
        for sequence, node in enumerate(route_nodes, start=1)
    )
    assert not route_links
    assert all(link["kind"] not in {"route", "stage_progress"} for link in series["links"])
    assert all("fromStage" not in link and "toStage" not in link for link in series["links"])


def test_existing_intra_module_route_knowledge_is_upgraded_without_synthetic_edges() -> None:
    graph, route = _module_graph(3, children_per_module=3)
    route = [
        {"node_id": "module-01-node-1", "title": "First module item"},
        {"node_id": "module-01-node-2", "title": "Second module item"},
    ]
    graph["edges"].append(
        {
            "source_node_id": route[0]["node_id"],
            "target_node_id": route[1]["node_id"],
            "relation_type": "PREREQUISITE",
            "reason": "The first route node is a real prerequisite of the second.",
            "status": "ACTIVE",
        }
    )
    series = build_full_map_options(graph, route)["series"][0]
    rendered_by_chart_id = {str(node["id"]): node for node in series["data"]}
    route_links = [link for link in series["links"] if link["kind"] == "route_knowledge"]

    assert len(route_links) == 1
    link = route_links[0]
    assert rendered_by_chart_id[str(link["source"])]["nodeId"] == route[0]["node_id"]
    assert rendered_by_chart_id[str(link["target"])]["nodeId"] == route[1]["node_id"]
    assert link["routeSequence"] == 1
    assert link["fromRoute"] == 1
    assert link["toRoute"] == 2
    assert link["relationType"] == "PREREQUISITE"
    assert all(link["kind"] != "route" for link in series["links"])


def test_cross_module_prerequisite_stays_subtle_in_the_complete_map() -> None:
    graph, route = _module_graph(3, children_per_module=3)
    graph["edges"].append(
        {
            "source_node_id": route[0]["node_id"],
            "target_node_id": route[1]["node_id"],
            "relation_type": "PREREQUISITE",
            "reason": "A real dependency crosses module boundaries.",
            "status": "ACTIVE",
        }
    )

    series = build_full_map_options(graph, route)["series"][0]
    cross_module_link = next(
        link for link in series["links"] if link.get("relationType") == "PREREQUISITE"
    )

    assert cross_module_link["kind"] == "knowledge"
    assert cross_module_link["lineStyle"]["width"] < 3
    assert cross_module_link["lineStyle"]["opacity"] < 0.7


def test_complete_map_uses_semantic_shapes_passive_hierarchy_and_fixed_positions() -> None:
    graph, route = _module_graph(6, children_per_module=4)
    series = build_full_map_options(graph, route)["series"][0]
    modules = [node for node in series["data"] if node["nodeType"] == "MODULE"]
    children = [node for node in series["data"] if node["nodeType"] != "MODULE"]
    contains_links = [link for link in series["links"] if link.get("relationType") == "CONTAINS"]

    assert series["draggable"] is False
    assert modules
    assert children
    assert all(node["symbol"] == "roundRect" for node in modules)
    assert all(
        isinstance(node["symbolSize"], (list, tuple))
        and len(node["symbolSize"]) == 2
        and node["symbolSize"][0] >= node["symbolSize"][1] * 2
        for node in modules
    )
    assert all(node["symbol"] == "roundRect" for node in children)
    assert all(
        isinstance(node["symbolSize"], (list, tuple))
        and len(node["symbolSize"]) == 2
        and node["symbolSize"][0] >= node["symbolSize"][1] * 2
        and node["label"]["position"] == "inside"
        for node in children
    )
    assert contains_links
    assert all(link["symbol"] == ["none", "none"] for link in contains_links)
    assert all(link["symbolSize"] == [0, 0] for link in contains_links)
    assert all(link["lineStyle"]["opacity"] <= 0.2 for link in contains_links)
    assert all(link["lineStyle"]["width"] <= 1 for link in contains_links)
