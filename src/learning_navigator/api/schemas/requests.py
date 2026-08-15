"""Strict HTTP input schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from learning_navigator.application.dto.ai import (
    GoalSemanticProfileDraft,
    validate_semantic_profile_for_intent,
)
from learning_navigator.domain.enums import (
    EvidenceType,
    GoalIntent,
    NodeType,
    PathActionKind,
    RelationType,
    RoutePreference,
)
from learning_navigator.domain.services.mastery_dimensions import (
    MasteryDimension,
    MasteryEvidenceKind,
)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(APIModel):
    display_name: str = Field(default="Local learner", min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)


class SpaceCreate(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_audience: str = ""
    scope_included: list[str] = Field(default_factory=list)
    scope_excluded: list[str] = Field(default_factory=list)
    stable_key: str | None = Field(default=None, max_length=160)


class VersionPublishRequest(APIModel):
    change_summary: str = Field(default="Published reviewed knowledge map", max_length=2000)


class VersionRestoreRequest(APIModel):
    change_summary: str = Field(default="Restored historical map as a new draft", max_length=2000)


class NodeCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = ""
    node_type: NodeType = NodeType.CONCEPT
    difficulty: int = Field(default=1, ge=1, le=5)
    depth_level: int = Field(default=0, ge=0)
    learning_objectives: list[str] = Field(default_factory=list)
    source_basis: list[dict[str, Any]] = Field(default_factory=list)
    stable_key: str | None = Field(default=None, max_length=160)


class NodeUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    node_type: NodeType | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    depth_level: int | None = Field(default=None, ge=0)
    learning_objectives: list[str] | None = None
    source_basis: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def require_change(self) -> NodeUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one node field must be supplied")
        null_fields = [field for field in self.model_fields_set if getattr(self, field) is None]
        if null_fields:
            raise ValueError(f"Node fields cannot be null: {', '.join(sorted(null_fields))}")
        return self


class OutlineModuleOrder(APIModel):
    module_id: str = Field(min_length=1)
    node_ids: list[str] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def require_unique_nodes(self) -> OutlineModuleOrder:
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("A module cannot contain the same framework element twice")
        return self


class OutlineOrderUpdate(APIModel):
    """Atomic replacement of the editable framework outline."""

    expected_revision: int = Field(ge=1)
    modules: list[OutlineModuleOrder] = Field(default_factory=list, max_length=200)
    ungrouped_node_ids: list[str] = Field(default_factory=list, max_length=2000)
    # When a project is editing a draft route, the UI can submit the same
    # drag operation as a path order projection.  Keeping this optional
    # preserves framework-only callers while allowing the project view to
    # update both projections atomically.
    path_id: str | None = Field(default=None, min_length=1)
    path_expected_revision: int | None = Field(default=None, ge=1)
    path_step_ids: list[str] | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_unique_membership(self) -> OutlineOrderUpdate:
        module_ids = [item.module_id for item in self.modules]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("Each framework module must appear exactly once")
        node_ids = [node_id for item in self.modules for node_id in item.node_ids]
        node_ids.extend(self.ungrouped_node_ids)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Each framework element must appear exactly once")
        if set(module_ids) & set(node_ids):
            raise ValueError("Framework modules cannot also be module contents")
        path_fields = (self.path_id, self.path_expected_revision, self.path_step_ids)
        if any(value is not None for value in path_fields) and not all(
            value is not None for value in path_fields
        ):
            raise ValueError(
                "path_id, path_expected_revision and path_step_ids must be supplied together"
            )
        if self.path_step_ids is not None and len(self.path_step_ids) != len(
            set(self.path_step_ids)
        ):
            raise ValueError("A synced path cannot contain the same step twice")
        return self


class EdgeCreate(APIModel):
    source_node_id: str
    target_node_id: str
    relation_type: RelationType
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    required_mastery_level: int | None = Field(default=None, ge=0, le=5)
    reason: str = ""
    source_reference: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_requirement(self) -> EdgeCreate:
        if self.relation_type is not RelationType.PREREQUISITE:
            if self.required_mastery_level not in {None, 0}:
                raise ValueError("Only PREREQUISITE edges can set required_mastery_level")
        elif self.required_mastery_level == 0:
            raise ValueError("PREREQUISITE required_mastery_level must be 1 through 5")
        return self


class GoalCreate(APIModel):
    space_id: str
    target_node_id: str
    title: str = Field(min_length=1, max_length=240)
    intent_mode: GoalIntent = GoalIntent.LEARN
    semantic_profile: GoalSemanticProfileDraft | None = None
    target_mastery_level: int = Field(default=3, ge=1, le=5)
    route_preference: RoutePreference = RoutePreference.FOUNDATION_COMPLETE
    deadline: date | None = None
    load_preference: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_display_semantics(self) -> GoalCreate:
        if self.semantic_profile is not None:
            validate_semantic_profile_for_intent(self.semantic_profile, self.intent_mode)
        return self


class ProjectPermanentDeleteRequest(APIModel):
    """Deliberate confirmation required before destroying a trashed project."""

    confirm_title: str = Field(min_length=1, max_length=240)


class PathDraftGenerateRequest(APIModel):
    change_summary: str = Field(default="Generated editable path candidate", max_length=2000)


class PathRevisionCloneRequest(APIModel):
    expected_revision: int = Field(ge=1)
    change_summary: str = Field(default="Editable copy", max_length=2000)


class PathRevisionCheckRequest(APIModel):
    expected_revision: int = Field(ge=1)


class PathStepCreate(APIModel):
    expected_revision: int = Field(ge=1)
    node_id: str
    preferred_order: int = Field(ge=0)
    required_mastery_level: int = Field(default=3, ge=0, le=5)
    recommendation_reason: str = Field(default="Added by user", max_length=4000)
    is_required: bool = True
    action_kind: PathActionKind = PathActionKind.LEARN
    stage: str | None = Field(default=None, max_length=160)
    priority: int = Field(default=50, ge=0, le=100)
    estimated_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    is_pinned: bool = False
    is_deferred: bool = False
    user_note: str | None = Field(default=None, max_length=8000)


class PathStepUpdate(APIModel):
    expected_revision: int = Field(ge=1)
    preferred_order: int | None = Field(default=None, ge=0)
    required_mastery_level: int | None = Field(default=None, ge=0, le=5)
    recommendation_reason: str | None = Field(default=None, max_length=4000)
    is_required: bool | None = None
    action_kind: PathActionKind | None = None
    stage: str | None = Field(default=None, max_length=160)
    priority: int | None = Field(default=None, ge=0, le=100)
    estimated_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    is_pinned: bool | None = None
    is_deferred: bool | None = None
    user_note: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def require_step_change(self) -> PathStepUpdate:
        changed_fields = self.model_fields_set - {"expected_revision"}
        if not changed_fields:
            raise ValueError("At least one path step field must be supplied")
        required_fields = {
            "preferred_order",
            "required_mastery_level",
            "recommendation_reason",
            "is_required",
            "action_kind",
            "priority",
            "is_pinned",
            "is_deferred",
        }
        null_fields = [
            field for field in changed_fields & required_fields if getattr(self, field) is None
        ]
        if null_fields:
            raise ValueError(f"Path step fields cannot be null: {', '.join(sorted(null_fields))}")
        return self


class PathOrderUpdate(APIModel):
    """Atomic total-order replacement for one editable path revision."""

    expected_revision: int = Field(ge=1)
    step_ids: list[str] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_unique_steps(self) -> PathOrderUpdate:
        if len(self.step_ids) != len(set(self.step_ids)):
            raise ValueError("Path order cannot contain duplicate step ids")
        return self


class MasteryUpdateRequest(APIModel):
    update_kind: Literal["self_report", "exercise_result", "manual_review"]
    value: float = Field(ge=0.0, le=5.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verified_score: float | None = Field(default=None, ge=0.0, le=1.0)
    override: bool = False
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_scale(self) -> MasteryUpdateRequest:
        if self.update_kind in {"self_report", "exercise_result"} and self.value > 1:
            raise ValueError(f"{self.update_kind} value must be between 0 and 1")
        if self.update_kind == "manual_review" and not float(self.value).is_integer():
            raise ValueError("manual_review value must be an integer mastery level")
        if self.override and not (self.reason or "").strip():
            raise ValueError("manual override requires a reason")
        return self


class MasteryDimensionMeasurementRequest(APIModel):
    dimension: MasteryDimension
    score: float = Field(ge=0.0, le=100.0)


class MasteryProfileEvidenceRequest(APIModel):
    kind: MasteryEvidenceKind
    measurements: list[MasteryDimensionMeasurementRequest] = Field(min_length=1, max_length=4)
    evidence_confidence: float = Field(default=1.0, gt=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def unique_dimensions(self) -> MasteryProfileEvidenceRequest:
        dimensions = [item.dimension for item in self.measurements]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("measurements must use unique mastery dimensions")
        return self


class EvidenceCreate(APIModel):
    evidence_type: EvidenceType
    title: str | None = Field(default=None, max_length=240)
    content: str | None = None
    artifact_url: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningSessionCreate(APIModel):
    node_id: str
    started_at: datetime
    ended_at: datetime | None = None
    resource_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    difficulties: str | None = None
    self_rating: int | None = Field(default=None, ge=0, le=5)
    next_step: str | None = None
    evidence: list[EvidenceCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_time_window(self) -> LearningSessionCreate:
        if self.ended_at is None:
            return self
        try:
            ends_before_start = self.ended_at < self.started_at
        except TypeError as exc:
            raise ValueError(
                "started_at and ended_at must use compatible timezone information"
            ) from exc
        if ends_before_start:
            raise ValueError("ended_at must not precede started_at")
        return self


class ProgressCheckInCreate(APIModel):
    score: int = Field(ge=1, le=10)
    note: str | None = Field(default=None, max_length=2000)


class ProgressCheckInUpdate(APIModel):
    expected_revision: int = Field(ge=1)
    score: int | None = Field(default=None, ge=1, le=10)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_a_change(self) -> ProgressCheckInUpdate:
        changed_fields = self.model_fields_set - {"expected_revision"}
        if not changed_fields:
            raise ValueError("At least one progress check-in field must be supplied")
        if "score" in changed_fields and self.score is None:
            raise ValueError("Progress check-in score cannot be null")
        return self


class ProgressCheckInReset(APIModel):
    """Concurrency token for explicitly resetting a node's display progress.

    The pair identifies the latest check-in snapshot the caller rendered.  A
    project with no check-in history uses two null values.  Keeping the id in
    addition to the row revision prevents a newly-created row at revision 1
    from being mistaken for the previous latest row at revision 1.
    """

    expected_check_in_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_snapshot(self) -> ProgressCheckInReset:
        has_id = self.expected_check_in_id is not None
        has_revision = self.expected_revision is not None
        if has_id != has_revision:
            raise ValueError("expected_check_in_id and expected_revision must be supplied together")
        return self


class AIGenerateRequest(APIModel):
    source_text: str = Field(min_length=1, max_length=100_000)
    space_id: str | None = None
    provider_profile_id: str | None = None
    confirmed_external_ai: bool = False


class AIMindMapGenerateRequest(APIModel):
    """Request an AI layout/annotation proposal for an existing project map."""

    provider_profile_id: str | None = None
    confirmed_external_ai: bool = False


class AILearningPlanGenerateRequest(APIModel):
    topic: str = Field(min_length=1, max_length=500)
    requirements: str = Field(min_length=1, max_length=8000)
    provider_profile_id: str | None = None
    confirmed_external_ai: bool = False

    @field_validator("topic", "requirements")
    @classmethod
    def strip_and_reject_blank_intent(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("learning-plan intent fields cannot be blank")
        return normalized


class AIProviderProfileCreate(APIModel):
    display_name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=40)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    is_default: bool = True


class AIProviderProfileUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=40)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    clear_api_key: bool = False
    is_default: bool | None = None

    @model_validator(mode="after")
    def key_action_is_unambiguous(self) -> AIProviderProfileUpdate:
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class AIReviewRequest(APIModel):
    action: Literal["accept", "reject", "modify_accept"]
    edited_draft: dict[str, Any] | None = None
    review_note: str | None = None

    @model_validator(mode="after")
    def edited_payload_for_modified_accept(self) -> AIReviewRequest:
        if self.action == "modify_accept" and self.edited_draft is None:
            raise ValueError("modify_accept requires edited_draft")
        return self


class MapImportRequest(APIModel):
    payload: dict[str, Any]
