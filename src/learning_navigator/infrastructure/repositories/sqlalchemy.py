"""SQLAlchemy repository used by application orchestration.

All queries are space/version scoped so graph rows from separate versions cannot be mixed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from learning_navigator.domain.entities import GraphEdge, GraphNode, LearnerSnapshot
from learning_navigator.domain.enums import (
    GoalIntent,
    GoalStatus,
    NodeType,
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
from learning_navigator.domain.exceptions import (
    EntityNotFoundError,
    InvalidStateTransitionError,
    NodeInActivePathError,
    RevisionConflictError,
)
from learning_navigator.infrastructure.database.models import (
    AIConversationMessageModel,
    AIConversationModel,
    AIProviderProfileModel,
    AISuggestionModel,
    AssessmentAttemptModel,
    AssessmentModel,
    AuditLogModel,
    KnowledgeEdgeModel,
    KnowledgeMapVersionModel,
    KnowledgeNodeModel,
    KnowledgeNodeVersionModel,
    KnowledgeSpaceModel,
    LearnerNodeStateModel,
    LearningEvidenceModel,
    LearningGoalModel,
    LearningPathModel,
    LearningPathNodeModel,
    LearningResourceModel,
    LearningSessionModel,
    NodeProgressCheckInModel,
    UserModel,
)


def stable_key(value: str) -> str:
    """Make a readable stable key while retaining non-Latin letters."""

    normalized = re.sub(r"[^\w.-]+", "-", value.strip().casefold(), flags=re.UNICODE)
    normalized = normalized.strip("-._")
    return normalized[:150] or "item"


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_user(
        self, *, display_name: str = "Local learner", email: str | None = None
    ) -> UserModel:
        query: Select[tuple[UserModel]]
        if email:
            query = select(UserModel).where(UserModel.email == email)
        else:
            query = select(UserModel).order_by(UserModel.created_at).limit(1)
        existing = self.session.scalar(query)
        if existing is not None:
            return existing
        user = UserModel(display_name=display_name, email=email)
        self.session.add(user)
        self.session.flush()
        return user

    def get_user(self, user_id: str) -> UserModel:
        user = self.session.get(UserModel, user_id)
        if user is None or user.status == RecordStatus.ARCHIVED.value:
            raise EntityNotFoundError("user", user_id)
        return user

    def create_ai_provider_profile(self, **values: Any) -> AIProviderProfileModel:
        owner_id = str(values["owner_id"])
        requested_default = bool(values.get("is_default"))
        has_existing = self.session.scalar(
            select(AIProviderProfileModel.id).where(AIProviderProfileModel.owner_id == owner_id)
        )
        if requested_default or has_existing is None:
            self.clear_default_ai_provider_profile(owner_id)
            values["is_default"] = True
        profile = AIProviderProfileModel(**values)
        self.session.add(profile)
        self.session.flush()
        return profile

    def get_ai_provider_profile(self, profile_id: str, *, user_id: str) -> AIProviderProfileModel:
        profile = self.session.get(AIProviderProfileModel, profile_id)
        if profile is None or profile.owner_id != user_id:
            raise EntityNotFoundError("AI provider profile", profile_id)
        return profile

    def list_ai_provider_profiles(self, user_id: str) -> list[AIProviderProfileModel]:
        return list(
            self.session.scalars(
                select(AIProviderProfileModel)
                .where(AIProviderProfileModel.owner_id == user_id)
                .order_by(
                    AIProviderProfileModel.is_default.desc(),
                    AIProviderProfileModel.updated_at.desc(),
                )
            )
        )

    def get_default_ai_provider_profile(self, user_id: str) -> AIProviderProfileModel | None:
        return self.session.scalar(
            select(AIProviderProfileModel)
            .where(
                AIProviderProfileModel.owner_id == user_id,
                AIProviderProfileModel.is_default.is_(True),
            )
            .order_by(AIProviderProfileModel.updated_at.desc())
            .limit(1)
        )

    def clear_default_ai_provider_profile(self, user_id: str) -> None:
        self.session.execute(
            update(AIProviderProfileModel)
            .where(AIProviderProfileModel.owner_id == user_id)
            .values(is_default=False)
        )

    def set_default_ai_provider_profile(
        self, profile: AIProviderProfileModel
    ) -> AIProviderProfileModel:
        self.clear_default_ai_provider_profile(profile.owner_id)
        profile.is_default = True
        self.session.flush()
        return profile

    def count_active_conversations_for_ai_provider_profile(
        self,
        *,
        profile_id: str,
        user_id: str,
    ) -> int:
        """Count live conversations whose next turn would select this profile."""

        return int(
            self.session.scalar(
                select(func.count())
                .select_from(AIConversationModel)
                .where(
                    AIConversationModel.user_id == user_id,
                    AIConversationModel.provider_profile_id == profile_id,
                    AIConversationModel.status == "ACTIVE",
                )
            )
            or 0
        )

    def detach_archived_conversations_from_ai_provider_profile(
        self,
        *,
        profile_id: str,
        user_id: str,
    ) -> int:
        """Make restored historical conversations fall back to a live default profile."""

        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(AIConversationModel)
                .where(
                    AIConversationModel.user_id == user_id,
                    AIConversationModel.provider_profile_id == profile_id,
                    AIConversationModel.status == "ARCHIVED",
                )
                .values(
                    provider_profile_id=None,
                    updated_at=datetime.now().astimezone(),
                    row_version=AIConversationModel.row_version + 1,
                )
            ),
        )
        return int(result.rowcount or 0)

    def delete_ai_provider_profile(self, profile: AIProviderProfileModel) -> None:
        owner_id = profile.owner_id
        was_default = profile.is_default
        self.session.delete(profile)
        self.session.flush()
        if was_default:
            replacement = self.session.scalar(
                select(AIProviderProfileModel)
                .where(AIProviderProfileModel.owner_id == owner_id)
                .order_by(AIProviderProfileModel.updated_at.desc())
                .limit(1)
            )
            if replacement is not None:
                replacement.is_default = True
                self.session.flush()

    def create_space(
        self,
        *,
        user_id: str,
        title: str,
        description: str = "",
        target_audience: str = "",
        scope_included: list[str] | None = None,
        scope_excluded: list[str] | None = None,
        requested_stable_key: str | None = None,
    ) -> tuple[KnowledgeSpaceModel, KnowledgeMapVersionModel]:
        base_key = stable_key(requested_stable_key or title)
        candidate = base_key
        suffix = 2
        while self.session.scalar(
            select(KnowledgeSpaceModel.id).where(
                KnowledgeSpaceModel.owner_id == user_id,
                KnowledgeSpaceModel.stable_key == candidate,
            )
        ):
            candidate = f"{base_key[:140]}-{suffix}"
            suffix += 1
        space = KnowledgeSpaceModel(
            owner_id=user_id,
            stable_key=candidate,
            title=title,
            description=description,
            target_audience=target_audience,
            scope_included=scope_included or [],
            scope_excluded=scope_excluded or [],
            status=RecordStatus.DRAFT.value,
            created_by=user_id,
        )
        self.session.add(space)
        self.session.flush()
        version = KnowledgeMapVersionModel(
            space_id=space.id,
            version_number=1,
            status=VersionStatus.DRAFT.value,
            change_summary="Initial editable map",
            created_by=user_id,
        )
        self.session.add(version)
        self.session.flush()
        self.audit(
            user_id,
            "CREATE_SPACE",
            "KnowledgeSpace",
            space.id,
            after={"title": title, "draft_version_id": version.id},
        )
        return space, version

    def list_spaces(self, user_id: str | None = None) -> list[KnowledgeSpaceModel]:
        query = select(KnowledgeSpaceModel).where(
            KnowledgeSpaceModel.status != RecordStatus.ARCHIVED.value
        )
        if user_id:
            query = query.where(KnowledgeSpaceModel.owner_id == user_id)
        return list(self.session.scalars(query.order_by(KnowledgeSpaceModel.updated_at.desc())))

    def get_space(self, space_id: str, *, user_id: str | None = None) -> KnowledgeSpaceModel:
        space = self.session.get(KnowledgeSpaceModel, space_id)
        if (
            space is None
            or space.status == RecordStatus.ARCHIVED.value
            or (user_id is not None and space.owner_id != user_id)
        ):
            raise EntityNotFoundError("knowledge space", space_id)
        return space

    def get_node_for_user(self, user_id: str, node_id: str) -> KnowledgeNodeModel:
        node = self.session.scalar(
            select(KnowledgeNodeModel)
            .join(KnowledgeSpaceModel, KnowledgeSpaceModel.id == KnowledgeNodeModel.space_id)
            .where(
                KnowledgeNodeModel.id == node_id,
                KnowledgeNodeModel.status != RecordStatus.ARCHIVED.value,
                KnowledgeSpaceModel.owner_id == user_id,
                KnowledgeSpaceModel.status != RecordStatus.ARCHIVED.value,
            )
        )
        if node is None:
            raise EntityNotFoundError("node", node_id)
        return node

    def get_editable_version(self, space_id: str) -> KnowledgeMapVersionModel:
        self.get_space(space_id)
        version = self.session.scalar(
            select(KnowledgeMapVersionModel)
            .where(
                KnowledgeMapVersionModel.space_id == space_id,
                KnowledgeMapVersionModel.status == VersionStatus.DRAFT.value,
            )
            .order_by(KnowledgeMapVersionModel.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise InvalidStateTransitionError(
                f"Knowledge space '{space_id}' has no editable draft version"
            )
        return version

    def get_version(self, space_id: str, version_id: str) -> KnowledgeMapVersionModel:
        version = self.session.get(KnowledgeMapVersionModel, version_id)
        if version is None or version.space_id != space_id:
            raise EntityNotFoundError("knowledge map version", version_id)
        return version

    def list_versions(self, space_id: str) -> list[KnowledgeMapVersionModel]:
        self.get_space(space_id)
        return list(
            self.session.scalars(
                select(KnowledgeMapVersionModel)
                .where(KnowledgeMapVersionModel.space_id == space_id)
                .order_by(KnowledgeMapVersionModel.version_number.desc())
            )
        )

    def publish_editable_version(
        self, *, space_id: str, user_id: str, change_summary: str
    ) -> tuple[KnowledgeMapVersionModel, KnowledgeMapVersionModel]:
        space = self.get_space(space_id, user_id=user_id)
        draft = self.get_editable_version(space_id)
        self.session.execute(
            update(KnowledgeMapVersionModel)
            .where(
                KnowledgeMapVersionModel.space_id == space_id,
                KnowledgeMapVersionModel.status == VersionStatus.PUBLISHED.value,
            )
            .values(status=VersionStatus.SUPERSEDED.value)
        )
        draft.status = VersionStatus.PUBLISHED.value
        draft.change_summary = change_summary
        draft.published_at = datetime.now().astimezone()
        draft.published_by = user_id
        space.status = RecordStatus.ACTIVE.value
        new_draft = self._clone_version(
            source=draft,
            user_id=user_id,
            change_summary=f"Editable draft after version {draft.version_number}",
        )
        self.session.flush()
        return draft, new_draft

    def restore_version_as_draft(
        self,
        *,
        space_id: str,
        source_version_id: str,
        user_id: str,
        change_summary: str,
    ) -> KnowledgeMapVersionModel:
        self.get_space(space_id, user_id=user_id)
        source = self.get_version(space_id, source_version_id)
        current_draft = self.get_editable_version(space_id)
        if current_draft.id == source.id:
            raise InvalidStateTransitionError("The selected version is already the editable draft")
        current_draft.status = VersionStatus.SUPERSEDED.value
        restored = self._clone_version(
            source=source,
            user_id=user_id,
            change_summary=change_summary,
        )
        self.session.flush()
        return restored

    def _clone_version(
        self,
        *,
        source: KnowledgeMapVersionModel,
        user_id: str,
        change_summary: str,
    ) -> KnowledgeMapVersionModel:
        next_number = (
            int(
                self.session.scalar(
                    select(func.max(KnowledgeMapVersionModel.version_number)).where(
                        KnowledgeMapVersionModel.space_id == source.space_id
                    )
                )
                or 0
            )
            + 1
        )
        clone = KnowledgeMapVersionModel(
            space_id=source.space_id,
            version_number=next_number,
            status=VersionStatus.DRAFT.value,
            change_summary=change_summary,
            parent_version_id=source.id,
            schema_version=source.schema_version,
            created_by=user_id,
        )
        self.session.add(clone)
        self.session.flush()
        snapshots = list(
            self.session.scalars(
                select(KnowledgeNodeVersionModel).where(
                    KnowledgeNodeVersionModel.map_version_id == source.id
                )
            )
        )
        for snapshot in snapshots:
            base_node = self.session.get(KnowledgeNodeModel, snapshot.node_id)
            if base_node is None:
                raise EntityNotFoundError("node", snapshot.node_id)
            base_node.title = snapshot.title
            base_node.description = snapshot.description
            base_node.node_type = snapshot.node_type
            base_node.difficulty = snapshot.difficulty
            base_node.depth_level = snapshot.depth_level
            base_node.learning_objectives = list(snapshot.learning_objectives)
            base_node.status = snapshot.status
            self.session.add(
                KnowledgeNodeVersionModel(
                    space_id=source.space_id,
                    node_id=snapshot.node_id,
                    map_version_id=clone.id,
                    title=snapshot.title,
                    description=snapshot.description,
                    node_type=snapshot.node_type,
                    difficulty=snapshot.difficulty,
                    depth_level=snapshot.depth_level,
                    learning_objectives=list(snapshot.learning_objectives),
                    source_basis=list(snapshot.source_basis),
                    status=snapshot.status,
                    change_source=snapshot.change_source,
                    created_by=user_id,
                )
            )
        edges = list(
            self.session.scalars(
                select(KnowledgeEdgeModel).where(KnowledgeEdgeModel.map_version_id == source.id)
            )
        )
        for edge in edges:
            self.session.add(
                KnowledgeEdgeModel(
                    space_id=source.space_id,
                    map_version_id=clone.id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    relation_type=edge.relation_type,
                    strength=edge.strength,
                    confidence=edge.confidence,
                    required_mastery_level=edge.required_mastery_level,
                    is_hard_requirement=edge.is_hard_requirement,
                    status=edge.status,
                    created_by=user_id,
                    source_reference=list(edge.source_reference),
                    reason=edge.reason,
                    manually_locked=edge.manually_locked,
                )
            )
        self.session.flush()
        return clone

    def load_graph(
        self, space_id: str, map_version_id: str | None = None
    ) -> tuple[str, list[GraphNode], list[GraphEdge]]:
        version = (
            self.get_version(space_id, map_version_id)
            if map_version_id
            else self.get_editable_version(space_id)
        )
        rows = self.session.execute(
            select(KnowledgeNodeVersionModel, KnowledgeNodeModel)
            .join(KnowledgeNodeModel, KnowledgeNodeModel.id == KnowledgeNodeVersionModel.node_id)
            .where(KnowledgeNodeVersionModel.map_version_id == version.id)
        ).all()
        nodes = [
            GraphNode(
                id=node_version.node_id,
                title=node_version.title,
                description=node_version.description,
                node_type=NodeType(node_version.node_type),
                difficulty=node_version.difficulty,
                depth_level=node_version.depth_level,
                status=RecordStatus(node_version.status),
                manually_locked=node.manually_locked,
            )
            for node_version, node in rows
        ]
        edge_rows = self.session.scalars(
            select(KnowledgeEdgeModel).where(KnowledgeEdgeModel.map_version_id == version.id)
        )
        edges = [
            GraphEdge(
                id=edge.id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                relation_type=RelationType(edge.relation_type),
                required_mastery_level=edge.required_mastery_level,
                is_hard_requirement=edge.is_hard_requirement,
                strength=edge.strength,
                confidence=edge.confidence,
                status=RecordStatus(edge.status),
            )
            for edge in edge_rows
        ]
        return version.id, nodes, edges

    def create_node(
        self,
        *,
        node_id: str | None = None,
        space_id: str,
        map_version_id: str,
        user_id: str,
        title: str,
        description: str,
        node_type: NodeType,
        difficulty: int,
        depth_level: int,
        learning_objectives: list[str] | None = None,
        source_basis: list[dict[str, Any]] | None = None,
        requested_stable_key: str | None = None,
        change_source: str = "HUMAN",
        manually_locked: bool = True,
    ) -> KnowledgeNodeModel:
        self._require_draft(space_id, map_version_id)
        base_key = stable_key(requested_stable_key or title)
        candidate = base_key
        suffix = 2
        while self.session.scalar(
            select(KnowledgeNodeModel.id).where(
                KnowledgeNodeModel.space_id == space_id,
                KnowledgeNodeModel.stable_key == candidate,
            )
        ):
            candidate = f"{base_key[:140]}-{suffix}"
            suffix += 1
        node_values: dict[str, Any] = {
            "space_id": space_id,
            "stable_key": candidate,
            "title": title,
            "description": description,
            "node_type": node_type.value,
            "difficulty": difficulty,
            "depth_level": depth_level,
            "learning_objectives": learning_objectives or [],
            "status": RecordStatus.DRAFT.value,
            "created_by": user_id,
            "manually_locked": manually_locked,
        }
        if node_id is not None:
            node_values["id"] = node_id
        node = KnowledgeNodeModel(
            **node_values,
        )
        self.session.add(node)
        self.session.flush()
        snapshot = KnowledgeNodeVersionModel(
            space_id=space_id,
            node_id=node.id,
            map_version_id=map_version_id,
            title=title,
            description=description,
            node_type=node_type.value,
            difficulty=difficulty,
            depth_level=depth_level,
            learning_objectives=learning_objectives or [],
            source_basis=source_basis or [],
            status=RecordStatus.ACTIVE.value,
            change_source=change_source,
            created_by=user_id,
        )
        self.session.add(snapshot)
        self.session.flush()
        return node

    def update_node(
        self,
        *,
        space_id: str,
        map_version_id: str,
        node_id: str,
        user_id: str,
        changes: dict[str, Any],
        change_source: str = "HUMAN",
    ) -> KnowledgeNodeVersionModel:
        self._require_draft(space_id, map_version_id)
        node = self._get_node(space_id, node_id)
        snapshot = self.session.scalar(
            select(KnowledgeNodeVersionModel).where(
                KnowledgeNodeVersionModel.node_id == node_id,
                KnowledgeNodeVersionModel.map_version_id == map_version_id,
            )
        )
        if snapshot is None:
            raise EntityNotFoundError("node version", node_id)
        allowed = {
            "title",
            "description",
            "node_type",
            "difficulty",
            "depth_level",
            "learning_objectives",
            "source_basis",
            "status",
        }
        for key, value in changes.items():
            if key not in allowed:
                raise ValueError(f"Unsupported node field: {key}")
            if key == "node_type" and isinstance(value, NodeType):
                value = value.value
            setattr(snapshot, key, value)
            if hasattr(node, key) and key not in {"source_basis"}:
                setattr(node, key, value)
        snapshot.change_source = change_source
        if change_source == "HUMAN":
            node.manually_locked = True
        self.session.flush()
        return snapshot

    def archive_node(
        self, *, space_id: str, map_version_id: str, node_id: str, user_id: str
    ) -> None:
        active_path_count, project_count = self.active_path_reference_counts_for_node(
            node_id=node_id,
            user_id=user_id,
        )
        if active_path_count:
            raise NodeInActivePathError(
                active_path_count=active_path_count,
                project_count=project_count,
            )
        self.update_node(
            space_id=space_id,
            map_version_id=map_version_id,
            node_id=node_id,
            user_id=user_id,
            changes={"status": RecordStatus.ARCHIVED.value},
        )
        self.session.execute(
            update(KnowledgeEdgeModel)
            .where(
                KnowledgeEdgeModel.map_version_id == map_version_id,
                (KnowledgeEdgeModel.source_node_id == node_id)
                | (KnowledgeEdgeModel.target_node_id == node_id),
            )
            .values(status=RecordStatus.ARCHIVED.value)
        )

    def active_path_reference_counts_for_node(
        self,
        *,
        node_id: str,
        user_id: str,
    ) -> tuple[int, int]:
        """Count only live path references owned by the requesting user.

        Completed/superseded path revisions are historical snapshots. Likewise,
        projects in the trash must not prevent maintenance of their former map.
        """

        result = self.session.execute(
            select(
                func.count(func.distinct(LearningPathModel.id)),
                func.count(func.distinct(LearningGoalModel.id)),
            )
            .select_from(LearningPathNodeModel)
            .join(LearningPathModel, LearningPathModel.id == LearningPathNodeModel.path_id)
            .join(LearningGoalModel, LearningGoalModel.id == LearningPathModel.goal_id)
            .where(
                LearningPathNodeModel.node_id == node_id,
                LearningGoalModel.user_id == user_id,
                LearningGoalModel.status != GoalStatus.ARCHIVED.value,
                LearningPathModel.status.in_((PathStatus.ACTIVE.value, PathStatus.DRAFT.value)),
            )
        ).one()
        return int(result[0] or 0), int(result[1] or 0)

    def upsert_edge(
        self,
        *,
        space_id: str,
        map_version_id: str,
        user_id: str,
        edge: GraphEdge,
        reason: str = "",
        source_reference: list[dict[str, Any]] | None = None,
        manually_locked: bool = True,
    ) -> KnowledgeEdgeModel:
        self._require_draft(space_id, map_version_id)
        existing = self.session.scalar(
            select(KnowledgeEdgeModel).where(
                KnowledgeEdgeModel.map_version_id == map_version_id,
                KnowledgeEdgeModel.source_node_id == edge.source_node_id,
                KnowledgeEdgeModel.target_node_id == edge.target_node_id,
                KnowledgeEdgeModel.relation_type == edge.relation_type.value,
            )
        )
        if existing is not None:
            existing.status = RecordStatus.ACTIVE.value
            existing.strength = edge.strength
            existing.confidence = edge.confidence
            existing.required_mastery_level = edge.required_mastery_level
            existing.is_hard_requirement = edge.is_hard_requirement
            existing.reason = reason
            existing.source_reference = source_reference or []
            existing.manually_locked = existing.manually_locked or manually_locked
            self.session.flush()
            return existing
        row = KnowledgeEdgeModel(
            id=edge.id,
            space_id=space_id,
            map_version_id=map_version_id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            relation_type=edge.relation_type.value,
            strength=edge.strength,
            confidence=edge.confidence,
            required_mastery_level=edge.required_mastery_level,
            is_hard_requirement=edge.is_hard_requirement,
            status=RecordStatus.ACTIVE.value,
            created_by=user_id,
            source_reference=source_reference or [],
            reason=reason,
            manually_locked=manually_locked,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def archive_edge(self, *, map_version_id: str, edge_id: str) -> KnowledgeEdgeModel:
        edge = self.session.get(KnowledgeEdgeModel, edge_id)
        if edge is None or edge.map_version_id != map_version_id:
            raise EntityNotFoundError("edge", edge_id)
        edge.status = RecordStatus.ARCHIVED.value
        self.session.flush()
        return edge

    def get_mastery(self, user_id: str, node_ids: set[str]) -> dict[str, LearnerSnapshot]:
        if not node_ids:
            return {}
        rows = self.session.scalars(
            select(LearnerNodeStateModel).where(
                LearnerNodeStateModel.user_id == user_id,
                LearnerNodeStateModel.node_id.in_(node_ids),
            )
        )
        return {
            row.node_id: LearnerSnapshot(
                node_id=row.node_id,
                mastery_level=row.mastery_level,
                mastery_score=row.mastery_score,
                confidence=row.confidence,
                numeric_evidence_count=row.numeric_evidence_count,
                last_studied_at=row.last_studied_at,
                next_review_at=row.next_review_at,
            )
            for row in rows
        }

    def get_state(self, user_id: str, node_id: str) -> LearnerNodeStateModel | None:
        return self.session.scalar(
            select(LearnerNodeStateModel).where(
                LearnerNodeStateModel.user_id == user_id,
                LearnerNodeStateModel.node_id == node_id,
            )
        )

    def save_state(
        self, user_id: str, node_id: str, values: dict[str, Any]
    ) -> LearnerNodeStateModel:
        row = self.get_state(user_id, node_id)
        if row is None:
            row = LearnerNodeStateModel(user_id=user_id, node_id=node_id)
            self.session.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        self.session.flush()
        return row

    def create_goal(
        self,
        *,
        user_id: str,
        space_id: str,
        target_node_id: str,
        title: str,
        target_mastery_level: int,
        route_preference: RoutePreference,
        intent_mode: GoalIntent = GoalIntent.LEARN,
        semantic_profile: dict[str, Any] | None = None,
        deadline: Any = None,
        load_preference: str | None = None,
    ) -> LearningGoalModel:
        self._get_node(space_id, target_node_id)
        goal = LearningGoalModel(
            user_id=user_id,
            space_id=space_id,
            target_node_id=target_node_id,
            title=title,
            intent_mode=intent_mode.value,
            semantic_profile=semantic_profile,
            target_mastery_level=target_mastery_level,
            route_preference=route_preference.value,
            deadline=deadline,
            load_preference=load_preference,
            status=GoalStatus.ACTIVE.value,
        )
        self.session.add(goal)
        self.session.flush()
        return goal

    def get_goal(
        self,
        goal_id: str,
        *,
        user_id: str | None = None,
        include_archived: bool = False,
    ) -> LearningGoalModel:
        goal = self.session.get(LearningGoalModel, goal_id)
        if (
            goal is None
            or (user_id is not None and goal.user_id != user_id)
            or (not include_archived and goal.status == GoalStatus.ARCHIVED.value)
        ):
            raise EntityNotFoundError("learning goal", goal_id)
        return goal

    def archive_goal(
        self,
        goal_id: str,
        *,
        user_id: str,
    ) -> tuple[LearningGoalModel, bool, list[str]]:
        """Soft-delete one user-owned project without touching its shared framework."""

        goal = self.get_goal(goal_id, user_id=user_id, include_archived=True)
        if goal.status == GoalStatus.ARCHIVED.value:
            return goal, False, []
        conversations = list(
            self.session.scalars(
                select(AIConversationModel).where(
                    AIConversationModel.user_id == user_id,
                    AIConversationModel.goal_id == goal_id,
                    AIConversationModel.status == GoalStatus.ACTIVE.value,
                )
            )
        )
        archived_at = datetime.now().astimezone()
        for conversation in conversations:
            conversation.status = GoalStatus.ARCHIVED.value
            conversation.archived_at = archived_at
            conversation.updated_at = archived_at
            conversation.row_version += 1
        goal.status = GoalStatus.ARCHIVED.value
        goal.updated_at = archived_at
        self.session.flush()
        return goal, True, [conversation.id for conversation in conversations]

    def latest_project_archive_conversation_ids(
        self,
        *,
        goal_id: str,
        user_id: str,
    ) -> list[str]:
        """Read the latest lifecycle audit so restore never revives unrelated archived chats."""

        audit = self.session.scalar(
            select(AuditLogModel)
            .where(
                AuditLogModel.actor_user_id == user_id,
                AuditLogModel.action == "ARCHIVE_PROJECT",
                AuditLogModel.entity_type == "LearningGoal",
                AuditLogModel.entity_id == goal_id,
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .limit(1)
        )
        if audit is None:
            return []
        raw_ids = audit.details.get("auto_archived_conversation_ids", [])
        if not isinstance(raw_ids, list):
            return []
        return [item for item in raw_ids if isinstance(item, str)]

    def restore_goal(
        self,
        goal_id: str,
        *,
        user_id: str,
        conversation_ids: list[str],
    ) -> tuple[LearningGoalModel, bool, list[str]]:
        """Restore one trashed project and its lifecycle-owned conversation state."""

        goal = self.get_goal(goal_id, user_id=user_id, include_archived=True)
        if goal.status != GoalStatus.ARCHIVED.value:
            return goal, False, []
        restored_at = datetime.now().astimezone()
        conversations = (
            list(
                self.session.scalars(
                    select(AIConversationModel).where(
                        AIConversationModel.id.in_(conversation_ids),
                        AIConversationModel.user_id == user_id,
                        AIConversationModel.goal_id == goal_id,
                        AIConversationModel.status == GoalStatus.ARCHIVED.value,
                    )
                )
            )
            if conversation_ids
            else []
        )
        for conversation in conversations:
            conversation.status = GoalStatus.ACTIVE.value
            conversation.archived_at = None
            conversation.updated_at = restored_at
            conversation.row_version += 1
        goal.status = GoalStatus.ACTIVE.value
        goal.updated_at = restored_at
        self.session.flush()
        return goal, True, [conversation.id for conversation in conversations]

    def delete_goal_permanently(self, goal_id: str, *, user_id: str) -> dict[str, Any]:
        """Permanently delete one project without crossing its ownership boundary.

        Paths, check-ins and goal-scoped conversations belong to the goal and are
        always removed.  A knowledge space is reclaimed only when no other goal
        or independently useful node/space record still references it.
        """

        goal = self.get_goal(goal_id, user_id=user_id, include_archived=True)
        if goal.status != GoalStatus.ARCHIVED.value:
            raise InvalidStateTransitionError(
                "Only a project in the trash can be permanently deleted"
            )
        space_id = goal.space_id

        path_ids = list(
            self.session.scalars(
                select(LearningPathModel.id).where(LearningPathModel.goal_id == goal_id)
            )
        )
        path_node_ids = (
            list(
                self.session.scalars(
                    select(LearningPathNodeModel.id).where(
                        LearningPathNodeModel.path_id.in_(path_ids)
                    )
                )
            )
            if path_ids
            else []
        )
        check_in_ids = list(
            self.session.scalars(
                select(NodeProgressCheckInModel.id).where(
                    NodeProgressCheckInModel.goal_id == goal_id
                )
            )
        )
        conversation_ids = list(
            self.session.scalars(
                select(AIConversationModel.id).where(
                    AIConversationModel.user_id == user_id,
                    AIConversationModel.goal_id == goal_id,
                )
            )
        )
        message_ids = (
            list(
                self.session.scalars(
                    select(AIConversationMessageModel.id).where(
                        AIConversationMessageModel.conversation_id.in_(conversation_ids)
                    )
                )
            )
            if conversation_ids
            else []
        )

        project_suggestions = list(
            self.session.scalars(
                select(AISuggestionModel).where(AISuggestionModel.user_id == user_id)
            )
        )
        suggestion_ids = [
            row.id
            for row in project_suggestions
            if row.target_id == goal_id
            or _json_contains_value(row.raw_structured_output, goal_id)
            or _json_contains_value(row.proposed_changes, goal_id)
            or _json_contains_value(row.accepted_changes, goal_id)
        ]

        project_row_ids = {
            goal_id,
            *path_ids,
            *path_node_ids,
            *check_in_ids,
            *conversation_ids,
            *message_ids,
            *suggestion_ids,
        }
        self._redact_deleted_project_audits(
            user_id=user_id,
            goal_id=goal_id,
            deleted_ids=project_row_ids,
        )

        if message_ids:
            self.session.execute(
                delete(AIConversationMessageModel).where(
                    AIConversationMessageModel.id.in_(message_ids)
                )
            )
        if conversation_ids:
            self.session.execute(
                delete(AIConversationModel).where(AIConversationModel.id.in_(conversation_ids))
            )
        if path_node_ids:
            self.session.execute(
                delete(LearningPathNodeModel).where(LearningPathNodeModel.id.in_(path_node_ids))
            )
        if path_ids:
            # Defensive detachment also preserves an anomalous surviving path
            # that was linked to a revision owned by the deleted project.
            self.session.execute(
                update(LearningPathModel)
                .where(LearningPathModel.parent_path_id.in_(path_ids))
                .values(parent_path_id=None)
            )
            self.session.execute(
                update(LearningPathModel)
                .where(LearningPathModel.base_active_path_id.in_(path_ids))
                .values(base_active_path_id=None)
            )
            self.session.execute(
                delete(LearningPathModel).where(LearningPathModel.id.in_(path_ids))
            )
        if check_in_ids:
            self.session.execute(
                delete(NodeProgressCheckInModel).where(
                    NodeProgressCheckInModel.id.in_(check_in_ids)
                )
            )
        if suggestion_ids:
            self.session.execute(
                delete(AISuggestionModel).where(AISuggestionModel.id.in_(suggestion_ids))
            )
        self.session.delete(goal)
        self.session.flush()

        framework_deleted = self._delete_unreferenced_space(
            space_id=space_id,
            user_id=user_id,
        )
        self.session.flush()
        return {
            "path_count": len(path_ids),
            "path_node_count": len(path_node_ids),
            "check_in_count": len(check_in_ids),
            "conversation_count": len(conversation_ids),
            "message_count": len(message_ids),
            "suggestion_count": len(suggestion_ids),
            "framework_deleted": framework_deleted,
        }

    def _delete_unreferenced_space(self, *, space_id: str, user_id: str) -> bool:
        """Delete a framework only when no independent persisted reference remains."""

        space = self.session.get(KnowledgeSpaceModel, space_id)
        if space is None:
            return False
        if space.owner_id != user_id:
            return False
        if self.session.scalar(
            select(LearningGoalModel.id).where(LearningGoalModel.space_id == space_id).limit(1)
        ):
            return False
        node_ids = list(
            self.session.scalars(
                select(KnowledgeNodeModel.id).where(KnowledgeNodeModel.space_id == space_id)
            )
        )
        if node_ids and self._nodes_are_referenced_by_another_project(node_ids):
            return False

        conversation_ids = list(
            self.session.scalars(
                select(AIConversationModel.id).where(AIConversationModel.space_id == space_id)
            )
        )
        message_ids = (
            list(
                self.session.scalars(
                    select(AIConversationMessageModel.id).where(
                        AIConversationMessageModel.conversation_id.in_(conversation_ids)
                    )
                )
            )
            if conversation_ids
            else []
        )
        suggestion_ids = list(
            self.session.scalars(
                select(AISuggestionModel.id).where(AISuggestionModel.space_id == space_id)
            )
        )
        state_ids = (
            list(
                self.session.scalars(
                    select(LearnerNodeStateModel.id).where(
                        LearnerNodeStateModel.node_id.in_(node_ids)
                    )
                )
            )
            if node_ids
            else []
        )
        session_ids = (
            list(
                self.session.scalars(
                    select(LearningSessionModel.id).where(
                        LearningSessionModel.node_id.in_(node_ids)
                    )
                )
            )
            if node_ids
            else []
        )
        evidence_ids = (
            list(
                self.session.scalars(
                    select(LearningEvidenceModel.id).where(
                        or_(
                            LearningEvidenceModel.node_id.in_(node_ids),
                            LearningEvidenceModel.session_id.in_(session_ids),
                        )
                    )
                )
            )
            if node_ids
            else []
        )
        resource_ids = (
            list(
                self.session.scalars(
                    select(LearningResourceModel.id).where(
                        LearningResourceModel.node_id.in_(node_ids)
                    )
                )
            )
            if node_ids
            else []
        )
        assessment_ids = (
            list(
                self.session.scalars(
                    select(AssessmentModel.id).where(AssessmentModel.node_id.in_(node_ids))
                )
            )
            if node_ids
            else []
        )
        attempt_ids = (
            list(
                self.session.scalars(
                    select(AssessmentAttemptModel.id).where(
                        AssessmentAttemptModel.assessment_id.in_(assessment_ids)
                    )
                )
            )
            if assessment_ids
            else []
        )

        version_ids = list(
            self.session.scalars(
                select(KnowledgeMapVersionModel.id).where(
                    KnowledgeMapVersionModel.space_id == space_id
                )
            )
        )
        edge_ids = list(
            self.session.scalars(
                select(KnowledgeEdgeModel.id).where(KnowledgeEdgeModel.space_id == space_id)
            )
        )
        node_version_ids = list(
            self.session.scalars(
                select(KnowledgeNodeVersionModel.id).where(
                    KnowledgeNodeVersionModel.space_id == space_id
                )
            )
        )
        core_framework_ids = {
            space_id,
            *node_ids,
            *version_ids,
            *edge_ids,
            *node_version_ids,
        }
        suggestions = list(
            self.session.scalars(
                select(AISuggestionModel).where(AISuggestionModel.user_id == user_id)
            )
        )
        suggestion_ids = list(
            {
                *suggestion_ids,
                *(
                    row.id
                    for row in suggestions
                    if row.target_id in core_framework_ids
                    or any(
                        _json_contains_value(payload, row_id)
                        for payload in (
                            row.raw_structured_output,
                            row.proposed_changes,
                            row.accepted_changes,
                        )
                        for row_id in core_framework_ids
                    )
                ),
            }
        )
        framework_ids = {
            *core_framework_ids,
            *conversation_ids,
            *message_ids,
            *suggestion_ids,
            *state_ids,
            *session_ids,
            *evidence_ids,
            *resource_ids,
            *assessment_ids,
            *attempt_ids,
        }
        self._redact_deleted_project_audits(
            user_id=user_id,
            goal_id=None,
            deleted_ids=framework_ids,
        )

        if message_ids:
            self.session.execute(
                delete(AIConversationMessageModel).where(
                    AIConversationMessageModel.id.in_(message_ids)
                )
            )
        if conversation_ids:
            self.session.execute(
                delete(AIConversationModel).where(AIConversationModel.id.in_(conversation_ids))
            )
        if suggestion_ids:
            self.session.execute(
                delete(AISuggestionModel).where(AISuggestionModel.id.in_(suggestion_ids))
            )
        if attempt_ids:
            self.session.execute(
                delete(AssessmentAttemptModel).where(AssessmentAttemptModel.id.in_(attempt_ids))
            )
        if evidence_ids:
            self.session.execute(
                delete(LearningEvidenceModel).where(LearningEvidenceModel.id.in_(evidence_ids))
            )
        if assessment_ids:
            self.session.execute(
                delete(AssessmentModel).where(AssessmentModel.id.in_(assessment_ids))
            )
        if resource_ids:
            self.session.execute(
                delete(LearningResourceModel).where(LearningResourceModel.id.in_(resource_ids))
            )
        if state_ids:
            self.session.execute(
                delete(LearnerNodeStateModel).where(LearnerNodeStateModel.id.in_(state_ids))
            )
        if session_ids:
            self.session.execute(
                delete(LearningSessionModel).where(LearningSessionModel.id.in_(session_ids))
            )
        if edge_ids:
            self.session.execute(
                delete(KnowledgeEdgeModel).where(KnowledgeEdgeModel.id.in_(edge_ids))
            )
        if node_version_ids:
            self.session.execute(
                delete(KnowledgeNodeVersionModel).where(
                    KnowledgeNodeVersionModel.id.in_(node_version_ids)
                )
            )
        if version_ids:
            self.session.execute(
                update(KnowledgeMapVersionModel)
                .where(KnowledgeMapVersionModel.parent_version_id.in_(version_ids))
                .values(parent_version_id=None)
            )
        if node_ids:
            self.session.execute(
                delete(KnowledgeNodeModel).where(KnowledgeNodeModel.id.in_(node_ids))
            )
        if version_ids:
            self.session.execute(
                delete(KnowledgeMapVersionModel).where(KnowledgeMapVersionModel.id.in_(version_ids))
            )
        self.session.delete(space)
        return True

    def _nodes_are_referenced_by_another_project(self, node_ids: list[str]) -> bool:
        """Fail closed for malformed cross-space project references."""

        checks = (
            select(LearningGoalModel.id).where(LearningGoalModel.target_node_id.in_(node_ids)),
            select(LearningPathNodeModel.id).where(LearningPathNodeModel.node_id.in_(node_ids)),
            select(NodeProgressCheckInModel.id).where(
                NodeProgressCheckInModel.node_id.in_(node_ids)
            ),
            select(KnowledgeNodeVersionModel.id).where(
                KnowledgeNodeVersionModel.node_id.in_(node_ids),
                KnowledgeNodeVersionModel.space_id.not_in(
                    select(KnowledgeNodeModel.space_id).where(KnowledgeNodeModel.id.in_(node_ids))
                ),
            ),
            select(KnowledgeEdgeModel.id).where(
                or_(
                    KnowledgeEdgeModel.source_node_id.in_(node_ids),
                    KnowledgeEdgeModel.target_node_id.in_(node_ids),
                ),
                KnowledgeEdgeModel.space_id.not_in(
                    select(KnowledgeNodeModel.space_id).where(KnowledgeNodeModel.id.in_(node_ids))
                ),
            ),
        )
        return any(self.session.scalar(query.limit(1)) is not None for query in checks)

    def _redact_deleted_project_audits(
        self,
        *,
        user_id: str,
        goal_id: str | None,
        deleted_ids: set[str],
    ) -> None:
        if not deleted_ids and goal_id is None:
            return
        rows = list(
            self.session.scalars(
                select(AuditLogModel).where(AuditLogModel.actor_user_id == user_id)
            )
        )
        for row in rows:
            references_deleted_row = row.entity_id in deleted_ids
            references_goal = goal_id is not None and (
                _json_contains_value(row.before_state, goal_id)
                or _json_contains_value(row.after_state, goal_id)
                or _json_contains_value(row.details, goal_id)
            )
            if not references_deleted_row and not references_goal:
                continue
            row.before_state = None
            row.after_state = None
            row.details = {
                "redacted": True,
                "reason": "PROJECT_PERMANENTLY_DELETED",
            }

    def mark_goal_current(self, goal_id: str, *, user_id: str) -> LearningGoalModel:
        """Make an existing long-term goal the dashboard's current navigation context."""

        goal = self.get_goal(goal_id, user_id=user_id)
        goal.status = GoalStatus.ACTIVE.value
        goal.updated_at = datetime.now().astimezone()
        self.session.flush()
        return goal

    def list_goals(self, user_id: str, *, active_only: bool = False) -> list[LearningGoalModel]:
        query = select(LearningGoalModel).where(LearningGoalModel.user_id == user_id)
        if active_only:
            query = query.where(LearningGoalModel.status == GoalStatus.ACTIVE.value)
        return list(
            self.session.scalars(
                query.order_by(
                    LearningGoalModel.updated_at.desc(),
                    LearningGoalModel.id.desc(),
                )
            )
        )

    def _active_path_for_goal(self, goal_id: str) -> LearningPathModel | None:
        return self.session.scalar(
            select(LearningPathModel)
            .where(
                LearningPathModel.goal_id == goal_id,
                LearningPathModel.status == PathStatus.ACTIVE.value,
            )
            .order_by(LearningPathModel.generation_number.desc())
            .limit(1)
        )

    def _next_path_generation(self, goal_id: str) -> int:
        return (
            int(
                self.session.scalar(
                    select(func.max(LearningPathModel.generation_number)).where(
                        LearningPathModel.goal_id == goal_id
                    )
                )
                or 0
            )
            + 1
        )

    def create_path_revision(
        self,
        *,
        goal: LearningGoalModel,
        map_version_id: str,
        algorithm_version: str,
        recommendations: list[dict[str, Any]],
        activate: bool,
        origin: PathOrigin,
        parent_path_id: str | None = None,
        change_summary: str = "",
    ) -> LearningPathModel:
        active_path = self._active_path_for_goal(goal.id)
        now = datetime.now().astimezone()
        if activate and active_path is not None:
            active_path.status = PathStatus.SUPERSEDED.value
            active_path.superseded_at = now
            active_path.row_version += 1
            # Release the database-level single-active slot before inserting the
            # replacement. SQLAlchemy is otherwise free to INSERT first.
            self.session.flush()
        path = LearningPathModel(
            goal_id=goal.id,
            space_id=goal.space_id,
            map_version_id=map_version_id,
            parent_path_id=parent_path_id or (active_path.id if active_path is not None else None),
            base_active_path_id=active_path.id if active_path is not None else None,
            generation_number=self._next_path_generation(goal.id),
            algorithm_version=algorithm_version,
            status=PathStatus.ACTIVE.value if activate else PathStatus.DRAFT.value,
            validity_status=PathValidityStatus.VALID.value,
            origin=origin.value,
            row_version=1,
            change_summary=change_summary,
            preference_snapshot={
                "route_preference": goal.route_preference,
                "intent_mode": goal.intent_mode,
            },
            activated_at=now if activate else None,
        )
        self.session.add(path)
        self.session.flush()
        step_source = {
            PathOrigin.AI_GENERATED: PathStepSource.AI_GENERATED,
            PathOrigin.ALGORITHM_GENERATED: PathStepSource.ALGORITHM_GENERATED,
        }.get(origin, PathStepSource.LEGACY)
        for index, recommendation in enumerate(recommendations):
            self.session.add(
                LearningPathNodeModel(
                    path_id=path.id,
                    node_id=recommendation["node_id"],
                    sequence_number=index,
                    preferred_order=index,
                    required_mastery_level=recommendation["required_mastery_level"],
                    recommendation_reason=recommendation["reason"],
                    satisfied_prerequisites=recommendation["satisfied_prerequisites"],
                    unmet_prerequisites=recommendation["unmet_prerequisites"],
                    unlocks=recommendation["unlocks"],
                    computed_status=recommendation["status"],
                    is_required=True,
                    action_kind=str(recommendation.get("action_kind", "LEARN")),
                    source=step_source.value,
                )
            )
        self.session.flush()
        return path

    def replace_path(
        self,
        *,
        goal: LearningGoalModel,
        map_version_id: str,
        algorithm_version: str,
        recommendations: list[dict[str, Any]],
        origin: PathOrigin = PathOrigin.ALGORITHM_GENERATED,
    ) -> LearningPathModel:
        """Compatibility wrapper for the legacy generate-and-activate endpoint."""

        return self.create_path_revision(
            goal=goal,
            map_version_id=map_version_id,
            algorithm_version=algorithm_version,
            recommendations=recommendations,
            activate=True,
            origin=origin,
            change_summary="Generated and activated through the legacy path endpoint",
        )

    def get_path_revision(self, path_id: str, *, user_id: str | None = None) -> LearningPathModel:
        path = self.session.get(LearningPathModel, path_id)
        if path is None:
            raise EntityNotFoundError("learning path revision", path_id)
        if user_id is not None:
            goal = self.get_goal(path.goal_id, user_id=user_id)
            if goal.id != path.goal_id:
                raise EntityNotFoundError("learning path revision", path_id)
        return path

    def list_path_revisions(self, *, goal_id: str, user_id: str) -> list[LearningPathModel]:
        self.get_goal(goal_id, user_id=user_id)
        return list(
            self.session.scalars(
                select(LearningPathModel)
                .where(LearningPathModel.goal_id == goal_id)
                .order_by(
                    LearningPathModel.generation_number.desc(),
                    LearningPathModel.id.desc(),
                )
            )
        )

    def assert_path_revision(self, path: LearningPathModel, expected_revision: int) -> None:
        if path.row_version != expected_revision:
            raise RevisionConflictError(
                expected_revision=expected_revision,
                current_revision=path.row_version,
            )

    def clone_path_revision(
        self,
        *,
        source: LearningPathModel,
        expected_revision: int,
        change_summary: str,
    ) -> LearningPathModel:
        self.assert_path_revision(source, expected_revision)
        active_path = self._active_path_for_goal(source.goal_id)
        clone = LearningPathModel(
            goal_id=source.goal_id,
            space_id=source.space_id,
            map_version_id=source.map_version_id,
            parent_path_id=source.id,
            base_active_path_id=active_path.id if active_path is not None else None,
            generation_number=self._next_path_generation(source.goal_id),
            algorithm_version=source.algorithm_version,
            status=PathStatus.DRAFT.value,
            validity_status=source.validity_status,
            origin=PathOrigin.USER_EDITED.value,
            row_version=1,
            change_summary=change_summary,
            preference_snapshot=dict(source.preference_snapshot),
        )
        self.session.add(clone)
        self.session.flush()
        for item in self.get_path_items(source.id):
            values = {
                column.key: getattr(item, column.key)
                for column in LearningPathNodeModel.__table__.columns
                if column.key not in {"id", "path_id", "source"}
            }
            self.session.add(
                LearningPathNodeModel(
                    **values,
                    path_id=clone.id,
                    source=PathStepSource.INHERITED.value,
                )
            )
        self.session.flush()
        return clone

    def mark_path_revision_edited(self, path: LearningPathModel) -> None:
        path.row_version += 1
        path.validity_status = PathValidityStatus.STALE.value
        path.origin = (
            PathOrigin.USER_EDITED.value
            if path.origin == PathOrigin.USER_EDITED.value
            else PathOrigin.MIXED.value
        )

    def activate_path_revision(
        self, path: LearningPathModel, *, expected_revision: int
    ) -> LearningPathModel:
        self.assert_path_revision(path, expected_revision)
        if path.status != PathStatus.DRAFT.value:
            raise InvalidStateTransitionError("Only draft path revisions can be activated")
        active_path = self._active_path_for_goal(path.goal_id)
        current_active_id = active_path.id if active_path is not None else None
        if current_active_id != path.base_active_path_id:
            raise InvalidStateTransitionError(
                "The active path changed after this draft was created; clone the current "
                "active revision before applying these edits"
            )
        now = datetime.now().astimezone()
        if active_path is not None:
            active_path.status = PathStatus.SUPERSEDED.value
            active_path.superseded_at = now
            active_path.row_version += 1
            # The partial unique index permits one ACTIVE path per goal.  Flush
            # the predecessor transition before promoting the draft.
            self.session.flush()
        path.status = PathStatus.ACTIVE.value
        path.validity_status = PathValidityStatus.VALID.value
        path.activated_at = now
        path.row_version += 1
        self.session.flush()
        return path

    def get_path_items(self, path_id: str) -> list[LearningPathNodeModel]:
        return list(
            self.session.scalars(
                select(LearningPathNodeModel)
                .where(LearningPathNodeModel.path_id == path_id)
                .order_by(
                    LearningPathNodeModel.preferred_order,
                    LearningPathNodeModel.sequence_number,
                )
            )
        )

    def _require_editable_path(self, path: LearningPathModel) -> None:
        if path.status != PathStatus.DRAFT.value:
            raise InvalidStateTransitionError(
                "Active and historical path revisions are immutable; clone one before editing"
            )

    def get_path_item(self, path_id: str, item_id: str) -> LearningPathNodeModel:
        item = self.session.get(LearningPathNodeModel, item_id)
        if item is None or item.path_id != path_id:
            raise EntityNotFoundError("learning path step", item_id)
        return item

    def _set_path_item_order(
        self,
        path_id: str,
        ordered_items: list[LearningPathNodeModel],
    ) -> None:
        # ``sequence_number`` remains the compatibility projection used by older
        # readers.  Move every row out of the occupied range before assigning its
        # final order so SQLite's unique constraint is never transiently violated.
        highest = max((item.sequence_number for item in ordered_items), default=-1)
        temporary_start = highest + len(ordered_items) + 1
        for index, item in enumerate(ordered_items):
            item.sequence_number = temporary_start + index
        self.session.flush()
        for index, item in enumerate(ordered_items):
            item.preferred_order = index
            item.sequence_number = index
        self.session.flush()

    def add_path_item(
        self,
        *,
        path: LearningPathModel,
        expected_revision: int,
        node_id: str,
        preferred_order: int,
        required_mastery_level: int,
        recommendation_reason: str,
        is_required: bool,
        action_kind: str,
        stage: str | None,
        priority: int,
        estimated_minutes: int | None,
        is_pinned: bool,
        is_deferred: bool,
        user_note: str | None,
    ) -> LearningPathNodeModel:
        self.assert_path_revision(path, expected_revision)
        self._require_editable_path(path)
        existing = self.session.scalar(
            select(LearningPathNodeModel).where(
                LearningPathNodeModel.path_id == path.id,
                LearningPathNodeModel.node_id == node_id,
            )
        )
        if existing is not None:
            raise InvalidStateTransitionError("This node is already present in the path revision")
        items = self.get_path_items(path.id)
        insertion_index = min(preferred_order, len(items))
        item = LearningPathNodeModel(
            path_id=path.id,
            node_id=node_id,
            sequence_number=len(items),
            preferred_order=len(items),
            required_mastery_level=required_mastery_level,
            recommendation_reason=recommendation_reason,
            satisfied_prerequisites=[],
            unmet_prerequisites=[],
            unlocks=[],
            computed_status="AVAILABLE",
            is_required=is_required,
            action_kind=action_kind,
            stage=stage,
            priority=priority,
            estimated_minutes=estimated_minutes,
            is_pinned=is_pinned,
            is_deferred=is_deferred,
            user_note=user_note,
            source=PathStepSource.USER_CREATED.value,
        )
        self.session.add(item)
        self.session.flush()
        items.insert(insertion_index, item)
        self._set_path_item_order(path.id, items)
        self.mark_path_revision_edited(path)
        self.session.flush()
        return item

    def update_path_item(
        self,
        *,
        path: LearningPathModel,
        item_id: str,
        expected_revision: int,
        values: dict[str, Any],
    ) -> LearningPathNodeModel:
        self.assert_path_revision(path, expected_revision)
        self._require_editable_path(path)
        item = self.get_path_item(path.id, item_id)
        preferred_order = values.pop("preferred_order", None)
        for key, value in values.items():
            setattr(item, key, value)
        item.source = PathStepSource.USER_EDITED.value
        if preferred_order is not None:
            items = self.get_path_items(path.id)
            items.remove(item)
            items.insert(min(int(preferred_order), len(items)), item)
            self._set_path_item_order(path.id, items)
        self.mark_path_revision_edited(path)
        self.session.flush()
        return item

    def remove_path_item(
        self,
        *,
        path: LearningPathModel,
        item_id: str,
        expected_revision: int,
    ) -> None:
        self.assert_path_revision(path, expected_revision)
        self._require_editable_path(path)
        item = self.get_path_item(path.id, item_id)
        remaining = [
            candidate for candidate in self.get_path_items(path.id) if candidate.id != item.id
        ]
        self.session.delete(item)
        self.session.flush()
        self._set_path_item_order(path.id, remaining)
        self.mark_path_revision_edited(path)
        self.session.flush()

    def create_learning_session(self, **values: Any) -> LearningSessionModel:
        row = LearningSessionModel(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def create_progress_check_in(self, **values: Any) -> NodeProgressCheckInModel:
        row = NodeProgressCheckInModel(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def reset_progress_check_in_if_revision(
        self,
        *,
        check_in_id: str,
        user_id: str,
        expected_revision: int,
        reset_at: datetime,
    ) -> NodeProgressCheckInModel | None:
        """Atomically turn one current daily record into a reset marker.

        A direct conditional UPDATE avoids a read/check/write race.  Returning
        ``None`` means another request changed the snapshot and the application
        service must either treat an already-zero row as an idempotent success
        or report a revision conflict.
        """

        result = self.session.execute(
            update(NodeProgressCheckInModel)
            .where(
                NodeProgressCheckInModel.id == check_in_id,
                NodeProgressCheckInModel.user_id == user_id,
                NodeProgressCheckInModel.row_version == expected_revision,
            )
            .values(
                score=0,
                corrected_at=reset_at,
                updated_at=reset_at,
                row_version=NodeProgressCheckInModel.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            self.session.expire_all()
            return None
        self.session.expire_all()
        return self.get_progress_check_in(check_in_id, user_id=user_id)

    def list_progress_check_ins(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NodeProgressCheckInModel]:
        return list(
            self.session.scalars(
                select(NodeProgressCheckInModel)
                .where(
                    NodeProgressCheckInModel.user_id == user_id,
                    NodeProgressCheckInModel.goal_id == goal_id,
                    NodeProgressCheckInModel.node_id == node_id,
                )
                .order_by(
                    NodeProgressCheckInModel.check_in_date.desc(),
                    NodeProgressCheckInModel.checked_in_at.desc(),
                    NodeProgressCheckInModel.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )

    def count_progress_check_ins(self, *, user_id: str, goal_id: str, node_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(NodeProgressCheckInModel)
                .where(
                    NodeProgressCheckInModel.user_id == user_id,
                    NodeProgressCheckInModel.goal_id == goal_id,
                    NodeProgressCheckInModel.node_id == node_id,
                )
            )
            or 0
        )

    def latest_progress_check_in(
        self, *, user_id: str, goal_id: str, node_id: str
    ) -> NodeProgressCheckInModel | None:
        return self.session.scalar(
            select(NodeProgressCheckInModel)
            .where(
                NodeProgressCheckInModel.user_id == user_id,
                NodeProgressCheckInModel.goal_id == goal_id,
                NodeProgressCheckInModel.node_id == node_id,
            )
            .order_by(
                NodeProgressCheckInModel.check_in_date.desc(),
                NodeProgressCheckInModel.checked_in_at.desc(),
                NodeProgressCheckInModel.id.desc(),
            )
            .limit(1)
        )

    def latest_progress_check_ins_by_node(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_ids: Iterable[str],
    ) -> dict[str, NodeProgressCheckInModel]:
        """Return the newest durable check-in for every requested route node.

        A window query keeps this projection bounded to one row per node even
        after a project has accumulated years of daily check-ins.
        """

        requested_ids = sorted({str(node_id) for node_id in node_ids if node_id})
        if not requested_ids:
            return {}
        ranked = (
            select(
                NodeProgressCheckInModel.id.label("check_in_id"),
                func.row_number()
                .over(
                    partition_by=NodeProgressCheckInModel.node_id,
                    order_by=(
                        NodeProgressCheckInModel.check_in_date.desc(),
                        NodeProgressCheckInModel.checked_in_at.desc(),
                        NodeProgressCheckInModel.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(
                NodeProgressCheckInModel.user_id == user_id,
                NodeProgressCheckInModel.goal_id == goal_id,
                NodeProgressCheckInModel.node_id.in_(requested_ids),
            )
            .subquery()
        )
        rows = self.session.scalars(
            select(NodeProgressCheckInModel)
            .join(ranked, NodeProgressCheckInModel.id == ranked.c.check_in_id)
            .where(ranked.c.row_number == 1)
        )
        return {row.node_id: row for row in rows}

    def list_goal_progress_check_ins(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_ids: Iterable[str] | None = None,
        limit: int = 5,
    ) -> list[NodeProgressCheckInModel]:
        """Return recent project check-ins, optionally limited to its active route."""

        query = select(NodeProgressCheckInModel).where(
            NodeProgressCheckInModel.user_id == user_id,
            NodeProgressCheckInModel.goal_id == goal_id,
        )
        if node_ids is not None:
            requested_ids = sorted({str(node_id) for node_id in node_ids if node_id})
            if not requested_ids:
                return []
            query = query.where(NodeProgressCheckInModel.node_id.in_(requested_ids))
        return list(
            self.session.scalars(
                query.order_by(
                    NodeProgressCheckInModel.checked_in_at.desc(),
                    NodeProgressCheckInModel.check_in_date.desc(),
                    NodeProgressCheckInModel.id.desc(),
                ).limit(max(int(limit), 0))
            )
        )

    def progress_check_in_for_date(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        check_in_date: date,
    ) -> NodeProgressCheckInModel | None:
        return self.session.scalar(
            select(NodeProgressCheckInModel).where(
                NodeProgressCheckInModel.user_id == user_id,
                NodeProgressCheckInModel.goal_id == goal_id,
                NodeProgressCheckInModel.node_id == node_id,
                NodeProgressCheckInModel.check_in_date == check_in_date,
            )
        )

    def get_progress_check_in(self, check_in_id: str, *, user_id: str) -> NodeProgressCheckInModel:
        row = self.session.scalar(
            select(NodeProgressCheckInModel).where(
                NodeProgressCheckInModel.id == check_in_id,
                NodeProgressCheckInModel.user_id == user_id,
            )
        )
        if row is None:
            raise EntityNotFoundError("progress check-in", check_in_id)
        return row

    def list_learning_sessions(
        self,
        *,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LearningSessionModel]:
        """Return one learner's sessions newest-first without loading a data export."""

        return list(
            self.session.scalars(
                select(LearningSessionModel)
                .where(LearningSessionModel.user_id == user_id)
                .order_by(
                    LearningSessionModel.started_at.desc(),
                    LearningSessionModel.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )

    def count_learning_sessions(self, *, user_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(LearningSessionModel)
                .where(LearningSessionModel.user_id == user_id)
            )
            or 0
        )

    def create_evidence(self, **values: Any) -> LearningEvidenceModel:
        row = LearningEvidenceModel(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def create_suggestion(self, **values: Any) -> AISuggestionModel:
        suggestion = AISuggestionModel(**values)
        self.session.add(suggestion)
        self.session.flush()
        return suggestion

    def get_suggestion(
        self, suggestion_id: str, *, user_id: str | None = None
    ) -> AISuggestionModel:
        suggestion = self.session.get(AISuggestionModel, suggestion_id)
        if suggestion is None or (user_id is not None and suggestion.user_id != user_id):
            raise EntityNotFoundError("AI suggestion", suggestion_id)
        return suggestion

    def list_suggestions(
        self,
        *,
        user_id: str,
        space_id: str | None = None,
        status: ReviewStatus | None = None,
    ) -> list[AISuggestionModel]:
        query = select(AISuggestionModel).where(AISuggestionModel.user_id == user_id)
        if space_id:
            query = query.where(AISuggestionModel.space_id == space_id)
        if status:
            query = query.where(AISuggestionModel.review_status == status.value)
        return list(self.session.scalars(query.order_by(AISuggestionModel.created_at.desc())))

    def get_learning_plan(self, plan_id: str, *, user_id: str) -> AISuggestionModel:
        plan = self.session.scalar(
            select(AISuggestionModel).where(
                AISuggestionModel.id == plan_id,
                AISuggestionModel.user_id == user_id,
                AISuggestionModel.suggestion_type == SuggestionType.LEARNING_PLAN.value,
            )
        )
        if plan is None:
            raise EntityNotFoundError("learning plan", plan_id)
        return plan

    def list_learning_plans(self, *, user_id: str) -> list[AISuggestionModel]:
        query = (
            select(AISuggestionModel)
            .where(
                AISuggestionModel.user_id == user_id,
                AISuggestionModel.suggestion_type == SuggestionType.LEARNING_PLAN.value,
            )
            .order_by(AISuggestionModel.created_at.desc(), AISuggestionModel.id.desc())
        )
        return list(self.session.scalars(query))

    def delete_suggestion(self, suggestion: AISuggestionModel) -> None:
        self.session.delete(suggestion)

    def ai_revert_issues(
        self,
        *,
        suggestion_id: str,
        space_id: str,
        node_ids: list[str],
        edge_ids: list[str],
    ) -> list[str]:
        """Return reasons an accepted AI change can no longer be reverted losslessly."""

        version = self.get_editable_version(space_id)
        accepted_edge_ids = set(edge_ids)
        issues: list[str] = []
        for edge_id in edge_ids:
            edge = self.session.get(KnowledgeEdgeModel, edge_id)
            if edge is None or edge.map_version_id != version.id:
                issues.append(f"accepted edge {edge_id} is no longer in the editable version")
                continue
            if edge.status == RecordStatus.ARCHIVED.value:
                continue
            if not any(
                isinstance(reference, dict) and reference.get("suggestion_id") == suggestion_id
                for reference in edge.source_reference
            ):
                issues.append(f"accepted edge {edge_id} was modified after review")

        for node_id in node_ids:
            snapshot = self.session.scalar(
                select(KnowledgeNodeVersionModel).where(
                    KnowledgeNodeVersionModel.map_version_id == version.id,
                    KnowledgeNodeVersionModel.node_id == node_id,
                )
            )
            if snapshot is None or snapshot.status == RecordStatus.ARCHIVED.value:
                continue
            if snapshot.change_source != "AI_ACCEPTED":
                issues.append(f"accepted node {node_id} was edited after review")
            extra_edge = self.session.scalar(
                select(KnowledgeEdgeModel.id).where(
                    KnowledgeEdgeModel.map_version_id == version.id,
                    KnowledgeEdgeModel.status != RecordStatus.ARCHIVED.value,
                    (KnowledgeEdgeModel.source_node_id == node_id)
                    | (KnowledgeEdgeModel.target_node_id == node_id),
                    KnowledgeEdgeModel.id.not_in(accepted_edge_ids),
                )
            )
            if extra_edge is not None:
                issues.append(f"accepted node {node_id} has a later relationship")
            reference_queries = (
                select(LearningGoalModel.id).where(LearningGoalModel.target_node_id == node_id),
                select(LearnerNodeStateModel.id).where(LearnerNodeStateModel.node_id == node_id),
                select(LearningSessionModel.id).where(LearningSessionModel.node_id == node_id),
                select(LearningEvidenceModel.id).where(LearningEvidenceModel.node_id == node_id),
                select(LearningResourceModel.id).where(LearningResourceModel.node_id == node_id),
                select(AssessmentModel.id).where(AssessmentModel.node_id == node_id),
            )
            referenced = any(
                self.session.scalar(query.limit(1)) is not None for query in reference_queries
            )
            if referenced:
                issues.append(f"accepted node {node_id} now has learner or content records")
        return issues

    def audit(
        self,
        actor_user_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLogModel:
        row = AuditLogModel(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before,
            after_state=after,
            details=details or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _get_node(self, space_id: str, node_id: str) -> KnowledgeNodeModel:
        node = self.session.get(KnowledgeNodeModel, node_id)
        if node is None or node.space_id != space_id:
            raise EntityNotFoundError("node", node_id)
        return node

    def _require_draft(self, space_id: str, map_version_id: str) -> KnowledgeMapVersionModel:
        version = self.get_version(space_id, map_version_id)
        if version.status != VersionStatus.DRAFT.value:
            raise InvalidStateTransitionError("Published map versions are immutable")
        return version


def count_rows(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def rows_by_ids(session: Session, model: type[Any], ids: Iterable[str]) -> list[Any]:
    id_list = list(ids)
    if not id_list:
        return []
    return list(session.scalars(select(model).where(model.id.in_(id_list))))


def _json_contains_value(value: Any, target: str) -> bool:
    """Return whether a persisted JSON value contains an exact opaque identifier."""

    if isinstance(value, dict):
        return any(_json_contains_value(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_json_contains_value(item, target) for item in value)
    return isinstance(value, str) and value == target
