"""AI proposal and explicit human-review endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from learning_navigator.api.dependencies import ApplicationDependency, CurrentUserDependency
from learning_navigator.api.schemas.requests import (
    AIGenerateRequest,
    AILearningPlanGenerateRequest,
    AIProviderProfileCreate,
    AIProviderProfileUpdate,
    AIReviewRequest,
)
from learning_navigator.domain.enums import ReviewStatus

router = APIRouter(tags=["AI suggestions"])


@router.get("/ai/providers")
def list_providers(application: ApplicationDependency) -> dict[str, object]:
    return application.list_ai_providers()


@router.get("/ai/status")
def ai_status(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.ai_status(user_id=user_id)


@router.get("/ai/provider-profiles")
def list_provider_profiles(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> list[dict[str, object]]:
    return application.list_ai_provider_profiles(user_id=user_id)


@router.post("/ai/provider-profiles", status_code=status.HTTP_201_CREATED)
def create_provider_profile(
    payload: AIProviderProfileCreate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump()
    if payload.api_key is not None:
        values["api_key"] = payload.api_key.get_secret_value()
    return application.create_ai_provider_profile(
        user_id=user_id,
        **values,
    )


@router.patch("/ai/provider-profiles/{profile_id}")
def update_provider_profile(
    profile_id: str,
    payload: AIProviderProfileUpdate,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    values = payload.model_dump(exclude_unset=True)
    if payload.api_key is not None:
        values["api_key"] = payload.api_key.get_secret_value()
    return application.update_ai_provider_profile(
        user_id=user_id,
        profile_id=profile_id,
        **values,
    )


@router.delete(
    "/ai/provider-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_provider_profile(
    profile_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> Response:
    application.delete_ai_provider_profile(user_id=user_id, profile_id=profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ai/provider-profiles/{profile_id}/test")
async def test_provider_profile(
    profile_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await application.test_ai_provider_profile(
        user_id=user_id,
        profile_id=profile_id,
    )


@router.get("/ai/provider-profiles/{profile_id}/models")
async def list_provider_models(
    profile_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await application.list_ai_provider_models(
        user_id=user_id,
        profile_id=profile_id,
    )


@router.post("/ai/suggestions/generate", status_code=status.HTTP_201_CREATED)
async def generate_suggestion(
    payload: AIGenerateRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await application.generate_ai_suggestion(user_id=user_id, **payload.model_dump())


@router.post("/ai/learning-plans/generate", status_code=status.HTTP_201_CREATED)
async def generate_learning_plan(
    payload: AILearningPlanGenerateRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return await application.generate_ai_learning_plan(
        user_id=user_id,
        **payload.model_dump(),
    )


@router.get("/ai/suggestions")
def list_suggestions(
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
    space_id: Annotated[str | None, Query()] = None,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
) -> list[dict[str, object]]:
    return application.list_ai_suggestions(user_id=user_id, space_id=space_id, status=review_status)


@router.post("/ai/suggestions/{suggestion_id}/review")
def review_suggestion(
    suggestion_id: str,
    payload: AIReviewRequest,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.review_ai_suggestion(
        user_id=user_id, suggestion_id=suggestion_id, **payload.model_dump()
    )


@router.post("/ai/suggestions/{suggestion_id}/revert")
def revert_suggestion(
    suggestion_id: str,
    application: ApplicationDependency,
    user_id: CurrentUserDependency,
) -> dict[str, object]:
    return application.revert_ai_suggestion(user_id=user_id, suggestion_id=suggestion_id)
