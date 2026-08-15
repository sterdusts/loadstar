"""Durable AI collaboration orchestration and draft-only tool execution."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from learning_navigator.application.dto.ai import (
    LearningPlanDraft,
    analyze_draft,
    extract_explicit_outline_sections,
    extract_explicit_outline_titles,
    validate_explicit_outline_alignment,
    validate_generated_plan_outline,
)
from learning_navigator.application.dto.collaboration import (
    AddNodeToolCall,
    AddPathStepToolCall,
    AddRelationToolCall,
    ArchiveNodeToolCall,
    ClonePathDraftToolCall,
    CollaborationAIResponse,
    CollaborationToolCall,
    CreatePathDraftToolCall,
    RemovePathStepToolCall,
    ReorderPathStepToolCall,
    UpdateNodeToolCall,
    UpdatePathStepToolCall,
)
from learning_navigator.application.services import NavigatorApplication, json_safe, model_dict
from learning_navigator.domain.collaboration import ConversationMessageOrigin
from learning_navigator.domain.enums import (
    GoalStatus,
    PathOrigin,
    PathStepSource,
    ReviewStatus,
    SuggestionType,
)
from learning_navigator.domain.exceptions import (
    AIOutputValidationError,
    DomainError,
    InvalidStateTransitionError,
)
from learning_navigator.infrastructure.ai.providers import AIProvider, AIProviderError
from learning_navigator.infrastructure.database.base import new_id, now_utc
from learning_navigator.infrastructure.database.models import (
    AIConversationMessageModel,
    AIConversationModel,
    AIProviderProfileModel,
    LearningPathModel,
    LearningPathNodeModel,
)
from learning_navigator.infrastructure.repositories.collaboration import (
    SqlAlchemyCollaborationRepository,
)

COLLABORATION_PROMPT_VERSION = "project-collaboration-v3"
MAX_CONTEXT_CHARS = 24_000
MAX_CONTEXT_MESSAGE_CHARS = 6_000
MAX_SUMMARY_CHARS = 8_000
MAX_PROJECT_CONTEXT_GOALS = 20
MAX_PROJECT_CONTEXT_PATH_REVISIONS = 20
MAX_PROJECT_CONTEXT_NODES = 80
MAX_PROJECT_CONTEXT_EDGES = 160
MAX_PROJECT_NODE_TEXT_CHARS = 600
MAX_PROJECT_EDGE_REASON_CHARS = 300
MAX_PROJECT_LIST_ITEMS = 10
MAX_PROJECT_LIST_TEXT_CHARS = 300

ALLOWED_TOOL_NAMES = (
    "add_node",
    "update_node",
    "archive_node",
    "add_relation",
    "create_path_draft",
    "clone_path_draft",
    "add_path_step",
    "update_path_step",
    "remove_path_step",
    "reorder_path_step",
)
PAGE_CONTEXT_FIELDS = (
    "page_key",
    "page_kind",
    "page_title",
    "section",
    "space_id",
    "goal_id",
    "node_id",
    "path_revision_id",
)
PROJECT_PAGE_CONTEXT_FIELDS = ("space_id", "goal_id", "node_id", "path_revision_id")
PAGE_STATE_COUNT_FIELDS = ("total", "completed", "in_progress", "not_started")
PAGE_STATE_NODE_TEXT_FIELDS = ("node_id", "name", "status")
MAX_PAGE_STATE_STEPS = 40

logger = logging.getLogger(__name__)


def _bounded_page_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    return normalized[:limit] or None


def _bounded_page_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(int(value), minimum), maximum)


def _safe_page_node(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    node: dict[str, Any] = {}
    limits = {"node_id": 128, "name": 240, "status": 64}
    for key in PAGE_STATE_NODE_TEXT_FIELDS:
        item = _bounded_page_text(value.get(key), limits[key])
        if item:
            node[key] = item
    position = _bounded_page_int(value.get("path_position"), minimum=1, maximum=10_000)
    if position is not None:
        node["path_position"] = position
    score = _bounded_page_int(value.get("score"), minimum=0, maximum=10)
    if score is not None:
        node["score"] = score
    return node or None


def _safe_page_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    state: dict[str, Any] = {}
    project_title = _bounded_page_text(value.get("project_title"), 240)
    if project_title:
        state["project_title"] = project_title
    current_node = _safe_page_node(value.get("current_node"))
    if current_node:
        state["current_node"] = current_node

    raw_path = value.get("path_summary")
    if isinstance(raw_path, dict):
        path: dict[str, Any] = {}
        for key in PAGE_STATE_COUNT_FIELDS:
            item = _bounded_page_int(raw_path.get(key), minimum=0, maximum=10_000)
            if item is not None:
                path[key] = item
        raw_steps = raw_path.get("steps")
        if isinstance(raw_steps, list):
            steps: list[dict[str, Any]] = []
            for raw in raw_steps[:MAX_PAGE_STATE_STEPS]:
                node = _safe_page_node(raw)
                if node is not None:
                    steps.append(node)
            if steps:
                path["steps"] = steps
        if path:
            state["path_summary"] = path

    raw_progress = value.get("progress_summary")
    if isinstance(raw_progress, dict):
        progress: dict[str, Any] = {}
        percent = _bounded_page_int(raw_progress.get("percent"), minimum=0, maximum=100)
        if percent is not None:
            progress["percent"] = percent
        for key in ("completed", "total"):
            item = _bounded_page_int(raw_progress.get(key), minimum=0, maximum=10_000)
            if item is not None:
                progress[key] = item
        if progress:
            state["progress_summary"] = progress
    return state or None


def _bounded_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:MAX_PROJECT_LIST_ITEMS]:
        text = _bounded_page_text(item, MAX_PROJECT_LIST_TEXT_CHARS)
        if text:
            result.append(text)
    return result


def _bounded_scalar_dict(value: Any) -> dict[str, Any] | None:
    """Keep a small scalar snapshot while rejecting arbitrarily nested provider context."""

    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:16]:
        safe_key = _bounded_page_text(str(key), 80)
        if safe_key is None or not isinstance(item, str | int | float | bool | type(None)):
            continue
        result[safe_key] = (
            _bounded_page_text(item, MAX_PROJECT_LIST_TEXT_CHARS) if isinstance(item, str) else item
        )
    return result or None


def _bounded_project_map(
    graph: dict[str, Any],
    *,
    priority_node_ids: list[str],
) -> dict[str, Any]:
    """Project an editable graph into a deterministic, size-bounded AI context."""

    raw_nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    raw_edges = [item for item in graph.get("edges", []) if isinstance(item, dict)]
    nodes_by_id = {
        str(item["id"]): item
        for item in raw_nodes
        if isinstance(item.get("id"), str) and item["id"]
    }

    ordered_ids: list[str] = []

    def add_node_id(node_id: Any) -> None:
        if isinstance(node_id, str) and node_id in nodes_by_id and node_id not in ordered_ids:
            ordered_ids.append(node_id)

    for node_id in priority_node_ids:
        add_node_id(node_id)
    priority_set = set(ordered_ids)
    for edge in raw_edges:
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        if source_id in priority_set or target_id in priority_set:
            add_node_id(source_id)
            add_node_id(target_id)
    for node in raw_nodes:
        add_node_id(node.get("id"))

    selected_ids = ordered_ids[:MAX_PROJECT_CONTEXT_NODES]
    selected_set = set(selected_ids)

    nodes: list[dict[str, Any]] = []
    for node_id in selected_ids:
        source = nodes_by_id[node_id]
        projected: dict[str, Any] = {
            "id": node_id,
            "title": _bounded_page_text(source.get("title"), 240) or "Untitled node",
            "node_type": _bounded_page_text(source.get("node_type"), 64),
            "difficulty": source.get("difficulty"),
            "depth_level": source.get("depth_level"),
            "status": _bounded_page_text(source.get("status"), 64),
            "computed_status": _bounded_page_text(source.get("computed_status"), 64),
            "stable_key": _bounded_page_text(source.get("stable_key"), 160),
        }
        for key in ("description", "application", "verification_method"):
            text = _bounded_page_text(source.get(key), MAX_PROJECT_NODE_TEXT_CHARS)
            if text:
                projected[key] = text
        objectives = _bounded_text_list(source.get("learning_objectives"))
        if objectives:
            projected["learning_objectives"] = objectives
        mastery = _bounded_scalar_dict(source.get("mastery"))
        if mastery:
            projected["mastery"] = mastery
        nodes.append({key: value for key, value in projected.items() if value is not None})

    eligible_edges = [
        edge
        for edge in raw_edges
        if edge.get("source_node_id") in selected_set and edge.get("target_node_id") in selected_set
    ]
    edges: list[dict[str, Any]] = []
    for source in eligible_edges[:MAX_PROJECT_CONTEXT_EDGES]:
        projected = {
            "id": source.get("id"),
            "source_node_id": source.get("source_node_id"),
            "target_node_id": source.get("target_node_id"),
            "relation_type": _bounded_page_text(source.get("relation_type"), 64),
            "strength": source.get("strength"),
            "confidence": source.get("confidence"),
            "required_mastery_level": source.get("required_mastery_level"),
            "is_hard_requirement": source.get("is_hard_requirement"),
            "manually_locked": source.get("manually_locked"),
        }
        reason = _bounded_page_text(source.get("reason"), MAX_PROJECT_EDGE_REASON_CHARS)
        if reason:
            projected["reason"] = reason
        edges.append({key: value for key, value in projected.items() if value is not None})

    raw_cycle = graph.get("cycle")
    cycle = (
        [node_id for node_id in raw_cycle[:MAX_PROJECT_LIST_ITEMS] if node_id in selected_set]
        if isinstance(raw_cycle, list)
        else None
    )
    return {
        "space_id": graph.get("space_id"),
        "map_version_id": graph.get("map_version_id"),
        "nodes": nodes,
        "edges": edges,
        "cycle": cycle,
        "total_counts": {"nodes": len(raw_nodes), "edges": len(raw_edges)},
        "omitted_counts": {
            "nodes": max(len(raw_nodes) - len(nodes), 0),
            "edges": max(len(raw_edges) - len(edges), 0),
        },
    }


class AICollaborationService:
    def __init__(self, application: NavigatorApplication) -> None:
        self.application = application
        self.repository = SqlAlchemyCollaborationRepository(application.repository.session)

    def create_conversation(
        self,
        *,
        user_id: str,
        title: str,
        space_id: str | None,
        goal_id: str | None,
        provider_profile_id: str | None,
        purpose: str,
        context_key: str | None,
        context_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.application.repository.get_user(user_id)
        if space_id is not None:
            self.application.repository.get_space(space_id, user_id=user_id)
        if goal_id is not None:
            goal = self.application.repository.get_goal(goal_id, user_id=user_id)
            if goal.space_id != space_id:
                raise InvalidStateTransitionError(
                    "Conversation goal must belong to the selected framework space"
                )
        if provider_profile_id is not None:
            self.application.repository.get_ai_provider_profile(
                provider_profile_id,
                user_id=user_id,
            )
        snapshot = self._safe_page_context(context_snapshot)
        if purpose == "PLANNING":
            snapshot = self._planning_page_context(snapshot)
        self._assert_context_scope(
            purpose=purpose,
            context_key=context_key,
            space_id=space_id,
            goal_id=goal_id,
            page_context=snapshot,
        )
        conversation = self.repository.create_conversation(
            user_id=user_id,
            title=title.strip(),
            space_id=space_id,
            goal_id=goal_id,
            provider_profile_id=provider_profile_id,
            purpose=purpose,
            context_key=context_key,
            context_snapshot=snapshot,
        )
        self.application.repository.audit(
            user_id,
            "CREATE_AI_CONVERSATION",
            "AIConversation",
            conversation.id,
            after={
                "title": conversation.title,
                "space_id": conversation.space_id,
                "goal_id": conversation.goal_id,
                "purpose": conversation.purpose,
                "context_key": conversation.context_key,
            },
        )
        return self._detail(conversation)

    def list_conversations(
        self,
        *,
        user_id: str,
        space_id: str | None,
        goal_id: str | None,
        include_archived: bool,
        pre_project_only: bool,
        purpose: str | None,
        context_key: str | None,
    ) -> list[dict[str, Any]]:
        self.application.repository.get_user(user_id)
        if space_id is not None:
            self.application.repository.get_space(space_id, user_id=user_id)
        if goal_id is not None:
            goal = self.application.repository.get_goal(
                goal_id,
                user_id=user_id,
                include_archived=include_archived,
            )
            if space_id is not None and goal.space_id != space_id:
                return []
        return [
            self._conversation_payload(item)
            for item in self.repository.list_conversations(
                user_id=user_id,
                space_id=space_id,
                goal_id=goal_id,
                include_archived=include_archived,
                pre_project_only=pre_project_only,
                purpose=purpose,
                context_key=context_key,
            )
        ]

    def get_conversation(self, *, user_id: str, conversation_id: str) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        return self._detail(conversation)

    def archive_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        before = self._conversation_payload(conversation)
        archived = self.repository.archive(
            conversation,
            expected_revision=expected_revision,
        )
        self.application.repository.audit(
            user_id,
            "ARCHIVE_AI_CONVERSATION",
            "AIConversation",
            archived.id,
            before=before,
            after=self._conversation_payload(archived),
        )
        return self._detail(archived)

    def restore_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        before = self._conversation_payload(conversation)
        if conversation.goal_id is not None:
            # A project-scoped thread cannot outlive the active project lifecycle.
            self.application.repository.get_goal(conversation.goal_id, user_id=user_id)
        restored = self.repository.restore(
            conversation,
            expected_revision=expected_revision,
        )
        self.application.repository.audit(
            user_id,
            "RESTORE_AI_CONVERSATION",
            "AIConversation",
            restored.id,
            before=before,
            after=self._conversation_payload(restored),
        )
        return self._detail(restored)

    def delete_conversation_permanently(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_revision: int,
        confirm_title: str,
    ) -> None:
        """Permanently erase one reviewed conversation without touching derived projects."""

        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.assert_revision(conversation, expected_revision)
        if conversation.status != "ARCHIVED":
            raise InvalidStateTransitionError(
                "Only an archived conversation can be permanently deleted"
            )
        if confirm_title != conversation.title:
            raise InvalidStateTransitionError(
                "Permanent deletion confirmation must exactly match the conversation title"
            )
        deleted_message_count = self.repository.delete_permanently(conversation)
        self.application.repository.audit(
            user_id,
            "DELETE_AI_CONVERSATION",
            "AIConversation",
            conversation_id,
            details={
                "permanent": True,
                "content_redacted": True,
                "deleted_message_count": deleted_message_count,
            },
        )

    async def send_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
        provider_profile_id: str | None,
        confirmed_external_ai: bool,
        page_context: dict[str, Any] | None,
        message_origin: ConversationMessageOrigin = ConversationMessageOrigin.USER_INPUT,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.require_active(conversation)
        selected_profile_id = provider_profile_id or conversation.provider_profile_id
        safe_page_context = self._safe_page_context(page_context or conversation.context_snapshot)
        if conversation.purpose == "PLANNING":
            safe_page_context = self._planning_page_context(safe_page_context)
        self._assert_context_scope(
            purpose=conversation.purpose,
            context_key=conversation.context_key,
            space_id=conversation.space_id,
            goal_id=conversation.goal_id,
            page_context=safe_page_context,
        )
        if page_context is not None:
            conversation.context_snapshot = safe_page_context

        self._reopen_finalized_pre_project(conversation, user_id=user_id)

        # Persist the user's local turn before resolving or contacting an AI provider. Provider
        # configuration and per-turn consent can fail independently of the user's intent, and
        # those failures must not make the local conversation appear to have lost their message.
        user_message_metadata: dict[str, Any] = {
            "message_origin": str(message_origin),
        }
        if safe_page_context:
            user_message_metadata["page_context"] = safe_page_context
        user_message = self.repository.append_message(
            conversation,
            role="USER",
            content=content.strip(),
            message_metadata=user_message_metadata,
        )
        messages = self.repository.list_messages(conversation.id)
        explicit_outline_source = "\n\n".join(
            message.content for message in messages if message.role == "USER"
        )
        history, context_metadata, compacted_summary, summary_through = self._build_context(
            conversation,
            messages,
        )
        project_context = self._project_context(conversation, user_id=user_id)
        project_omitted_counts = project_context.get("omitted_counts", {})
        project_context_truncated = bool(
            isinstance(project_omitted_counts, dict)
            and any(
                isinstance(value, int) and value > 0 for value in project_omitted_counts.values()
            )
        )
        history_truncated = bool(context_metadata["truncated"])
        context_metadata["history_truncated"] = history_truncated
        context_metadata["project_context_truncated"] = project_context_truncated
        context_metadata["project_context_omitted_counts"] = project_omitted_counts
        context_metadata["truncated"] = history_truncated or project_context_truncated
        context = {
            "conversation_id": conversation.id,
            "latest_user_message": user_message.content,
            "history": history,
            "prior_summary": compacted_summary or None,
            "working_plan": json_safe(conversation.working_plan),
            # This is presentation context only. Project identity and every draft tool
            # authorization continue to come from the persisted conversation scope.
            "page_context": safe_page_context or None,
            "project": project_context,
            "tool_policy": {
                "enabled": conversation.space_id is not None
                and conversation.purpose in {"PLANNING", "PROJECT_ASSISTANT"},
                "allowed_tools": list(ALLOWED_TOOL_NAMES),
                "draft_only": True,
                "requires_human_approval": True,
                "forbidden": [
                    "publish_map",
                    "activate_path",
                    "update_mastery",
                    "delete_history",
                ],
            },
        }
        provider: AIProvider | None = None
        profile: AIProviderProfileModel | None = None
        raw_response: dict[str, Any] | None = None
        response_validation_issues: list[dict[str, Any]] = []
        used_planning_fallback = False
        try:
            provider, profile = self.application._resolve_ai_provider(
                user_id=user_id,
                provider_profile_id=selected_profile_id,
            )
            # Consent is evaluated for every network-bound turn; a prior turn is never reused as
            # blanket authorization for future context transmission.
            self.application._require_external_ai_confirmation(
                provider,
                confirmed_external_ai=confirmed_external_ai,
            )
            if provider_profile_id is not None:
                conversation.provider_profile_id = provider_profile_id
            provider_context = context
            response: CollaborationAIResponse | None = None
            explicit_sections = extract_explicit_outline_sections(explicit_outline_source)
            if (
                provider.name != "mock"
                and self._can_use_initial_planning_fallback(conversation, context)
                and 3 <= len(explicit_sections) <= 12
                and all(section.items for section in explicit_sections)
            ):
                # A detailed user-authored outline is far smaller and safer through the compact
                # plan protocol. Sending the full collaboration schema first can exceed an
                # 8K-output provider limit before any valid JSON reaches this process.
                response = await self._initial_planning_fallback(
                    provider,
                    latest_user_message=explicit_outline_source,
                    prior_summary=compacted_summary,
                )
                used_planning_fallback = True
            # External models occasionally return a nearly-correct structured
            # response even when JSON schema mode is enabled. Give them one
            # bounded repair attempt with field locations only; never persist
            # the invalid candidate and never duplicate the user's message.
            max_response_attempts = (
                0 if response is not None else (2 if provider.name != "mock" else 1)
            )
            for response_attempt in range(max_response_attempts):
                try:
                    raw_response = await provider.collaborate(
                        provider_context,
                        response_schema=CollaborationAIResponse.model_json_schema(),
                    )
                except AIProviderError as exc:
                    # Some OpenAI-compatible providers reject or truncate a large structured
                    # response before the adapter can return a Python mapping. Treat only the
                    # provider's explicit structured-output failure as repairable here; network,
                    # authentication and policy failures must retain their original semantics.
                    if exc.code != "invalid_response":
                        raise
                    issue = [{"type": "provider_invalid_response", "location": []}]
                    response_validation_issues = issue
                    if response_attempt + 1 >= max_response_attempts:
                        if provider.name != "mock" and self._can_use_initial_planning_fallback(
                            conversation, context
                        ):
                            response = await self._initial_planning_fallback(
                                provider,
                                latest_user_message=user_message.content,
                                prior_summary=compacted_summary,
                            )
                            used_planning_fallback = True
                            break
                        raise
                    provider_context = {
                        **context,
                        "response_repair": {
                            "attempt": response_attempt + 1,
                            "instruction": (
                                "The previous provider output could not be parsed as the required "
                                "JSON object. Return the entire response again as compact JSON "
                                "matching the schema and all modular outline rules."
                            ),
                            "issues": issue,
                        },
                    }
                    continue
                try:
                    candidate = CollaborationAIResponse.model_validate(raw_response)
                    if candidate.working_plan is not None:
                        explicit_outline = extract_explicit_outline_titles(explicit_outline_source)
                        validate_generated_plan_outline(
                            candidate.working_plan,
                            max_children_per_module=(8 if 3 <= len(explicit_outline) <= 12 else 4),
                        )
                        validate_explicit_outline_alignment(
                            candidate.working_plan,
                            explicit_outline_source,
                        )
                    response = candidate
                    break
                except (ValidationError, ValueError) as exc:
                    if isinstance(exc, ValidationError):
                        issue = [
                            {
                                "type": error["type"],
                                "location": [str(part) for part in error["loc"]],
                            }
                            for error in exc.errors(include_input=False, include_url=False)[:20]
                        ]
                    else:
                        issue = [{"type": "outline_validation", "message": str(exc)[:1200]}]
                    response_validation_issues = issue
                    if response_attempt + 1 >= max_response_attempts:
                        if provider.name != "mock" and self._can_use_initial_planning_fallback(
                            conversation, context
                        ):
                            response = await self._initial_planning_fallback(
                                provider,
                                latest_user_message=user_message.content,
                                prior_summary=compacted_summary,
                            )
                            used_planning_fallback = True
                            break
                        logger.warning(
                            "AI collaboration response rejected after repair; "
                            "provider=%s issues=%s",
                            provider.name,
                            issue,
                        )
                        if isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
                            raise AIProviderError(
                                "AI provider returned a plan without a complete modular outline",
                                code="invalid_response",
                                retryable=True,
                            ) from exc
                        raise
                    provider_context = {
                        **context,
                        "response_repair": {
                            "attempt": response_attempt + 1,
                            "instruction": (
                                "The previous candidate was rejected. Return the entire response "
                                "again as JSON matching the schema and all modular outline rules."
                            ),
                            "issues": issue,
                        },
                    }
            assert response is not None
        except (AIProviderError, DomainError, ValidationError) as exc:
            error_code = (
                exc.code
                if isinstance(exc, AIProviderError | DomainError)
                else "invalid_collaboration_response"
            )
            public_error_message = self._public_error_message(error_code)
            failure_provider, failure_model, failure_profile_id = self._provider_failure_identity(
                user_id=user_id,
                selected_profile_id=selected_profile_id,
                provider=provider,
                profile=profile,
            )
            assistant_message = self.repository.append_message(
                conversation,
                role="ASSISTANT",
                content="AI 请求未完成。你的消息已保存在本地，可以稍后重试。",
                structured_content={
                    "error": {"code": error_code, "message": public_error_message},
                    "tool_calls": [],
                },
                provider=failure_provider,
                model=failure_model,
                prompt_version=COLLABORATION_PROMPT_VERSION,
                message_metadata={
                    **context_metadata,
                    "provider_profile_id": failure_profile_id,
                    "request_failed": True,
                    "response_validation_issues": response_validation_issues,
                },
            )
            denied_tool_message_ids: list[str] = []
            raw_tool_calls = (
                raw_response.get("tool_calls") if isinstance(raw_response, dict) else None
            )
            if isinstance(raw_tool_calls, list):
                for index, raw_call in enumerate(raw_tool_calls[:20]):
                    raw_call_payload = raw_call if isinstance(raw_call, dict) else {"raw": raw_call}
                    raw_call_id = raw_call_payload.get("tool_call_id")
                    raw_name = raw_call_payload.get("name")
                    denied_call_id = f"denied-{assistant_message.id}-{index}"
                    tool_message = self.repository.append_message(
                        conversation,
                        role="TOOL",
                        content=f"{raw_name or 'unknown_tool'} denied",
                        structured_content={
                            "status": "DENIED",
                            "tool_call_id": denied_call_id,
                            "provider_tool_call_id": (
                                raw_call_id if isinstance(raw_call_id, str) else None
                            ),
                            "tool_name": raw_name if isinstance(raw_name, str) else "unknown",
                            "error": {
                                "code": "invalid_tool_call",
                                "message": "Tool call failed the controlled schema or whitelist",
                            },
                            "raw_call": json_safe(raw_call_payload),
                        },
                        tool_call_id=denied_call_id,
                        tool_name=raw_name if isinstance(raw_name, str) else "unknown",
                        prompt_version=COLLABORATION_PROMPT_VERSION,
                        message_metadata={
                            "denied": True,
                            "full_result_persisted": True,
                        },
                    )
                    denied_tool_message_ids.append(tool_message.id)
            self.repository.update_context(
                conversation,
                summary=compacted_summary,
                summary_through_sequence=summary_through,
                metadata={
                    **context_metadata,
                    "assistant_message_id": assistant_message.id,
                    "request_failed": True,
                    "error_code": error_code,
                    "denied_tool_message_count": len(denied_tool_message_ids),
                },
            )
            self.application.repository.audit(
                user_id,
                "AI_CONVERSATION_TURN_FAILED",
                "AIConversation",
                conversation.id,
                details={
                    "user_message_id": user_message.id,
                    "assistant_message_id": assistant_message.id,
                    "provider": failure_provider,
                    "model": failure_model,
                    "error_code": error_code,
                },
            )
            detail = self._detail(conversation)
            detail["turn"] = {
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "tool_message_ids": denied_tool_message_ids,
                "error": {"code": error_code, "message": public_error_message},
            }
            return detail
        except Exception:
            failure_id = new_id()
            logger.exception("Unexpected AI collaboration failure; trace_id=%s", failure_id)
            raise RuntimeError(
                f"Unexpected AI collaboration failure; trace_id={failure_id}"
            ) from None

        assert provider is not None
        assistant_message = self.repository.append_message(
            conversation,
            role="ASSISTANT",
            content=response.message,
            structured_content={
                "tool_calls": [call.model_dump(mode="json") for call in response.tool_calls],
                "working_plan": (
                    response.working_plan.model_dump(mode="json")
                    if response.working_plan is not None
                    else None
                ),
                "plan_ready": response.plan_ready,
            },
            provider=provider.name,
            model=provider.model,
            prompt_version=COLLABORATION_PROMPT_VERSION,
            message_metadata={
                **context_metadata,
                "provider_profile_id": profile.id if profile is not None else None,
                "structured_response_fallback": used_planning_fallback,
            },
        )

        tool_message_ids: list[str] = []
        for proposal_index, tool_call in enumerate(response.tool_calls):
            proposal_id = f"proposal-{assistant_message.id}-{proposal_index}"
            proposal = tool_call.model_dump(mode="json", exclude_unset=True)
            tool_message = self.repository.append_message(
                conversation,
                role="TOOL",
                content=f"{tool_call.name} pending review",
                structured_content={
                    "status": "PENDING",
                    "tool_call_id": proposal_id,
                    "provider_tool_call_id": tool_call.tool_call_id,
                    "tool_name": tool_call.name,
                    "proposal": proposal,
                },
                tool_call_id=proposal_id,
                tool_name=tool_call.name,
                prompt_version=COLLABORATION_PROMPT_VERSION,
                message_metadata={
                    "proposal": True,
                    "requires_human_review": True,
                    "full_result_persisted": True,
                },
            )
            tool_message_ids.append(tool_message.id)

        summary = response.conversation_summary or compacted_summary
        summary_sequence = (
            assistant_message.sequence_number if response.conversation_summary else summary_through
        )
        self.repository.update_context(
            conversation,
            summary=summary,
            summary_through_sequence=summary_sequence,
            metadata={
                **context_metadata,
                "assistant_message_id": assistant_message.id,
                "tool_message_count": len(tool_message_ids),
            },
            working_plan=(
                response.working_plan.model_dump(mode="json")
                if response.working_plan is not None
                else None
            ),
            replace_working_plan=response.working_plan is not None,
        )
        self.application.repository.audit(
            user_id,
            "AI_CONVERSATION_TURN",
            "AIConversation",
            conversation.id,
            details={
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "tool_message_ids": tool_message_ids,
                "provider": provider.name,
                "model": provider.model,
                "context_truncated": context_metadata["truncated"],
                "tool_proposal_count": len(tool_message_ids),
            },
        )
        detail = self._detail(conversation)
        detail["turn"] = {
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "tool_message_ids": tool_message_ids,
        }
        return detail

    def approve_tool_proposal(
        self,
        *,
        user_id: str,
        conversation_id: str,
        tool_call_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Execute one persisted proposal only after an explicit, revision-bound approval."""

        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.require_active(conversation)
        self.repository.assert_revision(conversation, expected_revision)
        tool_call = self._pending_tool_proposal(conversation, tool_call_id=tool_call_id)
        self._require_live_project_scope(conversation, user_id=user_id)

        result = self._execute_tool_safely(conversation, tool_call, user_id=user_id)
        serialized_result = json_safe(
            {
                **result,
                "proposal_tool_call_id": tool_call_id,
                "review_action": "APPROVE",
            }
        )
        decision = self.repository.append_message(
            conversation,
            role="TOOL",
            content=f"{tool_call.name} {str(result['status']).casefold()} after approval",
            structured_content=serialized_result,
            tool_call_id=f"review-{new_id()}",
            tool_name=tool_call.name,
            prompt_version=COLLABORATION_PROMPT_VERSION,
            message_metadata={
                "proposal_review": True,
                "review_action": "APPROVE",
                "full_result_persisted": True,
            },
        )
        self.repository.touch(conversation)
        self.application.repository.audit(
            user_id,
            "APPROVE_AI_TOOL_PROPOSAL",
            "AIConversation",
            conversation.id,
            details={
                "proposal_tool_call_id": tool_call_id,
                "tool_name": tool_call.name,
                "result_status": result["status"],
                "decision_message_id": decision.id,
            },
        )
        detail = self._detail(conversation)
        detail["proposal_review"] = serialized_result
        return detail

    def reject_tool_proposal(
        self,
        *,
        user_id: str,
        conversation_id: str,
        tool_call_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Record a rejection without applying any map or path mutation."""

        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.require_active(conversation)
        self.repository.assert_revision(conversation, expected_revision)
        tool_call = self._pending_tool_proposal(conversation, tool_call_id=tool_call_id)
        structured = {
            "status": "REJECTED",
            "proposal_tool_call_id": tool_call_id,
            "tool_name": tool_call.name,
            "review_action": "REJECT",
        }
        decision = self.repository.append_message(
            conversation,
            role="TOOL",
            content=f"{tool_call.name} rejected",
            structured_content=structured,
            tool_call_id=f"review-{new_id()}",
            tool_name=tool_call.name,
            prompt_version=COLLABORATION_PROMPT_VERSION,
            message_metadata={
                "proposal_review": True,
                "review_action": "REJECT",
                "full_result_persisted": True,
            },
        )
        self.repository.touch(conversation)
        self.application.repository.audit(
            user_id,
            "REJECT_AI_TOOL_PROPOSAL",
            "AIConversation",
            conversation.id,
            details={
                "proposal_tool_call_id": tool_call_id,
                "tool_name": tool_call.name,
                "decision_message_id": decision.id,
            },
        )
        detail = self._detail(conversation)
        detail["proposal_review"] = structured
        return detail

    def finalize_plan(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_revision: int,
        plan: LearningPlanDraft | None,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.assert_revision(conversation, expected_revision)
        self.repository.require_active(conversation)
        if conversation.purpose != "PLANNING":
            raise InvalidStateTransitionError(
                "Only a planning conversation can be finalized into a learning plan"
            )
        if conversation.space_id is not None or conversation.goal_id is not None:
            raise InvalidStateTransitionError(
                "Only a pre-project conversation can be finalized into a learning plan"
            )
        if conversation.final_plan is not None or conversation.learning_plan_id is not None:
            raise InvalidStateTransitionError(
                "This conversation plan is already finalized; continue the conversation to "
                "reopen its working draft"
            )
        payload = plan.model_dump(mode="json") if plan is not None else conversation.working_plan
        if not isinstance(payload, dict):
            raise InvalidStateTransitionError(
                "The conversation does not yet contain a complete working plan"
            )
        try:
            final_plan = LearningPlanDraft.model_validate(payload)
            analyzed = analyze_draft(final_plan)
        except (ValidationError, ValueError) as exc:
            raise AIOutputValidationError(f"Final conversation plan was rejected: {exc}") from exc

        assistant_messages = [
            message
            for message in self.repository.list_messages(conversation.id)
            if message.role == "ASSISTANT"
        ]
        provenance = assistant_messages[-1] if assistant_messages else None
        confidence_values = [node.confidence for node in final_plan.nodes] + [
            edge.confidence for edge in final_plan.edges
        ]
        proposed_changes = analyzed.model_dump(mode="json")
        proposed_changes["navigation"] = final_plan.navigation.model_dump(mode="json")
        proposed_changes["generation_input"] = {
            "conversation_id": conversation.id,
            "title": conversation.title,
        }
        proposed_changes["schema_version"] = "learning-plan-v1"
        suggestion = self.application.repository.create_suggestion(
            user_id=user_id,
            space_id=None,
            suggestion_type=SuggestionType.LEARNING_PLAN.value,
            target_type="LearningPlan",
            target_id=None,
            provider=(
                provenance.provider if provenance and provenance.provider else "conversation"
            ),
            model=(provenance.model if provenance and provenance.model else "unknown"),
            prompt_version=(
                provenance.prompt_version
                if provenance and provenance.prompt_version
                else COLLABORATION_PROMPT_VERSION
            ),
            raw_structured_output=final_plan.model_dump(mode="json"),
            proposed_changes=proposed_changes,
            reason="Conversation-refined framework awaiting explicit activation",
            confidence=(
                sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
            ),
            sources=[],
            # Finalization freezes a reviewable proposal only. Structural conflicts remain in
            # proposed_changes and are rejected by the separate activation boundary.
            review_status=ReviewStatus.PENDING.value,
        )
        finalized = self.repository.finalize_plan(
            conversation,
            expected_revision=expected_revision,
            plan=final_plan.model_dump(mode="json"),
            learning_plan_id=suggestion.id,
        )
        self.application.repository.audit(
            user_id,
            "FINALIZE_CONVERSATION_PLAN",
            "AIConversation",
            finalized.id,
            after={
                "learning_plan_id": suggestion.id,
                "conflicts": len(analyzed.conflicts),
                "row_version": finalized.row_version,
            },
        )
        return self._detail(finalized)

    def activate_plan(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id, user_id=user_id)
        self.repository.assert_revision(conversation, expected_revision)
        self.repository.require_active(conversation)
        if conversation.purpose != "PLANNING":
            raise InvalidStateTransitionError("Only a planning conversation can create a project")
        if conversation.space_id is not None or conversation.goal_id is not None:
            raise InvalidStateTransitionError(
                "This conversation has already created a project and cannot be activated again"
            )
        if not conversation.learning_plan_id or not conversation.final_plan:
            raise InvalidStateTransitionError(
                "Finalize the conversation plan before creating a project"
            )
        activation = self.application.activate_learning_plan(
            user_id=user_id,
            plan_id=conversation.learning_plan_id,
        )
        space = activation.get("space")
        goal = activation.get("goal")
        if not isinstance(space, dict) or not isinstance(space.get("id"), str):
            raise InvalidStateTransitionError("Learning plan activation returned no project")
        if not isinstance(goal, dict) or not isinstance(goal.get("id"), str):
            raise InvalidStateTransitionError("Learning plan activation returned no goal")
        self.repository.bind_activation(
            conversation,
            plan_id=conversation.learning_plan_id,
            space_id=str(space["id"]),
            goal_id=str(goal["id"]),
        )
        self.application.repository.audit(
            user_id,
            "ACTIVATE_CONVERSATION_PLAN",
            "AIConversation",
            conversation.id,
            after={
                "learning_plan_id": conversation.learning_plan_id,
                "space_id": conversation.space_id,
                "goal_id": conversation.goal_id,
            },
        )
        return {
            "conversation": self._conversation_payload(conversation),
            "activation": json_safe(activation),
        }

    def _reopen_finalized_pre_project(
        self,
        conversation: AIConversationModel,
        *,
        user_id: str,
    ) -> None:
        """Continuing a pre-project chat supersedes, rather than silently reuses, its lock."""

        if conversation.purpose != "PLANNING":
            return
        plan_id = conversation.learning_plan_id
        if (
            conversation.space_id is not None
            or conversation.goal_id is not None
            or plan_id is None
            or conversation.final_plan is None
        ):
            return
        suggestion = self.application.repository.get_suggestion(plan_id, user_id=user_id)
        if suggestion.review_status in {
            ReviewStatus.ACCEPTED.value,
            ReviewStatus.MODIFIED_ACCEPTED.value,
        }:
            raise InvalidStateTransitionError(
                "The finalized plan has already been accepted and cannot return to draft"
            )
        if suggestion.review_status in {
            ReviewStatus.PENDING.value,
            ReviewStatus.CONFLICT.value,
        }:
            suggestion.review_status = ReviewStatus.REJECTED.value
            suggestion.reviewed_by = user_id
            suggestion.reviewed_at = now_utc()
            suggestion.review_note = (
                "Superseded because the conversation continued after finalization"
            )
        self.repository.reopen_working_plan(conversation)
        self.application.repository.audit(
            user_id,
            "REOPEN_FINALIZED_CONVERSATION_PLAN",
            "AIConversation",
            conversation.id,
            before={"learning_plan_id": plan_id},
            after={"learning_plan_id": None, "working_plan_retained": True},
        )

    def _provider_failure_identity(
        self,
        *,
        user_id: str,
        selected_profile_id: str | None,
        provider: AIProvider | None,
        profile: AIProviderProfileModel | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Return non-secret provider metadata without masking the original failure."""

        if provider is not None:
            return provider.name, provider.model, profile.id if profile is not None else None

        fallback_profile = profile
        if fallback_profile is None:
            try:
                fallback_profile = (
                    self.application.repository.get_ai_provider_profile(
                        selected_profile_id,
                        user_id=user_id,
                    )
                    if selected_profile_id is not None
                    else self.application.repository.get_default_ai_provider_profile(user_id)
                )
            except DomainError:
                fallback_profile = None
        if fallback_profile is not None:
            return (
                fallback_profile.provider,
                fallback_profile.model,
                fallback_profile.id,
            )
        if selected_profile_id is None:
            return (
                self.application.ai_provider.name,
                self.application.ai_provider.model,
                None,
            )
        return None, None, selected_profile_id

    @staticmethod
    def _can_use_initial_planning_fallback(
        conversation: AIConversationModel,
        context: dict[str, Any],
    ) -> bool:
        """Allow the smaller plan schema only for a new, still-empty planning draft."""

        return (
            conversation.purpose == "PLANNING"
            and conversation.goal_id is None
            and context.get("working_plan") is None
        )

    @staticmethod
    async def _initial_planning_fallback(
        provider: AIProvider,
        *,
        latest_user_message: str,
        prior_summary: str | None,
    ) -> CollaborationAIResponse:
        """Recover an initial plan through the provider's smaller dedicated schema."""

        requirements = (
            "This is a structured-output recovery for the same user request. Preserve every "
            "explicit scope, time, background, module, grouping, route and verification "
            "constraint from the topic. Infer LEARN, UNDERSTAND or DO from the user's actual "
            "purpose. Return a complete modular plan, not an explanation."
        )
        if prior_summary:
            requirements += f" Prior conversation summary: {prior_summary[:2000]}"
        plan = await provider.generate_learning_plan(latest_user_message, requirements)
        return CollaborationAIResponse(
            message=(
                "已根据你的目标生成一份完整、可编辑的框架草稿。你可以继续要求增删模块、"
                "调整关系或修改路径，确认后再建立项目。"
            ),
            tool_calls=[],
            working_plan=plan,
            plan_ready=True,
            conversation_summary=latest_user_message[:1000],
        )

    @staticmethod
    def _safe_page_context(value: dict[str, Any] | None) -> dict[str, Any]:
        """Apply the same allow-list below the HTTP boundary for internal callers too."""

        if not isinstance(value, dict):
            return {}
        safe: dict[str, Any] = {
            key: item
            for key in PAGE_CONTEXT_FIELDS
            if isinstance((item := value.get(key)), str) and item
        }
        page_state = _safe_page_state(value.get("page_state"))
        if page_state:
            safe["page_state"] = page_state
        return safe

    @staticmethod
    def _planning_page_context(page_context: dict[str, Any]) -> dict[str, Any]:
        """Remove existing-project facts before a new-project planning turn."""

        safe = dict(page_context)
        for key in PROJECT_PAGE_CONTEXT_FIELDS:
            safe.pop(key, None)
        return safe

    @staticmethod
    def _assert_context_scope(
        *,
        purpose: str,
        context_key: str | None,
        space_id: str | None,
        goal_id: str | None,
        page_context: dict[str, Any],
    ) -> None:
        """Keep UI context descriptive; persisted conversation fields remain authoritative."""

        allowed_purposes = {"PLANNING", "PAGE_ASSISTANT", "PROJECT_ASSISTANT"}
        if purpose not in allowed_purposes:
            raise InvalidStateTransitionError("Unsupported AI conversation purpose")
        if purpose in {"PLANNING", "PAGE_ASSISTANT"} and (
            page_context.get("space_id") or page_context.get("goal_id")
        ):
            raise InvalidStateTransitionError(
                "A page or planning conversation cannot claim project scope"
            )
        if purpose == "PAGE_ASSISTANT":
            if context_key is None or not context_key.startswith("page:"):
                raise InvalidStateTransitionError(
                    "Page assistants require a stable page context key"
                )
            if space_id is not None or goal_id is not None:
                raise InvalidStateTransitionError("Page assistants cannot own a project scope")
            page_key = page_context.get("page_key")
            if isinstance(page_key, str) and context_key != f"page:{page_key}":
                raise InvalidStateTransitionError(
                    "Page assistant context does not match its persisted context key"
                )
        if purpose != "PROJECT_ASSISTANT":
            return
        if space_id is None or goal_id is None:
            raise InvalidStateTransitionError(
                "Project assistants require a persisted project scope"
            )
        if context_key != f"project:{goal_id}":
            raise InvalidStateTransitionError(
                "Project assistant context does not match its persisted goal"
            )
        page_space_id = page_context.get("space_id")
        page_goal_id = page_context.get("goal_id")
        if isinstance(page_space_id, str) and page_space_id != space_id:
            raise InvalidStateTransitionError(
                "Page context cannot change the assistant's project space"
            )
        if isinstance(page_goal_id, str) and page_goal_id != goal_id:
            raise InvalidStateTransitionError(
                "Page context cannot change the assistant's project goal"
            )

    def _execute_tool_safely(
        self,
        conversation: AIConversationModel,
        tool_call: CollaborationToolCall,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        try:
            with self.application.repository.session.begin_nested():
                result = self._execute_tool(conversation, tool_call, user_id=user_id)
            return {
                "status": "SUCCEEDED",
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.name,
                "result": json_safe(result),
            }
        except DomainError as exc:  # expected domain rejection is durable and reviewable
            code = exc.code
            return {
                "status": "FAILED",
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.name,
                "error": {"code": code, "message": self._public_error_message(code)},
            }

    def _pending_tool_proposal(
        self,
        conversation: AIConversationModel,
        *,
        tool_call_id: str,
    ) -> CollaborationToolCall:
        messages = self.repository.list_messages(conversation.id)
        proposal_message = next(
            (
                message
                for message in messages
                if message.role == "TOOL"
                and message.tool_call_id == tool_call_id
                and isinstance(message.structured_content, dict)
                and message.structured_content.get("status") == "PENDING"
            ),
            None,
        )
        if proposal_message is None:
            raise InvalidStateTransitionError("The AI tool proposal is not pending review")
        if any(
            isinstance(message.structured_content, dict)
            and message.structured_content.get("proposal_tool_call_id") == tool_call_id
            for message in messages
        ):
            raise InvalidStateTransitionError("The AI tool proposal was already reviewed")

        proposal = proposal_message.structured_content.get("proposal")
        try:
            parsed = CollaborationAIResponse.model_validate(
                {"message": "", "tool_calls": [proposal]}
            )
        except ValidationError as exc:
            raise InvalidStateTransitionError(
                "The stored AI tool proposal is invalid and cannot be approved"
            ) from exc
        tool_call = parsed.tool_calls[0]
        provider_tool_call_id = proposal_message.structured_content.get("provider_tool_call_id")
        if (
            tool_call.tool_call_id != provider_tool_call_id
            or tool_call.name not in ALLOWED_TOOL_NAMES
        ):
            raise InvalidStateTransitionError(
                "The stored AI tool proposal no longer matches its review record"
            )
        return tool_call

    def _require_live_project_scope(
        self,
        conversation: AIConversationModel,
        *,
        user_id: str,
    ) -> None:
        if conversation.space_id is None:
            raise InvalidStateTransitionError(
                "AI tool proposals require an active project framework"
            )
        self.application.repository.get_space(conversation.space_id, user_id=user_id)
        if conversation.goal_id is not None:
            goal = self.application.repository.get_goal(
                conversation.goal_id,
                user_id=user_id,
            )
            if goal.space_id != conversation.space_id:
                raise InvalidStateTransitionError(
                    "The conversation project scope no longer matches its framework"
                )

    @staticmethod
    def _public_error_message(code: str) -> str:
        messages = {
            "authentication_error": "AI provider authentication failed",
            "rate_limit_error": "AI provider rate limit was reached",
            "timeout_error": "AI provider request timed out",
            "configuration_error": "AI provider configuration is unavailable or invalid",
            "invalid_collaboration_response": "AI response did not match the required format",
            "invalid_state_transition": "The requested change is no longer valid in current state",
            "revision_conflict": "The project changed; refresh before retrying",
            "entity_not_found": "The referenced project data is no longer available",
        }
        return messages.get(code, "The request could not be completed safely")

    def _execute_tool(
        self,
        conversation: AIConversationModel,
        tool_call: CollaborationToolCall,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        if conversation.space_id is None or conversation.purpose not in {
            "PLANNING",
            "PROJECT_ASSISTANT",
        }:
            raise InvalidStateTransitionError(
                "Draft tools are disabled outside a persisted project collaboration scope"
            )
        space_id = conversation.space_id
        if isinstance(tool_call, AddNodeToolCall):
            add_node_args = tool_call.arguments
            self._require_editable_map_version(
                space_id,
                expected_map_version_id=add_node_args.expected_map_version_id,
            )
            return self.application.create_node(
                user_id=user_id,
                space_id=space_id,
                title=add_node_args.title,
                description=add_node_args.description,
                node_type=add_node_args.node_type,
                difficulty=add_node_args.difficulty,
                depth_level=add_node_args.depth_level,
                learning_objectives=add_node_args.learning_objectives,
                source_basis=[{"reference": item} for item in add_node_args.source_references],
                stable_key=add_node_args.stable_key,
                change_source="AI_COLLABORATION",
                manually_locked=False,
            )
        if isinstance(tool_call, UpdateNodeToolCall):
            update_node_args = tool_call.arguments
            self._require_editable_map_version(
                space_id,
                expected_map_version_id=update_node_args.expected_map_version_id,
            )
            values = update_node_args.model_dump(exclude_unset=True)
            values.pop("node_id")
            values.pop("expected_map_version_id")
            source_references = values.pop("source_references", None)
            if source_references is not None:
                values["source_basis"] = [{"reference": item} for item in source_references]
            return self.application.update_node(
                user_id=user_id,
                space_id=space_id,
                node_id=update_node_args.node_id,
                changes=values,
            )
        if isinstance(tool_call, ArchiveNodeToolCall):
            archive_node_args = tool_call.arguments
            self._require_editable_map_version(
                space_id,
                expected_map_version_id=archive_node_args.expected_map_version_id,
            )
            result = self.application.delete_node_permanently(
                user_id=user_id,
                space_id=space_id,
                node_id=archive_node_args.node_id,
            )
            return {"node_id": archive_node_args.node_id, **result}
        if isinstance(tool_call, AddRelationToolCall):
            add_relation_args = tool_call.arguments
            self._require_editable_map_version(
                space_id,
                expected_map_version_id=add_relation_args.expected_map_version_id,
            )
            return self.application.create_edge(
                user_id=user_id,
                space_id=space_id,
                source_node_id=add_relation_args.source_node_id,
                target_node_id=add_relation_args.target_node_id,
                relation_type=add_relation_args.relation_type,
                strength=add_relation_args.strength,
                confidence=add_relation_args.confidence,
                required_mastery_level=add_relation_args.required_mastery_level,
                reason=add_relation_args.reason,
                source_reference=[
                    {"reference": item} for item in add_relation_args.source_references
                ],
                manually_locked=False,
            )
        if isinstance(tool_call, CreatePathDraftToolCall):
            create_path_args = tool_call.arguments
            map_version_id = self._require_editable_map_version(
                space_id,
                expected_map_version_id=create_path_args.expected_map_version_id,
            )
            goal = self._scoped_goal(
                create_path_args.goal_id,
                space_id=space_id,
                user_id=user_id,
            )
            return self.application.generate_path(
                user_id=user_id,
                goal_id=goal.id,
                map_version_id=map_version_id,
                activate=False,
                origin=PathOrigin.AI_GENERATED,
                change_summary=create_path_args.change_summary,
            )
        if isinstance(tool_call, ClonePathDraftToolCall):
            clone_path_args = tool_call.arguments
            path = self._scoped_path(
                clone_path_args.path_id,
                space_id=space_id,
                user_id=user_id,
            )
            result = self.application.clone_path_revision(
                user_id=user_id,
                path_id=path.id,
                expected_revision=clone_path_args.expected_revision,
                change_summary=clone_path_args.change_summary,
            )
            clone = self.application.repository.get_path_revision(
                str(result["path"]["id"]),
                user_id=user_id,
            )
            clone.origin = PathOrigin.AI_GENERATED.value
            return result
        if isinstance(tool_call, AddPathStepToolCall):
            add_step_args = tool_call.arguments
            self._scoped_path(add_step_args.path_id, space_id=space_id, user_id=user_id)
            result = self.application.add_path_step(
                user_id=user_id,
                **add_step_args.model_dump(),
            )
            self._mark_ai_path_step(result, node_id=add_step_args.node_id)
            return result
        if isinstance(tool_call, UpdatePathStepToolCall):
            update_step_args = tool_call.arguments
            self._scoped_path(update_step_args.path_id, space_id=space_id, user_id=user_id)
            values = update_step_args.model_dump(exclude_unset=True)
            path_id = str(values.pop("path_id"))
            step_id = str(values.pop("step_id"))
            expected_revision = int(values.pop("expected_revision"))
            result = self.application.update_path_step(
                user_id=user_id,
                path_id=path_id,
                step_id=step_id,
                expected_revision=expected_revision,
                changes=values,
            )
            self._mark_ai_path_step(result, step_id=step_id)
            return result
        if isinstance(tool_call, ReorderPathStepToolCall):
            reorder_step_args = tool_call.arguments
            self._scoped_path(
                reorder_step_args.path_id,
                space_id=space_id,
                user_id=user_id,
            )
            result = self.application.update_path_step(
                user_id=user_id,
                path_id=reorder_step_args.path_id,
                step_id=reorder_step_args.step_id,
                expected_revision=reorder_step_args.expected_revision,
                changes={"preferred_order": reorder_step_args.preferred_order},
            )
            self._mark_ai_path_step(result, step_id=reorder_step_args.step_id)
            return result
        if isinstance(tool_call, RemovePathStepToolCall):
            remove_step_args = tool_call.arguments
            self._scoped_path(remove_step_args.path_id, space_id=space_id, user_id=user_id)
            return self.application.remove_path_step(
                user_id=user_id,
                path_id=remove_step_args.path_id,
                step_id=remove_step_args.step_id,
                expected_revision=remove_step_args.expected_revision,
            )
        raise InvalidStateTransitionError(f"Unsupported collaboration tool: {tool_call.name}")

    def _require_editable_map_version(
        self,
        space_id: str,
        *,
        expected_map_version_id: str,
    ) -> str:
        current = self.application.repository.get_editable_version(space_id)
        if current.id != expected_map_version_id:
            raise InvalidStateTransitionError(
                "Editable map revision changed while the AI was preparing its draft; "
                "refresh the conversation context before retrying"
            )
        return current.id

    def _scoped_goal(self, goal_id: str, *, space_id: str, user_id: str) -> Any:
        goal = self.application.repository.get_goal(goal_id, user_id=user_id)
        if goal.space_id != space_id:
            raise InvalidStateTransitionError("Tool goal is outside this conversation project")
        return goal

    def _scoped_path(
        self,
        path_id: str,
        *,
        space_id: str,
        user_id: str,
    ) -> LearningPathModel:
        path = self.application.repository.get_path_revision(path_id, user_id=user_id)
        if path.space_id != space_id:
            raise InvalidStateTransitionError("Tool path is outside this conversation project")
        return path

    def _mark_ai_path_step(
        self,
        result: dict[str, Any],
        *,
        node_id: str | None = None,
        step_id: str | None = None,
    ) -> None:
        raw_steps = result.get("steps")
        if not isinstance(raw_steps, list):
            return
        target = next(
            (
                item
                for item in raw_steps
                if isinstance(item, dict)
                and (step_id is None or item.get("id") == step_id)
                and (node_id is None or item.get("node_id") == node_id)
            ),
            None,
        )
        if not isinstance(target, dict) or not isinstance(target.get("id"), str):
            return
        row = self.application.repository.session.get(
            LearningPathNodeModel,
            str(target["id"]),
        )
        if row is not None:
            row.source = PathStepSource.AI_GENERATED.value

    def _project_context(
        self,
        conversation: AIConversationModel,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        if conversation.space_id is None:
            return {"exists": False, "goal_id": None}
        space = self.application.repository.get_space(conversation.space_id, user_id=user_id)
        all_goals = [
            goal
            for goal in self.application.repository.list_goals(user_id)
            if goal.space_id == space.id and goal.status != GoalStatus.ARCHIVED.value
        ]
        goals = sorted(
            all_goals,
            key=lambda goal: (goal.id != conversation.goal_id, goal.created_at, goal.id),
        )[:MAX_PROJECT_CONTEXT_GOALS]
        visible_goal_ids = [goal.id for goal in all_goals]
        selected_goal = next(
            (goal for goal in all_goals if goal.id == conversation.goal_id),
            None,
        )
        priority_node_ids: list[str] = []
        if selected_goal is not None:
            priority_node_ids.append(selected_goal.target_node_id)
        page_state = conversation.context_snapshot.get("page_state")
        current_node = page_state.get("current_node") if isinstance(page_state, dict) else None
        for candidate in (
            conversation.context_snapshot.get("node_id"),
            current_node.get("node_id") if isinstance(current_node, dict) else None,
        ):
            if isinstance(candidate, str) and candidate not in priority_node_ids:
                priority_node_ids.append(candidate)

        path_query = (
            self.application.repository.session.query(LearningPathModel)
            .filter(
                LearningPathModel.space_id == space.id,
                LearningPathModel.goal_id.in_(visible_goal_ids),
            )
            .order_by(LearningPathModel.generated_at.desc())
        )
        path_revision_count = path_query.count()
        path_revisions = path_query.limit(MAX_PROJECT_CONTEXT_PATH_REVISIONS).all()
        editable_map = _bounded_project_map(
            self.application.graph_view(
                space_id=space.id,
                user_id=user_id,
            ),
            priority_node_ids=priority_node_ids,
        )
        map_omitted = editable_map["omitted_counts"]
        omitted_counts = {
            "goals": max(len(all_goals) - len(goals), 0),
            "path_revisions": max(path_revision_count - len(path_revisions), 0),
            "map_nodes": int(map_omitted["nodes"]),
            "map_edges": int(map_omitted["edges"]),
        }
        return {
            "exists": True,
            "space": {
                "id": space.id,
                "title": _bounded_page_text(space.title, 240),
                "description": _bounded_page_text(
                    space.description,
                    MAX_PROJECT_NODE_TEXT_CHARS,
                ),
                "target_audience": _bounded_page_text(space.target_audience, 500),
                "scope_included": _bounded_text_list(space.scope_included),
                "scope_excluded": _bounded_text_list(space.scope_excluded),
                "status": space.status,
            },
            "selected_goal_id": conversation.goal_id,
            "goals": [
                {
                    "id": goal.id,
                    "title": goal.title,
                    "target_node_id": goal.target_node_id,
                    "intent_mode": goal.intent_mode,
                    "status": goal.status,
                }
                for goal in goals
            ],
            "editable_map": editable_map,
            "path_revisions": [
                {
                    "id": path.id,
                    "goal_id": path.goal_id,
                    "status": path.status,
                    "row_version": path.row_version,
                    "map_version_id": path.map_version_id,
                    "origin": path.origin,
                }
                for path in path_revisions
            ],
            "total_counts": {
                "goals": len(all_goals),
                "path_revisions": path_revision_count,
                "map_nodes": editable_map["total_counts"]["nodes"],
                "map_edges": editable_map["total_counts"]["edges"],
            },
            "omitted_counts": omitted_counts,
        }

    def _build_context(
        self,
        conversation: AIConversationModel,
        messages: list[AIConversationMessageModel],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str, int]:
        unsummarized = [
            message
            for message in messages
            if message.sequence_number > conversation.summary_through_sequence
        ]
        summarized_tail = [
            message
            for message in messages
            if message.sequence_number <= conversation.summary_through_sequence
            and message.role in {"USER", "ASSISTANT"}
        ][-4:]
        candidates = [*summarized_tail, *unsummarized]
        selected: list[tuple[AIConversationMessageModel, dict[str, Any], int]] = []
        used_chars = len(conversation.summary)
        for message in reversed(candidates):
            serialized = self._message_for_context(message)
            char_count = len(json.dumps(serialized, ensure_ascii=False, separators=(",", ":")))
            if selected and used_chars + char_count > MAX_CONTEXT_CHARS:
                break
            selected.append((message, serialized, char_count))
            used_chars += char_count
        selected.reverse()
        selected_ids = {message.id for message, _, _ in selected}
        omitted = [message for message in unsummarized if message.id not in selected_ids]
        summary = conversation.summary
        summary_through = conversation.summary_through_sequence
        if omitted:
            summary = self._merge_summary(summary, omitted)
            summary_through = max(item.sequence_number for item in omitted)
        history = [serialized for _, serialized, _ in selected]
        metadata = {
            "history_message_count": len(messages),
            "included_message_count": len(selected),
            "replayed_recent_message_count": sum(
                message.id in selected_ids for message in summarized_tail
            ),
            "omitted_message_count": len(omitted),
            "truncated": bool(omitted),
            "summary_used": bool(summary),
            "summary_through_sequence": summary_through,
            "context_chars": used_chars,
        }
        return history, metadata, summary, summary_through

    @staticmethod
    def _message_for_context(message: AIConversationMessageModel) -> dict[str, Any]:
        structured = json.dumps(
            json_safe(message.structured_content),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(structured) > MAX_CONTEXT_MESSAGE_CHARS:
            structured = structured[:MAX_CONTEXT_MESSAGE_CHARS] + "…"
        content = message.content
        if len(content) > MAX_CONTEXT_MESSAGE_CHARS:
            content = content[:MAX_CONTEXT_MESSAGE_CHARS] + "…"
        return {
            "sequence": message.sequence_number,
            "role": message.role,
            "content": content,
            "structured_content": structured,
            "tool_name": message.tool_name,
        }

    @staticmethod
    def _merge_summary(
        existing: str,
        omitted: list[AIConversationMessageModel],
    ) -> str:
        lines = [existing] if existing else []
        for message in omitted:
            content = " ".join(message.content.split())
            if message.role == "TOOL":
                content = f"{message.tool_name or 'tool'}: {content}"
            lines.append(f"{message.role}: {content[:800]}")
        return "\n".join(lines)[-MAX_SUMMARY_CHARS:]

    def _detail(self, conversation: AIConversationModel) -> dict[str, Any]:
        return {
            "conversation": self._conversation_payload(conversation),
            "messages": [
                self._message_payload(message)
                for message in self.repository.list_messages(conversation.id)
            ],
        }

    @staticmethod
    def _conversation_payload(conversation: AIConversationModel) -> dict[str, Any]:
        return model_dict(conversation)

    @staticmethod
    def _message_payload(message: AIConversationMessageModel) -> dict[str, Any]:
        return model_dict(message)
