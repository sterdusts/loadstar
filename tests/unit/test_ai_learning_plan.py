"""Strict composite learning-plan DTO and deterministic Mock contracts."""

import asyncio
import copy
from itertools import pairwise
from typing import Any

import pytest
from pydantic import ValidationError

from learning_navigator.application.dto.ai import (
    CompactExplicitPlanDraft,
    KnowledgeMapDraft,
    LearningPlanDraft,
    analyze_draft,
    build_compact_explicit_outline_plan,
    explicit_outline_item_catalog,
    extract_explicit_outline_sections,
    extract_explicit_outline_titles,
    validate_explicit_outline_alignment,
    validate_generated_plan_outline,
)
from learning_navigator.domain.enums import NodeType, RelationType
from learning_navigator.infrastructure.ai.providers import MockProvider


def _node(temp_id: str, title: str, node_type: str = "CONCEPT") -> dict[str, Any]:
    return {"temp_id": temp_id, "title": title, "node_type": node_type}


def _contains(module_id: str, node_id: str) -> dict[str, Any]:
    return {
        "source_temp_id": module_id,
        "target_temp_id": node_id,
        "relation_type": "CONTAINS",
        "required_mastery_level": 0,
    }


def _prerequisite(source: str, target: str) -> dict[str, Any]:
    return {
        "source_temp_id": source,
        "target_temp_id": target,
        "relation_type": "PREREQUISITE",
        "required_mastery_level": 3,
    }


def _stage(sequence: int, node_id: str) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "title": f"Stage {sequence}",
        "objective": f"Master {node_id}",
        "node_temp_ids": [node_id],
        "completion_criteria": [f"Demonstrate {node_id} with a checked example"],
        "deliverable": f"{node_id} artifact",
        "estimated_effort": "2 hours",
    }


def _valid_plan_payload() -> dict[str, Any]:
    module_pairs = [("m1", "a"), ("m2", "b"), ("m3", "c"), ("m4", "target")]
    nodes = [
        item
        for module_id, node_id in module_pairs
        for item in (
            _node(module_id, f"Module {module_id}", "MODULE"),
            _node(node_id, f"Node {node_id}", "PROJECT" if node_id == "target" else "CONCEPT"),
        )
    ]
    nodes.append(_node("optional", "Optional enrichment"))
    return {
        "space": {"title": "Composite learning plan"},
        "nodes": nodes,
        "edges": [
            *[_contains(module_id, node_id) for module_id, node_id in module_pairs],
            _contains("m4", "optional"),
            _prerequisite("a", "b"),
            _prerequisite("b", "c"),
            _prerequisite("c", "target"),
        ],
        "navigation": {
            "goal_title": "Deliver the final project",
            "target_temp_id": "target",
            "target_mastery_level": 4,
            "success_definition": "Complete and explain a reviewable project independently.",
            "stages": [
                _stage(1, "a"),
                _stage(2, "b"),
                _stage(3, "c"),
                _stage(4, "target"),
            ],
        },
    }


def _linear_plan_payload(stage_count: int) -> dict[str, Any]:
    """Build a valid route whose module and stage counts can exceed the old four-item shape."""

    concrete_ids = [f"topic-{sequence}" for sequence in range(1, stage_count + 1)]
    nodes = [
        item
        for sequence, node_id in enumerate(concrete_ids, start=1)
        for item in (
            _node(f"module-{sequence}", f"Module {sequence}", "MODULE"),
            _node(
                node_id,
                f"Topic {sequence}",
                "PROJECT" if sequence == stage_count else "CONCEPT",
            ),
        )
    ]
    return {
        "space": {"title": f"{stage_count}-stage learning plan"},
        "nodes": nodes,
        "edges": [
            *[
                _contains(f"module-{sequence}", node_id)
                for sequence, node_id in enumerate(concrete_ids, start=1)
            ],
            *[_prerequisite(source, target) for source, target in pairwise(concrete_ids)],
        ],
        "navigation": {
            "goal_title": "Complete the extended route",
            "target_temp_id": concrete_ids[-1],
            "target_mastery_level": 4,
            "success_definition": "Complete every stage and deliver the final project.",
            "stages": [
                _stage(sequence, node_id) for sequence, node_id in enumerate(concrete_ids, start=1)
            ],
        },
    }


def test_learning_plan_accepts_modules_outside_stages_and_closed_prerequisite_route() -> None:
    plan = LearningPlanDraft.model_validate(_valid_plan_payload())

    assert plan.navigation.target_mastery_level == 4
    assert len(plan.navigation.stages) == 4
    assert all(
        node.node_type is not NodeType.MODULE
        for stage in plan.navigation.stages
        for node_id in stage.node_temp_ids
        for node in plan.nodes
        if node.temp_id == node_id
    )
    assert analyze_draft(plan).conflicts == []


def test_legacy_flat_plan_remains_readable_but_cannot_be_accepted_as_new_ai_output() -> None:
    payload = _valid_plan_payload()
    payload["nodes"] = [node for node in payload["nodes"] if node["node_type"] != "MODULE"]
    payload["edges"] = [edge for edge in payload["edges"] if edge["relation_type"] != "CONTAINS"]

    legacy_plan = LearningPlanDraft.model_validate(payload)
    assert all(node.node_type is not NodeType.MODULE for node in legacy_plan.nodes)

    with pytest.raises(ValueError, match="between 3 and 12"):
        validate_generated_plan_outline(legacy_plan)


def test_learning_plan_rejects_structural_modules_as_route_steps() -> None:
    payload = _valid_plan_payload()
    payload["navigation"]["stages"][0]["node_temp_ids"] = ["m1", "a"]

    with pytest.raises(ValidationError, match="cannot contain MODULE"):
        LearningPlanDraft.model_validate(payload)


def test_learning_plan_rejects_module_prerequisites_and_ungrouped_nodes() -> None:
    module_dependency = _valid_plan_payload()
    module_dependency["edges"].append(_prerequisite("m1", "b"))
    with pytest.raises(ValidationError, match="structural containers"):
        LearningPlanDraft.model_validate(module_dependency)

    ungrouped = _valid_plan_payload()
    ungrouped["edges"] = [
        edge
        for edge in ungrouped["edges"]
        if not (edge["relation_type"] == "CONTAINS" and edge["target_temp_id"] == "optional")
    ]
    with pytest.raises(ValidationError, match="assign every concrete node"):
        LearningPlanDraft.model_validate(ungrouped)


def test_learning_plan_accepts_eight_modules_and_eight_ordered_stages() -> None:
    plan = LearningPlanDraft.model_validate(_linear_plan_payload(8))

    modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    assert len(modules) == 8
    assert [stage.sequence for stage in plan.navigation.stages] == list(range(1, 9))
    assert plan.navigation.target_temp_id == "topic-8"
    assert analyze_draft(plan).conflicts == []


def test_explicit_chinese_phase_outline_is_authoritative() -> None:
    source = """
第一阶段：
初中数学基础重建
包括：数与运算、方程

第二阶段：高中数学核心
第三阶段：高等数学基础
第四阶段：线性代数
第五阶段：概率统计
第六阶段：AI/量化数学应用
"""
    titles = extract_explicit_outline_titles(source)

    assert titles == [
        "初中数学基础重建",
        "高中数学核心",
        "高等数学基础",
        "线性代数",
        "概率统计",
        "AI/量化数学应用",
    ]
    valid_payload = _linear_plan_payload(6)
    module_titles = titles.copy()
    for node in valid_payload["nodes"]:
        if node["node_type"] == "MODULE":
            node["title"] = module_titles.pop(0)
    valid_plan = LearningPlanDraft.model_validate(valid_payload)
    assert validate_explicit_outline_alignment(valid_plan, source) is valid_plan

    malformed_plan = LearningPlanDraft.model_validate(_linear_plan_payload(9))
    with pytest.raises(ValueError, match="expected=6, actual=9"):
        validate_explicit_outline_alignment(malformed_plan, source)


def test_isolated_stage_phrase_does_not_override_module_heuristic() -> None:
    plan = LearningPlanDraft.model_validate(_linear_plan_payload(5))

    assert validate_explicit_outline_alignment(plan, "先完成阶段 1，再复盘") is plan


def test_explicit_outline_requires_every_concrete_node_in_the_route() -> None:
    source = """第一阶段：基础
第二阶段：进阶
第三阶段：应用
第四阶段：验证"""
    payload = _valid_plan_payload()
    module_titles = extract_explicit_outline_titles(source)
    for node in payload["nodes"]:
        if node["node_type"] == "MODULE":
            node["title"] = module_titles.pop(0)
    plan = LearningPlanDraft.model_validate(payload)

    with pytest.raises(ValueError, match="optional"):
        validate_explicit_outline_alignment(plan, source)


def test_explicit_outline_sections_preserve_each_authored_bullet() -> None:
    sections = extract_explicit_outline_sections(
        """第一阶段：
基础重建
包括：
* 数与运算
* 方程

第二阶段：进阶
* 导数
* 积分

第三阶段：应用
* 梯度下降
"""
    )

    assert [(section.title, list(section.items)) for section in sections] == [
        ("基础重建", ["数与运算", "方程"]),
        ("进阶", ["导数", "积分"]),
        ("应用", ["梯度下降"]),
    ]


def test_explicit_outline_stops_at_the_end_of_each_included_bullet_block() -> None:
    sections = extract_explicit_outline_sections(
        """第一阶段：
基础重建
包括：
* 数与运算
* 方程
第二阶段：
函数核心
包括：
* 函数
* 图像
第三阶段：
应用
包括：
* 梯度下降
* 风险统计
不要：
* 严格小时计划
最终能够：
* 理解大学数学
"""
    )

    assert [section.title for section in sections] == ["基础重建", "函数核心", "应用"]
    assert sections[-1].items == ("梯度下降", "风险统计")


def test_compact_explicit_plan_preserves_hierarchy_and_builds_complete_route() -> None:
    source = """第一阶段：
基础重建
包括：
* 数与运算
* 方程
第二阶段：
函数核心
包括：
* 函数
* 图像
第三阶段：
应用
包括：
* 梯度下降
* 风险统计
"""
    _, catalog = explicit_outline_item_catalog(source)
    item_ids = [item["item_id"] for module in catalog for item in module["items"]]
    proposal = CompactExplicitPlanDraft.model_validate(
        {
            "goal_title": "系统数学基础",
            "success_definition": "建立完整数学框架并用于 AI 与量化。",
            "target_item_id": item_ids[-1],
            "item_profiles": [
                {"item_id": item_id, "node_type": "CONCEPT", "difficulty": 2}
                for item_id in item_ids
            ],
            "prerequisite_edges": [
                {
                    "source_item_id": item_ids[0],
                    "target_item_id": item_ids[2],
                    "reason": "基础支持函数。",
                },
                {
                    "source_item_id": item_ids[-1],
                    "target_item_id": item_ids[0],
                    "reason": "非法的逆阶段关系应被忽略。",
                },
            ],
        }
    )

    plan = build_compact_explicit_outline_plan(source, proposal)

    modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    content = [node for node in plan.nodes if node.node_type is not NodeType.MODULE]
    contains = [edge for edge in plan.edges if edge.relation_type is RelationType.CONTAINS]
    assert [node.title for node in modules] == ["基础重建", "函数核心", "应用"]
    assert [node.title for node in content] == [
        "数与运算",
        "方程",
        "函数",
        "图像",
        "梯度下降",
        "风险统计",
    ]
    assert len(contains) == 6
    assert [len(stage.node_temp_ids) for stage in plan.navigation.stages] == [2, 2, 2]
    assert sum(len(stage.node_temp_ids) for stage in plan.navigation.stages) == 6


def test_explicit_outline_rejects_merged_or_missing_bullet_nodes() -> None:
    payload = _linear_plan_payload(3)
    explicit = [
        ("基础", ["数与运算"]),
        ("进阶", ["导数"]),
        ("应用", ["梯度下降"]),
    ]
    module_index = 0
    concrete_index = 0
    for node in payload["nodes"]:
        if node["node_type"] == "MODULE":
            node["title"] = explicit[module_index][0]
            module_index += 1
        else:
            node["title"] = explicit[concrete_index][1][0]
            concrete_index += 1
    plan = LearningPlanDraft.model_validate(payload)
    source = """第一阶段：基础
* 数与运算
第二阶段：进阶
* 导数
* 积分
第三阶段：应用
* 梯度下降"""

    with pytest.raises(ValueError, match="积分"):
        validate_explicit_outline_alignment(plan, source)


def test_explicit_outline_may_keep_up_to_eight_children_per_module() -> None:
    payload = _linear_plan_payload(3)
    for index in range(2, 6):
        child_id = f"module-1-child-{index}"
        payload["nodes"].append(_node(child_id, f"Module 1 child {index}"))
        payload["edges"].append(_contains("module-1", child_id))
        payload["navigation"]["stages"][0]["node_temp_ids"].append(child_id)
    plan = LearningPlanDraft.model_validate(payload)

    assert validate_generated_plan_outline(plan, max_children_per_module=8) is plan
    with pytest.raises(ValueError, match="between 1 and 4"):
        validate_generated_plan_outline(plan)


def test_plain_knowledge_map_remains_compatible_without_navigation() -> None:
    payload = _valid_plan_payload()
    payload.pop("navigation")

    map_draft = KnowledgeMapDraft.model_validate(payload)

    assert len(map_draft.nodes) == 9
    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_framework_schema_supports_understanding_and_execution_nodes() -> None:
    framework = KnowledgeMapDraft.model_validate(
        {
            "space": {"title": "理解并进入新能源行业"},
            "nodes": [
                _node("question", "行业靠什么创造价值", "QUESTION"),
                _node("mechanism", "供需与成本传导", "MECHANISM"),
                _node("evidence", "产能与价格数据", "EVIDENCE"),
                _node("decision", "选择切入环节", "DECISION"),
                _node("risk", "政策与周期风险", "RISK"),
                _node("deliverable", "形成行业判断框架", "DELIVERABLE"),
            ],
            "edges": [
                {
                    "source_temp_id": "evidence",
                    "target_temp_id": "mechanism",
                    "relation_type": "SUPPORTS",
                    "required_mastery_level": 0,
                },
                {
                    "source_temp_id": "risk",
                    "target_temp_id": "decision",
                    "relation_type": "CONSTRAINS",
                    "required_mastery_level": 0,
                },
                {
                    "source_temp_id": "decision",
                    "target_temp_id": "deliverable",
                    "relation_type": "ENABLES",
                    "required_mastery_level": 0,
                },
            ],
        }
    )

    assert {node.node_type for node in framework.nodes} >= {
        NodeType.QUESTION,
        NodeType.MECHANISM,
        NodeType.EVIDENCE,
        NodeType.DECISION,
        NodeType.RISK,
        NodeType.DELIVERABLE,
    }
    assert {edge.relation_type for edge in framework.edges} == {
        RelationType.SUPPORTS,
        RelationType.CONSTRAINS,
        RelationType.ENABLES,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["navigation"]["stages"][0]["node_temp_ids"].__setitem__(
                0, "missing"
            ),
            "unknown temp_id",
        ),
        (
            lambda payload: payload["navigation"]["stages"][1].__setitem__("sequence", 3),
            "contiguous",
        ),
        (
            lambda payload: payload["navigation"]["stages"][1]["node_temp_ids"].append("a"),
            "appears more than once",
        ),
        (
            lambda payload: payload["navigation"]["stages"][3]["node_temp_ids"].__setitem__(
                0, "optional"
            ),
            "final learning stage",
        ),
        (
            lambda payload: payload["navigation"].__setitem__("target_temp_id", "m4"),
            "cannot be a MODULE",
        ),
        (
            lambda payload: payload["navigation"]["stages"][1]["node_temp_ids"].__setitem__(
                0, "optional"
            ),
            "prerequisite ancestors",
        ),
        (
            lambda payload: (
                payload["navigation"]["stages"][0]["node_temp_ids"].__setitem__(0, "b"),
                payload["navigation"]["stages"][1]["node_temp_ids"].__setitem__(0, "a"),
            ),
            "prerequisite stage cannot be later",
        ),
    ],
)
def test_learning_plan_rejects_invalid_stage_graph_contract(mutate: Any, message: str) -> None:
    payload = copy.deepcopy(_valid_plan_payload())
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        LearningPlanDraft.model_validate(payload)


def test_learning_stage_rejects_blank_criteria_and_invalid_temp_id() -> None:
    blank_criterion = _valid_plan_payload()
    blank_criterion["navigation"]["stages"][0]["completion_criteria"] = ["   "]
    with pytest.raises(ValidationError, match="completion criteria cannot be blank"):
        LearningPlanDraft.model_validate(blank_criterion)

    invalid_id = _valid_plan_payload()
    invalid_id["navigation"]["stages"][0]["node_temp_ids"] = ["not valid"]
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        LearningPlanDraft.model_validate(invalid_id)


def test_mock_provider_expands_broad_professional_goal_to_six_modules() -> None:
    provider = MockProvider(model="learning-plan-test-model")

    plan = asyncio.run(
        provider.generate_learning_plan(
            "FastAPI backend engineering",
            "Independently build a production-ready API with tests",
        )
    )

    modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    contains_edges = [edge for edge in plan.edges if edge.relation_type is RelationType.CONTAINS]
    assert len(modules) == 6
    assert len(contains_edges) == 6
    assert [stage.sequence for stage in plan.navigation.stages] == list(range(1, 7))
    assert plan.navigation.target_mastery_level == 4
    assert plan.navigation.target_temp_id in plan.navigation.stages[-1].node_temp_ids
    assert all(stage.completion_criteria for stage in plan.navigation.stages)
    assert all(stage.deliverable for stage in plan.navigation.stages)
    assert analyze_draft(plan).conflicts == []


def test_mock_provider_expands_complex_cross_domain_goal_to_eight_modules() -> None:
    provider = MockProvider(model="learning-plan-test-model")

    plan = asyncio.run(
        provider.generate_learning_plan(
            "跨领域 AI 量化研究系统",
            (
                "从零系统掌握数学、统计学、机器学习、金融工程、数据工程和风险管理，"
                "建立完整知识地图，并独立完成可验证的生产级综合项目"
            ),
        )
    )

    modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    assert len(modules) == 8
    assert len(plan.navigation.stages) == 8
    assert [stage.sequence for stage in plan.navigation.stages] == list(range(1, 9))
    assert plan.navigation.target_temp_id in plan.navigation.stages[-1].node_temp_ids
    assert analyze_draft(plan).conflicts == []


@pytest.mark.parametrize(
    ("topic", "requirements", "expected_type", "expected_intent", "first_level"),
    [
        (
            "学习概率统计",
            "掌握基础并通过测试",
            NodeType.ASSESSMENT,
            "LEARN",
            "未开始",
        ),
        (
            "了解新能源汽车行业",
            "形成完整行业判断",
            NodeType.DELIVERABLE,
            "UNDERSTAND",
            "不知道",
        ),
        (
            "做一个个人网站",
            "完成发布并可访问",
            NodeType.DELIVERABLE,
            "DO",
            "未启动",
        ),
        ("建立系统数学体系", "半年形成完整基础", NodeType.ASSESSMENT, "LEARN", "未开始"),
    ],
)
def test_mock_provider_infers_goal_template_without_extra_user_setting(
    topic: str,
    requirements: str,
    expected_type: NodeType,
    expected_intent: str,
    first_level: str,
) -> None:
    plan = asyncio.run(MockProvider().generate_learning_plan(topic, requirements))
    target = next(node for node in plan.nodes if node.temp_id == plan.navigation.target_temp_id)

    assert target.node_type is expected_type
    assert plan.navigation.goal_title == topic
    assert plan.navigation.intent_mode.value == expected_intent
    assert plan.navigation.semantic_profile is not None
    assert plan.navigation.semantic_profile.progress_levels[0].label == first_level


def test_mock_provider_does_not_treat_building_a_mental_framework_as_doing() -> None:
    plan = asyncio.run(
        MockProvider().generate_learning_plan(
            "Understand the semiconductor industry",
            (
                "Build a comprehensive cross-domain map of the industry field, "
                "its technology, economics, evidence and competing perspectives."
            ),
        )
    )

    assert plan.navigation.intent_mode.value == "UNDERSTAND"
