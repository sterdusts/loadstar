"""Use-case orchestration for maps, routes, learner state and AI review."""

from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect

from learning_navigator.application.dto.ai import (
    GoalSemanticProfileDraft,
    KnowledgeMapDraft,
    LearningPlanDraft,
    analyze_draft,
    semantic_profile_payload_or_none,
    validate_semantic_profile_for_intent,
    with_sanitized_semantic_profile,
)
from learning_navigator.application.dto.check_in import CheckInAIEvaluation
from learning_navigator.application.mastery_profiles import (
    MasteryProfileApplicationService,
)
from learning_navigator.config import Settings
from learning_navigator.domain.entities import (
    GraphEdge,
    GraphNode,
    LearnerSnapshot,
    RouteRequest,
)
from learning_navigator.domain.enums import (
    ComputedNodeStatus,
    EvidenceType,
    GoalIntent,
    GoalStatus,
    NodeType,
    PathActionKind,
    PathOrigin,
    PathStatus,
    PathValidityStatus,
    RecordStatus,
    RelationType,
    ReviewStatus,
    RoutePreference,
    SuggestionType,
)
from learning_navigator.domain.exceptions import (
    AIConfigurationError,
    AIOutputValidationError,
    AIProviderProfileInUseError,
    DuplicateProgressCheckInError,
    EntityNotFoundError,
    InvalidPathRevisionError,
    InvalidStateTransitionError,
    ProgressCheckInRevisionConflictError,
    ProgressScoreRegressionError,
    SuggestionReviewError,
)
from learning_navigator.domain.services.graph import KnowledgeGraphService
from learning_navigator.domain.services.mastery import MasteryService
from learning_navigator.infrastructure.ai.providers import (
    PROVIDER_PRESETS,
    AIProvider,
    build_provider,
)
from learning_navigator.infrastructure.database.base import new_id
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
    ProgressCheckInAttachmentModel,
    ProgressCheckInClearBatchModel,
    UserModel,
)
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)
from learning_navigator.infrastructure.security.credentials import (
    CredentialStore,
    CredentialStoreError,
)
from learning_navigator.infrastructure.storage.check_in_attachments import (
    CheckInAttachmentStorage,
)

SYMMETRIC_RELATIONS = {RelationType.RELATED, RelationType.ALTERNATIVE_TO}
DASHBOARD_CURRENT_STATUS_PRIORITY = (
    ComputedNodeStatus.NEEDS_REVIEW.value,
    ComputedNodeStatus.IN_PROGRESS.value,
    ComputedNodeStatus.AVAILABLE.value,
)
DISPLAY_PROGRESS_COMPLETED = "COMPLETED"
DISPLAY_PROGRESS_IN_PROGRESS = "IN_PROGRESS"
DISPLAY_PROGRESS_NOT_STARTED = "NOT_STARTED"


class NavigatorApplication:
    """Application service; HTTP and UI layers contain no domain rules."""

    def __init__(
        self,
        repository: SqlAlchemyKnowledgeRepository,
        settings: Settings,
        ai_provider: AIProvider,
        credential_store: CredentialStore,
        ai_http_client: httpx.AsyncClient,
        attachment_storage: CheckInAttachmentStorage,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.ai_provider = ai_provider
        self.credential_store = credential_store
        self.ai_http_client = ai_http_client
        self.attachment_storage = attachment_storage
        self.mastery_service = MasteryService(
            review_after_days=settings.review_after_days,
            algorithm_version=settings.mastery_algorithm_version,
        )
        self.mastery_profiles = MasteryProfileApplicationService(repository)

    def ensure_local_user(
        self, *, display_name: str = "Local learner", email: str | None = None
    ) -> dict[str, Any]:
        return model_dict(self.repository.ensure_user(display_name=display_name, email=email))

    def _editable_graph(
        self, *, user_id: str, space_id: str
    ) -> tuple[str, list[GraphNode], list[GraphEdge]]:
        """Load the graph used by a mutation, recovering legacy maps without drafts."""
        draft, created = self.repository.ensure_editable_version(
            space_id,
            user_id=user_id,
            change_summary="Automatic editable draft created for direct editing",
        )
        if created:
            self.repository.audit(
                user_id,
                "CREATE_EDITABLE_MAP_DRAFT",
                "KnowledgeMapVersion",
                draft.id,
                after={
                    "space_id": space_id,
                    "version_number": draft.version_number,
                    "parent_version_id": draft.parent_version_id,
                    "reason": "direct_edit",
                },
            )
        return self.repository.load_graph(space_id, draft.id)

    def list_ai_providers(self) -> dict[str, object]:
        return {
            "providers": [
                {"id": name, "name": name, **asdict(preset)}
                for name, preset in PROVIDER_PRESETS.items()
            ],
            "environment_fallback": {
                "provider": self.ai_provider.name,
                "model": self.ai_provider.model,
                "base_url": self.settings.ai_base_url,
                "has_api_key": self.settings.ai_api_key is not None,
            },
        }

    def ai_status(self, *, user_id: str) -> dict[str, object]:
        self.repository.get_user(user_id)
        profile = self.repository.get_default_ai_provider_profile(user_id)
        if profile is not None:
            try:
                provider = self._build_profile_provider(profile)
                is_ready = True
            except AIConfigurationError:
                provider = None
                is_ready = False
            return {
                "provider": provider.name if provider is not None else profile.provider,
                "model": provider.model if provider is not None else profile.model,
                "is_external": profile.provider != "mock",
                "is_ready": is_ready,
                "display_name": profile.display_name,
            }
        return {
            "provider": self.ai_provider.name,
            "model": self.ai_provider.model,
            "is_external": self.ai_provider.name != "mock",
            "is_ready": True,
            "display_name": "Environment default",
        }

    def list_ai_provider_profiles(self, *, user_id: str) -> list[dict[str, Any]]:
        self.repository.get_user(user_id)
        return [
            self._provider_profile_dict(profile)
            for profile in self.repository.list_ai_provider_profiles(user_id)
        ]

    def create_ai_provider_profile(
        self,
        *,
        user_id: str,
        display_name: str,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        is_default: bool = True,
    ) -> dict[str, Any]:
        self.repository.get_user(user_id)
        provider, base_url, model = self._validate_provider_configuration(
            provider=provider,
            base_url=base_url,
            model=model,
        )
        normalized_name = display_name.strip()
        if any(
            item.display_name.casefold() == normalized_name.casefold()
            for item in self.repository.list_ai_provider_profiles(user_id)
        ):
            raise AIConfigurationError(
                f"An AI provider profile named '{normalized_name}' already exists."
            )
        profile: AIProviderProfileModel | None = None
        previous_secret: str | None = None
        key_change_attempted = False
        try:
            profile = self.repository.create_ai_provider_profile(
                owner_id=user_id,
                display_name=normalized_name,
                provider=provider,
                base_url=base_url,
                model=model,
                key_last4=None,
                is_default=is_default,
            )
            if api_key:
                # Read the vault before changing it, even for a newly generated profile id.
                # This makes compensation deterministic if a custom credential backend has
                # stale state or mutates successfully before reporting an error.
                previous_secret = self._get_profile_api_key(profile)
                key_change_attempted = True
                self._save_profile_api_key(profile, api_key)
            self.repository.audit(
                user_id,
                "CREATE_AI_PROVIDER_PROFILE",
                "AIProviderProfile",
                profile.id,
                details={"provider": provider, "model": model},
            )
            self.repository.session.flush()
            self.repository.session.commit()
        except Exception:
            self.repository.session.rollback()
            if key_change_attempted and profile is not None:
                self._restore_profile_api_key(
                    user_id=user_id,
                    profile_id=profile.id,
                    previous_secret=previous_secret,
                    operation="creation",
                )
            raise
        assert profile is not None
        return self._provider_profile_dict(profile)

    def update_ai_provider_profile(
        self,
        *,
        user_id: str,
        profile_id: str,
        display_name: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        profile = self.repository.get_ai_provider_profile(profile_id, user_id=user_id)
        next_provider, next_base_url, next_model = self._validate_provider_configuration(
            provider=provider or profile.provider,
            base_url=base_url if base_url is not None else profile.base_url,
            model=model or profile.model,
        )
        normalized_name = profile.display_name
        if display_name is not None:
            normalized_name = display_name.strip()
            if any(
                item.id != profile.id and item.display_name.casefold() == normalized_name.casefold()
                for item in self.repository.list_ai_provider_profiles(user_id)
            ):
                raise AIConfigurationError(
                    f"An AI provider profile named '{normalized_name}' already exists."
                )

        key_change_requested = bool(clear_api_key or api_key)
        previous_secret: str | None = None
        if key_change_requested:
            # Capture the credential before any database or vault mutation. Database rollback
            # restores configuration fields; this value restores the non-transactional vault.
            previous_secret = self._get_profile_api_key(profile)

        key_change_attempted = False
        try:
            profile.display_name = normalized_name
            profile.provider = next_provider
            profile.base_url = next_base_url
            profile.model = next_model
            if clear_api_key:
                key_change_attempted = True
                self._delete_profile_api_key(profile)
            elif api_key:
                key_change_attempted = True
                self._save_profile_api_key(profile, api_key)
            if is_default:
                self.repository.set_default_ai_provider_profile(profile)
            self.repository.audit(
                user_id,
                "UPDATE_AI_PROVIDER_PROFILE",
                "AIProviderProfile",
                profile.id,
                details={
                    "provider": profile.provider,
                    "model": profile.model,
                    "key_changed": key_change_requested,
                },
            )
            self.repository.session.flush()
            self.repository.session.commit()
        except Exception:
            self.repository.session.rollback()
            if key_change_attempted:
                self._restore_profile_api_key(
                    user_id=user_id,
                    profile_id=profile.id,
                    previous_secret=previous_secret,
                    operation="update",
                )
            raise
        return self._provider_profile_dict(profile)

    def delete_ai_provider_profile(self, *, user_id: str, profile_id: str) -> None:
        profile = self.repository.get_ai_provider_profile(profile_id, user_id=user_id)
        reference_count = self.repository.count_active_conversations_for_ai_provider_profile(
            profile_id=profile.id,
            user_id=user_id,
        )
        if reference_count:
            raise AIProviderProfileInUseError(reference_count=reference_count)

        # The OS credential vault and SQL database cannot share one transaction. Read the
        # secret first, then compensate the vault if any SQL flush/commit fails. This method
        # deliberately owns its commit so the compensation boundary includes the real commit,
        # rather than only the preceding flush.
        previous_secret = self._get_profile_api_key(profile)
        key_delete_attempted = False
        try:
            key_delete_attempted = True
            self._delete_profile_api_key(profile)
            detached_conversation_count = (
                self.repository.detach_archived_conversations_from_ai_provider_profile(
                    profile_id=profile.id,
                    user_id=user_id,
                )
            )
            self.repository.audit(
                user_id,
                "DELETE_AI_PROVIDER_PROFILE",
                "AIProviderProfile",
                profile.id,
                details={
                    "provider": profile.provider,
                    "model": profile.model,
                    "detached_archived_conversation_count": detached_conversation_count,
                },
            )
            self.repository.delete_ai_provider_profile(profile)
            self.repository.session.commit()
        except Exception:
            self.repository.session.rollback()
            if key_delete_attempted and previous_secret is not None:
                try:
                    self.credential_store.set(
                        user_id=user_id,
                        profile_id=profile_id,
                        secret=previous_secret,
                    )
                except CredentialStoreError as restore_error:
                    raise AIConfigurationError(
                        "The provider deletion failed and its API key could not be restored "
                        "to the operating-system credential vault."
                    ) from restore_error
            raise

    async def test_ai_provider_profile(self, *, user_id: str, profile_id: str) -> dict[str, Any]:
        profile = self.repository.get_ai_provider_profile(profile_id, user_id=user_id)
        provider = self._build_profile_provider(profile)
        started = perf_counter()
        models = await provider.list_models()
        return {
            "ok": True,
            "provider": provider.name,
            "model": provider.model,
            "model_available": not models or provider.model in models,
            "models": models[:200],
            "latency_ms": round((perf_counter() - started) * 1000),
        }

    async def list_ai_provider_models(self, *, user_id: str, profile_id: str) -> dict[str, Any]:
        profile = self.repository.get_ai_provider_profile(profile_id, user_id=user_id)
        provider = self._build_profile_provider(profile)
        models = await provider.list_models()
        return {"profile_id": profile.id, "models": models[:500]}

    @staticmethod
    def _provider_profile_dict(profile: AIProviderProfileModel) -> dict[str, Any]:
        return {
            "id": profile.id,
            "display_name": profile.display_name,
            "provider": profile.provider,
            "base_url": profile.base_url,
            "model": profile.model,
            "has_api_key": profile.key_last4 is not None,
            "key_last4": profile.key_last4,
            "is_default": profile.is_default,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _validate_provider_configuration(
        *, provider: str, base_url: str, model: str
    ) -> tuple[str, str, str]:
        normalized_provider = provider.strip().casefold().replace("_", "-")
        if normalized_provider not in PROVIDER_PRESETS:
            raise AIConfigurationError(f"Unsupported AI provider: {provider}")
        normalized_model = model.strip()
        if not normalized_model:
            raise AIConfigurationError("The model name cannot be empty.")
        if normalized_provider == "mock":
            return normalized_provider, "", normalized_model

        normalized_url = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AIConfigurationError("The provider Base URL must be an HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AIConfigurationError(
                "The provider Base URL cannot contain credentials, a query, or a fragment."
            )
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise AIConfigurationError(
                "Plain HTTP is allowed only for a local provider such as Ollama."
            )
        return normalized_provider, normalized_url, normalized_model

    def _save_profile_api_key(self, profile: AIProviderProfileModel, api_key: str) -> None:
        secret = api_key.strip()
        if not secret:
            raise AIConfigurationError("The API key cannot be empty.")
        try:
            self.credential_store.set(
                user_id=profile.owner_id,
                profile_id=profile.id,
                secret=secret,
            )
        except CredentialStoreError as exc:
            raise AIConfigurationError(str(exc)) from exc
        profile.key_last4 = secret[-4:]

    def _get_profile_api_key(self, profile: AIProviderProfileModel) -> str | None:
        try:
            return self.credential_store.get(
                user_id=profile.owner_id,
                profile_id=profile.id,
            )
        except CredentialStoreError as exc:
            raise AIConfigurationError(str(exc)) from exc

    def _delete_profile_api_key(self, profile: AIProviderProfileModel) -> None:
        try:
            self.credential_store.delete(
                user_id=profile.owner_id,
                profile_id=profile.id,
            )
        except CredentialStoreError as exc:
            raise AIConfigurationError(str(exc)) from exc
        profile.key_last4 = None

    def _restore_profile_api_key(
        self,
        *,
        user_id: str,
        profile_id: str,
        previous_secret: str | None,
        operation: str,
    ) -> None:
        """Compensate a vault write after its SQL transaction did not commit."""

        try:
            if previous_secret is None:
                self.credential_store.delete(user_id=user_id, profile_id=profile_id)
            else:
                self.credential_store.set(
                    user_id=user_id,
                    profile_id=profile_id,
                    secret=previous_secret,
                )
        except CredentialStoreError as exc:
            raise AIConfigurationError(
                f"The provider profile {operation} failed and the operating-system "
                "credential vault could not be restored."
            ) from exc

    def _build_profile_provider(self, profile: AIProviderProfileModel) -> AIProvider:
        try:
            api_key = self.credential_store.get(
                user_id=profile.owner_id,
                profile_id=profile.id,
            )
        except CredentialStoreError as exc:
            raise AIConfigurationError(str(exc)) from exc
        preset = PROVIDER_PRESETS[profile.provider]
        if preset.requires_key and not api_key:
            raise AIConfigurationError(
                f"Profile '{profile.display_name}' does not have an API key."
            )
        return build_provider(
            profile.provider,
            base_url=profile.base_url,
            model=profile.model,
            api_key=api_key,
            client=self.ai_http_client,
        )

    def _resolve_ai_provider(
        self,
        *,
        user_id: str,
        provider_profile_id: str | None,
    ) -> tuple[AIProvider, AIProviderProfileModel | None]:
        profile = (
            self.repository.get_ai_provider_profile(provider_profile_id, user_id=user_id)
            if provider_profile_id is not None
            else self.repository.get_default_ai_provider_profile(user_id)
        )
        return (
            (self._build_profile_provider(profile), profile)
            if profile
            else (
                self.ai_provider,
                None,
            )
        )

    @staticmethod
    def _require_external_ai_confirmation(
        provider: AIProvider, *, confirmed_external_ai: bool
    ) -> None:
        if provider.name != "mock" and not confirmed_external_ai:
            raise AIConfigurationError(
                "Confirm external AI processing before sending learning material."
            )

    def create_space(
        self,
        *,
        user_id: str,
        title: str,
        description: str = "",
        target_audience: str = "",
        scope_included: list[str] | None = None,
        scope_excluded: list[str] | None = None,
        stable_key: str | None = None,
    ) -> dict[str, Any]:
        space, version = self.repository.create_space(
            user_id=user_id,
            title=title,
            description=description,
            target_audience=target_audience,
            scope_included=scope_included,
            scope_excluded=scope_excluded,
            requested_stable_key=stable_key,
        )
        result = model_dict(space)
        result["draft_version_id"] = version.id
        return result

    def list_spaces(self, user_id: str | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for space in self.repository.list_spaces(user_id):
            item = model_dict(space)
            item["draft_version_id"] = self.repository.get_editable_version(space.id).id
            result.append(item)
        return result

    def list_map_versions(self, *, user_id: str, space_id: str) -> list[dict[str, Any]]:
        self.repository.get_space(space_id, user_id=user_id)
        return [model_dict(version) for version in self.repository.list_versions(space_id)]

    def publish_map_version(
        self, *, user_id: str, space_id: str, change_summary: str
    ) -> dict[str, Any]:
        self.repository.get_space(space_id, user_id=user_id)
        _, nodes, edges = self.repository.load_graph(space_id)
        cycle = KnowledgeGraphService(nodes, edges).detect_cycle()
        if cycle:
            raise InvalidStateTransitionError(
                "Cannot publish a map with a dependency cycle: " + " -> ".join(cycle)
            )
        published, draft = self.repository.publish_editable_version(
            space_id=space_id,
            user_id=user_id,
            change_summary=change_summary or "Published reviewed knowledge map",
        )
        self.repository.audit(
            user_id,
            "PUBLISH_MAP_VERSION",
            "KnowledgeMapVersion",
            published.id,
            after={"published_version": published.version_number, "new_draft_id": draft.id},
        )
        return {"published": model_dict(published), "new_draft": model_dict(draft)}

    def restore_map_version(
        self,
        *,
        user_id: str,
        space_id: str,
        version_id: str,
        change_summary: str,
    ) -> dict[str, Any]:
        self.repository.get_space(space_id, user_id=user_id)
        restored = self.repository.restore_version_as_draft(
            space_id=space_id,
            source_version_id=version_id,
            user_id=user_id,
            change_summary=change_summary or f"Restored from version {version_id}",
        )
        self.repository.audit(
            user_id,
            "RESTORE_MAP_VERSION",
            "KnowledgeMapVersion",
            restored.id,
            after={"source_version_id": version_id, "new_draft_id": restored.id},
        )
        return model_dict(restored)

    def compare_map_versions(
        self,
        *,
        user_id: str,
        space_id: str,
        base_version_id: str,
        head_version_id: str,
    ) -> dict[str, Any]:
        self.repository.get_space(space_id, user_id=user_id)
        _, base_nodes, base_edges = self.repository.load_graph(space_id, base_version_id)
        _, head_nodes, head_edges = self.repository.load_graph(space_id, head_version_id)
        base_by_id = {node.id: node for node in base_nodes}
        head_by_id = {node.id: node for node in head_nodes}
        added_ids = head_by_id.keys() - base_by_id.keys()
        removed_ids = base_by_id.keys() - head_by_id.keys()
        shared_ids = base_by_id.keys() & head_by_id.keys()
        changed_ids = [
            node_id
            for node_id in shared_ids
            if asdict(base_by_id[node_id]) != asdict(head_by_id[node_id])
        ]

        def edge_key(edge: GraphEdge) -> tuple[str, str, str]:
            return (edge.source_node_id, edge.target_node_id, edge.relation_type.value)

        base_edge_keys = {edge_key(edge) for edge in base_edges if edge.is_active}
        head_edge_keys = {edge_key(edge) for edge in head_edges if edge.is_active}
        return {
            "base_version_id": base_version_id,
            "head_version_id": head_version_id,
            "nodes": {
                "added": [json_safe(asdict(head_by_id[item])) for item in sorted(added_ids)],
                "removed": [json_safe(asdict(base_by_id[item])) for item in sorted(removed_ids)],
                "changed": [
                    {
                        "node_id": item,
                        "before": json_safe(asdict(base_by_id[item])),
                        "after": json_safe(asdict(head_by_id[item])),
                    }
                    for item in sorted(changed_ids)
                ],
            },
            "edges": {
                "added": [list(item) for item in sorted(head_edge_keys - base_edge_keys)],
                "removed": [list(item) for item in sorted(base_edge_keys - head_edge_keys)],
            },
        }

    def create_node(
        self,
        *,
        user_id: str,
        space_id: str,
        title: str,
        description: str = "",
        node_type: NodeType = NodeType.CONCEPT,
        difficulty: int = 1,
        depth_level: int = 0,
        learning_objectives: list[str] | None = None,
        source_basis: list[dict[str, Any]] | None = None,
        stable_key: str | None = None,
        change_source: str = "HUMAN",
        manually_locked: bool = True,
    ) -> dict[str, Any]:
        map_version_id, nodes, edges = self._editable_graph(user_id=user_id, space_id=space_id)
        node_id = new_id()
        candidate = GraphNode(
            id=node_id,
            title=title,
            description=description,
            node_type=node_type,
            difficulty=difficulty,
            depth_level=depth_level,
            status=RecordStatus.ACTIVE,
            manually_locked=manually_locked,
        )
        KnowledgeGraphService(nodes, edges).create_node(candidate)
        row = self.repository.create_node(
            node_id=node_id,
            space_id=space_id,
            map_version_id=map_version_id,
            user_id=user_id,
            title=title,
            description=description,
            node_type=node_type,
            difficulty=difficulty,
            depth_level=depth_level,
            learning_objectives=learning_objectives,
            source_basis=source_basis,
            requested_stable_key=stable_key,
            change_source=change_source,
            manually_locked=manually_locked,
        )
        self.repository.audit(
            user_id,
            "CREATE_NODE",
            "KnowledgeNode",
            row.id,
            after={"space_id": space_id, "title": title, "change_source": change_source},
        )
        return model_dict(row)

    def update_node(
        self, *, user_id: str, space_id: str, node_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        map_version_id, nodes, edges = self._editable_graph(user_id=user_id, space_id=space_id)
        engine = KnowledgeGraphService(nodes, edges)
        graph_changes = {
            key: value
            for key, value in changes.items()
            if key in {"title", "description", "node_type", "difficulty", "depth_level"}
        }
        if "node_type" in graph_changes and isinstance(graph_changes["node_type"], str):
            graph_changes["node_type"] = NodeType(graph_changes["node_type"])
        engine.update_node(node_id, **graph_changes)
        before = next(asdict(node) for node in nodes if node.id == node_id)
        snapshot = self.repository.update_node(
            space_id=space_id,
            map_version_id=map_version_id,
            node_id=node_id,
            user_id=user_id,
            changes=changes,
        )
        self.repository.audit(
            user_id,
            "UPDATE_NODE",
            "KnowledgeNode",
            node_id,
            before=json_safe(before),
            after=model_dict(snapshot),
        )
        return model_dict(snapshot)

    def update_outline(
        self,
        *,
        user_id: str,
        space_id: str,
        expected_revision: int,
        modules: list[dict[str, Any]],
        ungrouped_node_ids: list[str],
        path_id: str | None = None,
        path_expected_revision: int | None = None,
        path_step_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        map_version_id, _, _ = self._editable_graph(user_id=user_id, space_id=space_id)
        before = self.graph_view(space_id=space_id, user_id=user_id)
        version = self.repository.replace_outline(
            space_id=space_id,
            map_version_id=map_version_id,
            user_id=user_id,
            expected_revision=expected_revision,
            modules=modules,
            ungrouped_node_ids=ungrouped_node_ids,
        )
        path_sync: dict[str, Any] | None = None
        if path_id is not None:
            if path_expected_revision is None or path_step_ids is None:
                raise InvalidStateTransitionError(
                    "A synced path requires its revision and complete step order"
                )
            path = self.repository.get_path_revision(path_id, user_id=user_id)
            if path.space_id != space_id:
                raise InvalidStateTransitionError(
                    "The synced path does not belong to this framework"
                )
            if path.map_version_id != map_version_id:
                if path.status != PathStatus.DRAFT.value:
                    raise InvalidStateTransitionError(
                        "The active path does not belong to this editable framework draft"
                    )
                # A legacy project may have a draft route tied to a published
                # framework. Rebind that editable route to the automatically
                # created framework draft before synchronizing its order.
                path.map_version_id = map_version_id
                path.validity_status = PathValidityStatus.STALE.value
                self.repository.session.flush()
                self.repository.audit(
                    user_id,
                    "SYNC_PATH_FRAMEWORK_DRAFT",
                    "LearningPath",
                    path.id,
                    after={"map_version_id": map_version_id},
                )
            before_path = [item.id for item in self.repository.get_path_items(path.id)]
            if before_path != path_step_ids:
                self.repository.replace_path_item_order(
                    path=path,
                    expected_revision=path_expected_revision,
                    item_ids=path_step_ids,
                )
                self.repository.audit(
                    user_id,
                    "REORDER_PATH",
                    "LearningPath",
                    path.id,
                    before={"step_ids": before_path, "row_version": path_expected_revision},
                    after={"step_ids": path_step_ids, "row_version": path.row_version},
                )
            path_sync = {
                "path_id": path.id,
                "row_version": path.row_version,
                "changed": before_path != path_step_ids,
            }
        self.repository.audit(
            user_id,
            "REORDER_FRAMEWORK_OUTLINE",
            "KnowledgeMapVersion",
            map_version_id,
            before={"outline_revision": expected_revision},
            after={
                "outline_revision": version.outline_revision,
                "module_ids": [item["module_id"] for item in modules],
                "element_count": sum(len(item.get("node_ids", [])) for item in modules)
                + len(ungrouped_node_ids),
                "path_sync": path_sync,
            },
        )
        result = self.graph_view(space_id=space_id, user_id=user_id)
        result["previous_outline_revision"] = before.get("outline_revision")
        if path_sync is not None:
            result["path_sync"] = path_sync
        return result

    def node_delete_impact(self, *, user_id: str, space_id: str, node_id: str) -> dict[str, Any]:
        map_version_id, _, _ = self._editable_graph(user_id=user_id, space_id=space_id)
        return self.repository.node_delete_impact(
            space_id=space_id,
            map_version_id=map_version_id,
            node_id=node_id,
            user_id=user_id,
        )

    def delete_node_permanently(
        self, *, user_id: str, space_id: str, node_id: str
    ) -> dict[str, Any]:
        map_version_id, _, _ = self._editable_graph(user_id=user_id, space_id=space_id)
        impact = self.repository.delete_node_permanently(
            space_id=space_id,
            map_version_id=map_version_id,
            node_id=node_id,
            user_id=user_id,
        )
        self.repository.audit(
            user_id,
            "DELETE_FRAMEWORK_NODE",
            "KnowledgeNode",
            node_id,
            details={"permanent": True, **impact},
        )
        return {"deleted": True, **impact}

    def create_edge(
        self,
        *,
        user_id: str,
        space_id: str,
        source_node_id: str,
        target_node_id: str,
        relation_type: RelationType,
        strength: float = 1.0,
        confidence: float = 1.0,
        required_mastery_level: int | None = None,
        reason: str = "",
        source_reference: list[dict[str, Any]] | None = None,
        manually_locked: bool = True,
    ) -> dict[str, Any]:
        map_version_id, nodes, edges = self._editable_graph(user_id=user_id, space_id=space_id)
        if relation_type in SYMMETRIC_RELATIONS and source_node_id > target_node_id:
            source_node_id, target_node_id = target_node_id, source_node_id
        required = (
            self.settings.mastery_required_level
            if required_mastery_level is None and relation_type is RelationType.PREREQUISITE
            else (required_mastery_level or 0)
        )
        edge = GraphEdge(
            id=new_id(),
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation_type=relation_type,
            strength=strength,
            confidence=confidence,
            required_mastery_level=required,
            is_hard_requirement=relation_type is RelationType.PREREQUISITE,
        )
        KnowledgeGraphService(nodes, edges).create_edge(edge)
        row = self.repository.upsert_edge(
            space_id=space_id,
            map_version_id=map_version_id,
            user_id=user_id,
            edge=edge,
            reason=reason,
            source_reference=source_reference,
            manually_locked=manually_locked,
        )
        self.repository.audit(
            user_id,
            "CREATE_EDGE",
            "KnowledgeEdge",
            row.id,
            after={
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "relation_type": relation_type.value,
            },
        )
        return model_dict(row)

    def remove_edge(self, *, user_id: str, space_id: str, edge_id: str) -> None:
        map_version_id, nodes, edges = self._editable_graph(user_id=user_id, space_id=space_id)
        KnowledgeGraphService(nodes, edges).remove_edge(edge_id)
        self.repository.archive_edge(map_version_id=map_version_id, edge_id=edge_id)
        self.repository.audit(user_id, "ARCHIVE_EDGE", "KnowledgeEdge", edge_id)

    def graph_view(
        self,
        *,
        space_id: str,
        user_id: str | None = None,
        target_node_id: str | None = None,
    ) -> dict[str, Any]:
        if user_id is not None:
            self.repository.get_space(space_id, user_id=user_id)
        map_version_id, nodes, edges = self.repository.load_graph(space_id)
        node_rows = self.repository.session.execute(
            select(KnowledgeNodeVersionModel, KnowledgeNodeModel)
            .join(KnowledgeNodeModel, KnowledgeNodeModel.id == KnowledgeNodeVersionModel.node_id)
            .where(KnowledgeNodeVersionModel.map_version_id == map_version_id)
        ).all()
        node_details = {
            version.node_id: {
                "stable_key": node.stable_key,
                "learning_objectives": list(version.learning_objectives),
                "source_basis": list(version.source_basis),
                "change_source": version.change_source,
                "outline_order": version.outline_order,
            }
            for version, node in node_rows
        }
        edge_rows = list(
            self.repository.session.scalars(
                select(KnowledgeEdgeModel).where(
                    KnowledgeEdgeModel.map_version_id == map_version_id
                )
            )
        )
        edge_details = {
            edge.id: {
                "reason": edge.reason,
                "source_reference": list(edge.source_reference),
                "manually_locked": edge.manually_locked,
            }
            for edge in edge_rows
        }
        engine = KnowledgeGraphService(nodes, edges)
        active_nodes = [node for node in nodes if node.is_active]
        relevant = (
            {node.id for node in engine.calculate_target_subgraph(target_node_id)}
            if target_node_id
            else {node.id for node in active_nodes}
        )
        mastery = (
            self.repository.get_mastery(user_id, {node.id for node in active_nodes})
            if user_id
            else {}
        )
        return {
            "space_id": space_id,
            "map_version_id": map_version_id,
            "outline_revision": self.repository.get_version(
                space_id, map_version_id
            ).outline_revision,
            "nodes": [
                {
                    **json_safe(asdict(node)),
                    **node_details.get(node.id, {}),
                    "computed_status": engine.classify_node(node.id, relevant, mastery).value
                    if user_id
                    else None,
                    "mastery": json_safe(asdict(mastery[node.id])) if node.id in mastery else None,
                }
                for node in nodes
            ],
            "edges": [
                {**json_safe(asdict(edge)), **edge_details.get(edge.id, {})} for edge in edges
            ],
            "cycle": engine.detect_cycle(),
        }

    def create_goal(
        self,
        *,
        user_id: str,
        space_id: str,
        target_node_id: str,
        title: str,
        intent_mode: GoalIntent = GoalIntent.LEARN,
        semantic_profile: GoalSemanticProfileDraft | dict[str, Any] | None = None,
        target_mastery_level: int = 3,
        route_preference: RoutePreference = RoutePreference.FOUNDATION_COMPLETE,
        deadline: date | None = None,
        load_preference: str | None = None,
    ) -> dict[str, Any]:
        self.repository.get_space(space_id, user_id=user_id)
        _, nodes, edges = self.repository.load_graph(space_id)
        KnowledgeGraphService(nodes, edges).calculate_target_subgraph(target_node_id)
        if semantic_profile is not None:
            semantic_profile_draft = GoalSemanticProfileDraft.model_validate(semantic_profile)
            validate_semantic_profile_for_intent(semantic_profile_draft, intent_mode)
            semantic_profile_payload = semantic_profile_draft.model_dump(mode="json")
        else:
            semantic_profile_payload = None
        goal = self.repository.create_goal(
            user_id=user_id,
            space_id=space_id,
            target_node_id=target_node_id,
            title=title,
            intent_mode=intent_mode,
            semantic_profile=semantic_profile_payload,
            target_mastery_level=target_mastery_level,
            route_preference=route_preference,
            deadline=deadline,
            load_preference=load_preference,
        )
        self.repository.audit(
            user_id, "CREATE_GOAL", "LearningGoal", goal.id, after=model_dict(goal)
        )
        return model_dict(goal)

    def list_archived_projects(self, *, user_id: str) -> list[dict[str, Any]]:
        """Return recoverable projects without mixing them into active navigation."""

        archived = [
            goal
            for goal in self.repository.list_goals(user_id)
            if goal.status == GoalStatus.ARCHIVED.value
        ]
        summaries: list[dict[str, Any]] = []
        for goal in archived:
            path_count = int(
                self.repository.session.scalar(
                    select(func.count())
                    .select_from(LearningPathModel)
                    .where(LearningPathModel.goal_id == goal.id)
                )
                or 0
            )
            conversation_count = int(
                self.repository.session.scalar(
                    select(func.count())
                    .select_from(AIConversationModel)
                    .where(
                        AIConversationModel.user_id == user_id,
                        AIConversationModel.goal_id == goal.id,
                    )
                )
                or 0
            )
            summaries.append(
                {
                    "goal": model_dict(goal),
                    "archived_at": json_safe(_aware_datetime(goal.updated_at)),
                    "path_revision_count": path_count,
                    "conversation_count": conversation_count,
                }
            )
        return summaries

    def archive_project(self, *, user_id: str, goal_id: str) -> dict[str, Any]:
        """Move a project to the recoverable trash and hide its project conversations."""

        before = self.repository.get_goal(
            goal_id,
            user_id=user_id,
            include_archived=True,
        )
        before_payload = model_dict(before)
        goal, changed, conversation_ids = self.repository.archive_goal(
            goal_id,
            user_id=user_id,
        )
        if changed:
            self.repository.audit(
                user_id,
                "ARCHIVE_PROJECT",
                "LearningGoal",
                goal.id,
                before=before_payload,
                after=model_dict(goal),
                details={
                    "space_id": goal.space_id,
                    "auto_archived_conversation_ids": conversation_ids,
                    "retained_framework": True,
                    "retained_learning_history": True,
                },
            )
        return {
            "goal": model_dict(goal),
            "changed": changed,
            "archived_conversation_count": len(conversation_ids),
        }

    def restore_project(self, *, user_id: str, goal_id: str) -> dict[str, Any]:
        """Restore a trashed project and only conversations archived with that project."""

        before = self.repository.get_goal(
            goal_id,
            user_id=user_id,
            include_archived=True,
        )
        before_payload = model_dict(before)
        conversation_ids = self.repository.latest_project_archive_conversation_ids(
            goal_id=goal_id,
            user_id=user_id,
        )
        goal, changed, restored_conversation_ids = self.repository.restore_goal(
            goal_id,
            user_id=user_id,
            conversation_ids=conversation_ids,
        )
        if changed:
            self.repository.audit(
                user_id,
                "RESTORE_PROJECT",
                "LearningGoal",
                goal.id,
                before=before_payload,
                after=model_dict(goal),
                details={
                    "space_id": goal.space_id,
                    "restored_conversation_ids": restored_conversation_ids,
                },
            )
        return {
            "goal": model_dict(goal),
            "changed": changed,
            "restored_conversation_count": len(restored_conversation_ids),
        }

    def delete_project_permanently(
        self,
        *,
        user_id: str,
        goal_id: str,
        confirm_title: str | None,
    ) -> None:
        """Destroy a trashed project only after exact, user-visible confirmation."""

        goal = self.repository.get_goal(goal_id, user_id=user_id, include_archived=True)
        if goal.status != GoalStatus.ARCHIVED.value:
            raise InvalidStateTransitionError(
                "Only a project in the trash can be permanently deleted"
            )
        if confirm_title != goal.title:
            raise InvalidStateTransitionError(
                "Permanent deletion confirmation must exactly match the project title"
            )
        summary = self.repository.delete_goal_permanently(goal_id, user_id=user_id)
        attachment_storage_keys = [
            str(item) for item in summary.pop("attachment_storage_keys", []) if item
        ]
        self.attachment_storage.delete_many(attachment_storage_keys)
        self.repository.audit(
            user_id,
            "DELETE_PROJECT",
            "LearningGoal",
            goal_id,
            details={
                "permanent": True,
                "framework_deleted": bool(summary["framework_deleted"]),
                "deleted_path_count": int(summary["path_count"]),
                "deleted_path_node_count": int(summary["path_node_count"]),
                "deleted_check_in_count": int(summary["check_in_count"]),
                "deleted_cleared_progress_count": int(summary["cleared_progress_count"]),
                "deleted_attachment_count": int(summary["attachment_count"]),
                "deleted_conversation_count": int(summary["conversation_count"]),
                "deleted_message_count": int(summary["message_count"]),
                "deleted_suggestion_count": int(summary["suggestion_count"]),
                "title_confirmation_verified": True,
            },
        )

    def generate_path(
        self,
        *,
        user_id: str,
        goal_id: str,
        map_version_id: str | None = None,
        activate: bool = True,
        origin: PathOrigin = PathOrigin.ALGORITHM_GENERATED,
        change_summary: str = "",
    ) -> dict[str, Any]:
        goal = self.repository.get_goal(goal_id, user_id=user_id)
        self.repository.get_space(goal.space_id, user_id=user_id)
        resolved_map_version_id, nodes, edges = self.repository.load_graph(
            goal.space_id, map_version_id
        )
        engine = KnowledgeGraphService(nodes, edges)
        mastery = self.repository.get_mastery(user_id, {node.id for node in nodes})
        request = RouteRequest(
            target_node_id=goal.target_node_id,
            intent_mode=GoalIntent(goal.intent_mode),
            target_mastery_level=goal.target_mastery_level,
            preference=RoutePreference(goal.route_preference),
            algorithm_version=self.settings.algorithm_version,
        )
        recommendations = engine.generate_route(request, mastery)
        default_action_kind = {
            GoalIntent.LEARN: PathActionKind.LEARN,
            GoalIntent.UNDERSTAND: PathActionKind.EXPLORE,
            GoalIntent.DO: PathActionKind.EXECUTE,
        }[GoalIntent(goal.intent_mode)]
        items = [
            {
                **json_safe(asdict(item)),
                "status": item.status.value,
                "action_kind": default_action_kind.value,
            }
            for item in recommendations
        ]
        path = (
            self.repository.replace_path(
                goal=goal,
                map_version_id=resolved_map_version_id,
                algorithm_version=self.settings.algorithm_version,
                recommendations=items,
                origin=origin,
            )
            if activate
            else self.repository.create_path_revision(
                goal=goal,
                map_version_id=resolved_map_version_id,
                algorithm_version=self.settings.algorithm_version,
                recommendations=items,
                activate=False,
                origin=origin,
                change_summary=change_summary or "Generated editable path candidate",
            )
        )
        self.repository.audit(
            user_id,
            "GENERATE_PATH" if activate else "GENERATE_PATH_DRAFT",
            "LearningPath",
            path.id,
            after={
                "goal_id": goal_id,
                "node_count": len(items),
                "status": path.status,
                "origin": path.origin,
                "row_version": path.row_version,
            },
        )
        result: dict[str, Any] = {"path": model_dict(path), "items": items}
        if not activate:
            result["steps"] = self._path_revision_payload(path)["steps"]
        return result

    def _activate_navigation_path(
        self,
        *,
        user_id: str,
        goal: dict[str, Any],
        map_version_id: str,
        draft: LearningPlanDraft,
        node_ids: dict[str, str],
    ) -> dict[str, Any]:
        """Persist the reviewed AI navigation as the initial actionable path.

        The knowledge graph describes dependencies; the reviewed navigation
        describes the intended route.  Re-running the generic target-subgraph
        planner here used to discard stage order and could insert structural
        MODULE nodes.  Activation now materializes the accepted stage sequence
        directly, while still deriving live prerequisite explanations/statuses
        from the same graph.
        """

        goal_model = self.repository.get_goal(str(goal["id"]), user_id=user_id)
        _, nodes, edges = self.repository.load_graph(goal_model.space_id, map_version_id)
        node_by_id = {node.id: node for node in nodes}
        ordered_stage_nodes = [
            (stage, node_ids[temp_id])
            for stage in draft.navigation.stages
            for temp_id in stage.node_temp_ids
        ]
        relevant_ids = {node_id for _, node_id in ordered_stage_nodes}
        if any(
            node_by_id.get(node_id) is None or node_by_id[node_id].node_type is NodeType.MODULE
            for _, node_id in ordered_stage_nodes
        ):
            raise InvalidStateTransitionError(
                "Reviewed navigation contains a missing or structural module node"
            )

        mastery = self.repository.get_mastery(user_id, relevant_ids)
        engine = KnowledgeGraphService(nodes, edges)
        default_required_level = min(3, draft.navigation.target_mastery_level)
        default_action_kind = {
            GoalIntent.LEARN: PathActionKind.LEARN,
            GoalIntent.UNDERSTAND: PathActionKind.EXPLORE,
            GoalIntent.DO: PathActionKind.EXECUTE,
        }[draft.navigation.intent_mode]
        items: list[dict[str, Any]] = []
        for stage, node_id in ordered_stage_nodes:
            prerequisite_edges = [
                edge
                for edge in edges
                if edge.is_active
                and edge.relation_type is RelationType.PREREQUISITE
                and edge.target_node_id == node_id
                and edge.source_node_id in relevant_ids
            ]
            required_level = (
                draft.navigation.target_mastery_level
                if node_id == goal_model.target_node_id
                else max(
                    (edge.required_mastery_level for edge in prerequisite_edges),
                    default=default_required_level,
                )
            )
            satisfied = [
                edge.source_node_id
                for edge in prerequisite_edges
                if mastery.get(
                    edge.source_node_id, LearnerSnapshot(edge.source_node_id)
                ).mastery_level
                >= edge.required_mastery_level
            ]
            unmet = [
                edge.source_node_id
                for edge in prerequisite_edges
                if edge.source_node_id not in satisfied
            ]
            unlocks = [
                edge.target_node_id
                for edge in edges
                if edge.is_active
                and edge.relation_type is RelationType.PREREQUISITE
                and edge.source_node_id == node_id
                and edge.target_node_id in relevant_ids
            ]
            items.append(
                {
                    "node_id": node_id,
                    "title": node_by_id[node_id].title,
                    "required_mastery_level": required_level,
                    "reason": f"第 {stage.sequence} 阶段：{stage.objective}",
                    "satisfied_prerequisites": satisfied,
                    "unmet_prerequisites": unmet,
                    "unlocks": unlocks,
                    "algorithm_version": self.settings.algorithm_version,
                    "status": engine.classify_node(
                        node_id,
                        relevant_ids,
                        mastery,
                        target_mastery_level=required_level,
                    ).value,
                    "action_kind": default_action_kind.value,
                }
            )

        path = self.repository.replace_path(
            goal=goal_model,
            map_version_id=map_version_id,
            algorithm_version=self.settings.algorithm_version,
            recommendations=items,
            origin=PathOrigin.AI_GENERATED,
        )
        self.repository.audit(
            user_id,
            "ACTIVATE_REVIEWED_NAVIGATION",
            "LearningPath",
            path.id,
            after={
                "goal_id": goal_model.id,
                "node_count": len(items),
                "status": path.status,
                "origin": path.origin,
                "row_version": path.row_version,
            },
        )
        return {"path": model_dict(path), "items": items}

    def list_path_revisions(self, *, user_id: str, goal_id: str) -> list[dict[str, Any]]:
        return [
            self._path_revision_payload(path)
            for path in self.repository.list_path_revisions(
                goal_id=goal_id,
                user_id=user_id,
            )
        ]

    def get_path_revision(self, *, user_id: str, path_id: str) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        return self._path_revision_payload(path)

    def clone_path_revision(
        self,
        *,
        user_id: str,
        path_id: str,
        expected_revision: int,
        change_summary: str,
    ) -> dict[str, Any]:
        source = self.repository.get_path_revision(path_id, user_id=user_id)
        current_map_version_id, current_nodes, _ = self.repository.load_graph(source.space_id)
        allowed_node_ids = {node.id for node in current_nodes if node.is_active}
        clone = self.repository.clone_path_revision(
            source=source,
            expected_revision=expected_revision,
            change_summary=change_summary,
            target_map_version_id=current_map_version_id,
            allowed_node_ids=allowed_node_ids,
        )
        self.repository.audit(
            user_id,
            "CLONE_PATH_REVISION",
            "LearningPath",
            clone.id,
            before={"source_path_id": source.id, "source_row_version": expected_revision},
            after={
                **model_dict(clone),
                "rebased_from_map_version_id": source.map_version_id,
                "rebased_to_map_version_id": current_map_version_id,
            },
        )
        return self._path_revision_payload(clone)

    def add_path_step(
        self,
        *,
        user_id: str,
        path_id: str,
        expected_revision: int,
        node_id: str,
        preferred_order: int,
        required_mastery_level: int,
        recommendation_reason: str,
        is_required: bool,
        action_kind: PathActionKind,
        stage: str | None,
        priority: int,
        estimated_minutes: int | None,
        is_pinned: bool,
        is_deferred: bool,
        user_note: str | None,
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        _, nodes, _ = self.repository.load_graph(path.space_id, path.map_version_id)
        if node_id not in {node.id for node in nodes if node.is_active}:
            raise InvalidStateTransitionError(
                "Path steps must reference an active node in the path's map version"
            )
        item = self.repository.add_path_item(
            path=path,
            expected_revision=expected_revision,
            node_id=node_id,
            preferred_order=preferred_order,
            required_mastery_level=required_mastery_level,
            recommendation_reason=recommendation_reason,
            is_required=is_required,
            action_kind=action_kind.value,
            stage=stage,
            priority=priority,
            estimated_minutes=estimated_minutes,
            is_pinned=is_pinned,
            is_deferred=is_deferred,
            user_note=user_note,
        )
        self.repository.audit(
            user_id,
            "ADD_PATH_STEP",
            "LearningPathNode",
            item.id,
            after={**model_dict(item), "path_row_version": path.row_version},
        )
        return self._path_revision_payload(path)

    def update_path_step(
        self,
        *,
        user_id: str,
        path_id: str,
        step_id: str,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        before_item = self.repository.get_path_item(path.id, step_id)
        before = model_dict(before_item)
        if isinstance(changes.get("action_kind"), PathActionKind):
            changes["action_kind"] = changes["action_kind"].value
        item = self.repository.update_path_item(
            path=path,
            item_id=step_id,
            expected_revision=expected_revision,
            values=changes,
        )
        self.repository.audit(
            user_id,
            "UPDATE_PATH_STEP",
            "LearningPathNode",
            item.id,
            before=before,
            after={**model_dict(item), "path_row_version": path.row_version},
        )
        return self._path_revision_payload(path)

    def remove_path_step(
        self,
        *,
        user_id: str,
        path_id: str,
        step_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        item = self.repository.get_path_item(path.id, step_id)
        before = model_dict(item)
        self.repository.remove_path_item(
            path=path,
            item_id=step_id,
            expected_revision=expected_revision,
        )
        self.repository.audit(
            user_id,
            "REMOVE_PATH_STEP",
            "LearningPathNode",
            step_id,
            before=before,
            after={"path_row_version": path.row_version},
        )
        return self._path_revision_payload(path)

    def update_path_order(
        self,
        *,
        user_id: str,
        path_id: str,
        expected_revision: int,
        step_ids: list[str],
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        before = [item.id for item in self.repository.get_path_items(path.id)]
        self.repository.replace_path_item_order(
            path=path,
            expected_revision=expected_revision,
            item_ids=step_ids,
        )
        self.repository.audit(
            user_id,
            "REORDER_PATH",
            "LearningPath",
            path.id,
            before={"step_ids": before, "row_version": expected_revision},
            after={"step_ids": step_ids, "row_version": path.row_version},
        )
        return self._path_revision_payload(path)

    def validate_path_revision(
        self,
        *,
        user_id: str,
        path_id: str,
        expected_revision: int | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        if expected_revision is not None:
            self.repository.assert_path_revision(path, expected_revision)
        goal = self.repository.get_goal(path.goal_id, user_id=user_id)
        _, nodes, edges = self.repository.load_graph(path.space_id, path.map_version_id)
        active_node_ids = {node.id for node in nodes if node.is_active}
        items = self.repository.get_path_items(path.id)
        position_by_node = {item.node_id: item.preferred_order for item in items}
        mastery = self.repository.get_mastery(user_id, active_node_ids)
        issues: list[dict[str, object]] = []

        for item in items:
            if item.node_id not in active_node_ids:
                issues.append(
                    {
                        "code": "NODE_NOT_IN_MAP_VERSION",
                        "severity": "ERROR",
                        "step_id": item.id,
                        "node_id": item.node_id,
                        "message": "The step references a node absent from the base map version.",
                    }
                )

        target_mastery = mastery.get(goal.target_node_id)
        target_already_satisfied = (
            target_mastery is not None and target_mastery.mastery_level >= goal.target_mastery_level
        )
        if goal.target_node_id not in position_by_node and not target_already_satisfied:
            issues.append(
                {
                    "code": "MISSING_TARGET",
                    "severity": "ERROR",
                    "node_id": goal.target_node_id,
                    "message": "The goal target is not present and has not already been satisfied.",
                }
            )

        for edge in edges:
            if (
                not edge.is_active
                or edge.relation_type is not RelationType.PREREQUISITE
                or not edge.is_hard_requirement
                or edge.target_node_id not in position_by_node
            ):
                continue
            target_position = position_by_node[edge.target_node_id]
            source_position = position_by_node.get(edge.source_node_id)
            required_level = max(edge.required_mastery_level, 1)
            source_mastery = mastery.get(edge.source_node_id)
            source_already_satisfied = (
                source_mastery is not None and source_mastery.mastery_level >= required_level
            )
            if source_position is None and not source_already_satisfied:
                issues.append(
                    {
                        "code": "MISSING_PREREQUISITE",
                        "severity": "WARNING",
                        "node_id": edge.target_node_id,
                        "prerequisite_node_id": edge.source_node_id,
                        "required_mastery_level": required_level,
                        "message": (
                            "A recommended prerequisite is neither in the path nor mastered; "
                            "the path can still be activated."
                        ),
                    }
                )
            elif source_position is not None and source_position >= target_position:
                issues.append(
                    {
                        "code": "PREREQUISITE_ORDER",
                        "severity": "WARNING",
                        "node_id": edge.target_node_id,
                        "prerequisite_node_id": edge.source_node_id,
                        "message": (
                            "The recommended prerequisite does not appear before its dependent "
                            "step; the path can still be activated."
                        ),
                    }
                )

        valid = not any(issue.get("severity") == "ERROR" for issue in issues)
        if persist:
            path.validity_status = (
                PathValidityStatus.VALID.value if valid else PathValidityStatus.INVALID.value
            )
            self.repository.audit(
                user_id,
                "VALIDATE_PATH_REVISION",
                "LearningPath",
                path.id,
                after={
                    "validity_status": path.validity_status,
                    "issue_count": len(issues),
                    "row_version": path.row_version,
                },
            )
        return {
            "path_id": path.id,
            "row_version": path.row_version,
            "valid": valid,
            "validity_status": (
                PathValidityStatus.VALID.value if valid else PathValidityStatus.INVALID.value
            ),
            "issues": issues,
        }

    def activate_path_revision(
        self,
        *,
        user_id: str,
        path_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        path = self.repository.get_path_revision(path_id, user_id=user_id)
        validation = self.validate_path_revision(
            user_id=user_id,
            path_id=path_id,
            expected_revision=expected_revision,
        )
        issues = validation["issues"]
        if not validation["valid"]:
            raise InvalidPathRevisionError(issues if isinstance(issues, list) else [])
        before = model_dict(path)
        activated = self.repository.activate_path_revision(
            path,
            expected_revision=expected_revision,
        )
        self.repository.audit(
            user_id,
            "ACTIVATE_PATH_REVISION",
            "LearningPath",
            activated.id,
            before=before,
            after=model_dict(activated),
        )
        return self._path_revision_payload(activated)

    def _path_revision_payload(self, path: LearningPathModel) -> dict[str, Any]:
        # Stable node ids and path order belong to the revision. Labels belong
        # to the live editable framework and must update everywhere at once.
        _, nodes, _ = self.repository.load_graph(path.space_id)
        title_by_id = {node.id: node.title for node in nodes}
        return {
            "path": model_dict(path),
            "steps": [
                {**model_dict(item), "title": title_by_id.get(item.node_id, "")}
                for item in self.repository.get_path_items(path.id)
            ],
        }

    def explain_blockage(self, *, user_id: str, space_id: str, node_id: str) -> dict[str, Any]:
        self.repository.get_space(space_id, user_id=user_id)
        _, nodes, edges = self.repository.load_graph(space_id)
        mastery = self.repository.get_mastery(user_id, {node.id for node in nodes})
        explanation = KnowledgeGraphService(nodes, edges).explain_blockage(node_id, mastery)
        return cast(dict[str, Any], json_safe(asdict(explanation)))

    def node_learning_context(self, *, user_id: str, node_id: str) -> dict[str, Any]:
        self.repository.get_node_for_user(user_id, node_id)
        resources = list(
            self.repository.session.scalars(
                select(LearningResourceModel)
                .where(
                    LearningResourceModel.node_id == node_id,
                    LearningResourceModel.status != RecordStatus.ARCHIVED.value,
                )
                .order_by(LearningResourceModel.updated_at.desc())
            )
        )
        evidence = list(
            self.repository.session.scalars(
                select(LearningEvidenceModel)
                .where(
                    LearningEvidenceModel.user_id == user_id,
                    LearningEvidenceModel.node_id == node_id,
                )
                .order_by(LearningEvidenceModel.created_at.desc())
                .limit(20)
            )
        )
        sessions = list(
            self.repository.session.scalars(
                select(LearningSessionModel)
                .where(
                    LearningSessionModel.user_id == user_id,
                    LearningSessionModel.node_id == node_id,
                )
                .order_by(LearningSessionModel.started_at.desc())
                .limit(10)
            )
        )
        assessments = list(
            self.repository.session.scalars(
                select(AssessmentModel).where(
                    AssessmentModel.node_id == node_id,
                    AssessmentModel.status != RecordStatus.ARCHIVED.value,
                )
            )
        )
        route_rows = self.repository.session.execute(
            select(LearningPathNodeModel, LearningGoalModel)
            .join(LearningPathModel, LearningPathModel.id == LearningPathNodeModel.path_id)
            .join(LearningGoalModel, LearningGoalModel.id == LearningPathModel.goal_id)
            .where(
                LearningPathNodeModel.node_id == node_id,
                LearningPathModel.status == PathStatus.ACTIVE.value,
                LearningGoalModel.user_id == user_id,
                LearningGoalModel.status == GoalStatus.ACTIVE.value,
            )
        ).all()
        return {
            "resources": [model_dict(item) for item in resources],
            "evidence": [model_dict(item) for item in evidence],
            "sessions": [model_dict(item) for item in sessions],
            "assessments": [model_dict(item) for item in assessments],
            "route_reasons": [
                {
                    "goal_id": goal.id,
                    "goal_title": goal.title,
                    "reason": path_node.recommendation_reason,
                    "required_mastery_level": path_node.required_mastery_level,
                }
                for path_node, goal in route_rows
            ],
        }

    def update_mastery(
        self,
        *,
        user_id: str,
        node_id: str,
        update_kind: str,
        value: float | int,
        confidence: float | None = None,
        evidence_confidence: float = 1.0,
        verified_score: float | None = None,
        override: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self.repository.get_node_for_user(user_id, node_id)
        current_row = self.repository.get_state(user_id, node_id)
        current = (
            LearnerSnapshot(
                node_id=node_id,
                mastery_level=current_row.mastery_level,
                mastery_score=current_row.mastery_score,
                confidence=current_row.confidence,
                numeric_evidence_count=current_row.numeric_evidence_count,
                last_studied_at=current_row.last_studied_at,
                next_review_at=current_row.next_review_at,
            )
            if current_row
            else LearnerSnapshot(node_id)
        )
        if update_kind == "self_report":
            update = self.mastery_service.apply_self_report(current, float(value))
            evidence_type = EvidenceType.SELF_REPORT
        elif update_kind == "exercise_result":
            update = self.mastery_service.apply_exercise_result(
                current,
                float(value),
                evidence_confidence=evidence_confidence,
            )
            evidence_type = EvidenceType.EXERCISE_RESULT
        elif update_kind == "manual_review":
            update = self.mastery_service.apply_manual_review(
                current,
                int(value),
                confidence=confidence,
                verified_score=verified_score,
                override=override,
            )
            evidence_type = EvidenceType.MANUAL_REVIEW
        else:
            raise ValueError(f"Unsupported mastery update kind: {update_kind}")
        before_state = model_dict(current_row) if current_row else None
        values = {
            "mastery_level": update.mastery_level,
            "mastery_score": update.mastery_score,
            "confidence": update.confidence,
            "numeric_evidence_count": current.numeric_evidence_count
            + (1 if update_kind == "exercise_result" else 0),
            "state_source": update.source,
            "manually_overridden": update.manually_overridden,
            "algorithm_version": update.algorithm_version,
            "last_studied_at": (
                current.last_studied_at if update_kind == "self_report" else datetime.now(UTC)
            ),
            "next_review_at": update.next_review_at,
        }
        row = self.repository.save_state(user_id, node_id, values)
        self.repository.create_evidence(
            user_id=user_id,
            node_id=node_id,
            evidence_type=evidence_type.value,
            title=evidence_type.value.replace("_", " ").title(),
            content=reason,
            score=float(value) if update_kind == "exercise_result" else verified_score,
            metadata_json={
                "algorithm_version": update.algorithm_version,
                "audit_details": update.audit_details,
                "mastery_level": update.mastery_level,
            },
            reviewed_by=user_id if update_kind == "manual_review" else None,
            reviewed_at=datetime.now(UTC) if update_kind == "manual_review" else None,
        )
        self.repository.audit(
            user_id,
            "UPDATE_MASTERY",
            "LearnerNodeState",
            row.id,
            before=before_state,
            after=model_dict(row),
            details=update.audit_details,
        )
        return model_dict(row)

    def get_mastery_profile(self, *, user_id: str, node_id: str) -> dict[str, Any]:
        return self.mastery_profiles.get_profile(user_id=user_id, node_id=node_id)

    def record_mastery_profile_evidence(
        self,
        *,
        user_id: str,
        node_id: str,
        kind: Any,
        measurements: list[dict[str, Any]],
        evidence_confidence: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.mastery_profiles.record_evidence(
            user_id=user_id,
            node_id=node_id,
            kind=kind,
            measurements=measurements,
            evidence_confidence=evidence_confidence,
            note=note,
        )

    def list_progress_check_ins(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        rows = self.repository.list_progress_check_ins(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
            limit=limit,
            offset=offset,
        )
        latest = self.repository.latest_progress_check_in(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        today = self.repository.progress_check_in_for_date(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
            check_in_date=datetime.now().astimezone().date(),
        )
        attachment_rows = self.repository.list_progress_check_in_attachments(
            user_id=user_id,
            check_in_ids=[row.id for row in rows],
        )
        attachments_by_check_in: dict[str, list[ProgressCheckInAttachmentModel]] = {}
        for attachment in attachment_rows:
            attachments_by_check_in.setdefault(attachment.check_in_id, []).append(attachment)
        items = [
            _progress_check_in_dict(row, attachments_by_check_in.get(row.id, [])) for row in rows
        ]
        item_by_id = {str(item["id"]): item for item in items}
        clear_batch = self.repository.latest_progress_check_in_clear_batch(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        return {
            "items": items,
            "total": self.repository.count_progress_check_ins(
                user_id=user_id,
                goal_id=goal_id,
                node_id=node_id,
            ),
            "current_score": latest.score if latest is not None else None,
            "today_check_in": item_by_id.get(today.id) if today is not None else None,
            "clear_recovery": (
                _progress_check_in_clear_batch_dict(clear_batch)
                if clear_batch is not None
                else None
            ),
        }

    def get_progress_check_in(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        check_in_id: str,
    ) -> dict[str, Any]:
        """Return one exact, owned check-in within its project/node scope."""

        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        row = self.repository.get_progress_check_in(check_in_id, user_id=user_id)
        if row.goal_id != goal_id or row.node_id != node_id:
            raise EntityNotFoundError("progress check-in", check_in_id)
        return _progress_check_in_dict(
            row,
            self.repository.list_progress_check_in_attachments(
                user_id=user_id,
                check_in_ids=[row.id],
            ),
        )

    def create_progress_check_in(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        score: int,
        note: str | None = None,
        duration_minutes: int = 60,
    ) -> dict[str, Any]:
        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        now_local = datetime.now().astimezone()
        check_in_date = now_local.date()
        if (
            self.repository.progress_check_in_for_date(
                user_id=user_id,
                goal_id=goal_id,
                node_id=node_id,
                check_in_date=check_in_date,
            )
            is not None
        ):
            raise DuplicateProgressCheckInError(check_in_date=check_in_date.isoformat())

        latest = self.repository.latest_progress_check_in(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        if latest is not None and score < latest.score:
            raise ProgressScoreRegressionError(
                attempted_score=score,
                current_score=latest.score,
            )

        try:
            with self.repository.session.begin_nested():
                row = self.repository.create_progress_check_in(
                    user_id=user_id,
                    goal_id=goal_id,
                    node_id=node_id,
                    checked_in_at=now_local.astimezone(UTC),
                    check_in_date=check_in_date,
                    score=score,
                    note=_normalized_optional_text(note),
                    duration_minutes=duration_minutes,
                    row_version=1,
                )
        except IntegrityError as exc:
            # The unique constraint is the final guard against a double-click or
            # concurrent request after the read-side daily check above.
            raise DuplicateProgressCheckInError(check_in_date=check_in_date.isoformat()) from exc

        self.repository.audit(
            user_id,
            "CREATE_PROGRESS_CHECK_IN",
            "NodeProgressCheckIn",
            row.id,
            after=model_dict(row),
            details={"goal_id": goal_id, "node_id": node_id},
        )
        return _progress_check_in_dict(row, [])

    def update_progress_check_in(
        self,
        *,
        user_id: str,
        check_in_id: str,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.repository.get_progress_check_in(check_in_id, user_id=user_id)
        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=row.goal_id,
            node_id=row.node_id,
        )
        if row.row_version != expected_revision:
            raise ProgressCheckInRevisionConflictError(
                expected_revision=expected_revision,
                current_revision=row.row_version,
            )

        before = model_dict(row)
        previous_score = row.score
        if "score" in changes:
            row.score = int(changes["score"])
        if "note" in changes:
            row.note = _normalized_optional_text(changes["note"])
        if "duration_minutes" in changes:
            row.duration_minutes = int(changes["duration_minutes"])
        row.corrected_at = datetime.now(UTC)
        row.row_version += 1
        self.repository.session.flush()
        after = model_dict(row)
        self.repository.audit(
            user_id,
            "UPDATE_PROGRESS_CHECK_IN",
            "NodeProgressCheckIn",
            row.id,
            before=before,
            after=after,
            details={
                "goal_id": row.goal_id,
                "node_id": row.node_id,
                "score_decreased": row.score < previous_score,
            },
        )
        return _progress_check_in_dict(
            row,
            self.repository.list_progress_check_in_attachments(
                user_id=user_id,
                check_in_ids=[row.id],
            ),
        )

    async def evaluate_progress_check_in(
        self,
        *,
        user_id: str,
        check_in_id: str,
        provider_profile_id: str | None = None,
        confirmed_external_ai: bool = True,
    ) -> dict[str, Any]:
        """Generate bounded, evidence-aware feedback without changing mastery state."""

        row = self.repository.get_progress_check_in(check_in_id, user_id=user_id)
        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=row.goal_id,
            node_id=row.node_id,
        )
        node = self.repository.get_node_for_user(user_id, row.node_id)
        attachments = self.repository.list_progress_check_in_attachments(
            user_id=user_id,
            check_in_ids=[row.id],
        )
        excerpts: list[dict[str, str]] = []
        remaining_chars = 12_000
        text_suffixes = {".txt", ".md", ".csv", ".json", ".py", ".ipynb"}
        for attachment in attachments:
            if remaining_chars <= 0:
                break
            suffix = Path(attachment.original_name).suffix.lower()
            if not (
                str(attachment.media_type).lower().startswith("text/") or suffix in text_suffixes
            ):
                continue
            path = self.attachment_storage.path_for(attachment.storage_key)
            if not path.is_file():
                continue
            try:
                excerpt = path.read_text(encoding="utf-8", errors="replace")[:remaining_chars]
            except OSError:
                continue
            if excerpt.strip():
                excerpts.append({"name": attachment.original_name, "excerpt": excerpt})
                remaining_chars -= len(excerpt)

        provider, profile = self._resolve_ai_provider(
            user_id=user_id,
            provider_profile_id=provider_profile_id,
        )
        self._require_external_ai_confirmation(
            provider,
            confirmed_external_ai=confirmed_external_ai,
        )
        if provider.name == "mock":
            evidence_score = min(85, 25 + len(attachments) * 10 + (15 if row.note else 0))
            result = CheckInAIEvaluation(
                summary=(
                    f"已记录对“{node.title}”的推进：{len(attachments)} 个附件、"
                    f"{row.duration_minutes} 分钟投入。建议下一次补充可核验的解题或应用过程。"
                ),
                concept_understanding={
                    "score": evidence_score,
                    "comment": "记录显示已开始形成概念理解，仍需用自己的话解释。",
                },
                procedural_skill={
                    "score": max(15, evidence_score - 10),
                    "comment": "附件可作为练习痕迹，建议补充完整步骤与纠错过程。",
                },
                application_skill={
                    "score": max(10, evidence_score - 20),
                    "comment": "尚需增加迁移到新问题或实际任务的证据。",
                },
                memory_strength={
                    "score": max(10, evidence_score - 25),
                    "comment": "单次记录不足以判断保持度，建议间隔复习后再次验证。",
                },
                limitations="离线评估只参考备注、文件元数据和可读取文本，不识别图片内容。",
            )
        else:
            context = {
                "task": (
                    "根据学习者备注和附件证据生成简短、克制、可执行的四维评语。"
                    "不得把文件存在本身当作掌握证明。"
                ),
                "output_schema": CheckInAIEvaluation.model_json_schema(),
                "node": {"title": node.title, "description": node.description},
                "check_in": {
                    "score": row.score,
                    "note": row.note,
                    "duration_minutes": row.duration_minutes,
                },
                "attachments": [
                    {
                        "name": item.original_name,
                        "media_type": item.media_type,
                        "size_bytes": item.size_bytes,
                    }
                    for item in attachments[:30]
                ],
                "text_excerpts": excerpts,
                "constraints": {
                    "language": "zh-CN",
                    "summary": "不超过120个汉字",
                    "comments": "每项一句话，指出证据与下一步",
                    "image_limitation": "当前未执行图片OCR或视觉识别，不得声称看懂图片内容",
                },
            }
            raw = await provider.evaluate_explanation(context)
            candidate = raw.get("evaluation") if isinstance(raw.get("evaluation"), dict) else raw
            try:
                result = CheckInAIEvaluation.model_validate(candidate)
            except ValidationError as exc:
                raise AIOutputValidationError(
                    "AI progress feedback did not match the required structure."
                ) from exc

        before = model_dict(row)
        row.ai_evaluation = result.model_dump(mode="json")
        row.ai_evaluated_at = datetime.now(UTC)
        self.repository.session.flush()
        self.repository.audit(
            user_id,
            "EVALUATE_PROGRESS_CHECK_IN",
            "NodeProgressCheckIn",
            row.id,
            before=before,
            after=model_dict(row),
            details={
                "provider": provider.name,
                "model": provider.model,
                "provider_profile_id": profile.id if profile is not None else None,
                "attachment_count": len(attachments),
                "text_excerpt_count": len(excerpts),
            },
        )
        return _progress_check_in_dict(row, attachments)

    async def add_progress_check_in_attachment(
        self,
        *,
        user_id: str,
        check_in_id: str,
        original_name: str,
        media_type: str | None,
        chunks: AsyncIterable[bytes],
    ) -> dict[str, Any]:
        """Stream one file into durable storage and bind it to a check-in."""

        check_in = self.repository.get_progress_check_in(check_in_id, user_id=user_id)
        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=check_in.goal_id,
            node_id=check_in.node_id,
        )
        safe_name = original_name.replace("\x00", "").replace("\\", "/").rsplit("/", 1)[-1]
        safe_name = safe_name.strip()[:255] or "attachment"
        safe_media_type = str(media_type or "application/octet-stream").strip()[:255]
        storage_key = f"{user_id}/{check_in_id}/{new_id()}"
        stored = await self.attachment_storage.store(storage_key, chunks)
        try:
            attachment = self.repository.create_progress_check_in_attachment(
                user_id=user_id,
                check_in_id=check_in_id,
                original_name=safe_name,
                media_type=safe_media_type or "application/octet-stream",
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                storage_key=storage_key,
            )
        except BaseException:
            self.attachment_storage.delete(storage_key)
            raise
        payload = _progress_check_in_attachment_dict(attachment)
        self.repository.audit(
            user_id,
            "ADD_PROGRESS_CHECK_IN_ATTACHMENT",
            "ProgressCheckInAttachment",
            attachment.id,
            details={
                "check_in_id": check_in_id,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
                "media_type": attachment.media_type,
            },
        )
        return payload

    def get_progress_check_in_attachment_content(
        self,
        *,
        user_id: str,
        attachment_id: str,
    ) -> tuple[dict[str, Any], Path]:
        attachment = self.repository.get_progress_check_in_attachment(
            attachment_id,
            user_id=user_id,
        )
        path = self.attachment_storage.path_for(attachment.storage_key)
        if not path.is_file():
            raise EntityNotFoundError("progress check-in attachment content", attachment_id)
        return _progress_check_in_attachment_dict(attachment), path

    def delete_progress_check_in_attachment(
        self,
        *,
        user_id: str,
        attachment_id: str,
    ) -> None:
        attachment = self.repository.get_progress_check_in_attachment(
            attachment_id,
            user_id=user_id,
        )
        self.repository.get_progress_check_in(attachment.check_in_id, user_id=user_id)
        storage_key = attachment.storage_key
        self.repository.delete_progress_check_in_attachment(
            attachment_id,
            user_id=user_id,
        )
        self.attachment_storage.delete(storage_key)
        self.repository.audit(
            user_id,
            "DELETE_PROGRESS_CHECK_IN_ATTACHMENT",
            "ProgressCheckInAttachment",
            attachment_id,
            details={
                "check_in_id": attachment.check_in_id,
                "content_deleted": True,
            },
        )

    def clear_progress_check_ins(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        expected_check_in_id: str | None,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        """Remove every live check-in while retaining one local recovery batch."""

        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        latest = self.repository.latest_progress_check_in(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        if latest is None:
            if expected_check_in_id is not None or expected_revision is not None:
                raise ProgressCheckInRevisionConflictError(
                    expected_check_in_id=expected_check_in_id,
                    expected_revision=expected_revision,
                    current_check_in_id=None,
                    current_revision=None,
                )
            recovery = self.repository.latest_progress_check_in_clear_batch(
                user_id=user_id,
                goal_id=goal_id,
                node_id=node_id,
            )
            # There is nothing live to clear.  Do not create an empty history row.
            return {
                "current_score": None,
                "display_progress_state": DISPLAY_PROGRESS_NOT_STARTED,
                "changed": False,
                "clear_recovery": (
                    _progress_check_in_clear_batch_dict(recovery) if recovery is not None else None
                ),
            }

        if (
            expected_check_in_id != latest.id
            or expected_revision is None
            or expected_revision != latest.row_version
        ):
            raise ProgressCheckInRevisionConflictError(
                expected_check_in_id=expected_check_in_id,
                expected_revision=expected_revision,
                current_check_in_id=latest.id,
                current_revision=latest.row_version,
            )

        rows = self.repository.list_progress_check_ins(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
            limit=1_000_000,
            offset=0,
        )
        attachments = self.repository.list_progress_check_in_attachments(
            user_id=user_id,
            check_in_ids=[row.id for row in rows],
        )
        attachments_by_check_in: dict[str, list[ProgressCheckInAttachmentModel]] = {}
        for attachment in attachments:
            attachments_by_check_in.setdefault(attachment.check_in_id, []).append(attachment)
        snapshot_items: list[dict[str, Any]] = []
        for row in rows:
            check_in_payload = model_dict(row)
            legacy_reset_marker = int(check_in_payload.get("score", 0)) == 0
            if legacy_reset_marker:
                # Keep the payload compatible with the 1..10 snapshot schema.
                # Restore deliberately skips this synthetic legacy marker; it
                # is retained only so any local attachment keys stay traceable.
                check_in_payload["score"] = 1
            snapshot_items.append(
                {
                    "check_in": check_in_payload,
                    "attachments": [
                        model_dict(item) for item in attachments_by_check_in.get(row.id, [])
                    ],
                    "legacy_reset_marker": legacy_reset_marker,
                }
            )
        cleared_at = datetime.now(UTC)
        batch = self.repository.move_progress_check_ins_to_recycle_bin(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
            check_in_ids=[row.id for row in rows],
            attachment_ids=[item.id for item in attachments],
            snapshot={"version": 1, "check_ins": snapshot_items},
            record_count=len(rows),
            attachment_count=len(attachments),
            cleared_at=cleared_at,
        )
        self.repository.audit(
            user_id,
            "CLEAR_PROGRESS_CHECK_INS",
            "ProgressCheckInClearBatch",
            batch.id,
            details={
                "goal_id": goal_id,
                "node_id": node_id,
                "record_count": len(rows),
                "attachment_count": len(attachments),
                "recoverable": True,
            },
        )
        return {
            "current_score": None,
            "display_progress_state": DISPLAY_PROGRESS_NOT_STARTED,
            "changed": True,
            "clear_recovery": _progress_check_in_clear_batch_dict(batch),
        }

    def restore_cleared_progress_check_ins(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        batch_id: str,
    ) -> dict[str, Any]:
        """Restore one clear batch only while the live timeline is still empty."""

        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        batch = self.repository.get_progress_check_in_clear_batch(
            batch_id,
            user_id=user_id,
        )
        if batch.goal_id != goal_id or batch.node_id != node_id:
            raise EntityNotFoundError("cleared progress", batch_id)
        if batch.restored_at is not None:
            raise InvalidStateTransitionError("Cleared progress has already been restored")
        if (
            self.repository.latest_progress_check_in(
                user_id=user_id,
                goal_id=goal_id,
                node_id=node_id,
            )
            is not None
        ):
            raise InvalidStateTransitionError(
                "New progress exists; clear it before restoring the previous timeline"
            )
        raw_items = batch.snapshot.get("check_ins", [])
        if not isinstance(raw_items, list) or not raw_items:
            raise InvalidStateTransitionError("Cleared progress snapshot is invalid")
        check_ins: list[dict[str, Any]] = []
        attachments: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise InvalidStateTransitionError("Cleared progress snapshot is invalid")
            # Releases before the recycle-bin workflow represented a reset by
            # appending a synthetic 0/10 check-in.  The migration retains that
            # opaque item only so its local attachment keys remain traceable,
            # but it is not learner progress and must never be restored as a
            # fabricated 1/10 check-in.
            if bool(raw_item.get("legacy_reset_marker")):
                continue
            check_in = raw_item.get("check_in")
            raw_attachments = raw_item.get("attachments", [])
            if not isinstance(check_in, dict) or not isinstance(raw_attachments, list):
                raise InvalidStateTransitionError("Cleared progress snapshot is invalid")
            check_ins.append(_restored_progress_check_in_values(check_in))
            attachments.extend(
                _restored_progress_attachment_values(item)
                for item in raw_attachments
                if isinstance(item, dict)
            )
        restored_at = datetime.now(UTC)
        self.repository.restore_progress_check_in_clear_batch(
            batch=batch,
            check_ins=check_ins,
            attachments=attachments,
            restored_at=restored_at,
        )
        self.repository.audit(
            user_id,
            "RESTORE_CLEARED_PROGRESS_CHECK_INS",
            "ProgressCheckInClearBatch",
            batch.id,
            details={
                "goal_id": goal_id,
                "node_id": node_id,
                "record_count": len(check_ins),
                "attachment_count": len(attachments),
            },
        )
        return self.list_progress_check_ins(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )

    def delete_cleared_progress_check_ins_permanently(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
        batch_id: str,
    ) -> None:
        """Destroy one recycle-bin snapshot and all files retained only by it."""

        self._validate_progress_check_in_scope(
            user_id=user_id,
            goal_id=goal_id,
            node_id=node_id,
        )
        batch = self.repository.get_progress_check_in_clear_batch(
            batch_id,
            user_id=user_id,
        )
        if batch.goal_id != goal_id or batch.node_id != node_id:
            raise EntityNotFoundError("cleared progress", batch_id)
        if batch.restored_at is not None:
            raise InvalidStateTransitionError(
                "Restored progress is no longer available in the recycle bin"
            )

        storage_keys: list[str] = []
        raw_items = batch.snapshot.get("check_ins", [])
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                raw_attachments = raw_item.get("attachments", [])
                if not isinstance(raw_attachments, list):
                    continue
                storage_keys.extend(
                    str(attachment["storage_key"])
                    for attachment in raw_attachments
                    if isinstance(attachment, dict) and attachment.get("storage_key")
                )

        record_count = batch.record_count
        attachment_count = batch.attachment_count
        self.repository.delete_progress_check_in_clear_batch(batch)
        self.repository.audit(
            user_id,
            "DELETE_CLEARED_PROGRESS_CHECK_INS",
            "ProgressCheckInClearBatch",
            batch_id,
            details={
                "goal_id": goal_id,
                "node_id": node_id,
                "record_count": record_count,
                "attachment_count": attachment_count,
                "permanent": True,
                "content_deleted": True,
            },
        )

        # The database is the source of reachability for locally retained files.
        # Commit the irreversible metadata deletion before removing file bytes so a
        # later request rollback cannot resurrect a recovery snapshot whose files
        # have already disappeared.
        self.repository.session.commit()
        self.attachment_storage.delete_many(sorted(set(storage_keys)))

    def _validate_progress_check_in_scope(
        self,
        *,
        user_id: str,
        goal_id: str,
        node_id: str,
    ) -> tuple[LearningGoalModel, KnowledgeNodeModel]:
        goal = self.repository.get_goal(goal_id, user_id=user_id)
        self.repository.get_space(goal.space_id, user_id=user_id)
        node = self.repository.get_node_for_user(user_id, node_id)
        if node.space_id != goal.space_id:
            # Return the same not-found shape used for cross-user access so a
            # caller cannot use this endpoint to probe unrelated project nodes.
            raise EntityNotFoundError("project node", node_id)
        return goal, node

    def record_learning_session(
        self,
        *,
        user_id: str,
        node_id: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        resource_ids: list[str] | None = None,
        note: str | None = None,
        difficulties: str | None = None,
        self_rating: int | None = None,
        next_step: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.repository.get_node_for_user(user_id, node_id)
        if ended_at is not None and ended_at < started_at:
            raise ValueError("ended_at must not precede started_at")
        row = self.repository.create_learning_session(
            user_id=user_id,
            node_id=node_id,
            started_at=started_at,
            ended_at=ended_at,
            resource_ids=resource_ids or [],
            note=note,
            difficulties=difficulties,
            self_rating=self_rating,
            next_step=next_step,
        )
        evidence_rows = []
        for item in evidence or []:
            evidence_type = EvidenceType(item["evidence_type"])
            evidence_rows.append(
                self.repository.create_evidence(
                    user_id=user_id,
                    node_id=node_id,
                    session_id=row.id,
                    evidence_type=evidence_type.value,
                    title=item.get("title", evidence_type.value.replace("_", " ").title()),
                    content=item.get("content"),
                    artifact_url=item.get("artifact_url"),
                    score=item.get("score"),
                    metadata_json=item.get("metadata", {}),
                )
            )
        self.repository.audit(user_id, "RECORD_SESSION", "LearningSession", row.id)
        return {
            "session": model_dict(row),
            "evidence": [model_dict(item) for item in evidence_rows],
        }

    def list_learning_sessions(
        self,
        *,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return the learner timeline page without coupling it to full data export."""

        rows = self.repository.list_learning_sessions(
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        node_ids = {row.node_id for row in rows}
        nodes = (
            list(
                self.repository.session.scalars(
                    select(KnowledgeNodeModel).where(KnowledgeNodeModel.id.in_(node_ids))
                )
            )
            if node_ids
            else []
        )
        node_by_id = {node.id: node for node in nodes}
        session_ids = {row.id for row in rows}
        evidence_rows = (
            list(
                self.repository.session.scalars(
                    select(LearningEvidenceModel).where(
                        LearningEvidenceModel.session_id.in_(session_ids)
                    )
                )
            )
            if session_ids
            else []
        )
        evidence_count: dict[str, int] = {}
        for evidence in evidence_rows:
            if evidence.session_id is not None:
                evidence_count[evidence.session_id] = evidence_count.get(evidence.session_id, 0) + 1
        items: list[dict[str, Any]] = []
        for row in rows:
            node = node_by_id.get(row.node_id)
            items.append(
                {
                    **model_dict(row),
                    "node": (
                        {
                            "id": node.id,
                            "title": node.title,
                            "space_id": node.space_id,
                        }
                        if node is not None
                        else {"id": row.node_id, "title": "", "space_id": None}
                    ),
                    "duration_minutes": _session_duration_minutes(row),
                    "evidence_count": evidence_count.get(row.id, 0),
                }
            )
        return {
            "items": items,
            "total": self.repository.count_learning_sessions(user_id=user_id),
            "limit": limit,
            "offset": offset,
        }

    def growth(self, *, user_id: str, days: int = 30) -> dict[str, Any]:
        """Build a stable growth read model from the learner facts available today.

        Historical scalar mastery snapshots do not exist yet, so the series deliberately
        reports activity and cumulative knowledge coverage rather than inventing past mastery.
        The summary exposes the current persisted mastery projection separately.
        """

        now = datetime.now().astimezone()
        end_date = now.date()
        start_date = end_date - timedelta(days=days - 1)
        sessions = list(
            self.repository.session.scalars(
                select(LearningSessionModel).where(LearningSessionModel.user_id == user_id)
            )
        )
        evidence = list(
            self.repository.session.scalars(
                select(LearningEvidenceModel).where(LearningEvidenceModel.user_id == user_id)
            )
        )
        states = list(
            self.repository.session.scalars(
                select(LearnerNodeStateModel).where(LearnerNodeStateModel.user_id == user_id)
            )
        )
        check_ins = list(
            self.repository.session.scalars(
                select(NodeProgressCheckInModel)
                .join(LearningGoalModel, LearningGoalModel.id == NodeProgressCheckInModel.goal_id)
                .where(
                    NodeProgressCheckInModel.user_id == user_id,
                    LearningGoalModel.status == GoalStatus.ACTIVE.value,
                )
            )
        )
        check_in_attachments = self.repository.list_progress_check_in_attachments(
            user_id=user_id,
            check_in_ids=[row.id for row in check_ins],
        )
        attachment_count_by_check_in: dict[str, int] = {}
        for attachment in check_in_attachments:
            attachment_count_by_check_in[attachment.check_in_id] = (
                attachment_count_by_check_in.get(attachment.check_in_id, 0) + 1
            )
        owned_nodes = list(
            self.repository.session.scalars(
                select(KnowledgeNodeModel)
                .join(KnowledgeSpaceModel, KnowledgeSpaceModel.id == KnowledgeNodeModel.space_id)
                .join(LearningGoalModel, LearningGoalModel.space_id == KnowledgeSpaceModel.id)
                .where(
                    KnowledgeSpaceModel.owner_id == user_id,
                    KnowledgeSpaceModel.status != RecordStatus.ARCHIVED.value,
                    LearningGoalModel.status == GoalStatus.ACTIVE.value,
                    KnowledgeNodeModel.status != RecordStatus.ARCHIVED.value,
                    KnowledgeNodeModel.node_type != NodeType.MODULE.value,
                )
                .distinct()
            )
        )

        owned_node_ids = {row.id for row in owned_nodes}
        owned_node_by_id = {row.id: row for row in owned_nodes}
        # Growth is a projection of the projects the user can still act on.  Keeping
        # archived/orphaned project activity here made the cards disagree with the
        # project dashboard after a project was removed.
        sessions = [row for row in sessions if row.node_id in owned_node_ids]
        evidence = [row for row in evidence if row.node_id in owned_node_ids]
        states = [row for row in states if row.node_id in owned_node_ids]
        touched_node_ids = {
            *(row.node_id for row in sessions),
            *(row.node_id for row in evidence),
            *(row.node_id for row in states),
            *(row.node_id for row in check_ins if row.score > 0),
        } & owned_node_ids
        total_nodes = len(owned_nodes)
        state_by_node = {row.node_id: row for row in states if row.node_id in owned_node_ids}
        latest_check_in_by_node: dict[str, NodeProgressCheckInModel] = {}
        for row in sorted(check_ins, key=lambda item: item.checked_in_at):
            latest_check_in_by_node[row.node_id] = row
        tracked_node_ids = set(state_by_node) | set(latest_check_in_by_node)
        normalized_scores = [
            (
                latest_check_in_by_node[node_id].score / 10
                if node_id in latest_check_in_by_node
                else state_by_node[node_id].mastery_score
            )
            for node_id in tracked_node_ids
        ]
        average_mastery_score = (
            sum(normalized_scores) / len(normalized_scores) * 100 if normalized_scores else 0.0
        )
        overall_progress_rate = sum(normalized_scores) / total_nodes * 100 if total_nodes else 0.0
        mastered_nodes = sum(
            (
                latest_check_in_by_node[node_id].score >= 10
                if node_id in latest_check_in_by_node
                else state_by_node[node_id].mastery_level >= self.settings.mastery_required_level
            )
            for node_id in tracked_node_ids
        )
        review_due_nodes = sum(
            row.next_review_at is not None and _aware_datetime(row.next_review_at) <= now
            for row in states
        )
        total_learning_minutes = round(
            sum(_session_duration_minutes(row) for row in sessions)
            + sum(row.duration_minutes for row in check_ins),
            2,
        )
        activity_dates = {
            *(_aware_datetime(row.started_at).astimezone().date() for row in sessions),
            *(_aware_datetime(row.created_at).astimezone().date() for row in evidence),
            *(row.check_in_date for row in check_ins),
        }
        activity_times = [
            *(_aware_datetime(row.started_at) for row in sessions),
            *(_aware_datetime(row.created_at) for row in evidence),
            *(_aware_datetime(row.checked_in_at) for row in check_ins),
        ]

        buckets: dict[date, dict[str, Any]] = {
            start_date + timedelta(days=index): {
                "session_count": 0,
                "evidence_count": 0,
                "check_in_count": 0,
                "learning_minutes": 0.0,
                "node_ids": set(),
            }
            for index in range(days)
        }
        cumulative_nodes = (
            {
                row.node_id
                for row in sessions
                if _aware_datetime(row.started_at).astimezone().date() < start_date
            }
            | {
                row.node_id
                for row in evidence
                if _aware_datetime(row.created_at).astimezone().date() < start_date
            }
            | {
                row.node_id
                for row in states
                if _aware_datetime(row.updated_at).astimezone().date() < start_date
            }
            | {row.node_id for row in check_ins if row.check_in_date < start_date and row.score > 0}
        ) & owned_node_ids

        for session_row in sessions:
            event_date = _aware_datetime(session_row.started_at).astimezone().date()
            bucket = buckets.get(event_date)
            if bucket is not None:
                bucket["session_count"] += 1
                bucket["learning_minutes"] += _session_duration_minutes(session_row)
                bucket["node_ids"].add(session_row.node_id)
        for evidence_row in evidence:
            event_date = _aware_datetime(evidence_row.created_at).astimezone().date()
            bucket = buckets.get(event_date)
            if bucket is not None:
                bucket["evidence_count"] += 1
                bucket["node_ids"].add(evidence_row.node_id)
        for state_row in states:
            event_date = _aware_datetime(state_row.updated_at).astimezone().date()
            bucket = buckets.get(event_date)
            if bucket is not None:
                bucket["node_ids"].add(state_row.node_id)
        for check_in_row in check_ins:
            bucket = buckets.get(check_in_row.check_in_date)
            if bucket is not None:
                bucket["check_in_count"] += 1
                bucket["learning_minutes"] += check_in_row.duration_minutes
                if check_in_row.score > 0:
                    bucket["node_ids"].add(check_in_row.node_id)

        series: list[dict[str, Any]] = []
        for event_date, bucket in buckets.items():
            bucket["node_ids"].intersection_update(owned_node_ids)
            cumulative_nodes.update(bucket["node_ids"])
            series.append(
                {
                    "date": event_date.isoformat(),
                    "session_count": bucket["session_count"],
                    "evidence_count": bucket["evidence_count"],
                    "check_in_count": bucket["check_in_count"],
                    "learning_minutes": round(bucket["learning_minutes"], 2),
                    "nodes_touched": len(bucket["node_ids"]),
                    "cumulative_nodes_touched": len(cumulative_nodes),
                    "coverage_rate": round(len(cumulative_nodes) / total_nodes * 100, 2)
                    if total_nodes
                    else 0.0,
                }
            )

        return {
            "summary": {
                "total_nodes": total_nodes,
                "touched_nodes": len(touched_node_ids),
                "tracked_nodes": len(tracked_node_ids),
                "mastered_nodes": mastered_nodes,
                "review_due_nodes": review_due_nodes,
                "coverage_rate": round(len(touched_node_ids) / total_nodes * 100, 2)
                if total_nodes
                else 0.0,
                "average_mastery_score": round(average_mastery_score, 2),
                "overall_progress_rate": round(overall_progress_rate, 2),
                "total_sessions": len(sessions),
                "total_check_ins": len(check_ins),
                "total_evidence": len(evidence),
                "upload_event_count": len(attachment_count_by_check_in),
                "uploaded_file_count": len(check_in_attachments),
                "total_learning_minutes": total_learning_minutes,
                "active_days": len(activity_dates),
                "last_activity_at": max(activity_times).isoformat() if activity_times else None,
            },
            "series": series,
            "check_ins": [
                {
                    **model_dict(row),
                    "attachment_count": attachment_count_by_check_in.get(row.id, 0),
                    "node": (
                        {
                            "id": node.id,
                            "title": node.title,
                            "space_id": node.space_id,
                        }
                        if (node := owned_node_by_id.get(row.node_id)) is not None
                        else {"id": row.node_id, "title": "", "space_id": None}
                    ),
                }
                for row in sorted(check_ins, key=lambda item: item.checked_in_at, reverse=True)[:50]
            ],
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        }

    async def generate_ai_suggestion(
        self,
        *,
        user_id: str,
        source_text: str,
        space_id: str | None = None,
        provider_profile_id: str | None = None,
        confirmed_external_ai: bool = False,
    ) -> dict[str, Any]:
        if space_id is not None:
            self.repository.get_space(space_id, user_id=user_id)
        provider, profile = self._resolve_ai_provider(
            user_id=user_id,
            provider_profile_id=provider_profile_id,
        )
        self._require_external_ai_confirmation(
            provider,
            confirmed_external_ai=confirmed_external_ai,
        )
        try:
            draft = await provider.generate_knowledge_map(source_text)
            analyzed = analyze_draft(draft)
        except (ValidationError, ValueError, KeyError) as exc:
            raise AIOutputValidationError(f"AI output was rejected: {exc}") from exc
        confidence_values = [node.confidence for node in draft.nodes] + [
            edge.confidence for edge in draft.edges
        ]
        average_confidence = (
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        )
        sources = sorted(
            {
                reference
                for node in draft.nodes
                for source in node.source_basis
                if (
                    reference := (
                        source
                        if isinstance(source, str)
                        else source.get("reference") or source.get("url") or source.get("title")
                    )
                )
            }
        )
        suggestion = self.repository.create_suggestion(
            user_id=user_id,
            space_id=space_id,
            suggestion_type=SuggestionType.KNOWLEDGE_MAP.value,
            target_type="KnowledgeSpace" if space_id else None,
            target_id=space_id,
            provider=provider.name,
            model=provider.model,
            prompt_version="knowledge-map-prompt-v2",
            raw_structured_output=draft.model_dump(mode="json"),
            proposed_changes=analyzed.model_dump(mode="json"),
            reason="AI-generated map draft awaiting human review",
            confidence=average_confidence,
            sources=sources,
            review_status=(
                ReviewStatus.CONFLICT.value if analyzed.conflicts else ReviewStatus.PENDING.value
            ),
        )
        self.repository.audit(
            user_id,
            "CREATE_AI_SUGGESTION",
            "AISuggestion",
            suggestion.id,
            details={
                "provider": provider.name,
                "model": provider.model,
                "provider_profile_id": profile.id if profile else None,
                "conflicts": len(analyzed.conflicts),
            },
        )
        return model_dict(suggestion)

    async def generate_ai_mind_map(
        self,
        *,
        user_id: str,
        goal_id: str,
        provider_profile_id: str | None = None,
        confirmed_external_ai: bool = False,
    ) -> dict[str, Any]:
        """Generate a reviewable view proposal without creating a second graph.

        The framework graph and active route remain the only source of truth.  The
        model may choose a focus and module ordering, but it can only reference
        existing IDs; this keeps edits in the framework/path editor synchronized
        with the mind map automatically.
        """

        goal = self.repository.get_goal(goal_id, user_id=user_id)
        graph = self.graph_view(space_id=goal.space_id, user_id=user_id)
        active_path = next(
            (
                path
                for path in self.repository.list_path_revisions(
                    goal_id=goal_id,
                    user_id=user_id,
                )
                if path.status == PathStatus.ACTIVE.value
            ),
            None,
        )
        route_items = (
            [
                {
                    "node_id": str(item.node_id),
                    "sequence": int(item.sequence_number),
                }
                for item in self.repository.get_path_items(active_path.id)
            ]
            if active_path is not None
            else []
        )
        provider, profile = self._resolve_ai_provider(
            user_id=user_id,
            provider_profile_id=provider_profile_id,
        )
        self._require_external_ai_confirmation(
            provider,
            confirmed_external_ai=confirmed_external_ai,
        )

        nodes = [
            {
                "id": str(node.get("id")),
                "title": str(node.get("title") or ""),
                "node_type": str(node.get("node_type") or ""),
                "outline_order": node.get("outline_order"),
            }
            for node in graph.get("nodes", [])
            if isinstance(node, dict)
            and node.get("status") != RecordStatus.ARCHIVED.value
            and node.get("id")
        ][:120]
        node_ids = {item["id"] for item in nodes}
        edges = [
            {
                "source": str(edge.get("source_node_id")),
                "target": str(edge.get("target_node_id")),
                "relation_type": str(edge.get("relation_type") or "RELATED"),
            }
            for edge in graph.get("edges", [])
            if isinstance(edge, dict)
            and str(edge.get("source_node_id")) in node_ids
            and str(edge.get("target_node_id")) in node_ids
        ][:240]
        module_ids = {
            item["id"] for item in nodes if item.get("node_type") == NodeType.MODULE.value
        }
        target_id = str(goal.target_node_id)
        context = {
            "task": "mind_map_view",
            "rule": (
                "Reference existing node IDs only; do not create, rename, delete, "
                "or edit graph data."
            ),
            "goal": {"id": str(goal.id), "title": goal.title, "target_node_id": target_id},
            "outline_revision": graph.get("outline_revision"),
            "path": {
                "id": str(active_path.id) if active_path is not None else None,
                "row_version": int(active_path.row_version) if active_path is not None else None,
                "items": route_items[:240],
            },
            "nodes": nodes,
            "edges": edges,
        }
        response_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "focus_node_ids": {"type": "array", "items": {"type": "string"}},
                "module_order": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "focus_node_ids", "module_order", "notes"],
            "additionalProperties": False,
        }
        try:
            raw = await provider.collaborate(context, response_schema=response_schema)
        except (ValidationError, ValueError, KeyError) as exc:
            raise AIOutputValidationError(f"AI mind-map output was rejected: {exc}") from exc

        raw = raw if isinstance(raw, dict) else {}
        focus_node_ids = [
            str(value) for value in raw.get("focus_node_ids", []) if str(value) in node_ids
        ][:16]
        module_order = [
            str(value) for value in raw.get("module_order", []) if str(value) in module_ids
        ][:32]
        if target_id in node_ids and target_id not in focus_node_ids:
            focus_node_ids.insert(0, target_id)
        remaining_module_ids = {str(value) for value in module_ids if value is not None}
        module_order.extend(sorted(remaining_module_ids - set(module_order)))
        summary = str(raw.get("summary") or "").strip()[:1200]
        notes = [str(value).strip()[:300] for value in raw.get("notes", []) if str(value).strip()][
            :12
        ]
        proposed_changes = {
            "schema_version": "mind-map-v1",
            "source_outline_revision": int(graph.get("outline_revision") or 1),
            "source_path_revision": (
                int(active_path.row_version) if active_path is not None else None
            ),
            "focus_node_ids": focus_node_ids,
            "module_order": module_order,
            "summary": summary,
            "notes": notes,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        suggestion = self.repository.create_suggestion(
            user_id=user_id,
            space_id=goal.space_id,
            suggestion_type=SuggestionType.MIND_MAP.value,
            target_type="LearningGoal",
            target_id=goal_id,
            provider=provider.name,
            model=provider.model,
            prompt_version="mind-map-view-prompt-v1",
            raw_structured_output=json_safe(raw),
            proposed_changes=proposed_changes,
            reason="AI-generated mind-map view proposal; framework and path remain authoritative",
            confidence=0.8 if focus_node_ids else 0.5,
            sources=[
                f"knowledge-space:{goal.space_id}",
                f"outline-revision:{graph.get('outline_revision', 1)}",
            ],
            review_status=ReviewStatus.PENDING.value,
        )
        self.repository.audit(
            user_id,
            "CREATE_AI_MIND_MAP",
            "AISuggestion",
            suggestion.id,
            details={
                "provider": provider.name,
                "model": provider.model,
                "provider_profile_id": profile.id if profile else None,
                "outline_revision": graph.get("outline_revision"),
            },
        )
        return {
            **model_dict(suggestion),
            "mind_map": proposed_changes,
            "source": {
                "space_id": goal.space_id,
                "outline_revision": graph.get("outline_revision"),
            },
        }

    async def generate_ai_learning_plan(
        self,
        *,
        user_id: str,
        topic: str,
        requirements: str,
        provider_profile_id: str | None = None,
        confirmed_external_ai: bool = False,
    ) -> dict[str, Any]:
        provider, profile = self._resolve_ai_provider(
            user_id=user_id,
            provider_profile_id=provider_profile_id,
        )
        self._require_external_ai_confirmation(
            provider,
            confirmed_external_ai=confirmed_external_ai,
        )
        normalized_topic = topic.strip()
        normalized_requirements = requirements.strip()
        try:
            plan = await provider.generate_learning_plan(normalized_topic, normalized_requirements)
            analyzed = analyze_draft(plan)
        except (ValidationError, ValueError, KeyError) as exc:
            raise AIOutputValidationError(f"AI learning plan was rejected: {exc}") from exc

        confidence_values = [node.confidence for node in plan.nodes] + [
            edge.confidence for edge in plan.edges
        ]
        average_confidence = (
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        )
        sources = sorted(
            {
                reference
                for node in plan.nodes
                for source in node.source_basis
                if (
                    reference := (
                        source
                        if isinstance(source, str)
                        else source.get("reference") or source.get("url") or source.get("title")
                    )
                )
            }
        )
        proposed_changes = analyzed.model_dump(mode="json")
        proposed_changes["navigation"] = plan.navigation.model_dump(mode="json")
        proposed_changes["generation_input"] = {
            "topic": normalized_topic,
            "requirements": normalized_requirements,
        }
        proposed_changes["schema_version"] = "learning-plan-v1"
        suggestion = self.repository.create_suggestion(
            user_id=user_id,
            space_id=None,
            suggestion_type=SuggestionType.LEARNING_PLAN.value,
            target_type="LearningPlan",
            target_id=None,
            provider=provider.name,
            model=provider.model,
            prompt_version="goal-framework-prompt-v2",
            raw_structured_output=plan.model_dump(mode="json"),
            proposed_changes=proposed_changes,
            reason="AI-generated goal framework and staged navigation awaiting review",
            confidence=average_confidence,
            sources=sources,
            review_status=(
                ReviewStatus.CONFLICT.value if analyzed.conflicts else ReviewStatus.PENDING.value
            ),
        )
        self.repository.audit(
            user_id,
            "CREATE_AI_LEARNING_PLAN",
            "AISuggestion",
            suggestion.id,
            details={
                "provider": provider.name,
                "model": provider.model,
                "provider_profile_id": profile.id if profile else None,
                "conflicts": len(analyzed.conflicts),
            },
        )
        result = model_dict(suggestion)
        result["intent_mode"] = plan.navigation.intent_mode.value
        result["semantic_profile"] = _semantic_profile_payload(
            plan.navigation.semantic_profile,
            plan.navigation.intent_mode,
        )
        return result

    def list_learning_plans(self, *, user_id: str) -> list[dict[str, Any]]:
        return [
            _learning_plan_summary(plan)
            for plan in self.repository.list_learning_plans(user_id=user_id)
        ]

    def get_learning_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any]:
        plan = self.repository.get_learning_plan(plan_id, user_id=user_id)
        proposed_changes = plan.proposed_changes if isinstance(plan.proposed_changes, dict) else {}
        raw_generation_input = proposed_changes.get("generation_input")
        generation_input = (
            {
                "topic": raw_generation_input.get("topic"),
                "requirements": raw_generation_input.get("requirements"),
            }
            if isinstance(raw_generation_input, dict)
            and isinstance(raw_generation_input.get("topic"), str)
            and isinstance(raw_generation_input.get("requirements"), str)
            else None
        )
        schema_version = proposed_changes.get("schema_version")
        return {
            **_learning_plan_summary(plan),
            "raw_structured_output": json_safe(plan.raw_structured_output),
            "confidence": plan.confidence,
            "sources": json_safe(plan.sources),
            "generation_input": generation_input,
            "schema_version": schema_version if isinstance(schema_version, str) else None,
        }

    def activate_learning_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any]:
        """Adopt a generated plan into the formal map -> goal -> route lifecycle.

        The request dependency owns the transaction, so a validation, publish, goal, or route
        failure rolls the entire activation back.  No learner-state row is inferred from the
        generated stage ordering.
        """

        suggestion = self.repository.get_learning_plan(plan_id, user_id=user_id)
        accepted_changes = (
            dict(suggestion.accepted_changes)
            if isinstance(suggestion.accepted_changes, dict)
            else {}
        )
        existing_activation = accepted_changes.get("activation")
        if isinstance(existing_activation, dict):
            result = self._activated_learning_plan_result(
                user_id=user_id,
                plan_id=plan_id,
                activation=existing_activation,
            )
            goal_payload = result.get("goal")
            goal_id = goal_payload.get("id") if isinstance(goal_payload, dict) else None
            if not isinstance(goal_id, str) or not goal_id:
                raise InvalidStateTransitionError(
                    "Learning plan activation no longer references a selectable goal"
                )
            current_goal = self.repository.mark_goal_current(goal_id, user_id=user_id)
            result["goal"] = model_dict(current_goal)
            self.repository.audit(
                user_id,
                "SELECT_CURRENT_GOAL",
                "LearningGoal",
                goal_id,
                after=model_dict(current_goal),
                details={"plan_id": plan_id},
            )
            return result

        if suggestion.review_status in {
            ReviewStatus.REJECTED.value,
            ReviewStatus.REVERTED.value,
        }:
            raise InvalidStateTransitionError(
                "Rejected or reverted learning plans cannot be activated"
            )

        accepted_draft = accepted_changes.get("accepted_draft")
        payload = (
            accepted_draft if isinstance(accepted_draft, dict) else suggestion.raw_structured_output
        )
        try:
            draft = LearningPlanDraft.model_validate(with_sanitized_semantic_profile(payload))
            analyzed = analyze_draft(draft)
        except ValidationError as exc:
            raise AIOutputValidationError(f"Learning plan activation was rejected: {exc}") from exc
        if analyzed.conflicts:
            raise SuggestionReviewError(
                "Learning plan cannot be activated while prerequisite cycles remain"
            )

        space_id = accepted_changes.get("space_id")
        raw_node_id_map = accepted_changes.get("node_id_map")
        node_ids: dict[str, str]
        created_node_ids: list[str]
        created_edge_ids: list[str]
        if isinstance(space_id, str):
            if not isinstance(raw_node_id_map, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in raw_node_id_map.items()
            ):
                raise InvalidStateTransitionError(
                    "Accepted learning plan is missing its node reference mapping"
                )
            node_ids = {str(key): str(value) for key, value in raw_node_id_map.items()}
            expected_temp_ids = {node.temp_id for node in draft.nodes}
            if set(node_ids) != expected_temp_ids:
                raise InvalidStateTransitionError(
                    "Accepted learning plan node references no longer match its source draft"
                )
            self.repository.get_space(space_id, user_id=user_id)
            created_node_ids = [str(item) for item in accepted_changes.get("node_ids", [])]
            created_edge_ids = [str(item) for item in accepted_changes.get("edge_ids", [])]
        else:
            space = self.create_space(
                user_id=user_id,
                title=draft.space.title,
                description=draft.space.description,
                target_audience=draft.space.target_audience,
                scope_included=draft.space.scope_included,
                scope_excluded=draft.space.scope_excluded,
            )
            space_id = str(space["id"])
            node_ids = {}
            created_node_ids = []
            provenance = {
                "suggestion_id": suggestion.id,
                "provider": suggestion.provider,
                "model": suggestion.model,
                "prompt_version": suggestion.prompt_version,
            }
            for node in draft.nodes:
                source_basis = [
                    item if isinstance(item, dict) else {"reference": item}
                    for item in node.source_basis
                ]
                source_basis.append(provenance)
                created = self.create_node(
                    user_id=user_id,
                    space_id=space_id,
                    title=node.title,
                    description=node.description,
                    node_type=node.node_type,
                    difficulty=node.difficulty,
                    learning_objectives=node.learning_objectives,
                    source_basis=source_basis,
                    stable_key=node.temp_id,
                    change_source="AI_ACCEPTED",
                    manually_locked=True,
                )
                node_ids[node.temp_id] = str(created["id"])
                created_node_ids.append(str(created["id"]))

            created_edge_ids = []
            for edge in analyzed.accepted_edges:
                created = self.create_edge(
                    user_id=user_id,
                    space_id=space_id,
                    source_node_id=node_ids[edge.source_temp_id],
                    target_node_id=node_ids[edge.target_temp_id],
                    relation_type=edge.relation_type,
                    confidence=edge.confidence,
                    required_mastery_level=edge.required_mastery_level,
                    reason=edge.reason,
                    source_reference=[provenance],
                    manually_locked=True,
                )
                created_edge_ids.append(str(created["id"]))

        target_node_id = node_ids.get(draft.navigation.target_temp_id)
        if target_node_id is None:
            raise InvalidStateTransitionError(
                "Learning plan target is missing from the materialized knowledge map"
            )

        published = self.publish_map_version(
            user_id=user_id,
            space_id=space_id,
            change_summary=f"Activated from AI learning plan {suggestion.id}",
        )["published"]
        goal = self.create_goal(
            user_id=user_id,
            space_id=space_id,
            target_node_id=target_node_id,
            title=draft.navigation.goal_title,
            intent_mode=draft.navigation.intent_mode,
            semantic_profile=draft.navigation.semantic_profile,
            target_mastery_level=draft.navigation.target_mastery_level,
            route_preference=RoutePreference.FOUNDATION_COMPLETE,
        )
        route = self._activate_navigation_path(
            user_id=user_id,
            goal=goal,
            map_version_id=str(published["id"]),
            draft=draft,
            node_ids=node_ids,
        )
        activated_at = datetime.now(UTC)
        activation = {
            "plan_id": suggestion.id,
            "space_id": space_id,
            "goal_id": str(goal["id"]),
            "intent_mode": draft.navigation.intent_mode.value,
            "semantic_profile": goal.get("semantic_profile"),
            "path_id": str(route["path"]["id"]),
            "published_map_version_id": str(published["id"]),
            "activated_at": activated_at.isoformat(),
        }
        suggestion.space_id = space_id
        suggestion.target_type = "KnowledgeSpace"
        suggestion.target_id = space_id
        if suggestion.review_status not in {
            ReviewStatus.ACCEPTED.value,
            ReviewStatus.MODIFIED_ACCEPTED.value,
        }:
            suggestion.review_status = ReviewStatus.ACCEPTED.value
            suggestion.reviewed_by = user_id
            suggestion.reviewed_at = activated_at
            suggestion.review_note = "Activated as a formal knowledge navigation workspace"
        suggestion.accepted_changes = {
            **accepted_changes,
            "space_id": space_id,
            "node_ids": created_node_ids,
            "node_id_map": node_ids,
            "edge_ids": created_edge_ids,
            "accepted_draft": draft.model_dump(mode="json"),
            "activation": activation,
        }
        self.repository.audit(
            user_id,
            "ACTIVATE_LEARNING_PLAN",
            "AISuggestion",
            suggestion.id,
            after=activation,
            details={
                "provider": suggestion.provider,
                "model": suggestion.model,
                "prompt_version": suggestion.prompt_version,
            },
        )
        return {
            "space": model_dict(self.repository.get_space(space_id, user_id=user_id)),
            "goal": goal,
            "route": route,
            "activation": activation,
        }

    def _activated_learning_plan_result(
        self,
        *,
        user_id: str,
        plan_id: str,
        activation: dict[str, Any],
    ) -> dict[str, Any]:
        """Rehydrate an idempotent activation response from persisted formal records."""

        required_ids = {
            key: activation.get(key)
            for key in (
                "space_id",
                "goal_id",
                "path_id",
                "published_map_version_id",
            )
        }
        if not all(isinstance(value, str) and value for value in required_ids.values()):
            raise InvalidStateTransitionError("Learning plan activation metadata is incomplete")
        space_id = cast(str, required_ids["space_id"])
        goal_id = cast(str, required_ids["goal_id"])
        path_id = cast(str, required_ids["path_id"])
        version_id = cast(str, required_ids["published_map_version_id"])
        space = self.repository.get_space(space_id, user_id=user_id)
        goal = self.repository.get_goal(goal_id, user_id=user_id)
        path = self.repository.session.get(LearningPathModel, path_id)
        if path is None or path.goal_id != goal.id or path.map_version_id != version_id:
            raise InvalidStateTransitionError(
                "Learning plan activation no longer references a valid route"
            )
        self.repository.get_version(space_id, version_id)
        _, nodes, _ = self.repository.load_graph(space_id, version_id)
        title_by_id = {node.id: node.title for node in nodes}
        items = [
            {
                "node_id": item.node_id,
                "title": title_by_id.get(item.node_id, ""),
                "required_mastery_level": item.required_mastery_level,
                "reason": item.recommendation_reason,
                "satisfied_prerequisites": item.satisfied_prerequisites,
                "unmet_prerequisites": item.unmet_prerequisites,
                "unlocks": item.unlocks,
                "algorithm_version": path.algorithm_version,
                "status": item.computed_status,
            }
            for item in self.repository.get_path_items(path.id)
        ]
        return {
            "space": model_dict(space),
            "goal": model_dict(goal),
            "route": {"path": model_dict(path), "items": json_safe(items)},
            "activation": {"plan_id": plan_id, **json_safe(activation)},
        }

    def delete_learning_plan(self, *, user_id: str, plan_id: str) -> None:
        plan = self.repository.get_learning_plan(plan_id, user_id=user_id)
        if plan.review_status in {
            ReviewStatus.ACCEPTED.value,
            ReviewStatus.MODIFIED_ACCEPTED.value,
        }:
            raise InvalidStateTransitionError(
                "Accepted learning plans cannot be deleted from the plan library"
            )
        self.repository.audit(
            user_id,
            "DELETE_LEARNING_PLAN",
            "AISuggestion",
            plan.id,
            details={
                "suggestion_type": plan.suggestion_type,
                "provider": plan.provider,
                "model": plan.model,
                "review_status": plan.review_status,
            },
        )
        self.repository.delete_suggestion(plan)

    def list_ai_suggestions(
        self,
        *,
        user_id: str,
        space_id: str | None = None,
        status: ReviewStatus | None = None,
    ) -> list[dict[str, Any]]:
        if space_id is not None:
            self.repository.get_space(space_id, user_id=user_id)
        return [
            model_dict(item)
            for item in self.repository.list_suggestions(
                user_id=user_id, space_id=space_id, status=status
            )
        ]

    def review_ai_suggestion(
        self,
        *,
        user_id: str,
        suggestion_id: str,
        action: str,
        edited_draft: dict[str, Any] | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        suggestion = self.repository.get_suggestion(suggestion_id, user_id=user_id)
        if suggestion.review_status not in {
            ReviewStatus.PENDING.value,
            ReviewStatus.CONFLICT.value,
        }:
            raise SuggestionReviewError("Suggestion has already been reviewed")
        if action == "reject":
            suggestion.review_status = ReviewStatus.REJECTED.value
            suggestion.reviewed_by = user_id
            suggestion.reviewed_at = datetime.now(UTC)
            suggestion.review_note = review_note
            self.repository.audit(user_id, "REJECT_AI_SUGGESTION", "AISuggestion", suggestion.id)
            return model_dict(suggestion)
        if action not in {"accept", "modify_accept"}:
            raise SuggestionReviewError(f"Unsupported review action: {action}")
        payload = edited_draft if edited_draft is not None else suggestion.raw_structured_output
        try:
            draft = (
                LearningPlanDraft.model_validate(with_sanitized_semantic_profile(payload))
                if suggestion.suggestion_type == SuggestionType.LEARNING_PLAN.value
                else KnowledgeMapDraft.model_validate(payload)
            )
            analyzed = analyze_draft(draft)
        except ValidationError as exc:
            raise AIOutputValidationError(f"Edited AI draft was rejected: {exc}") from exc
        if analyzed.conflicts:
            raise SuggestionReviewError(
                "Draft still contains circular prerequisite conflicts; edit or reject those edges"
            )
        if suggestion.space_id:
            space_id = suggestion.space_id
            self.repository.get_space(space_id, user_id=user_id)
        else:
            space = self.create_space(
                user_id=user_id,
                title=draft.space.title,
                description=draft.space.description,
                target_audience=draft.space.target_audience,
                scope_included=draft.space.scope_included,
                scope_excluded=draft.space.scope_excluded,
            )
            space_id = str(space["id"])
            suggestion.space_id = space_id
            suggestion.target_id = space_id
            suggestion.target_type = "KnowledgeSpace"
        node_ids: dict[str, str] = {}
        created_node_ids: list[str] = []
        for node in draft.nodes:
            source_basis = [
                item if isinstance(item, dict) else {"reference": item}
                for item in node.source_basis
            ]
            created = self.create_node(
                user_id=user_id,
                space_id=space_id,
                title=node.title,
                description=node.description,
                node_type=node.node_type,
                difficulty=node.difficulty,
                learning_objectives=node.learning_objectives,
                source_basis=source_basis,
                stable_key=node.temp_id,
                change_source="AI_ACCEPTED",
                manually_locked=True,
            )
            node_ids[node.temp_id] = str(created["id"])
            created_node_ids.append(str(created["id"]))
        created_edge_ids: list[str] = []
        for edge in analyzed.accepted_edges:
            created = self.create_edge(
                user_id=user_id,
                space_id=space_id,
                source_node_id=node_ids[edge.source_temp_id],
                target_node_id=node_ids[edge.target_temp_id],
                relation_type=edge.relation_type,
                confidence=edge.confidence,
                required_mastery_level=edge.required_mastery_level,
                reason=edge.reason,
                source_reference=[{"suggestion_id": suggestion.id}],
                manually_locked=True,
            )
            created_edge_ids.append(str(created["id"]))
        suggestion.review_status = (
            ReviewStatus.MODIFIED_ACCEPTED.value
            if action == "modify_accept" or edited_draft is not None
            else ReviewStatus.ACCEPTED.value
        )
        suggestion.reviewed_by = user_id
        suggestion.reviewed_at = datetime.now(UTC)
        suggestion.review_note = review_note
        suggestion.accepted_changes = {
            "space_id": space_id,
            "node_ids": created_node_ids,
            "node_id_map": node_ids,
            "edge_ids": created_edge_ids,
            "accepted_draft": draft.model_dump(mode="json"),
        }
        self.repository.audit(
            user_id,
            "ACCEPT_AI_SUGGESTION",
            "AISuggestion",
            suggestion.id,
            details={"modified": suggestion.review_status == ReviewStatus.MODIFIED_ACCEPTED.value},
        )
        return model_dict(suggestion)

    def revert_ai_suggestion(self, *, user_id: str, suggestion_id: str) -> dict[str, Any]:
        suggestion = self.repository.get_suggestion(suggestion_id, user_id=user_id)
        if suggestion.review_status not in {
            ReviewStatus.ACCEPTED.value,
            ReviewStatus.MODIFIED_ACCEPTED.value,
        }:
            raise SuggestionReviewError("Only accepted suggestions can be reverted")
        changes = suggestion.accepted_changes or {}
        space_id = changes.get("space_id")
        if not isinstance(space_id, str):
            raise SuggestionReviewError("Suggestion does not contain reversible change metadata")
        self.repository.get_space(space_id, user_id=user_id)
        edge_ids = [str(item) for item in changes.get("edge_ids", [])]
        node_ids = [str(item) for item in changes.get("node_ids", [])]
        issues = self.repository.ai_revert_issues(
            suggestion_id=suggestion.id,
            space_id=space_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
        )
        if issues:
            raise SuggestionReviewError(
                "Revert refused because later work would be lost: " + "; ".join(issues)
            )
        for edge_id in edge_ids:
            self.remove_edge(user_id=user_id, space_id=space_id, edge_id=edge_id)
        for node_id in node_ids:
            # Reverting an accepted AI proposal is an undo operation, not the
            # user's permanent-delete command. Keep an archived tombstone so
            # the review history remains inspectable without triggering the
            # product deletion rule that forbids empty frameworks.
            self.repository.update_node(
                space_id=space_id,
                map_version_id=self.repository.get_editable_version(space_id).id,
                node_id=node_id,
                user_id=user_id,
                changes={"status": RecordStatus.ARCHIVED.value},
                change_source="AI_REVERT",
            )
        suggestion.review_status = ReviewStatus.REVERTED.value
        suggestion.reverted_at = datetime.now(UTC)
        self.repository.audit(user_id, "REVERT_AI_SUGGESTION", "AISuggestion", suggestion.id)
        return model_dict(suggestion)

    def dashboard(self, *, user_id: str) -> dict[str, Any]:
        goals = self.repository.list_goals(user_id, active_only=True)
        sessions = list(
            self.repository.session.scalars(
                select(LearningSessionModel)
                .where(LearningSessionModel.user_id == user_id)
                .order_by(LearningSessionModel.started_at.desc())
                .limit(5)
            )
        )
        recent_sessions = [model_dict(item) for item in sessions]
        if not goals:
            return {
                "current_goal": None,
                "current_position": None,
                "next_step": None,
                "blocked": [],
                "recent_sessions": recent_sessions,
                "recent_check_ins": [],
                "route_overview": [],
                "current_goal_id": None,
                "intent_mode": None,
                "semantic_profile": None,
                "goal_overviews": [],
            }

        goal_overviews = [
            self._dashboard_goal_overview(
                user_id=user_id,
                goal=goal,
                is_current=index == 0,
            )
            for index, goal in enumerate(goals)
        ]
        current_overview = goal_overviews[0]
        return {
            # Keep the original single-goal projection for existing clients.
            "current_goal": current_overview["goal"],
            "current_position": current_overview["current_position"],
            "next_step": current_overview["next_step"],
            "blocked": current_overview["blocked"],
            "recent_sessions": recent_sessions,
            "recent_check_ins": current_overview["recent_check_ins"],
            "route_overview": current_overview["route_overview"],
            "current_goal_id": current_overview["goal"]["id"],
            "intent_mode": current_overview["intent_mode"],
            "semantic_profile": current_overview["semantic_profile"],
            "goal_overviews": goal_overviews,
        }

    def _dashboard_goal_overview(
        self,
        *,
        user_id: str,
        goal: LearningGoalModel,
        is_current: bool,
    ) -> dict[str, Any]:
        """Build one independent navigation snapshot for an active goal."""

        items = self._dashboard_route_items(user_id=user_id, goal=goal)
        current = _select_current_dashboard_item(items)
        blocked = [item for item in items if item["status"] == ComputedNodeStatus.BLOCKED.value]
        title_by_id = {str(item["node_id"]): str(item["title"]) for item in items}
        recent_check_ins = [
            {
                "id": row.id,
                "node_id": row.node_id,
                "title": title_by_id.get(row.node_id, row.node_id),
                "score": row.score,
                "note": row.note,
                "checked_in_at": json_safe(_aware_datetime(row.checked_in_at)),
                "check_in_date": json_safe(row.check_in_date),
                "display_progress_state": _display_progress_state(
                    status=None,
                    score=row.score,
                ),
            }
            for row in self.repository.list_goal_progress_check_ins(
                user_id=user_id,
                goal_id=goal.id,
                node_ids=title_by_id,
                limit=5,
            )
        ]
        goal_payload = model_dict(goal)
        goal_payload["semantic_profile"] = _semantic_profile_payload(
            goal.semantic_profile,
            goal.intent_mode,
        )
        return {
            "goal": goal_payload,
            "intent_mode": goal.intent_mode,
            "semantic_profile": goal_payload["semantic_profile"],
            "is_current": is_current,
            "current_position": current,
            "next_step": current,
            "blocked": blocked,
            "route_overview": items,
            "recent_check_ins": recent_check_ins,
        }

    def _dashboard_route_items(
        self, *, user_id: str, goal: LearningGoalModel
    ) -> list[dict[str, Any]]:
        """Read the active persisted route and refresh display-only learner statuses."""

        path = self.repository.session.scalar(
            select(LearningPathModel)
            .where(
                LearningPathModel.goal_id == goal.id,
                LearningPathModel.status == PathStatus.ACTIVE.value,
            )
            .order_by(LearningPathModel.generation_number.desc())
            .limit(1)
        )
        if path is None:
            return []
        persisted_items = self.repository.get_path_items(path.id)
        if not persisted_items:
            return []

        # A path owns stable node identities and order, while the knowledge map owns
        # the editable labels and relationships.  Always project the latest editable
        # graph here so one human edit is visible in the overview, timeline and AI
        # context without mutating the active path revision.
        _, nodes, edges = self.repository.load_graph(goal.space_id)
        node_by_id = {node.id: node for node in nodes}
        actionable_persisted_items = [
            item
            for item in persisted_items
            if (node := node_by_id.get(item.node_id)) is not None
            and node.is_active
            and node.node_type is not NodeType.MODULE
        ]
        relevant_ids = {item.node_id for item in actionable_persisted_items}
        if not relevant_ids:
            return []
        mastery = self.repository.get_mastery(user_id, {node.id for node in nodes})
        latest_check_ins = self.repository.latest_progress_check_ins_by_node(
            user_id=user_id,
            goal_id=goal.id,
            node_ids=relevant_ids,
        )
        engine = KnowledgeGraphService(nodes, edges)
        items: list[dict[str, Any]] = []
        completed_by_check_in = {
            node_id for node_id, row in latest_check_ins.items() if row.score >= 10
        }
        for persisted in actionable_persisted_items:
            node = node_by_id.get(persisted.node_id)
            latest_check_in = latest_check_ins.get(persisted.node_id)
            mastery_status = (
                engine.classify_node(
                    persisted.node_id,
                    relevant_ids,
                    mastery,
                    target_mastery_level=persisted.required_mastery_level,
                ).value
                if node is not None
                else ComputedNodeStatus.NOT_RELEVANT.value
            )
            display_progress_state = _display_progress_state(
                status=mastery_status,
                score=(latest_check_in.score if latest_check_in is not None else None),
            )
            prerequisite_edges = [
                edge
                for edge in edges
                if edge.is_active
                and edge.relation_type is RelationType.PREREQUISITE
                and edge.target_node_id == persisted.node_id
                and edge.source_node_id in relevant_ids
            ]
            satisfied_prerequisites = [
                edge.source_node_id
                for edge in prerequisite_edges
                if edge.source_node_id in completed_by_check_in
                or engine.classify_node(
                    edge.source_node_id,
                    relevant_ids,
                    mastery,
                    target_mastery_level=edge.required_mastery_level,
                )
                is ComputedNodeStatus.MASTERED
            ]
            unmet_prerequisites = [
                edge.source_node_id
                for edge in prerequisite_edges
                if edge.source_node_id not in satisfied_prerequisites
            ]
            if display_progress_state == DISPLAY_PROGRESS_COMPLETED:
                status = ComputedNodeStatus.MASTERED.value
                reason = "Required mastery is already demonstrated for this route."
            elif (
                latest_check_in is not None
                and display_progress_state == DISPLAY_PROGRESS_IN_PROGRESS
            ):
                status = ComputedNodeStatus.IN_PROGRESS.value
                reason = "You have started this node but have not reached the completion score."
            elif unmet_prerequisites:
                # Prerequisites are guidance, not a hard gate.  Keep the learner's
                # computed state so they can still open and work on the node, while
                # surfacing the missing foundations as an explicit recommendation.
                status = mastery_status
                names = ", ".join(
                    node_by_id[source_id].title
                    for source_id in unmet_prerequisites
                    if source_id in node_by_id
                )
                reason = (
                    f"Recommended prerequisites to review first: {names}."
                    if names
                    else "Recommended prerequisites are not yet satisfied."
                )
            else:
                status = mastery_status
                if status == ComputedNodeStatus.NEEDS_REVIEW.value:
                    reason = "Scheduled review is due before continuing this route."
                else:
                    reason = "All hard prerequisites are satisfied; this is the next route step."
            items.append(
                {
                    "node_id": persisted.node_id,
                    "title": node.title if node is not None else persisted.node_id,
                    "required_mastery_level": persisted.required_mastery_level,
                    "reason": reason,
                    "satisfied_prerequisites": satisfied_prerequisites,
                    "unmet_prerequisites": unmet_prerequisites,
                    "unlocks": list(persisted.unlocks),
                    "algorithm_version": path.algorithm_version,
                    "status": status,
                    "progress_score": (
                        latest_check_in.score if latest_check_in is not None else None
                    ),
                    "progress_checked_in_at": (
                        json_safe(_aware_datetime(latest_check_in.checked_in_at))
                        if latest_check_in is not None
                        else None
                    ),
                    "display_progress_state": display_progress_state,
                }
            )
        return items

    def export_user_data(self, *, user_id: str) -> dict[str, Any]:
        user = self.repository.get_user(user_id)
        spaces = self.repository.list_spaces(user_id)
        maps: list[dict[str, Any]] = []
        for space in spaces:
            versions = list(
                self.repository.session.scalars(
                    select(KnowledgeMapVersionModel)
                    .where(KnowledgeMapVersionModel.space_id == space.id)
                    .order_by(KnowledgeMapVersionModel.version_number)
                )
            )
            version_payloads: list[dict[str, Any]] = []
            for version in versions:
                node_rows = self.repository.session.execute(
                    select(KnowledgeNodeVersionModel, KnowledgeNodeModel)
                    .join(
                        KnowledgeNodeModel,
                        KnowledgeNodeModel.id == KnowledgeNodeVersionModel.node_id,
                    )
                    .where(KnowledgeNodeVersionModel.map_version_id == version.id)
                ).all()
                edges = list(
                    self.repository.session.scalars(
                        select(KnowledgeEdgeModel).where(
                            KnowledgeEdgeModel.map_version_id == version.id
                        )
                    )
                )
                version_payloads.append(
                    {
                        "version": model_dict(version),
                        "nodes": [
                            {
                                **model_dict(snapshot),
                                "stable_key": node.stable_key,
                                "manually_locked": node.manually_locked,
                            }
                            for snapshot, node in node_rows
                        ],
                        "edges": [model_dict(edge) for edge in edges],
                    }
                )
            editable = self.repository.get_editable_version(space.id)
            current = next(
                item for item in version_payloads if item["version"]["id"] == editable.id
            )
            maps.append(
                {
                    "space": model_dict(space),
                    "map_version_id": editable.id,
                    "nodes": current["nodes"],
                    "edges": current["edges"],
                    "versions": version_payloads,
                }
            )
        goals = self.repository.list_goals(user_id)
        goal_ids = [item.id for item in goals]
        paths = (
            list(
                self.repository.session.scalars(
                    select(LearningPathModel).where(LearningPathModel.goal_id.in_(goal_ids))
                )
            )
            if goal_ids
            else []
        )
        path_ids = [item.id for item in paths]
        path_nodes = (
            list(
                self.repository.session.scalars(
                    select(LearningPathNodeModel).where(LearningPathNodeModel.path_id.in_(path_ids))
                )
            )
            if path_ids
            else []
        )
        states = list(
            self.repository.session.scalars(
                select(LearnerNodeStateModel).where(LearnerNodeStateModel.user_id == user_id)
            )
        )
        sessions = list(
            self.repository.session.scalars(
                select(LearningSessionModel).where(LearningSessionModel.user_id == user_id)
            )
        )
        progress_check_ins = list(
            self.repository.session.scalars(
                select(NodeProgressCheckInModel).where(NodeProgressCheckInModel.user_id == user_id)
            )
        )
        progress_check_in_attachments = list(
            self.repository.session.scalars(
                select(ProgressCheckInAttachmentModel).where(
                    ProgressCheckInAttachmentModel.user_id == user_id
                )
            )
        )
        evidence = list(
            self.repository.session.scalars(
                select(LearningEvidenceModel).where(LearningEvidenceModel.user_id == user_id)
            )
        )
        resources = list(
            self.repository.session.scalars(
                select(LearningResourceModel).where(LearningResourceModel.created_by == user_id)
            )
        )
        assessments = list(
            self.repository.session.scalars(
                select(AssessmentModel).where(AssessmentModel.created_by == user_id)
            )
        )
        attempts = list(
            self.repository.session.scalars(
                select(AssessmentAttemptModel).where(AssessmentAttemptModel.user_id == user_id)
            )
        )
        suggestions = self.repository.list_suggestions(user_id=user_id)
        conversations = list(
            self.repository.session.scalars(
                select(AIConversationModel)
                .where(AIConversationModel.user_id == user_id)
                .order_by(AIConversationModel.created_at, AIConversationModel.id)
            )
        )
        conversation_ids = [item.id for item in conversations]
        conversation_messages = (
            list(
                self.repository.session.scalars(
                    select(AIConversationMessageModel)
                    .where(AIConversationMessageModel.conversation_id.in_(conversation_ids))
                    .order_by(
                        AIConversationMessageModel.conversation_id,
                        AIConversationMessageModel.sequence_number,
                    )
                )
            )
            if conversation_ids
            else []
        )
        audit_logs = list(
            self.repository.session.scalars(
                select(AuditLogModel).where(AuditLogModel.actor_user_id == user_id)
            )
        )
        export_audits = [_export_audit_dict(item) for item in audit_logs]
        return {
            "format": "learning-navigator-export-v1",
            "schema_version": 2,
            "exported_at": datetime.now(UTC).isoformat(),
            "user_id": user_id,
            "user": model_dict(user),
            "maps": maps,
            "goals": [model_dict(item) for item in goals],
            "learning_paths": [model_dict(item) for item in paths],
            "learning_path_nodes": [model_dict(item) for item in path_nodes],
            "path_nodes": [model_dict(item) for item in path_nodes],
            "learner_states": [model_dict(item) for item in states],
            "learning_sessions": [model_dict(item) for item in sessions],
            "progress_check_ins": [model_dict(item) for item in progress_check_ins],
            "progress_check_in_attachments": [
                _progress_check_in_attachment_dict(item) for item in progress_check_in_attachments
            ],
            "learning_evidence": [model_dict(item) for item in evidence],
            "learning_resources": [model_dict(item) for item in resources],
            "resources": [model_dict(item) for item in resources],
            "assessments": [model_dict(item) for item in assessments],
            "assessment_attempts": [model_dict(item) for item in attempts],
            "ai_suggestions": [model_dict(item) for item in suggestions],
            "ai_conversations": [model_dict(item) for item in conversations],
            "ai_conversation_messages": [model_dict(item) for item in conversation_messages],
            "audit_logs": export_audits,
            "audit": export_audits,
        }

    def import_map(self, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("format") in {
            "learning-navigator-export-v1",
            "learning-navigator-export-v2",
        }:
            maps = payload.get("maps")
            if not isinstance(maps, list) or not maps:
                raise ValueError("Export contains no maps")
            imported = [
                self._import_draft(
                    user_id=user_id,
                    draft_payload=self._draft_payload_from_export_map(source),
                )
                for source in maps
            ]
            if len(imported) == 1:
                return {**imported[0], "imported_map_count": 1}
            return {
                "format": "learning-navigator-import-result-v1",
                "imported_map_count": len(imported),
                "maps": imported,
            }
        return self._import_draft(user_id=user_id, draft_payload=payload)

    @staticmethod
    def _draft_payload_from_export_map(source: dict[str, Any]) -> dict[str, Any]:
        space_payload = source["space"]
        node_payloads = source["nodes"]
        edge_payloads = source["edges"]
        return {
            "space": {
                "title": f"{space_payload['title']} (imported)",
                "description": space_payload.get("description", ""),
                "target_audience": space_payload.get("target_audience", ""),
                "scope_included": space_payload.get("scope_included", []),
                "scope_excluded": space_payload.get("scope_excluded", []),
            },
            "nodes": [
                {
                    "temp_id": item.get("node_id", item["id"]),
                    "title": item["title"],
                    "description": item.get("description", ""),
                    "node_type": item.get("node_type", "CONCEPT"),
                    "difficulty": item.get("difficulty", 1),
                    "learning_objectives": item.get("learning_objectives", []),
                    "source_basis": item.get("source_basis", []),
                    "confidence": 1.0,
                }
                for item in node_payloads
                if item.get("status") != RecordStatus.ARCHIVED.value
            ],
            "edges": [
                {
                    "source_temp_id": item["source_node_id"],
                    "target_temp_id": item["target_node_id"],
                    "relation_type": item["relation_type"],
                    "reason": item.get("reason", "Imported relation"),
                    "confidence": item.get("confidence", 1.0),
                    "required_mastery_level": item.get("required_mastery_level", 0),
                }
                for item in edge_payloads
                if item.get("status") != RecordStatus.ARCHIVED.value
            ],
            "warnings": [],
            "uncertain_items": [],
        }

    def _import_draft(self, *, user_id: str, draft_payload: dict[str, Any]) -> dict[str, Any]:
        draft = KnowledgeMapDraft.model_validate(draft_payload)
        analyzed = analyze_draft(draft)
        if analyzed.conflicts:
            raise ValueError("Imported map contains circular prerequisite edges")
        space = self.create_space(
            user_id=user_id,
            title=draft.space.title,
            description=draft.space.description,
            target_audience=draft.space.target_audience,
            scope_included=draft.space.scope_included,
            scope_excluded=draft.space.scope_excluded,
        )
        node_ids: dict[str, str] = {}
        for node in draft.nodes:
            created = self.create_node(
                user_id=user_id,
                space_id=str(space["id"]),
                title=node.title,
                description=node.description,
                node_type=node.node_type,
                difficulty=node.difficulty,
                learning_objectives=node.learning_objectives,
                source_basis=[
                    item if isinstance(item, dict) else {"reference": item}
                    for item in node.source_basis
                ],
                stable_key=node.temp_id,
                change_source="IMPORT",
                manually_locked=True,
            )
            node_ids[node.temp_id] = str(created["id"])
        for edge in analyzed.accepted_edges:
            self.create_edge(
                user_id=user_id,
                space_id=str(space["id"]),
                source_node_id=node_ids[edge.source_temp_id],
                target_node_id=node_ids[edge.target_temp_id],
                relation_type=edge.relation_type,
                confidence=edge.confidence,
                required_mastery_level=edge.required_mastery_level,
                reason=edge.reason,
            )
        return self.graph_view(space_id=str(space["id"]), user_id=user_id)


def _select_current_dashboard_item(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    # A durable check-in is the clearest statement of where the user currently
    # is.  It is display-only: selection never mutates mastery or prerequisites.
    checked_in_progress = next(
        (
            item
            for item in items
            if item.get("progress_score") is not None
            and item.get("display_progress_state") == DISPLAY_PROGRESS_IN_PROGRESS
        ),
        None,
    )
    if checked_in_progress is not None:
        return checked_in_progress
    for status in DASHBOARD_CURRENT_STATUS_PRIORITY:
        current = next(
            (
                item
                for item in items
                if item.get("status") == status
                and item.get("display_progress_state") != DISPLAY_PROGRESS_COMPLETED
            ),
            None,
        )
        if current is not None:
            return current
    return next(
        (
            item
            for item in items
            if item.get("display_progress_state") == DISPLAY_PROGRESS_NOT_STARTED
        ),
        None,
    )


def _display_progress_state(*, status: str | None, score: int | None) -> str:
    """Project a check-in/mastery snapshot without changing either source."""

    if score is not None:
        if score <= 0:
            return DISPLAY_PROGRESS_NOT_STARTED
        return DISPLAY_PROGRESS_COMPLETED if score >= 10 else DISPLAY_PROGRESS_IN_PROGRESS
    if status == ComputedNodeStatus.MASTERED.value:
        return DISPLAY_PROGRESS_COMPLETED
    if status in {
        ComputedNodeStatus.IN_PROGRESS.value,
        ComputedNodeStatus.NEEDS_REVIEW.value,
    }:
        return DISPLAY_PROGRESS_IN_PROGRESS
    return DISPLAY_PROGRESS_NOT_STARTED


def _semantic_profile_payload(
    value: Any,
    intent_mode: GoalIntent | str = GoalIntent.LEARN,
) -> dict[str, Any] | None:
    """Return only a profile that still satisfies the canonical display contract."""

    return semantic_profile_payload_or_none(value, intent_mode)


def _learning_plan_summary(plan: AISuggestionModel) -> dict[str, Any]:
    raw: dict[str, Any] = (
        plan.raw_structured_output if isinstance(plan.raw_structured_output, dict) else {}
    )
    raw_space = raw.get("space")
    raw_navigation = raw.get("navigation")
    raw_nodes = raw.get("nodes")
    space: dict[str, Any] = raw_space if isinstance(raw_space, dict) else {}
    navigation: dict[str, Any] = raw_navigation if isinstance(raw_navigation, dict) else {}
    nodes: list[Any] = raw_nodes if isinstance(raw_nodes, list) else []
    accepted_changes = plan.accepted_changes if isinstance(plan.accepted_changes, dict) else {}
    accepted_draft = accepted_changes.get("accepted_draft")
    accepted_navigation = (
        accepted_draft.get("navigation") if isinstance(accepted_draft, dict) else None
    )
    effective_navigation = (
        accepted_navigation if isinstance(accepted_navigation, dict) else navigation
    )
    intent_mode = effective_navigation.get("intent_mode", GoalIntent.LEARN.value)
    if intent_mode not in {item.value for item in GoalIntent}:
        intent_mode = GoalIntent.LEARN.value
    semantic_profile = _semantic_profile_payload(
        effective_navigation.get("semantic_profile"),
        intent_mode,
    )
    raw_stages = navigation.get("stages")
    stages: list[Any] = raw_stages if isinstance(raw_stages, list) else []

    goal_title = navigation.get("goal_title")
    space_title = space.get("title")
    title = (
        goal_title.strip()
        if isinstance(goal_title, str) and goal_title.strip()
        else space_title.strip()
        if isinstance(space_title, str) and space_title.strip()
        else "Untitled learning plan"
    )
    space_description = space.get("description")
    success_definition = navigation.get("success_definition")
    description = (
        space_description.strip()
        if isinstance(space_description, str) and space_description.strip()
        else success_definition.strip()
        if isinstance(success_definition, str) and success_definition.strip()
        else ""
    )
    module_count = len(
        [node for node in nodes if isinstance(node, dict) and node.get("node_type") == "MODULE"]
    )
    raw_activation = accepted_changes.get("activation")
    activation = (
        {
            "space_id": raw_activation.get("space_id"),
            "goal_id": raw_activation.get("goal_id"),
            "activated_at": raw_activation.get("activated_at"),
        }
        if isinstance(raw_activation, dict)
        and isinstance(raw_activation.get("space_id"), str)
        and isinstance(raw_activation.get("goal_id"), str)
        else None
    )
    return {
        "id": plan.id,
        "title": title,
        "description": description,
        "created_at": json_safe(plan.created_at),
        "updated_at": json_safe(plan.updated_at),
        "provider": plan.provider,
        "model": plan.model,
        "review_status": plan.review_status,
        "intent_mode": intent_mode,
        "semantic_profile": semantic_profile,
        "module_count": module_count,
        "node_count": len(nodes),
        "stage_count": len(stages),
        "activation": json_safe(activation),
    }


def _aware_datetime(value: datetime) -> datetime:
    """Normalize SQLite's occasionally-naive timestamps for safe UTC comparisons."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _session_duration_minutes(session: LearningSessionModel) -> float:
    if session.ended_at is None:
        return 0.0
    started_at = _aware_datetime(session.started_at)
    ended_at = _aware_datetime(session.ended_at)
    return round(max((ended_at - started_at).total_seconds(), 0.0) / 60, 2)


def _normalized_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def model_dict(model: Any) -> dict[str, Any]:
    """Serialize mapped columns only, avoiding relationship traversal and hidden state."""

    return {
        column.key: json_safe(getattr(model, column.key))
        for column in inspect(model).mapper.column_attrs
    }


def _progress_check_in_attachment_dict(
    attachment: ProgressCheckInAttachmentModel,
) -> dict[str, Any]:
    payload = model_dict(attachment)
    payload.pop("storage_key", None)
    payload["created_at"] = json_safe(_aware_datetime(attachment.created_at))
    payload["updated_at"] = json_safe(_aware_datetime(attachment.updated_at))
    attachment_id = str(attachment.id)
    payload["content_url"] = f"/api/progress-check-in-attachments/{attachment_id}/content"
    payload["download_url"] = (
        f"/api/progress-check-in-attachments/{attachment_id}/content?download=true"
    )
    return payload


def _progress_check_in_dict(
    check_in: NodeProgressCheckInModel,
    attachments: list[ProgressCheckInAttachmentModel],
) -> dict[str, Any]:
    payload = model_dict(check_in)
    payload["attachments"] = [
        _progress_check_in_attachment_dict(attachment) for attachment in attachments
    ]
    return payload


def _progress_check_in_clear_batch_dict(
    batch: ProgressCheckInClearBatchModel,
) -> dict[str, Any]:
    return {
        "id": batch.id,
        "cleared_at": json_safe(_aware_datetime(batch.cleared_at)),
        "record_count": batch.record_count,
        "attachment_count": batch.attachment_count,
        "recoverable": batch.restored_at is None,
    }


def _parse_snapshot_datetime(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise InvalidStateTransitionError(f"Invalid cleared progress field: {field}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidStateTransitionError(f"Invalid cleared progress field: {field}") from exc


def _restored_progress_check_in_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    raw_date = values.get("check_in_date")
    if isinstance(raw_date, str):
        try:
            values["check_in_date"] = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise InvalidStateTransitionError(
                "Invalid cleared progress field: check_in_date"
            ) from exc
    elif not isinstance(raw_date, date):
        raise InvalidStateTransitionError("Invalid cleared progress field: check_in_date")
    for field in (
        "checked_in_at",
        "ai_evaluated_at",
        "corrected_at",
        "created_at",
        "updated_at",
    ):
        values[field] = _parse_snapshot_datetime(values.get(field), field=field)
    values["score"] = max(1, int(values.get("score", 1)))
    return values


def _restored_progress_attachment_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    for field in ("created_at", "updated_at"):
        parsed = _parse_snapshot_datetime(values.get(field), field=field)
        if parsed is None:
            raise InvalidStateTransitionError(f"Invalid cleared progress field: {field}")
        values[field] = parsed
    return values


def _export_audit_dict(model: AuditLogModel) -> dict[str, Any]:
    """Export audit history without resurrecting identifiers of deleted projects.

    Internal audit rows remain queryable for accountability.  A user data export
    is a portable copy, however, so a permanent project deletion must not leak
    the deleted goal id (or a stale before/after snapshot) back into that copy.
    Keep only aggregate, non-identifying deletion facts.
    """

    payload = model_dict(model)
    details = model.details if isinstance(model.details, dict) else {}
    project_redacted = details.get("reason") == "PROJECT_PERMANENTLY_DELETED"
    if model.action != "DELETE_PROJECT" and not project_redacted:
        return payload
    payload["entity_id"] = None
    payload["before_state"] = None
    payload["after_state"] = None
    exported_details = payload.get("details")
    if isinstance(exported_details, dict):
        safe_keys = {
            "permanent",
            "framework_deleted",
            "title_confirmation_verified",
            "content_redacted",
            "redacted",
            "reason",
        }
        safe_keys.update(key for key in exported_details if key.endswith("_count"))
        payload["details"] = {
            key: exported_details[key] for key in safe_keys if key in exported_details
        }
    else:
        payload["details"] = {"permanent": True, "content_redacted": True}
    return payload


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set):
        return [json_safe(item) for item in value]
    return value


EXPORT_MODELS = (
    UserModel,
    KnowledgeSpaceModel,
    KnowledgeMapVersionModel,
    KnowledgeNodeModel,
    KnowledgeNodeVersionModel,
    KnowledgeEdgeModel,
    LearningGoalModel,
    LearningPathModel,
    LearningPathNodeModel,
    LearnerNodeStateModel,
    LearningSessionModel,
    NodeProgressCheckInModel,
    LearningEvidenceModel,
    LearningResourceModel,
    AISuggestionModel,
    AuditLogModel,
)
