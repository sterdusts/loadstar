"""Persistence boundary for long-lived AI collaboration conversations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from learning_navigator.domain.exceptions import (
    EntityNotFoundError,
    InvalidStateTransitionError,
    RevisionConflictError,
)
from learning_navigator.infrastructure.database.base import now_utc
from learning_navigator.infrastructure.database.models import (
    AIConversationMessageModel,
    AIConversationModel,
)


class SqlAlchemyCollaborationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

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
        context_snapshot: dict[str, Any],
    ) -> AIConversationModel:
        conversation = AIConversationModel(
            user_id=user_id,
            title=title,
            space_id=space_id,
            goal_id=goal_id,
            provider_profile_id=provider_profile_id,
            purpose=purpose,
            context_key=context_key,
            context_snapshot=context_snapshot,
            status="ACTIVE",
            summary="",
            summary_through_sequence=0,
            last_context_metadata={},
            row_version=1,
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def list_conversations(
        self,
        *,
        user_id: str,
        space_id: str | None = None,
        goal_id: str | None = None,
        include_archived: bool = False,
        pre_project_only: bool = False,
        purpose: str | None = None,
        context_key: str | None = None,
    ) -> list[AIConversationModel]:
        query = select(AIConversationModel).where(AIConversationModel.user_id == user_id)
        if space_id is not None:
            query = query.where(AIConversationModel.space_id == space_id)
        elif pre_project_only:
            query = query.where(AIConversationModel.space_id.is_(None))
        if goal_id is not None:
            query = query.where(AIConversationModel.goal_id == goal_id)
        if pre_project_only:
            # This legacy selector powers the planning/onboarding history. Contextual
            # page assistants must never appear there, even though they also have no space.
            query = query.where(AIConversationModel.purpose == "PLANNING")
        elif purpose is not None:
            query = query.where(AIConversationModel.purpose == purpose)
        if context_key is not None:
            query = query.where(AIConversationModel.context_key == context_key)
        if not include_archived:
            query = query.where(AIConversationModel.status == "ACTIVE")
        # A conversation becomes history only after its first persisted turn.
        # Empty rows can exist after an interrupted create/send sequence, but
        # must never surface as user-visible conversation records.
        query = query.where(
            select(AIConversationMessageModel.id)
            .where(AIConversationMessageModel.conversation_id == AIConversationModel.id)
            .exists()
        )
        return list(
            self.session.scalars(
                query.order_by(
                    AIConversationModel.updated_at.desc(),
                    AIConversationModel.id.desc(),
                )
            )
        )

    def get_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str,
    ) -> AIConversationModel:
        conversation = self.session.scalar(
            select(AIConversationModel).where(
                AIConversationModel.id == conversation_id,
                AIConversationModel.user_id == user_id,
            )
        )
        if conversation is None:
            raise EntityNotFoundError("AI conversation", conversation_id)
        return conversation

    @staticmethod
    def assert_revision(conversation: AIConversationModel, expected_revision: int) -> None:
        if conversation.row_version != expected_revision:
            raise RevisionConflictError(
                expected_revision=expected_revision,
                current_revision=conversation.row_version,
            )

    @staticmethod
    def require_active(conversation: AIConversationModel) -> None:
        if conversation.status != "ACTIVE":
            raise InvalidStateTransitionError("Archived conversations are read-only")

    def archive(
        self,
        conversation: AIConversationModel,
        *,
        expected_revision: int,
    ) -> AIConversationModel:
        self.assert_revision(conversation, expected_revision)
        if conversation.status == "ARCHIVED":
            return conversation
        conversation.status = "ARCHIVED"
        conversation.archived_at = now_utc()
        self.touch(conversation)
        self.session.flush()
        return conversation

    def append_message(
        self,
        conversation: AIConversationModel,
        *,
        role: str,
        content: str,
        structured_content: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        message_metadata: dict[str, Any] | None = None,
    ) -> AIConversationMessageModel:
        next_sequence = (
            int(
                self.session.scalar(
                    select(func.max(AIConversationMessageModel.sequence_number)).where(
                        AIConversationMessageModel.conversation_id == conversation.id
                    )
                )
                or 0
            )
            + 1
        )
        message = AIConversationMessageModel(
            conversation_id=conversation.id,
            sequence_number=next_sequence,
            role=role,
            content=content,
            structured_content=structured_content or {},
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            message_metadata=message_metadata or {},
        )
        self.session.add(message)
        self.session.flush()
        return message

    def list_messages(self, conversation_id: str) -> list[AIConversationMessageModel]:
        return list(
            self.session.scalars(
                select(AIConversationMessageModel)
                .where(AIConversationMessageModel.conversation_id == conversation_id)
                .order_by(AIConversationMessageModel.sequence_number)
            )
        )

    def update_context(
        self,
        conversation: AIConversationModel,
        *,
        summary: str | None = None,
        summary_through_sequence: int | None = None,
        metadata: dict[str, Any],
        working_plan: dict[str, Any] | None = None,
        replace_working_plan: bool = False,
    ) -> None:
        if summary is not None:
            conversation.summary = summary
        if summary_through_sequence is not None:
            conversation.summary_through_sequence = summary_through_sequence
        conversation.last_context_metadata = metadata
        if replace_working_plan:
            conversation.working_plan = working_plan
        self.touch(conversation)
        self.session.flush()

    def finalize_plan(
        self,
        conversation: AIConversationModel,
        *,
        expected_revision: int,
        plan: dict[str, Any],
        learning_plan_id: str,
    ) -> AIConversationModel:
        self.assert_revision(conversation, expected_revision)
        self.require_active(conversation)
        conversation.final_plan = plan
        conversation.learning_plan_id = learning_plan_id
        self.touch(conversation)
        self.session.flush()
        return conversation

    def reopen_working_plan(self, conversation: AIConversationModel) -> None:
        """Clear the frozen proposal while retaining its draft and message history."""

        conversation.final_plan = None
        conversation.learning_plan_id = None
        self.session.flush()

    def bind_activation(
        self,
        conversation: AIConversationModel,
        *,
        plan_id: str,
        space_id: str,
        goal_id: str,
    ) -> None:
        conversation.learning_plan_id = plan_id
        conversation.space_id = space_id
        conversation.goal_id = goal_id
        # The same durable history now follows the concrete project in the global
        # assistant instead of becoming an orphaned onboarding-only thread.
        conversation.purpose = "PROJECT_ASSISTANT"
        conversation.context_key = f"project:{goal_id}"
        self.touch(conversation)
        self.session.flush()

    @staticmethod
    def touch(conversation: AIConversationModel) -> None:
        conversation.updated_at = now_utc()
        conversation.row_version += 1
