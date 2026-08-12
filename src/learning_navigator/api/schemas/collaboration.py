"""HTTP contracts for durable AI collaboration conversations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from learning_navigator.application.dto.ai import LearningPlanDraft
from learning_navigator.domain.collaboration import ConversationMessageOrigin


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ConversationPurpose = Literal["PLANNING", "PAGE_ASSISTANT", "PROJECT_ASSISTANT"]


class AssistantPageNode(APIModel):
    """One visible node or path step, deliberately smaller than the domain model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    node_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=240)
    status: str | None = Field(default=None, max_length=64)
    path_position: int | None = Field(default=None, ge=1, le=10_000)
    score: int | None = Field(default=None, ge=0, le=10)


class AssistantPathSummary(APIModel):
    model_config = ConfigDict(extra="forbid")

    total: int | None = Field(default=None, ge=0, le=10_000)
    completed: int | None = Field(default=None, ge=0, le=10_000)
    in_progress: int | None = Field(default=None, ge=0, le=10_000)
    not_started: int | None = Field(default=None, ge=0, le=10_000)
    steps: list[AssistantPageNode] = Field(default_factory=list, max_length=40)


class AssistantProgressSummary(APIModel):
    model_config = ConfigDict(extra="forbid")

    percent: int | None = Field(default=None, ge=0, le=100)
    completed: int | None = Field(default=None, ge=0, le=10_000)
    total: int | None = Field(default=None, ge=0, le=10_000)


class AssistantPageState(APIModel):
    """Bounded, structured facts visible on the current page; never raw DOM or form data."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_title: str | None = Field(default=None, max_length=240)
    current_node: AssistantPageNode | None = None
    path_summary: AssistantPathSummary | None = None
    progress_summary: AssistantProgressSummary | None = None


class AssistantPageContext(APIModel):
    """Small, explicitly allow-listed UI context safe to persist and forward."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    page_key: str = Field(min_length=1, max_length=240)
    page_kind: str = Field(min_length=1, max_length=64)
    page_title: str | None = Field(default=None, max_length=240)
    section: str | None = Field(default=None, max_length=160)
    space_id: str | None = Field(default=None, max_length=128)
    goal_id: str | None = Field(default=None, max_length=128)
    node_id: str | None = Field(default=None, max_length=128)
    path_revision_id: str | None = Field(default=None, max_length=128)
    page_state: AssistantPageState | None = None


class ConversationCreateRequest(APIModel):
    title: str = Field(default="新建框架对话", min_length=1, max_length=240)
    space_id: str | None = None
    goal_id: str | None = None
    provider_profile_id: str | None = Field(default=None, max_length=64)
    purpose: ConversationPurpose = "PLANNING"
    context_key: str | None = Field(default=None, min_length=1, max_length=320)
    context_snapshot: AssistantPageContext | None = None

    @model_validator(mode="after")
    def goal_requires_space(self) -> ConversationCreateRequest:
        if self.goal_id is not None and self.space_id is None:
            raise ValueError("goal_id requires space_id")
        if self.purpose == "PAGE_ASSISTANT" and (
            self.context_key is None or not self.context_key.startswith("page:")
        ):
            raise ValueError("PAGE_ASSISTANT requires a page: context_key")
        if self.purpose == "PAGE_ASSISTANT" and (
            self.space_id is not None or self.goal_id is not None
        ):
            raise ValueError("PAGE_ASSISTANT cannot own project scope")
        if self.purpose == "PROJECT_ASSISTANT":
            if self.space_id is None or self.goal_id is None:
                raise ValueError("PROJECT_ASSISTANT requires space_id and goal_id")
            if self.context_key != f"project:{self.goal_id}":
                raise ValueError("PROJECT_ASSISTANT context_key must match its goal_id")
        return self


class ConversationSendRequest(APIModel):
    content: str = Field(min_length=1, max_length=40_000)
    provider_profile_id: str | None = Field(default=None, max_length=64)
    confirmed_external_ai: bool = False
    page_context: AssistantPageContext | None = None
    message_origin: ConversationMessageOrigin = ConversationMessageOrigin.USER_INPUT


class ConversationRevisionRequest(APIModel):
    expected_revision: int = Field(ge=1)


class ConversationPermanentDeleteRequest(ConversationRevisionRequest):
    """Deliberate confirmation before destroying an archived conversation."""

    confirm_title: str = Field(min_length=1, max_length=240)


class ConversationFinalizePlanRequest(ConversationRevisionRequest):
    plan: LearningPlanDraft | None = None
