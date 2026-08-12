"""Durable AI collaboration and explicit project-creation endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.api.schemas.collaboration import (
    ConversationCreateRequest,
    ConversationFinalizePlanRequest,
    ConversationPermanentDeleteRequest,
    ConversationRevisionRequest,
    ConversationSendRequest,
)
from learning_navigator.application.collaboration import AICollaborationService

router = APIRouter(prefix="/ai/conversations", tags=["AI collaboration"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).create_conversation(
        user_id=user_id,
        **payload.model_dump(),
    )


@router.get("")
def list_conversations(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    space_id: Annotated[str | None, Query()] = None,
    goal_id: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    pre_project_only: Annotated[bool, Query()] = False,
    purpose: Annotated[
        Literal["PLANNING", "PAGE_ASSISTANT", "PROJECT_ASSISTANT"] | None,
        Query(),
    ] = None,
    context_key: Annotated[str | None, Query(min_length=1, max_length=320)] = None,
) -> list[dict[str, object]]:
    return AICollaborationService(application).list_conversations(
        user_id=user_id,
        space_id=space_id,
        goal_id=goal_id,
        include_archived=include_archived,
        pre_project_only=pre_project_only,
        purpose=purpose,
        context_key=context_key,
    )


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).get_conversation(
        user_id=user_id,
        conversation_id=conversation_id,
    )


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: ConversationSendRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await AICollaborationService(application).send_message(
        user_id=user_id,
        conversation_id=conversation_id,
        **payload.model_dump(),
    )


@router.post("/{conversation_id}/tool-proposals/{tool_call_id}/approve")
def approve_tool_proposal(
    conversation_id: str,
    tool_call_id: str,
    payload: ConversationRevisionRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).approve_tool_proposal(
        user_id=user_id,
        conversation_id=conversation_id,
        tool_call_id=tool_call_id,
        expected_revision=payload.expected_revision,
    )


@router.post("/{conversation_id}/tool-proposals/{tool_call_id}/reject")
def reject_tool_proposal(
    conversation_id: str,
    tool_call_id: str,
    payload: ConversationRevisionRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).reject_tool_proposal(
        user_id=user_id,
        conversation_id=conversation_id,
        tool_call_id=tool_call_id,
        expected_revision=payload.expected_revision,
    )


@router.post("/{conversation_id}/finalize-plan")
def finalize_plan(
    conversation_id: str,
    payload: ConversationFinalizePlanRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).finalize_plan(
        user_id=user_id,
        conversation_id=conversation_id,
        expected_revision=payload.expected_revision,
        plan=payload.plan,
    )


@router.post("/{conversation_id}/activate-plan")
def activate_plan(
    conversation_id: str,
    payload: ConversationRevisionRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).activate_plan(
        user_id=user_id,
        conversation_id=conversation_id,
        expected_revision=payload.expected_revision,
    )


@router.post("/{conversation_id}/archive")
def archive_conversation(
    conversation_id: str,
    payload: ConversationRevisionRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).archive_conversation(
        user_id=user_id,
        conversation_id=conversation_id,
        expected_revision=payload.expected_revision,
    )


@router.post("/{conversation_id}/restore")
def restore_conversation(
    conversation_id: str,
    payload: ConversationRevisionRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return AICollaborationService(application).restore_conversation(
        user_id=user_id,
        conversation_id=conversation_id,
        expected_revision=payload.expected_revision,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def permanently_delete_conversation(
    conversation_id: str,
    payload: ConversationPermanentDeleteRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    AICollaborationService(application).delete_conversation_permanently(
        user_id=user_id,
        conversation_id=conversation_id,
        expected_revision=payload.expected_revision,
        confirm_title=payload.confirm_title,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
