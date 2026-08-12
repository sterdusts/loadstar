"""Strict composite learning-plan DTO and deterministic Mock contracts."""

import asyncio
import copy
from itertools import pairwise
from typing import Any

import pytest
from pydantic import ValidationError

from learning_navigator.application.dto.ai import (
    KnowledgeMapDraft,
    LearningPlanDraft,
    analyze_draft,
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


def test_learning_plan_accepts_eight_modules_and_eight_ordered_stages() -> None:
    plan = LearningPlanDraft.model_validate(_linear_plan_payload(8))

    modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    assert len(modules) == 8
    assert [stage.sequence for stage in plan.navigation.stages] == list(range(1, 9))
    assert plan.navigation.target_temp_id == "topic-8"
    assert analyze_draft(plan).conflicts == []


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
