"""Strict schemas for AI-produced proposals.

Unknown fields and dangling references are rejected before any suggestion row is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any
from unicodedata import category, normalize

import networkx as nx
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from learning_navigator.domain.enums import (
    ComputedNodeStatus,
    GoalIntent,
    NodeType,
    RelationType,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TempId = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"),
]


def _non_blank_semantic_label(value: str) -> str:
    compatibility_normalized = normalize("NFKC", value)
    if any(category(character) in {"Cc", "Cf"} for character in compatibility_normalized):
        raise ValueError("semantic labels cannot contain control or format characters")
    normalized = " ".join(compatibility_normalized.strip().split())
    if not normalized:
        raise ValueError("semantic labels cannot be blank")
    if len(normalized) > 32:
        raise ValueError("semantic labels cannot exceed 32 normalized characters")
    if not normalized.isprintable():
        raise ValueError("semantic labels must be single-line printable text")
    return normalized


SemanticLabel = Annotated[
    str,
    Field(min_length=1, max_length=32),
    AfterValidator(_non_blank_semantic_label),
]


class KnowledgeSpaceDraft(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_audience: str = ""
    scope_included: list[str] = Field(default_factory=list)
    scope_excluded: list[str] = Field(default_factory=list)


class KnowledgeNodeDraft(StrictModel):
    temp_id: TempId
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    detailed_description: str = Field(default="", max_length=50_000)
    node_type: NodeType = NodeType.CONCEPT
    difficulty: int = Field(default=1, ge=1, le=5)
    learning_objectives: list[str] = Field(default_factory=list)
    source_basis: list[dict[str, Any] | str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


class KnowledgeEdgeDraft(StrictModel):
    source_temp_id: TempId
    target_temp_id: TempId
    relation_type: RelationType = RelationType.PREREQUISITE
    reason: str = ""
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    required_mastery_level: int = Field(default=3, ge=0, le=5)

    @model_validator(mode="after")
    def validate_unlock_fields(self) -> KnowledgeEdgeDraft:
        if self.source_temp_id == self.target_temp_id:
            raise ValueError("self-referential edges are not allowed")
        if self.relation_type is not RelationType.PREREQUISITE:
            if self.required_mastery_level != 0:
                raise ValueError("non-prerequisite edges must use required_mastery_level=0")
        elif self.required_mastery_level == 0:
            raise ValueError("prerequisite edges require mastery level 1 through 5")
        return self


class KnowledgeMapDraft(StrictModel):
    space: KnowledgeSpaceDraft
    nodes: list[KnowledgeNodeDraft]
    edges: list[KnowledgeEdgeDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    uncertain_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> KnowledgeMapDraft:
        temp_ids = [node.temp_id for node in self.nodes]
        if len(temp_ids) != len(set(temp_ids)):
            raise ValueError("node temp_id values must be unique")
        known_ids = set(temp_ids)
        edge_keys: set[tuple[str, str, RelationType]] = set()
        for edge in self.edges:
            missing = {edge.source_temp_id, edge.target_temp_id} - known_ids
            if missing:
                raise ValueError(f"edge references unknown temp_id values: {sorted(missing)}")
            key = (edge.source_temp_id, edge.target_temp_id, edge.relation_type)
            if key in edge_keys:
                raise ValueError(f"duplicate edge proposal: {key}")
            edge_keys.add(key)
        return self


class LearningStageDraft(StrictModel):
    sequence: int = Field(ge=1, le=20)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    node_temp_ids: list[TempId] = Field(min_length=1, max_length=100)
    completion_criteria: list[str] = Field(min_length=1, max_length=20)
    deliverable: str | None = Field(default=None, max_length=2000)
    estimated_effort: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_stage_content(self) -> LearningStageDraft:
        if not self.title.strip() or not self.objective.strip():
            raise ValueError("stage title and objective cannot be blank")
        if len(self.node_temp_ids) != len(set(self.node_temp_ids)):
            raise ValueError("stage node_temp_ids must be unique")
        if any(not item.strip() for item in self.completion_criteria):
            raise ValueError("completion criteria cannot be blank")
        if self.deliverable is not None and not self.deliverable.strip():
            raise ValueError("deliverable cannot be blank when supplied")
        if self.estimated_effort is not None and not self.estimated_effort.strip():
            raise ValueError("estimated_effort cannot be blank when supplied")
        return self


class SemanticProgressLevelDraft(StrictModel):
    min_score: int = Field(ge=0, le=100, strict=True)
    label: SemanticLabel


class SemanticStatusLabelsDraft(StrictModel):
    AVAILABLE: SemanticLabel
    BLOCKED: SemanticLabel
    MASTERED: SemanticLabel
    IN_PROGRESS: SemanticLabel
    NEEDS_REVIEW: SemanticLabel
    NOT_RELEVANT: SemanticLabel

    def as_canonical_map(self) -> dict[ComputedNodeStatus, str]:
        return {status: str(getattr(self, status.value)) for status in ComputedNodeStatus}


class SemanticActionLabelsDraft(StrictModel):
    AVAILABLE: SemanticLabel
    IN_PROGRESS: SemanticLabel
    NEEDS_REVIEW: SemanticLabel

    def as_canonical_map(self) -> dict[ComputedNodeStatus, str]:
        return {
            ComputedNodeStatus.AVAILABLE: str(self.AVAILABLE),
            ComputedNodeStatus.IN_PROGRESS: str(self.IN_PROGRESS),
            ComputedNodeStatus.NEEDS_REVIEW: str(self.NEEDS_REVIEW),
        }


class SemanticDimensionLabelsDraft(StrictModel):
    concept_understanding: SemanticLabel
    procedural_skill: SemanticLabel
    application_skill: SemanticLabel
    memory_strength: SemanticLabel


class SemanticTemplateId(StrEnum):
    LEARN_MASTERY_V1 = "LEARN_MASTERY_V1"
    LEARN_PRACTICE_V1 = "LEARN_PRACTICE_V1"
    UNDERSTAND_FAMILIARITY_V1 = "UNDERSTAND_FAMILIARITY_V1"
    UNDERSTAND_EVIDENCE_V1 = "UNDERSTAND_EVIDENCE_V1"
    DO_DELIVERY_V1 = "DO_DELIVERY_V1"
    DO_READINESS_V1 = "DO_READINESS_V1"


class GoalSemanticProfileDraft(StrictModel):
    """AI-authored display vocabulary constrained to stable domain keys.

    The profile may rename concepts for one goal, but it cannot introduce a new
    status, mastery dimension, or progress calculation.  Algorithms continue to
    operate exclusively on the canonical enum and numeric values.
    """

    template_id: SemanticTemplateId
    node_label: SemanticLabel
    module_label: SemanticLabel
    route_label: SemanticLabel
    record_label: SemanticLabel
    evidence_label: SemanticLabel
    status_labels: SemanticStatusLabelsDraft
    action_labels: SemanticActionLabelsDraft
    dimension_labels: SemanticDimensionLabelsDraft
    progress_levels: list[SemanticProgressLevelDraft] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def validate_canonical_coverage(self) -> GoalSemanticProfileDraft:
        scores = [level.min_score for level in self.progress_levels]
        if scores[0] != 0:
            raise ValueError("progress_levels must start at min_score 0")
        if any(current <= previous for previous, current in pairwise(scores)):
            raise ValueError("progress_levels min_score values must be strictly increasing")
        normalized_labels = [level.label.casefold() for level in self.progress_levels]
        if len(normalized_labels) != len(set(normalized_labels)):
            raise ValueError("progress_levels labels must be unique")

        status_values = [
            label.casefold() for label in self.status_labels.as_canonical_map().values()
        ]
        if len(status_values) != len(set(status_values)):
            raise ValueError("status_labels must remain distinguishable")
        action_values = [
            label.casefold() for label in self.action_labels.as_canonical_map().values()
        ]
        if len(action_values) != len(set(action_values)):
            raise ValueError("action_labels must remain distinguishable")

        score_bands = _PROGRESS_SCORE_BANDS[len(self.progress_levels)]
        for level, (minimum, maximum) in zip(self.progress_levels, score_bands, strict=True):
            if not minimum <= level.min_score <= maximum:
                raise ValueError(
                    "progress_levels thresholds must stay inside the safe ordered bands"
                )
        return self


_PROGRESS_SCORE_BANDS: dict[int, tuple[tuple[int, int], ...]] = {
    3: ((0, 0), (30, 55), (70, 100)),
    4: ((0, 0), (15, 40), (45, 70), (75, 100)),
    5: ((0, 0), (10, 30), (35, 55), (55, 80), (80, 100)),
    6: ((0, 0), (8, 25), (20, 45), (35, 65), (55, 85), (80, 100)),
}


@dataclass(frozen=True, slots=True)
class ControlledSemanticTemplate:
    """One reviewed, indivisible interpretation of canonical goal state."""

    intent_mode: GoalIntent
    status_labels: dict[ComputedNodeStatus, str]
    action_labels: dict[ComputedNodeStatus, str]
    progress_levels: tuple[tuple[int, str], ...]


_CONTROLLED_SEMANTIC_TEMPLATES: dict[SemanticTemplateId, ControlledSemanticTemplate] = {
    SemanticTemplateId.LEARN_MASTERY_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.LEARN,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "现在可学",
            ComputedNodeStatus.BLOCKED: "前置未满足",
            ComputedNodeStatus.MASTERED: "已掌握",
            ComputedNodeStatus.IN_PROGRESS: "学习中",
            ComputedNodeStatus.NEEDS_REVIEW: "需要复习",
            ComputedNodeStatus.NOT_RELEVANT: "非当前学习路径",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始学习",
            ComputedNodeStatus.IN_PROGRESS: "继续学习",
            ComputedNodeStatus.NEEDS_REVIEW: "开始复习",
        },
        progress_levels=(
            (0, "尚未掌握"),
            (20, "开始理解"),
            (45, "基本掌握"),
            (70, "能够应用"),
            (90, "熟练迁移"),
        ),
    ),
    SemanticTemplateId.LEARN_PRACTICE_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.LEARN,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "可以学习",
            ComputedNodeStatus.BLOCKED: "前置知识未掌握",
            ComputedNodeStatus.MASTERED: "已学会",
            ComputedNodeStatus.IN_PROGRESS: "正在学习",
            ComputedNodeStatus.NEEDS_REVIEW: "待复习",
            ComputedNodeStatus.NOT_RELEVANT: "暂不学习",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始学习",
            ComputedNodeStatus.IN_PROGRESS: "继续学习",
            ComputedNodeStatus.NEEDS_REVIEW: "复习巩固",
        },
        progress_levels=(
            (0, "未开始"),
            (20, "初步接触"),
            (45, "正在理解"),
            (70, "能够应用"),
            (90, "已经掌握"),
        ),
    ),
    SemanticTemplateId.UNDERSTAND_FAMILIARITY_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.UNDERSTAND,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "可以了解",
            ComputedNodeStatus.BLOCKED: "前提待补",
            ComputedNodeStatus.MASTERED: "已深入了解",
            ComputedNodeStatus.IN_PROGRESS: "了解中",
            ComputedNodeStatus.NEEDS_REVIEW: "待更新",
            ComputedNodeStatus.NOT_RELEVANT: "暂不关注",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始了解",
            ComputedNodeStatus.IN_PROGRESS: "继续了解",
            ComputedNodeStatus.NEEDS_REVIEW: "重新核验",
        },
        progress_levels=((0, "不知道"), (25, "听说过"), (55, "了解"), (85, "非常了解")),
    ),
    SemanticTemplateId.UNDERSTAND_EVIDENCE_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.UNDERSTAND,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "可以核验",
            ComputedNodeStatus.BLOCKED: "证据前提不足",
            ComputedNodeStatus.MASTERED: "已充分确认",
            ComputedNodeStatus.IN_PROGRESS: "核验中",
            ComputedNodeStatus.NEEDS_REVIEW: "需要复核",
            ComputedNodeStatus.NOT_RELEVANT: "非当前问题",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始核验",
            ComputedNodeStatus.IN_PROGRESS: "继续核验",
            ComputedNodeStatus.NEEDS_REVIEW: "复核结论",
        },
        progress_levels=((0, "未核验"), (25, "有线索"), (55, "有依据"), (85, "充分确认")),
    ),
    SemanticTemplateId.DO_DELIVERY_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.DO,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "可以执行",
            ComputedNodeStatus.BLOCKED: "条件未满足",
            ComputedNodeStatus.MASTERED: "已完成",
            ComputedNodeStatus.IN_PROGRESS: "进行中",
            ComputedNodeStatus.NEEDS_REVIEW: "待复核",
            ComputedNodeStatus.NOT_RELEVANT: "暂不执行",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始执行",
            ComputedNodeStatus.IN_PROGRESS: "继续执行",
            ComputedNodeStatus.NEEDS_REVIEW: "复核结果",
        },
        progress_levels=(
            (0, "未启动"),
            (20, "已准备"),
            (45, "进行中"),
            (75, "基本完成"),
            (95, "已交付"),
        ),
    ),
    SemanticTemplateId.DO_READINESS_V1: ControlledSemanticTemplate(
        intent_mode=GoalIntent.DO,
        status_labels={
            ComputedNodeStatus.AVAILABLE: "可以准备",
            ComputedNodeStatus.BLOCKED: "前置条件未满足",
            ComputedNodeStatus.MASTERED: "已就绪",
            ComputedNodeStatus.IN_PROGRESS: "准备中",
            ComputedNodeStatus.NEEDS_REVIEW: "待检查",
            ComputedNodeStatus.NOT_RELEVANT: "非当前阶段",
        },
        action_labels={
            ComputedNodeStatus.AVAILABLE: "开始准备",
            ComputedNodeStatus.IN_PROGRESS: "继续准备",
            ComputedNodeStatus.NEEDS_REVIEW: "检查结果",
        },
        progress_levels=((0, "未准备"), (25, "初步准备"), (55, "基本就绪"), (85, "完全就绪")),
    ),
}


def _semantic_key(value: str) -> str:
    return value.casefold()


def validate_semantic_profile_for_intent(
    profile: GoalSemanticProfileDraft,
    intent_mode: GoalIntent,
) -> GoalSemanticProfileDraft:
    """Allow only reviewed functional templates for the selected intent.

    AI remains free to adapt object and dimension names.  Functional state,
    action and ordinal copy is selected from this versioned registry instead
    of being interpreted as unrestricted natural language, so negation or
    cross-intent wording cannot invert the canonical model.
    """

    template = _CONTROLLED_SEMANTIC_TEMPLATES[profile.template_id]
    if template.intent_mode != intent_mode:
        raise ValueError("semantic template does not belong to the selected intent")

    actual_statuses = {
        status: _semantic_key(label)
        for status, label in profile.status_labels.as_canonical_map().items()
    }
    expected_statuses = {
        status: _semantic_key(label) for status, label in template.status_labels.items()
    }
    if actual_statuses != expected_statuses:
        raise ValueError("status_labels must exactly match the selected semantic template")

    actual_actions = {
        status: _semantic_key(label)
        for status, label in profile.action_labels.as_canonical_map().items()
    }
    expected_actions = {
        status: _semantic_key(label) for status, label in template.action_labels.items()
    }
    if actual_actions != expected_actions:
        raise ValueError("action_labels must exactly match the selected semantic template")

    actual_progress = tuple(
        (level.min_score, _semantic_key(level.label)) for level in profile.progress_levels
    )
    expected_progress = tuple(
        (score, _semantic_key(label)) for score, label in template.progress_levels
    )
    if actual_progress != expected_progress:
        raise ValueError("progress_levels must exactly match the selected semantic template")
    return profile


def controlled_semantic_template_catalog() -> list[dict[str, Any]]:
    """Expose the prompt-safe registry without duplicating functional copy."""

    return [
        {
            "template_id": template_id.value,
            "intent_mode": template.intent_mode.value,
            "status_labels": {
                status.value: label for status, label in template.status_labels.items()
            },
            "action_labels": {
                status.value: label for status, label in template.action_labels.items()
            },
            "progress_levels": [
                {"min_score": score, "label": label} for score, label in template.progress_levels
            ],
        }
        for template_id, template in _CONTROLLED_SEMANTIC_TEMPLATES.items()
    ]


def semantic_profile_payload_or_none(
    value: Any,
    intent_mode: GoalIntent | str,
) -> dict[str, Any] | None:
    """Validate optional display metadata without making it a core-plan dependency."""

    if value is None:
        return None
    try:
        resolved_intent = (
            intent_mode if isinstance(intent_mode, GoalIntent) else GoalIntent(intent_mode)
        )
        profile = GoalSemanticProfileDraft.model_validate(value)
        validate_semantic_profile_for_intent(profile, resolved_intent)
    except (TypeError, ValueError, ValidationError):
        return None
    return profile.model_dump(mode="json")


def with_sanitized_semantic_profile(payload: Any) -> Any:
    """Copy a plan payload and degrade invalid display vocabulary to its intent baseline."""

    if not isinstance(payload, dict):
        return payload
    navigation = payload.get("navigation")
    if not isinstance(navigation, dict) or navigation.get("semantic_profile") is None:
        return payload
    sanitized = dict(payload)
    sanitized_navigation = dict(navigation)
    sanitized_navigation["semantic_profile"] = semantic_profile_payload_or_none(
        navigation.get("semantic_profile"),
        navigation.get("intent_mode", GoalIntent.LEARN.value),
    )
    sanitized["navigation"] = sanitized_navigation
    return sanitized


class LearningNavigationDraft(StrictModel):
    intent_mode: GoalIntent = GoalIntent.LEARN
    semantic_profile: GoalSemanticProfileDraft | None = None
    goal_title: str = Field(min_length=1, max_length=240)
    target_temp_id: TempId
    target_mastery_level: int = Field(ge=1, le=5)
    success_definition: str = Field(min_length=1, max_length=4000)
    stages: list[LearningStageDraft] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_navigation_content(self) -> LearningNavigationDraft:
        if not self.goal_title.strip() or not self.success_definition.strip():
            raise ValueError("goal_title and success_definition cannot be blank")
        if self.semantic_profile is not None:
            validate_semantic_profile_for_intent(self.semantic_profile, self.intent_mode)
        return self


class LearningPlanDraft(KnowledgeMapDraft):
    navigation: LearningNavigationDraft

    @model_validator(mode="after")
    def validate_navigation_against_graph(self) -> LearningPlanDraft:
        known_nodes = {node.temp_id: node for node in self.nodes}
        target_id = self.navigation.target_temp_id
        if target_id not in known_nodes:
            raise ValueError(f"navigation target references unknown temp_id: {target_id}")
        if known_nodes[target_id].node_type is NodeType.MODULE:
            raise ValueError("navigation target cannot be a MODULE outline node")

        sequences = [stage.sequence for stage in self.navigation.stages]
        expected_sequences = list(range(1, len(self.navigation.stages) + 1))
        if sequences != expected_sequences:
            raise ValueError("learning stage sequence values must be contiguous and ordered from 1")

        stage_by_node: dict[str, int] = {}
        for stage in self.navigation.stages:
            for node_id in stage.node_temp_ids:
                if node_id not in known_nodes:
                    raise ValueError(f"learning stage references unknown temp_id: {node_id}")
                if known_nodes[node_id].node_type is NodeType.MODULE:
                    raise ValueError(
                        "learning stages cannot contain MODULE outline nodes; "
                        f"use their concrete children instead: {node_id}"
                    )
                if node_id in stage_by_node:
                    raise ValueError(f"learning stage node appears more than once: {node_id}")
                stage_by_node[node_id] = stage.sequence

        if target_id not in self.navigation.stages[-1].node_temp_ids:
            raise ValueError("navigation target must appear in the final learning stage")

        prerequisite_graph: nx.DiGraph[str] = nx.DiGraph()
        prerequisite_graph.add_nodes_from(known_nodes)
        prerequisite_edges = [
            edge for edge in self.edges if edge.relation_type is RelationType.PREREQUISITE
        ]
        module_ids = {
            node_id for node_id, node in known_nodes.items() if node.node_type is NodeType.MODULE
        }
        invalid_module_dependencies = [
            f"{edge.source_temp_id}->{edge.target_temp_id}"
            for edge in prerequisite_edges
            if edge.source_temp_id in module_ids or edge.target_temp_id in module_ids
        ]
        if invalid_module_dependencies:
            raise ValueError(
                "MODULE nodes are structural containers and cannot participate in "
                f"PREREQUISITE edges: {invalid_module_dependencies}"
            )

        contains_parents: dict[str, list[str]] = {}
        module_children: dict[str, list[str]] = {module_id: [] for module_id in module_ids}
        for edge in self.edges:
            if edge.relation_type is not RelationType.CONTAINS:
                continue
            if edge.source_temp_id not in module_ids:
                raise ValueError("CONTAINS edges must start at a MODULE outline node")
            if edge.target_temp_id in module_ids:
                raise ValueError("MODULE nodes cannot be nested inside another MODULE")
            contains_parents.setdefault(edge.target_temp_id, []).append(edge.source_temp_id)
            module_children[edge.source_temp_id].append(edge.target_temp_id)
        ungrouped_nodes = sorted(
            node_id
            for node_id, node in known_nodes.items()
            if node.node_type is not NodeType.MODULE and node_id not in contains_parents
        )
        multiply_grouped_nodes = sorted(
            node_id for node_id, parents in contains_parents.items() if len(parents) != 1
        )
        empty_modules = sorted(
            module_id for module_id, child_ids in module_children.items() if not child_ids
        )
        # Saved plans from the earliest schema did not have outline modules at
        # all.  They remain activatable as one implicit group.  Once a plan
        # introduces any MODULE, however, the hierarchy must be complete and
        # unambiguous; partially grouped plans are what caused the three UI
        # projections to disagree.
        if module_ids and (ungrouped_nodes or multiply_grouped_nodes or empty_modules):
            raise ValueError(
                "learning-plan outline must assign every concrete node to exactly one non-empty "
                "MODULE; "
                f"ungrouped={ungrouped_nodes}, multiply_grouped={multiply_grouped_nodes}, "
                f"empty_modules={empty_modules}"
            )

        prerequisite_graph.add_edges_from(
            (edge.source_temp_id, edge.target_temp_id) for edge in prerequisite_edges
        )
        required_route_nodes = {target_id, *nx.ancestors(prerequisite_graph, target_id)}
        missing_ancestors = sorted(
            node_id
            for node_id in required_route_nodes
            if known_nodes[node_id].node_type is not NodeType.MODULE
            and node_id not in stage_by_node
        )
        if missing_ancestors:
            raise ValueError(
                "learning stages must cover all non-module prerequisite ancestors: "
                f"{missing_ancestors}"
            )

        for edge in prerequisite_edges:
            source_stage = stage_by_node.get(edge.source_temp_id)
            target_stage = stage_by_node.get(edge.target_temp_id)
            if (
                source_stage is not None
                and target_stage is not None
                and source_stage > target_stage
            ):
                raise ValueError(
                    "prerequisite stage cannot be later than its dependent: "
                    f"{edge.source_temp_id} -> {edge.target_temp_id}"
                )
        return self


def validate_generated_plan_outline(
    plan: LearningPlanDraft,
    *,
    max_children_per_module: int = 4,
) -> LearningPlanDraft:
    """Apply current outline requirements only to newly generated AI plans.

    Historical plans created before outline modules existed remain readable via
    ``LearningPlanDraft.model_validate``.  Fresh provider output must not use
    that compatibility boundary to create another flat or partially navigable
    framework.
    """

    module_ids = {node.temp_id for node in plan.nodes if node.node_type is NodeType.MODULE}
    if not 3 <= len(module_ids) <= 12:
        raise ValueError("new generated plans must contain between 3 and 12 top-level MODULE nodes")

    module_children: dict[str, list[str]] = {module_id: [] for module_id in module_ids}
    for edge in plan.edges:
        if edge.relation_type is RelationType.CONTAINS and edge.source_temp_id in module_ids:
            module_children[edge.source_temp_id].append(edge.target_temp_id)

    invalid_module_sizes = {
        module_id: len(child_ids)
        for module_id, child_ids in module_children.items()
        if not 1 <= len(child_ids) <= max_children_per_module
    }
    if invalid_module_sizes:
        raise ValueError(
            "every generated MODULE must contain between 1 and "
            f"{max_children_per_module} concrete nodes; "
            f"invalid_modules={invalid_module_sizes}"
        )

    staged_node_ids = {
        node_id for stage in plan.navigation.stages for node_id in stage.node_temp_ids
    }
    modules_missing_from_route = sorted(
        module_id
        for module_id, child_ids in module_children.items()
        if staged_node_ids.isdisjoint(child_ids)
    )
    if modules_missing_from_route:
        raise ValueError(
            "every generated MODULE must contribute at least one concrete node to the route; "
            f"missing_modules={modules_missing_from_route}"
        )
    return plan


_EXPLICIT_OUTLINE_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"第\s*[一二三四五六七八九十百0-9]+\s*(?:阶段|模块)"
    r"|(?:phase|stage|module)\s*[0-9]+"
    r")\s*(?:(?:[:：\-—])\s*(.*))?$",
    re.IGNORECASE,
)
_EXPLICIT_OUTLINE_ITEM = re.compile(r"^[*+-]\s+(.+?)\s*$")


@dataclass(frozen=True)
class ExplicitOutlineSection:
    """One user-authored phase and the concrete items listed inside it."""

    title: str
    items: tuple[str, ...]


def extract_explicit_outline_sections(source_text: str) -> list[ExplicitOutlineSection]:
    """Extract explicit phase/module headings and their bullet items in source order."""

    lines = source_text.splitlines()
    headings: list[tuple[int, re.Match[str]]] = []
    for index, raw_line in enumerate(lines):
        match = _EXPLICIT_OUTLINE_HEADING.fullmatch(raw_line.strip())
        if match is not None:
            headings.append((index, match))

    sections: list[ExplicitOutlineSection] = []
    for heading_index, (line_index, match) in enumerate(headings):
        end_index = (
            headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        )
        body = lines[line_index + 1 : end_index]
        title = (match.group(1) or "").strip()
        if not title:
            for candidate_line in body:
                candidate = candidate_line.strip().lstrip("# ").strip()
                if not candidate or candidate == "---" or candidate in {"包括：", "包括:"}:
                    continue
                if _EXPLICIT_OUTLINE_ITEM.fullmatch(candidate):
                    continue
                title = candidate
                break
        item_lines = body
        for marker_index, candidate_line in enumerate(body):
            marker = candidate_line.strip().rstrip(":：").strip()
            if marker in {"包括", "包含"}:
                item_lines = body[marker_index + 1 :]
                break
        items: list[str] = []
        item_block_started = False
        for candidate_line in item_lines:
            item_match = _EXPLICIT_OUTLINE_ITEM.fullmatch(candidate_line.strip())
            if item_match is None:
                if item_block_started and candidate_line.strip():
                    break
                continue
            item_block_started = True
            item = item_match.group(1).strip()
            if item and item not in items:
                items.append(item[:240])
        if title and all(section.title != title for section in sections):
            sections.append(ExplicitOutlineSection(title=title[:240], items=tuple(items)))
    return sections


def extract_explicit_outline_titles(source_text: str) -> list[str]:
    """Extract user-authored phase/module headings without asking AI to reinterpret them.

    A heading may put its title after the colon or on the next non-empty line.  We only use
    these headings as an authoritative outline when at least three are present; callers can
    therefore safely inspect ordinary prose containing an isolated phrase such as ``阶段 1``.
    """

    return [section.title for section in extract_explicit_outline_sections(source_text)]


def validate_explicit_outline_alignment(
    plan: LearningPlanDraft,
    source_text: str,
) -> LearningPlanDraft:
    """Reject a generated plan that overrides a user's explicit top-level outline.

    The generic scope heuristic is useful when the user gives only a goal.  It must not replace
    a six-phase outline with nine folders, which previously produced empty modules, ungrouped
    content and a route covering only one branch.
    """

    explicit_sections = extract_explicit_outline_sections(source_text)
    explicit_titles = [section.title for section in explicit_sections]
    if not 3 <= len(explicit_sections) <= 12:
        return plan
    generated_modules = [node for node in plan.nodes if node.node_type is NodeType.MODULE]
    if len(generated_modules) != len(explicit_titles):
        raise ValueError(
            "generated MODULE count must match the user's explicit outline: "
            f"expected={len(explicit_titles)}, actual={len(generated_modules)}, "
            f"headings={explicit_titles}"
        )
    generated_titles = [module.title.strip() for module in generated_modules]
    if generated_titles != explicit_titles:
        raise ValueError(
            "generated MODULE titles must preserve the user's explicit outline order and text: "
            f"expected={explicit_titles}, actual={generated_titles}"
        )
    node_by_id = {node.temp_id: node for node in plan.nodes}
    children_by_module: dict[str, list[str]] = {module.temp_id: [] for module in generated_modules}
    for edge in plan.edges:
        if edge.relation_type is RelationType.CONTAINS:
            children_by_module.setdefault(edge.source_temp_id, []).append(edge.target_temp_id)
    missing_explicit_items: dict[str, list[str]] = {}
    for section, module in zip(explicit_sections, generated_modules, strict=True):
        child_titles = {
            node_by_id[child_id].title.strip()
            for child_id in children_by_module.get(module.temp_id, [])
            if child_id in node_by_id
        }
        missing = [item for item in section.items if item not in child_titles]
        if missing:
            missing_explicit_items[section.title] = missing
    if missing_explicit_items:
        raise ValueError(
            "generated outline must preserve every explicit bullet as its own child node: "
            f"missing={missing_explicit_items}"
        )
    content_ids = {node.temp_id for node in plan.nodes if node.node_type is not NodeType.MODULE}
    staged_ids = {node_id for stage in plan.navigation.stages for node_id in stage.node_temp_ids}
    missing_from_route = sorted(content_ids - staged_ids)
    if missing_from_route:
        raise ValueError(
            "every concrete node generated from an explicit outline must appear exactly once "
            f"in the navigation stages; missing={missing_from_route}"
        )
    return plan


class CompactExplicitItemProfileDraft(StrictModel):
    """The only AI-authored attributes needed for one user-locked outline item."""

    item_id: TempId
    node_type: NodeType = NodeType.CONCEPT
    difficulty: int = Field(default=1, ge=1, le=5)
    description: str = Field(min_length=1, max_length=2000)
    detailed_description: str = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def reject_structural_type(self) -> CompactExplicitItemProfileDraft:
        if self.node_type is NodeType.MODULE:
            raise ValueError("explicit outline items cannot be typed as MODULE")
        return self


class CompactExplicitPrerequisiteDraft(StrictModel):
    source_item_id: TempId
    target_item_id: TempId
    reason: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def reject_self_reference(self) -> CompactExplicitPrerequisiteDraft:
        if self.source_item_id == self.target_item_id:
            raise ValueError("compact prerequisite cannot reference itself")
        return self


class CompactExplicitPlanDraft(StrictModel):
    """Small provider response for a detailed outline whose hierarchy is user-authored."""

    goal_title: str = Field(min_length=1, max_length=240)
    success_definition: str = Field(min_length=1, max_length=1000)
    target_item_id: TempId
    item_profiles: list[CompactExplicitItemProfileDraft] = Field(
        min_length=1,
        max_length=100,
    )
    prerequisite_edges: list[CompactExplicitPrerequisiteDraft] = Field(
        default_factory=list,
        max_length=160,
    )


def explicit_outline_item_catalog(
    source_text: str,
) -> tuple[list[ExplicitOutlineSection], list[dict[str, Any]]]:
    """Return the authoritative outline plus stable compact IDs sent to the provider."""

    sections = extract_explicit_outline_sections(source_text)
    catalog: list[dict[str, Any]] = []
    for module_index, section in enumerate(sections, start=1):
        catalog.append(
            {
                "module_id": f"module-{module_index:02d}",
                "module_title": section.title,
                "items": [
                    {"item_id": f"item-{module_index:02d}-{item_index:02d}", "title": title}
                    for item_index, title in enumerate(section.items, start=1)
                ],
            }
        )
    return sections, catalog


def build_compact_explicit_outline_plan(
    source_text: str,
    proposal: CompactExplicitPlanDraft,
) -> LearningPlanDraft:
    """Combine a user-locked hierarchy with a compact AI dependency proposal.

    The outline text owns module and item identity. AI may classify items and propose forward
    prerequisite relationships, but it cannot drop, merge, rename, or relocate them.
    """

    sections, catalog = explicit_outline_item_catalog(source_text)
    if not 3 <= len(sections) <= 12 or any(not section.items for section in sections):
        raise ValueError("compact explicit-outline generation requires 3 to 12 non-empty modules")

    expected_item_ids = {item["item_id"] for module in catalog for item in module["items"]}
    profiles_by_id = {profile.item_id: profile for profile in proposal.item_profiles}
    if set(profiles_by_id) != expected_item_ids:
        raise ValueError(
            "compact item profiles must cover every explicit item exactly once: "
            f"missing={sorted(expected_item_ids - set(profiles_by_id))}, "
            f"unexpected={sorted(set(profiles_by_id) - expected_item_ids)}"
        )

    item_stage: dict[str, int] = {}
    nodes: list[KnowledgeNodeDraft] = []
    edges: list[KnowledgeEdgeDraft] = []
    stages: list[LearningStageDraft] = []
    ordered_item_ids: list[str] = []
    for module_index, (section, module) in enumerate(zip(sections, catalog, strict=True), start=1):
        module_id = str(module["module_id"])
        nodes.append(
            KnowledgeNodeDraft(
                temp_id=module_id,
                title=section.title,
                description=f"{section.title}阶段的结构容器。",
                detailed_description=(
                    f"本模块组织{section.title}相关的核心知识，帮助学习者看清本阶段的"
                    "范围、内部顺序以及与前后阶段的衔接。"
                ),
                node_type=NodeType.MODULE,
                difficulty=min(5, module_index),
                source_basis=["用户提供的长文本大纲"],
                confidence=1.0,
            )
        )
        stage_item_ids: list[str] = []
        for item in module["items"]:
            item_id = str(item["item_id"])
            item_title = str(item["title"])
            profile = profiles_by_id[item_id]
            item_stage[item_id] = module_index
            ordered_item_ids.append(item_id)
            stage_item_ids.append(item_id)
            nodes.append(
                KnowledgeNodeDraft(
                    temp_id=item_id,
                    title=item_title,
                    description=profile.description.strip(),
                    detailed_description=profile.detailed_description.strip(),
                    node_type=profile.node_type,
                    difficulty=profile.difficulty,
                    learning_objectives=[f"能够解释并应用{item_title}。"],
                    source_basis=["用户提供的长文本大纲"],
                    confidence=0.8,
                )
            )
            edges.append(
                KnowledgeEdgeDraft(
                    source_temp_id=module_id,
                    target_temp_id=item_id,
                    relation_type=RelationType.CONTAINS,
                    reason="用户明确指定的阶段归属。",
                    confidence=1.0,
                    required_mastery_level=0,
                )
            )
        stages.append(
            LearningStageDraft(
                sequence=module_index,
                title=section.title,
                objective=f"完成{section.title}的核心知识。",
                node_temp_ids=stage_item_ids,
                completion_criteria=["能够解释并应用本阶段各项知识。"],
            )
        )

    prerequisite_graph: nx.DiGraph[str] = nx.DiGraph()
    prerequisite_graph.add_nodes_from(expected_item_ids)
    accepted_prerequisites: set[tuple[str, str]] = set()

    def accept_prerequisite(source_id: str, target_id: str, reason: str) -> None:
        if (
            source_id not in expected_item_ids
            or target_id not in expected_item_ids
            or source_id == target_id
            or item_stage[source_id] > item_stage[target_id]
            or (source_id, target_id) in accepted_prerequisites
        ):
            return
        prerequisite_graph.add_edge(source_id, target_id)
        if not nx.is_directed_acyclic_graph(prerequisite_graph):
            prerequisite_graph.remove_edge(source_id, target_id)
            return
        accepted_prerequisites.add((source_id, target_id))
        edges.append(
            KnowledgeEdgeDraft(
                source_temp_id=source_id,
                target_temp_id=target_id,
                relation_type=RelationType.PREREQUISITE,
                reason=reason or "建议的前置关系。",
                confidence=0.75,
                required_mastery_level=3,
            )
        )

    # Keep the explicit phase order connected even if the provider omits dependencies.
    for previous_section, current_section in pairwise(catalog):
        previous_items = previous_section["items"]
        current_items = current_section["items"]
        if previous_items and current_items:
            accept_prerequisite(
                str(previous_items[-1]["item_id"]),
                str(current_items[0]["item_id"]),
                "连接相邻的用户指定学习阶段。",
            )
    for edge in proposal.prerequisite_edges:
        accept_prerequisite(edge.source_item_id, edge.target_item_id, edge.reason)

    target_item_id = proposal.target_item_id
    last_stage_ids = stages[-1].node_temp_ids
    if target_item_id not in last_stage_ids:
        target_item_id = last_stage_ids[-1]
    plan = LearningPlanDraft(
        space=KnowledgeSpaceDraft(
            title=proposal.goal_title,
            description=proposal.success_definition,
            target_audience="具有当前描述基础、希望系统建立完整框架的学习者。",
        ),
        nodes=nodes,
        edges=edges,
        navigation=LearningNavigationDraft(
            intent_mode=GoalIntent.LEARN,
            semantic_profile=None,
            goal_title=proposal.goal_title,
            target_temp_id=target_item_id,
            target_mastery_level=3,
            success_definition=proposal.success_definition,
            stages=stages,
        ),
    )
    validate_generated_plan_outline(plan, max_children_per_module=8)
    require_complete_node_explanations(plan)
    return validate_explicit_outline_alignment(plan, source_text)


def require_complete_node_explanations(plan: LearningPlanDraft) -> LearningPlanDraft:
    """Reject provider plans that leave a concrete knowledge point unexplained.

    The base DTO remains backward-compatible for manual drafts and legacy imports. This
    quality gate is applied only at AI-generation boundaries, where an empty explanation
    is an incomplete provider response rather than a valid user-authored draft.
    """

    missing: list[str] = []
    for node in plan.nodes:
        if node.node_type is NodeType.MODULE:
            continue
        fields: list[str] = []
        introduction = node.description.strip()
        explanation = node.detailed_description.strip()
        if not introduction:
            fields.append("description")
        if not explanation:
            fields.append("detailed_description")
        elif introduction and explanation.casefold() == introduction.casefold():
            fields.append("detailed_description_distinct")
        if fields:
            missing.append(f"{node.temp_id}({','.join(fields)})")
    if missing:
        preview = ", ".join(missing[:20])
        suffix = f" and {len(missing) - 20} more" if len(missing) > 20 else ""
        raise ValueError(
            "every concrete AI-generated node requires a non-blank introduction and "
            f"detailed explanation: {preview}{suffix}"
        )
    return plan


class DraftConflict(StrictModel):
    edge: KnowledgeEdgeDraft
    reason: str
    cycle_path: list[str] = Field(default_factory=list)


class AnalyzedKnowledgeMapDraft(StrictModel):
    draft: KnowledgeMapDraft
    accepted_edges: list[KnowledgeEdgeDraft]
    conflicts: list[DraftConflict]


def analyze_draft(draft: KnowledgeMapDraft) -> AnalyzedKnowledgeMapDraft:
    """Partition prerequisite cycles into explicit conflicts without mutating the draft."""

    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(node.temp_id for node in draft.nodes)
    accepted: list[KnowledgeEdgeDraft] = []
    conflicts: list[DraftConflict] = []
    for edge in draft.edges:
        if edge.relation_type is RelationType.PREREQUISITE:
            if nx.has_path(graph, edge.target_temp_id, edge.source_temp_id):
                path = nx.shortest_path(graph, edge.target_temp_id, edge.source_temp_id)
                conflicts.append(
                    DraftConflict(
                        edge=edge,
                        reason="Prerequisite proposal would create a cycle",
                        cycle_path=[*path, edge.target_temp_id],
                    )
                )
                continue
            graph.add_edge(edge.source_temp_id, edge.target_temp_id)
        accepted.append(edge)
    return AnalyzedKnowledgeMapDraft(draft=draft, accepted_edges=accepted, conflicts=conflicts)
