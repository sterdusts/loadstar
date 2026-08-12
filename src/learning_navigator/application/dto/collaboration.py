"""Strict structured-output contract for project collaboration conversations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from learning_navigator.application.dto.ai import LearningPlanDraft
from learning_navigator.domain.enums import NodeType, PathActionKind, RelationType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapDraftMutationArguments(StrictModel):
    expected_map_version_id: str = Field(min_length=1)


class AddNodeArguments(MapDraftMutationArguments):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=20_000)
    node_type: NodeType = NodeType.CONCEPT
    difficulty: int = Field(default=1, ge=1, le=5)
    depth_level: int = Field(default=0, ge=0)
    learning_objectives: list[str] = Field(default_factory=list, max_length=30)
    source_references: list[str] = Field(default_factory=list, max_length=30)
    stable_key: str | None = Field(default=None, max_length=160)


class UpdateNodeArguments(MapDraftMutationArguments):
    node_id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20_000)
    node_type: NodeType | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    depth_level: int | None = Field(default=None, ge=0)
    learning_objectives: list[str] | None = Field(default=None, max_length=30)
    source_references: list[str] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def require_change(self) -> UpdateNodeArguments:
        if self.model_fields_set <= {"node_id", "expected_map_version_id"}:
            raise ValueError("update_node requires at least one editable field")
        return self


class ArchiveNodeArguments(MapDraftMutationArguments):
    node_id: str = Field(min_length=1)


class AddRelationArguments(MapDraftMutationArguments):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    relation_type: RelationType
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    required_mastery_level: int | None = Field(default=None, ge=0, le=5)
    reason: str = Field(default="", max_length=4000)
    source_references: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_requirement(self) -> AddRelationArguments:
        if self.relation_type is RelationType.PREREQUISITE:
            if self.required_mastery_level == 0:
                raise ValueError("PREREQUISITE mastery level must be 1 through 5")
        elif self.required_mastery_level not in {None, 0}:
            raise ValueError("Only PREREQUISITE can set a mastery level")
        return self


class CreatePathDraftArguments(MapDraftMutationArguments):
    goal_id: str = Field(min_length=1)
    change_summary: str = Field(default="AI-created editable path draft", max_length=2000)


class ClonePathDraftArguments(StrictModel):
    path_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    change_summary: str = Field(default="AI-assisted editable copy", max_length=2000)


class AddPathStepArguments(StrictModel):
    path_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    node_id: str = Field(min_length=1)
    preferred_order: int = Field(ge=0)
    required_mastery_level: int = Field(default=3, ge=0, le=5)
    recommendation_reason: str = Field(default="Suggested in collaboration", max_length=4000)
    is_required: bool = True
    action_kind: PathActionKind = PathActionKind.LEARN
    stage: str | None = Field(default=None, max_length=160)
    priority: int = Field(default=50, ge=0, le=100)
    estimated_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    is_pinned: bool = False
    is_deferred: bool = False
    user_note: str | None = Field(default=None, max_length=8000)


class UpdatePathStepArguments(StrictModel):
    path_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
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
    def require_change(self) -> UpdatePathStepArguments:
        identity = {"path_id", "step_id", "expected_revision"}
        if self.model_fields_set <= identity:
            raise ValueError("update_path_step requires at least one editable field")
        return self


class RemovePathStepArguments(StrictModel):
    path_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)


class ReorderPathStepArguments(RemovePathStepArguments):
    preferred_order: int = Field(ge=0)


class AddNodeToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["add_node"]
    arguments: AddNodeArguments


class UpdateNodeToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["update_node"]
    arguments: UpdateNodeArguments


class ArchiveNodeToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["archive_node"]
    arguments: ArchiveNodeArguments


class AddRelationToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["add_relation"]
    arguments: AddRelationArguments


class CreatePathDraftToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["create_path_draft"]
    arguments: CreatePathDraftArguments


class ClonePathDraftToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["clone_path_draft"]
    arguments: ClonePathDraftArguments


class AddPathStepToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["add_path_step"]
    arguments: AddPathStepArguments


class UpdatePathStepToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["update_path_step"]
    arguments: UpdatePathStepArguments


class RemovePathStepToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["remove_path_step"]
    arguments: RemovePathStepArguments


class ReorderPathStepToolCall(StrictModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    name: Literal["reorder_path_step"]
    arguments: ReorderPathStepArguments


CollaborationToolCall = Annotated[
    AddNodeToolCall
    | UpdateNodeToolCall
    | ArchiveNodeToolCall
    | AddRelationToolCall
    | CreatePathDraftToolCall
    | ClonePathDraftToolCall
    | AddPathStepToolCall
    | UpdatePathStepToolCall
    | RemovePathStepToolCall
    | ReorderPathStepToolCall,
    Field(discriminator="name"),
]


class CollaborationAIResponse(StrictModel):
    message: str = Field(default="", max_length=40_000)
    tool_calls: list[CollaborationToolCall] = Field(default_factory=list, max_length=20)
    working_plan: LearningPlanDraft | None = None
    plan_ready: bool = False
    conversation_summary: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def unique_tool_call_ids(self) -> CollaborationAIResponse:
        call_ids = [call.tool_call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool_call_id values must be unique")
        return self
