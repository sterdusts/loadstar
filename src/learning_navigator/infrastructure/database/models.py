"""Relational persistence models.

Graph topology is stored as ordinary rows. NetworkX objects are built only for a computation
and are never persisted.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from learning_navigator.domain.enums import (
    EvidenceType,
    GoalIntent,
    GoalStatus,
    MasterySource,
    NodeType,
    PathActionKind,
    PathOrigin,
    PathStatus,
    PathStepSource,
    PathValidityStatus,
    RecordStatus,
    RelationType,
    ReviewStatus,
    RoutePreference,
    SuggestionType,
    VersionStatus,
)
from learning_navigator.infrastructure.database.base import Base, IdMixin, TimestampMixin, now_utc


def _enum_default(value: object) -> str:
    return str(getattr(value, "value", value))


class UserModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Local learner")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )


class AIProviderProfileModel(IdMixin, TimestampMixin, Base):
    """A user-owned provider configuration; the API key stays in the OS keyring."""

    __tablename__ = "ai_provider_profiles"
    __table_args__ = (UniqueConstraint("owner_id", "display_name"),)

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    key_last4: Mapped[str | None] = mapped_column(String(4))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KnowledgeSpaceModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_spaces"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    stable_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_included: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    scope_excluded: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("owner_id", "stable_key"),)


class KnowledgeMapVersionModel(IdMixin, Base):
    __tablename__ = "knowledge_map_versions"
    __table_args__ = (
        UniqueConstraint("space_id", "version_number"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("outline_revision >= 1", name="outline_revision_positive"),
    )

    space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VersionStatus.DRAFT.value
    )
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_map_versions.id"))
    schema_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="knowledge-map-v1"
    )
    outline_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class KnowledgeNodeModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("space_id", "stable_key"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint("depth_level >= 0", name="depth_nonnegative"),
    )

    space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=False, index=True
    )
    stable_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    node_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default=NodeType.CONCEPT.value
    )
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    depth_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    manually_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KnowledgeNodeVersionModel(IdMixin, Base):
    __tablename__ = "knowledge_node_versions"
    __table_args__ = (
        UniqueConstraint("node_id", "map_version_id"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint("depth_level >= 0", name="depth_nonnegative"),
        CheckConstraint("outline_order >= 0", name="outline_order_nonnegative"),
    )

    space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    map_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_map_versions.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    depth_level: Mapped[int] = mapped_column(Integer, nullable=False)
    outline_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_basis: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    change_source: Mapped[str] = mapped_column(String(30), nullable=False, default="HUMAN")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class KnowledgeEdgeModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        CheckConstraint("strength BETWEEN 0 AND 1", name="strength_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("required_mastery_level BETWEEN 0 AND 5", name="required_mastery_range"),
        CheckConstraint("source_node_id <> target_node_id", name="no_self_edge"),
        UniqueConstraint(
            "map_version_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
        ),
        CheckConstraint(
            "relation_type = 'PREREQUISITE' OR "
            "(is_hard_requirement = false AND required_mastery_level = 0)",
            name="requirements_only_on_prerequisite",
        ),
    )

    space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=False, index=True
    )
    map_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_map_versions.id"), nullable=False, index=True
    )
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    required_mastery_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_hard_requirement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_reference: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manually_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LearningGoalModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_goals"
    __table_args__ = (
        CheckConstraint("target_mastery_level BETWEEN 0 AND 5", name="target_mastery_range"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    intent_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=GoalIntent.LEARN.value,
        server_default=GoalIntent.LEARN.value,
    )
    semantic_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_mastery_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    route_preference: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RoutePreference.FOUNDATION_COMPLETE.value
    )
    deadline: Mapped[date | None] = mapped_column(Date)
    load_preference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GoalStatus.ACTIVE.value)


class LearningPathModel(IdMixin, Base):
    __tablename__ = "learning_paths"
    __table_args__ = (
        CheckConstraint("generation_number >= 1", name="generation_positive"),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        Index(
            "uq_learning_paths_goal_active",
            "goal_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    goal_id: Mapped[str] = mapped_column(
        ForeignKey("learning_goals.id"), nullable=False, index=True
    )
    space_id: Mapped[str] = mapped_column(ForeignKey("knowledge_spaces.id"), nullable=False)
    map_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_map_versions.id"), nullable=False, index=True
    )
    parent_path_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_paths.id"), nullable=True, index=True
    )
    base_active_path_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_paths.id"), nullable=True, index=True
    )
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PathStatus.ACTIVE.value)
    validity_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PathValidityStatus.VALID.value
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default=PathOrigin.LEGACY.value)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preference_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": row_version,
        "version_id_generator": False,
    }


class LearningPathNodeModel(IdMixin, Base):
    __tablename__ = "learning_path_nodes"
    __table_args__ = (
        UniqueConstraint(
            "path_id",
            "node_id",
            name="uq_learning_path_nodes_path_id",
        ),
        UniqueConstraint(
            "path_id",
            "sequence_number",
            name="uq_learning_path_nodes_path_sequence",
        ),
        CheckConstraint("sequence_number >= 0", name="sequence_nonnegative"),
        CheckConstraint("preferred_order >= 0", name="preferred_order_nonnegative"),
        CheckConstraint("priority BETWEEN 0 AND 100", name="priority_range"),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes >= 0",
            name="estimated_minutes_nonnegative",
        ),
        CheckConstraint("required_mastery_level BETWEEN 0 AND 5", name="required_mastery_range"),
    )

    path_id: Mapped[str] = mapped_column(
        ForeignKey("learning_paths.id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_mastery_level: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    satisfied_prerequisites: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    unmet_prerequisites: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    unlocks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    computed_status: Mapped[str] = mapped_column(String(24), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    action_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PathActionKind.LEARN.value
    )
    stage: Mapped[str | None] = mapped_column(String(160))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_deferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PathStepSource.LEGACY.value
    )


class AIConversationModel(IdMixin, TimestampMixin, Base):
    """A durable, user-owned AI collaboration thread scoped to one framework space."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_valid"),
        CheckConstraint(
            "purpose IN ('PLANNING', 'PAGE_ASSISTANT', 'PROJECT_ASSISTANT')",
            name="purpose_valid",
        ),
        CheckConstraint(
            "purpose = 'PLANNING' OR context_key IS NOT NULL",
            name="assistant_context_key_required",
        ),
        CheckConstraint(
            "purpose != 'PROJECT_ASSISTANT' OR (space_id IS NOT NULL AND goal_id IS NOT NULL)",
            name="project_assistant_scope_required",
        ),
        CheckConstraint(
            "purpose != 'PAGE_ASSISTANT' OR (space_id IS NULL AND goal_id IS NULL)",
            name="page_assistant_scope_forbidden",
        ),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        CheckConstraint(
            "goal_id IS NULL OR space_id IS NOT NULL",
            name="goal_requires_space",
        ),
        CheckConstraint(
            "summary_through_sequence >= 0",
            name="summary_through_sequence_nonnegative",
        ),
        Index(
            "ix_ai_conversations_user_purpose_context",
            "user_id",
            "purpose",
            "context_key",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    space_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=True, index=True
    )
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("learning_goals.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="PLANNING")
    context_key: Mapped[str | None] = mapped_column(String(320), index=True)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Kept as historical metadata rather than an FK so deleting a provider profile does not
    # destroy or block access to a long-lived conversation.
    provider_profile_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_through_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    working_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    final_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    learning_plan_id: Mapped[str | None] = mapped_column(String(64))
    last_context_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": row_version,
        "version_id_generator": False,
    }


class AIConversationMessageModel(IdMixin, Base):
    """An append-only USER, ASSISTANT, or TOOL message."""

    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_ai_conversation_messages_sequence",
        ),
        UniqueConstraint(
            "conversation_id",
            "tool_call_id",
            name="uq_ai_conversation_messages_tool_call",
        ),
        CheckConstraint("sequence_number >= 1", name="sequence_number_positive"),
        CheckConstraint("role IN ('USER', 'ASSISTANT', 'TOOL')", name="role_valid"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    structured_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tool_call_id: Mapped[str | None] = mapped_column(String(100))
    tool_name: Mapped[str | None] = mapped_column(String(80))
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    message_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class LearnerNodeStateModel(IdMixin, Base):
    __tablename__ = "learner_node_states"
    __table_args__ = (
        UniqueConstraint("user_id", "node_id"),
        CheckConstraint("mastery_level BETWEEN 0 AND 5", name="mastery_level_range"),
        CheckConstraint("mastery_score BETWEEN 0 AND 1", name="mastery_score_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("numeric_evidence_count >= 0", name="numeric_evidence_count_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    mastery_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    numeric_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_studied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MasterySource.SELF_REPORT.value
    )
    manually_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    algorithm_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="mastery-rules-v1"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class LearningSessionModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    difficulties: Mapped[str | None] = mapped_column(Text)
    self_rating: Mapped[int | None] = mapped_column(Integer)
    next_step: Mapped[str | None] = mapped_column(Text)


class NodeProgressCheckInModel(IdMixin, TimestampMixin, Base):
    """One user-authored daily progress snapshot for a project node."""

    __tablename__ = "node_progress_check_ins"
    __table_args__ = (
        UniqueConstraint("user_id", "goal_id", "node_id", "check_in_date"),
        CheckConstraint("score BETWEEN 1 AND 10", name="score_range"),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        Index(
            "ix_node_progress_check_ins_scope_date",
            "user_id",
            "goal_id",
            "node_id",
            "check_in_date",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    goal_id: Mapped[str] = mapped_column(
        ForeignKey("learning_goals.id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    ai_evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ai_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": row_version,
        "version_id_generator": False,
    }


class ProgressCheckInAttachmentModel(IdMixin, TimestampMixin, Base):
    """One durable image or file attached to a progress check-in."""

    __tablename__ = "progress_check_in_attachments"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        UniqueConstraint("storage_key"),
        Index(
            "ix_progress_check_in_attachments_owner_check_in",
            "user_id",
            "check_in_id",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    check_in_id: Mapped[str] = mapped_column(
        ForeignKey("node_progress_check_ins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)


class ProgressCheckInClearBatchModel(IdMixin, TimestampMixin, Base):
    """Recoverable snapshot created when a node's progress is cleared.

    Cleared rows are removed from the live check-in tables so every normal
    projection has one unambiguous source of truth.  The opaque local payload
    exists only for an explicit restore operation.
    """

    __tablename__ = "progress_check_in_clear_batches"
    __table_args__ = (
        CheckConstraint("record_count >= 1", name="record_count_positive"),
        CheckConstraint("attachment_count >= 0", name="attachment_count_nonnegative"),
        Index(
            "ix_progress_check_in_clear_batches_scope_time",
            "user_id",
            "goal_id",
            "node_id",
            "cleared_at",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    goal_id: Mapped[str] = mapped_column(
        ForeignKey("learning_goals.id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    cleared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LearningEvidenceModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_evidence"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    artifact_url: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningResourceModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_resources"

    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    uri: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_reference: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class AssessmentModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "assessments"

    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rubric: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecordStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class AssessmentAttemptModel(IdMixin, Base):
    __tablename__ = "assessment_attempts"

    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AISuggestionModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_suggestions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    space_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_spaces.id"), index=True)
    suggestion_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_structured_output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReviewStatus.PENDING.value
    )
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    accepted_changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLogModel(IdMixin, Base):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# Keep enum imports referenced so schema readers and static analyzers can discover the persisted
# vocabulary in one place. Values are stored as strings for SQLite/PostgreSQL portability.
PERSISTED_ENUMS = (
    EvidenceType,
    GoalIntent,
    GoalStatus,
    MasterySource,
    NodeType,
    PathActionKind,
    PathOrigin,
    PathStatus,
    PathStepSource,
    PathValidityStatus,
    RecordStatus,
    RelationType,
    ReviewStatus,
    RoutePreference,
    SuggestionType,
    VersionStatus,
)
