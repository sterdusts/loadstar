"""Pure visual-model contracts for the learner-facing plan component."""

import math
from itertools import pairwise

from learning_navigator.ui.components.learning_plan import (
    NODE_TYPE_COLORS,
    STAGE_ACCENTS,
    build_graph_options,
    build_stage_visual_model,
    graph_chart_height,
)


def _plan() -> dict[str, object]:
    return {
        "nodes": [
            {
                "temp_id": "module",
                "title": "基础 <模块> & 入门",
                "node_type": "MODULE",
                "difficulty": 1,
            },
            {
                "temp_id": "concept",
                "title": '变量 / 类型 "详解"',
                "description": "理解数据表示",
                "node_type": "CONCEPT",
                "difficulty": 2,
                "learning_objectives": ["解释变量"],
            },
            {
                "temp_id": "isolated",
                "title": "孤立练习",
                "node_type": "SKILL",
                "difficulty": 3,
            },
        ],
        "edges": [
            {
                "source_temp_id": "module",
                "target_temp_id": "concept",
                "relation_type": "CONTAINS",
            },
            {
                "source_temp_id": "missing",
                "target_temp_id": "concept",
                "relation_type": "RELATED",
            },
        ],
        "navigation": {
            "stages": [
                {
                    "sequence": 1,
                    "title": "建立基础",
                    "objective": "理解核心概念",
                    "node_temp_ids": ["concept", "missing"],
                    "completion_criteria": ["能够解释变量"],
                    "deliverable": "一页笔记",
                    "estimated_effort": "2 小时",
                }
            ]
        },
    }


def _four_stage_plan(stage_count: int = 4) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, str]] = []
    stages: list[dict[str, object]] = []
    previous_stage_target: str | None = None
    child_types = ("CONCEPT", "SKILL", "PROCEDURE")
    for stage_index in range(stage_count):
        module_id = f"module-{stage_index}"
        nodes.append(
            {
                "temp_id": module_id,
                "title": f"阶段 {stage_index + 1} 模块",
                "node_type": "MODULE",
                "difficulty": 2,
            }
        )
        stage_node_ids = []
        for child_index, node_type in enumerate(child_types):
            child_id = f"stage-{stage_index}-node-{child_index}"
            stage_node_ids.append(child_id)
            nodes.append(
                {
                    "temp_id": child_id,
                    "title": f"阶段 {stage_index + 1} 内容 {child_index + 1}",
                    "node_type": (
                        "PROJECT"
                        if stage_index == stage_count - 1 and child_index == 2
                        else node_type
                    ),
                    "difficulty": child_index + 1,
                }
            )
            edges.append(
                {
                    "source_temp_id": module_id,
                    "target_temp_id": child_id,
                    "relation_type": "CONTAINS",
                }
            )
        if previous_stage_target is not None:
            edges.append(
                {
                    "source_temp_id": previous_stage_target,
                    "target_temp_id": stage_node_ids[0],
                    "relation_type": "PREREQUISITE",
                }
            )
        previous_stage_target = stage_node_ids[-1]
        stages.append(
            {
                "sequence": stage_index + 1,
                "title": f"阶段 {stage_index + 1}",
                "node_temp_ids": stage_node_ids,
            }
        )
    return {"nodes": nodes, "edges": edges, "navigation": {"stages": stages}}


def test_graph_options_keep_special_titles_and_hide_temporary_ids() -> None:
    options = build_graph_options(_plan())
    series = options["series"][0]

    assert [node["name"] for node in series["data"]] == [
        "基础 <模块> & 入门",
        '变量 / 类型 "详解"',
        "孤立练习",
    ]
    assert [node["id"] for node in series["data"]] == ["node-0", "node-1", "node-2"]
    assert series["data"][0]["itemStyle"]["color"] == NODE_TYPE_COLORS["MODULE"]
    assert series["roam"] is True
    assert series["draggable"] is False
    assert series["layout"] == "none"
    assert series["preserveAspect"] is True
    assert "force" not in series
    assert all(isinstance(node["x"], int) for node in series["data"])
    assert all(isinstance(node["y"], int) for node in series["data"])


def test_graph_hover_emphasis_keeps_unrelated_nodes_and_edges_readable() -> None:
    series = build_graph_options(_four_stage_plan())["series"][0]

    # ECharts applies the emphasis style to the hovered element itself.  Any
    # other focus mode also moves unrelated graph elements into the blur state,
    # which makes a broad framework almost disappear while the pointer moves.
    emphasis = series["emphasis"]
    assert emphasis.get("focus") == "none"
    assert emphasis.get("blurScope") != "global"
    assert "blur" not in series

    # Node/link-specific overrides must not silently reintroduce adjacency or
    # global focus after the series-level contract has made hover local.
    for item in [*series["data"], *series["links"]]:
        item_emphasis = item.get("emphasis", {})
        assert item_emphasis.get("focus", "none") == "none"
        assert item_emphasis.get("blurScope") != "global"
        assert "blur" not in item


def test_graph_options_preserve_isolated_nodes_and_skip_dangling_edges() -> None:
    options = build_graph_options(_plan())
    series = options["series"][0]

    assert len(series["data"]) == 3
    assert len(series["links"]) == 1
    link = series["links"][0]
    assert link["kind"] == "knowledge"
    assert (link["source"], link["target"], link["value"]) == (
        "node-0",
        "node-1",
        "包含",
    )
    assert link["lineStyle"]["type"] == "dashed"
    assert link["lineStyle"]["width"] > 0


def test_knowledge_edge_tooltip_uses_real_titles_relation_and_reason() -> None:
    plan = _plan()
    plan["nodes"][0]["title"] = "真实源标题"
    plan["nodes"][1]["title"] = "真实目标标题"
    plan["edges"][0]["reason"] = "用于组织目标知识"

    series = build_graph_options(plan)["series"][0]
    link = next(link for link in series["links"] if link["kind"] == "knowledge")
    tooltip_text = link["tooltip"]["formatter"]

    assert isinstance(tooltip_text, str)
    assert all(
        expected in tooltip_text
        for expected in ("真实源标题", "真实目标标题", "包含", "用于组织目标知识")
    )
    assert "node-" not in tooltip_text


def test_knowledge_edge_tooltip_escapes_generated_content() -> None:
    plan = _plan()
    plan["edges"][0]["reason"] = "<script>unsafe()</script> & explanation"

    link = next(
        link
        for link in build_graph_options(plan)["series"][0]["links"]
        if link["kind"] == "knowledge"
    )
    tooltip_text = link["tooltip"]["formatter"]

    assert "基础 &lt;模块&gt; &amp; 入门" in tooltip_text
    assert "&lt;script&gt;unsafe()&lt;/script&gt; &amp; explanation" in tooltip_text
    assert "<script>" not in tooltip_text


def test_knowledge_edge_tooltip_has_readable_fallback_without_reason() -> None:
    plan = _plan()
    plan["nodes"][0]["title"] = "旧方案源标题"
    plan["nodes"][1]["title"] = "旧方案目标标题"

    series = build_graph_options(plan)["series"][0]
    link = next(link for link in series["links"] if link["kind"] == "knowledge")
    tooltip_text = link["tooltip"]["formatter"]

    assert isinstance(tooltip_text, str)
    assert all(expected in tooltip_text for expected in ("旧方案源标题", "旧方案目标标题", "包含"))
    assert "关联说明" in tooltip_text
    assert "None" not in tooltip_text
    assert "node-" not in tooltip_text


def test_graph_options_support_empty_edges() -> None:
    plan = _plan()
    plan["edges"] = []

    series = build_graph_options(plan)["series"][0]

    assert len(series["data"]) == 3
    assert series["links"] == []


def test_stage_visual_model_resolves_titles_and_omits_unknown_nodes() -> None:
    stages = build_stage_visual_model(_plan())

    assert stages[0]["node_titles"] == ['变量 / 类型 "详解"']
    assert stages[0]["completion_criteria"] == ["能够解释变量"]
    assert stages[0]["accent"] == "#1f6b4f"
    assert "temp_id" not in stages[0]


def test_four_stage_graph_uses_stable_organic_module_clusters() -> None:
    plan = _four_stage_plan()

    first = build_graph_options(plan)["series"][0]
    second = build_graph_options(plan)["series"][0]
    coordinates = [(node["x"], node["y"]) for node in first["data"]]

    assert coordinates == [(node["x"], node["y"]) for node in second["data"]]
    assert len(set(coordinates)) == 16
    assert len({x for x, _ in coordinates}) >= 12
    assert len({y for _, y in coordinates}) >= 10

    module_coordinates = [
        (first["data"][index]["x"], first["data"][index]["y"]) for index in (0, 4, 8, 12)
    ]
    module_x = [x for x, _ in module_coordinates]
    module_y = [y for _, y in module_coordinates]
    assert module_x == sorted(module_x)
    assert len(set(module_y)) >= 3
    assert max(module_y) - min(module_y) >= 200
    assert len({right - left for left, right in pairwise(module_x)}) >= 2
    assert 620 <= graph_chart_height(plan) <= 920

    for index, (x, y) in enumerate(coordinates):
        size = first["data"][index]["symbolSize"]
        for other_index, (other_x, other_y) in enumerate(coordinates[index + 1 :], start=index + 1):
            other_size = first["data"][other_index]["symbolSize"]
            assert math.hypot(x - other_x, y - other_y) >= (size + other_size) / 2 + 24

    for module_index in (0, 4, 8, 12):
        module_x, module_y = coordinates[module_index]
        children = coordinates[module_index + 1 : module_index + 4]
        horizontal_offsets = [child_x - module_x for child_x, _ in children]
        vertical_offsets = [child_y - module_y for _, child_y in children]
        assert min(horizontal_offsets) < 0 < max(horizontal_offsets)
        assert all(offset > 0 for offset in vertical_offsets) or all(
            offset < 0 for offset in vertical_offsets
        )


def test_graph_labels_are_bounded_with_overlap_protection() -> None:
    series = build_graph_options(_four_stage_plan())["series"][0]

    assert series["label"]["show"] is True
    assert series["label"]["overflow"] == "truncate"
    assert series["label"]["distance"] >= 8
    assert series["label"]["width"] <= 160
    assert series["labelLayout"] == {"hideOverlap": True}
    module_labels = [series["data"][index]["label"] for index in (0, 4, 8, 12)]
    assert len(module_labels) == 4
    assert {label["position"] for label in module_labels} == {"top", "bottom"}
    assert all(label["overflow"] == "truncate" for label in module_labels)
    assert all(node["label"]["distance"] >= 9 for node in series["data"])
    assert {node["label"]["position"] for node in series["data"]} == {"top", "bottom"}


def test_stage_sequence_resolves_module_anchors_and_numbered_badges() -> None:
    plan = _four_stage_plan()
    stages = plan["navigation"]["stages"]
    plan["navigation"]["stages"] = [stages[3], stages[1], stages[0], stages[2]]

    series = build_graph_options(plan)["series"][0]
    anchor_indices = [index for index, node in enumerate(series["data"]) if "stageBadge" in node]

    assert anchor_indices == [0, 4, 8, 12]
    expected_badges = ("①", "②", "③", "④")
    for sequence, (node_index, badge) in enumerate(
        zip(anchor_indices, expected_badges, strict=True),
        start=1,
    ):
        anchor = series["data"][node_index]
        assert anchor["name"] == f"阶段 {sequence} 模块"
        assert anchor["stageSequence"] == sequence
        assert anchor["stageBadge"] == badge
        assert badge in anchor["label"]["formatter"]


def test_stage_progress_links_form_a_distinct_one_to_four_backbone() -> None:
    plan = _four_stage_plan()
    stage_titles = {
        1: "基础认知",
        2: "核心练习",
        3: "综合应用",
        4: "项目交付",
    }
    for stage in plan["navigation"]["stages"]:
        stage["title"] = stage_titles[stage["sequence"]]
    series = build_graph_options(plan)["series"][0]
    knowledge_links = [link for link in series["links"] if link["kind"] == "knowledge"]
    progress_links = [link for link in series["links"] if link["kind"] == "stage_progress"]

    assert len(knowledge_links) == len(plan["edges"])
    assert all(link["kind"] == "knowledge" for link in knowledge_links)
    assert [
        (link["source"], link["target"], link["fromStage"], link["toStage"])
        for link in progress_links
    ] == [
        ("node-0", "node-4", 1, 2),
        ("node-4", "node-8", 2, 3),
        ("node-8", "node-12", 3, 4),
    ]

    widest_knowledge_edge = max(link["lineStyle"]["width"] for link in knowledge_links)
    knowledge_colors = {link["lineStyle"]["color"] for link in knowledge_links}
    for link in progress_links:
        assert link["lineStyle"]["width"] > widest_knowledge_edge
        assert link["lineStyle"]["color"] not in knowledge_colors
        assert link["symbol"] == ["none", "arrow"]
        assert link["symbolSize"][1] > 0
        tooltip_text = link["tooltip"]["formatter"]
        assert isinstance(tooltip_text, str)
        assert f"第 {link['fromStage']} 阶段" in tooltip_text
        assert f"第 {link['toStage']} 阶段" in tooltip_text
        assert stage_titles[link["fromStage"]] in tooltip_text
        assert stage_titles[link["toStage"]] in tooltip_text
        assert "node-" not in tooltip_text


def test_eight_stage_graph_and_stage_model_are_not_truncated() -> None:
    plan = _four_stage_plan(stage_count=8)

    visual_stages = build_stage_visual_model(plan)
    series = build_graph_options(plan)["series"][0]
    anchors = [node for node in series["data"] if "stageBadge" in node]
    progress_links = [link for link in series["links"] if link["kind"] == "stage_progress"]

    assert len(visual_stages) == 8
    assert [stage["sequence"] for stage in visual_stages] == list(range(1, 9))
    assert len(series["data"]) == 32
    assert [anchor["stageSequence"] for anchor in anchors] == list(range(1, 9))
    assert [anchor["stageBadge"] for anchor in anchors] == list("①②③④⑤⑥⑦⑧")
    assert [(link["fromStage"], link["toStage"]) for link in progress_links] == list(
        pairwise(range(1, 9))
    )


def test_extended_graph_wraps_module_lanes_without_node_collisions() -> None:
    plan = _four_stage_plan(stage_count=8)
    series = build_graph_options(plan)["series"][0]
    anchors = [node for node in series["data"] if "stageBadge" in node]

    assert len(anchors) == 8
    assert max(node["x"] for node in anchors) - min(node["x"] for node in anchors) < 2_000
    assert max(node["y"] for node in anchors) - min(node["y"] for node in anchors) > 600
    assert graph_chart_height(plan) > 920

    for index, node in enumerate(series["data"]):
        for other in series["data"][index + 1 :]:
            clearance = math.hypot(node["x"] - other["x"], node["y"] - other["y"])
            minimum = (node["symbolSize"] + other["symbolSize"]) / 2 + 24
            assert clearance >= minimum


def test_stage_members_receive_sequence_metadata_and_stage_colored_rings() -> None:
    series = build_graph_options(_four_stage_plan())["series"][0]

    for sequence, module_index in enumerate((0, 4, 8, 12), start=1):
        for node in series["data"][module_index + 1 : module_index + 4]:
            assert node["stageSequence"] == sequence
            assert node["itemStyle"]["borderColor"] == STAGE_ACCENTS[sequence - 1]
            assert node["itemStyle"]["borderWidth"] >= 3


def test_missing_stages_add_no_badges_or_progress_links() -> None:
    plan = _four_stage_plan()
    plan["navigation"] = {"stages": []}

    series = build_graph_options(plan)["series"][0]

    assert all("stageBadge" not in node for node in series["data"])
    assert all("stageSequence" not in node for node in series["data"])
    assert all(link["kind"] == "knowledge" for link in series["links"])
    assert len(series["links"]) == len(plan["edges"])


def test_unresolved_middle_stage_breaks_the_backbone_without_shortcutting() -> None:
    plan = _four_stage_plan()
    plan["navigation"]["stages"][1]["node_temp_ids"] = ["missing-stage-node"]

    series = build_graph_options(plan)["series"][0]
    progress_links = [link for link in series["links"] if link["kind"] == "stage_progress"]

    assert [(link["fromStage"], link["toStage"]) for link in progress_links] == [(3, 4)]
    assert {node.get("stageBadge") for node in series["data"]} == {None, "①", "③", "④"}
    assert not any(link["fromStage"] == 1 and link["toStage"] == 3 for link in progress_links)
