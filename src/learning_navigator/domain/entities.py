"""Transport- and persistence-independent domain value objects."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from learning_navigator.domain.enums import (
    ComputedNodeStatus,
    GoalIntent,
    NodeType,
    RecordStatus,
    RelationType,
    RoutePreference,
)


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    title: str
    node_type: NodeType = NodeType.CONCEPT
    difficulty: int = 1
    depth_level: int = 0
    status: RecordStatus = RecordStatus.ACTIVE
    description: str = ""
    manually_locked: bool = False

    @property
    def is_active(self) -> bool:
        return self.status is not RecordStatus.ARCHIVED


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: RelationType
    required_mastery_level: int = 0
    is_hard_requirement: bool = False
    strength: float = 1.0
    confidence: float = 1.0
    status: RecordStatus = RecordStatus.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status is not RecordStatus.ARCHIVED


@dataclass(frozen=True, slots=True)
class LearnerSnapshot:
    node_id: str
    mastery_level: int = 0
    mastery_score: float = 0.0
    confidence: float = 0.0
    numeric_evidence_count: int = 0
    last_studied_at: datetime | None = None
    next_review_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Blocker:
    node_id: str
    title: str
    current_level: int
    required_level: int
    status: ComputedNodeStatus


@dataclass(frozen=True, slots=True)
class BlockageExplanation:
    blocked_node_id: str
    blockers: tuple[Blocker, ...]
    recommended_first_node_id: str | None
    dependency_chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteRecommendation:
    node_id: str
    title: str
    required_mastery_level: int
    reason: str
    satisfied_prerequisites: tuple[str, ...]
    unmet_prerequisites: tuple[str, ...]
    unlocks: tuple[str, ...]
    algorithm_version: str
    status: ComputedNodeStatus


@dataclass(frozen=True, slots=True)
class MasteryUpdate:
    mastery_level: int
    mastery_score: float
    confidence: float
    source: str
    manually_overridden: bool
    algorithm_version: str
    next_review_at: datetime | None = None
    audit_details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteRequest:
    target_node_id: str
    intent_mode: GoalIntent = GoalIntent.LEARN
    target_mastery_level: int = 3
    preference: RoutePreference = RoutePreference.FOUNDATION_COMPLETE
    algorithm_version: str = "path-rule-v1"


def utc_now() -> datetime:
    """Return an aware UTC timestamp for domain defaults and comparisons."""

    return datetime.now(UTC)
