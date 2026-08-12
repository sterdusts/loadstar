"""Integration contracts for user-owned AI provider profiles."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learning_navigator.config import Settings
from learning_navigator.infrastructure.database.models import (
    AIConversationModel,
    AIProviderProfileModel,
)
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)
from learning_navigator.infrastructure.security.credentials import (
    CredentialStoreError,
    MemoryCredentialStore,
)
from learning_navigator.main import create_app

ProfileClient = tuple[TestClient, MemoryCredentialStore]


@pytest.fixture
def profile_client() -> Iterator[ProfileClient]:
    credential_store = MemoryCredentialStore()
    app = create_app(
        Settings(
            database_url="sqlite:///:memory:",
            auto_create_schema=True,
            allow_test_user_header=True,
            ai_provider="mock",
            ai_model="mock-learning-map-v1",
        ),
        include_ui=False,
        credential_store=credential_store,
    )
    with TestClient(app) as client:
        yield client, credential_store


def _create_profile(
    client: TestClient,
    *,
    display_name: str,
    provider: str = "mock",
    base_url: str = "",
    model: str = "mock-learning-map-v1",
    api_key: str | None = None,
    is_default: bool = True,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/api/ai/provider-profiles",
        headers=headers,
        json={
            "display_name": display_name,
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "is_default": is_default,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _profile_owner_id(client: TestClient, profile_id: str) -> str:
    with client.app.state.session_factory() as session:
        profile = session.get(AIProviderProfileModel, profile_id)
        assert profile is not None
        return profile.owner_id


def _create_second_user(client: TestClient) -> str:
    with client.app.state.session_factory() as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        user = repository.ensure_user(
            display_name="Second learner",
            email="provider-profile-second@example.test",
        )
        user_id = user.id
        session.commit()
    return user_id


@pytest.mark.integration
def test_provider_catalog_includes_supported_profiles(profile_client: ProfileClient) -> None:
    client, _ = profile_client

    response = client.get("/api/ai/providers")

    assert response.status_code == 200, response.text
    provider_names = {item["name"] for item in response.json()["providers"]}
    assert {
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "qwen",
        "kimi",
        "zhipu",
        "openrouter",
        "ollama",
        "openai-compatible",
    } <= provider_names


@pytest.mark.integration
def test_profile_creation_redacts_key_and_saves_it_in_memory_vault(
    profile_client: ProfileClient,
) -> None:
    client, credential_store = profile_client
    secret = "profile-secret-key-1234"

    response = client.post(
        "/api/ai/provider-profiles",
        json={
            "display_name": "OpenAI primary",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "test-model",
            "api_key": secret,
            "is_default": True,
        },
    )

    assert response.status_code == 201, response.text
    profile = response.json()
    assert profile["has_api_key"] is True
    assert profile["key_last4"] == "1234"
    assert "api_key" not in profile
    assert secret not in response.text

    owner_id = _profile_owner_id(client, profile["id"])
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == secret

    listed_response = client.get("/api/ai/provider-profiles")
    assert listed_response.status_code == 200, listed_response.text
    assert secret not in listed_response.text
    listed = listed_response.json()[0]
    assert listed["has_api_key"] is True
    assert listed["key_last4"] == "1234"
    assert "api_key" not in listed


@pytest.mark.integration
def test_profile_patch_replaces_and_clears_api_key(profile_client: ProfileClient) -> None:
    client, credential_store = profile_client
    original_secret = "original-secret-1111"
    replacement_secret = "replacement-secret-5678"
    profile = _create_profile(
        client,
        display_name="Replaceable key",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="test-model",
        api_key=original_secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])

    replaced_response = client.patch(
        f"/api/ai/provider-profiles/{profile['id']}",
        json={"api_key": replacement_secret},
    )

    assert replaced_response.status_code == 200, replaced_response.text
    replaced = replaced_response.json()
    assert replaced["has_api_key"] is True
    assert replaced["key_last4"] == "5678"
    assert "api_key" not in replaced
    assert original_secret not in replaced_response.text
    assert replacement_secret not in replaced_response.text
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == replacement_secret

    cleared_response = client.patch(
        f"/api/ai/provider-profiles/{profile['id']}",
        json={"clear_api_key": True},
    )

    assert cleared_response.status_code == 200, cleared_response.text
    cleared = cleared_response.json()
    assert cleared["has_api_key"] is False
    assert cleared["key_last4"] is None
    assert "api_key" not in cleared
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) is None


@pytest.mark.integration
def test_profile_creation_cleans_up_vault_and_database_when_keyring_set_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, credential_store = profile_client
    original_set = credential_store.set

    def set_then_fail(*, user_id: str, profile_id: str, secret: str) -> None:
        original_set(user_id=user_id, profile_id=profile_id, secret=secret)
        raise CredentialStoreError("simulated credential-vault set failure")

    monkeypatch.setattr(credential_store, "set", set_then_fail)

    response = client.post(
        "/api/ai/provider-profiles",
        json={
            "display_name": "Set failure",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "test-model",
            "api_key": "must-not-be-orphaned-1234",
            "is_default": True,
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "ai_configuration_error"
    assert credential_store._secrets == {}
    assert client.get("/api/ai/provider-profiles").json() == []


@pytest.mark.integration
def test_profile_creation_cleans_up_vault_when_database_commit_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, credential_store = profile_client
    assert client.get("/api/ai/provider-profiles").json() == []
    original_commit = Session.commit
    fail_once = {"pending": True}

    def fail_first_commit(session: Session) -> None:
        if fail_once["pending"]:
            fail_once["pending"] = False
            raise RuntimeError("simulated profile creation commit failure")
        original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_first_commit)

    with pytest.raises(RuntimeError, match="simulated profile creation commit failure"):
        client.post(
            "/api/ai/provider-profiles",
            json={
                "display_name": "Commit failure",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "test-model",
                "api_key": "must-not-survive-commit-failure-4567",
                "is_default": True,
            },
        )

    assert credential_store._secrets == {}
    assert client.get("/api/ai/provider-profiles").json() == []


@pytest.mark.integration
def test_profile_update_restores_key_and_configuration_when_keyring_delete_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, credential_store = profile_client
    original_secret = "clear-compensation-secret-2468"
    profile = _create_profile(
        client,
        display_name="Original profile",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="original-model",
        api_key=original_secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])
    original_delete = credential_store.delete

    def delete_then_fail(*, user_id: str, profile_id: str) -> None:
        original_delete(user_id=user_id, profile_id=profile_id)
        raise CredentialStoreError("simulated credential-vault delete failure")

    monkeypatch.setattr(credential_store, "delete", delete_then_fail)

    response = client.patch(
        f"/api/ai/provider-profiles/{profile['id']}",
        json={
            "display_name": "Must roll back",
            "model": "must-roll-back-model",
            "clear_api_key": True,
        },
    )

    assert response.status_code == 400, response.text
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == original_secret
    persisted = client.get("/api/ai/provider-profiles").json()[0]
    assert persisted["display_name"] == "Original profile"
    assert persisted["model"] == "original-model"
    assert persisted["has_api_key"] is True
    assert persisted["key_last4"] == "2468"


@pytest.mark.integration
@pytest.mark.parametrize("failure_point", ["flush", "commit"])
def test_profile_update_restores_key_and_configuration_when_database_write_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    client, credential_store = profile_client
    original_secret = "database-compensation-old-1357"
    replacement_secret = "database-compensation-new-9753"
    profile = _create_profile(
        client,
        display_name="Database original",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="database-original-model",
        api_key=original_secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])
    original_operation = getattr(Session, failure_point)
    fail_once = {"pending": True}

    def fail_first_write(session: Session, *args: Any, **kwargs: Any) -> Any:
        if fail_once["pending"]:
            fail_once["pending"] = False
            raise RuntimeError(f"simulated profile update {failure_point} failure")
        return original_operation(session, *args, **kwargs)

    monkeypatch.setattr(Session, failure_point, fail_first_write)

    with pytest.raises(
        RuntimeError,
        match=rf"simulated profile update {failure_point} failure",
    ):
        client.patch(
            f"/api/ai/provider-profiles/{profile['id']}",
            json={
                "display_name": "Database must roll back",
                "model": "database-must-roll-back-model",
                "api_key": replacement_secret,
            },
        )

    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == original_secret
    persisted = client.get("/api/ai/provider-profiles").json()[0]
    assert persisted["display_name"] == "Database original"
    assert persisted["model"] == "database-original-model"
    assert persisted["has_api_key"] is True
    assert persisted["key_last4"] == "1357"


@pytest.mark.integration
def test_default_profile_selection_and_deletion_transfers_default(
    profile_client: ProfileClient,
) -> None:
    client, _ = profile_client
    first = _create_profile(
        client,
        display_name="First profile",
        is_default=False,
    )
    second = _create_profile(
        client,
        display_name="Second profile",
        model="mock-learning-map-v2",
        is_default=False,
    )

    assert first["is_default"] is True
    assert second["is_default"] is False

    selected_response = client.patch(
        f"/api/ai/provider-profiles/{second['id']}",
        json={"is_default": True},
    )
    assert selected_response.status_code == 200, selected_response.text
    assert selected_response.json()["is_default"] is True

    selected_profiles = {
        item["id"]: item for item in client.get("/api/ai/provider-profiles").json()
    }
    assert selected_profiles[first["id"]]["is_default"] is False
    assert selected_profiles[second["id"]]["is_default"] is True

    deleted_response = client.delete(f"/api/ai/provider-profiles/{second['id']}")
    assert deleted_response.status_code == 204, deleted_response.text

    remaining = client.get("/api/ai/provider-profiles").json()
    assert [item["id"] for item in remaining] == [first["id"]]
    assert remaining[0]["is_default"] is True


@pytest.mark.integration
def test_provider_profile_delete_blocks_active_conversation_and_detaches_archived_one(
    profile_client: ProfileClient,
) -> None:
    client, credential_store = profile_client
    secret = "conversation-profile-secret-1357"
    profile = _create_profile(
        client,
        display_name="Conversation profile",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="test-model",
        api_key=secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])
    created = client.post(
        "/api/ai/conversations",
        json={
            "title": "Conversation using a saved provider",
            "provider_profile_id": profile["id"],
        },
    )
    assert created.status_code == 201, created.text
    conversation = created.json()["conversation"]

    blocked = client.delete(f"/api/ai/provider-profiles/{profile['id']}")

    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == {
        "code": "ai_provider_profile_in_use",
        "message": (
            "The AI provider profile is still used by 1 active conversation(s); "
            "switch or archive them before deleting it"
        ),
        "reference_count": 1,
    }
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == secret

    archived = client.post(
        f"/api/ai/conversations/{conversation['id']}/archive",
        json={"expected_revision": conversation["row_version"]},
    )
    assert archived.status_code == 200, archived.text
    deleted = client.delete(f"/api/ai/provider-profiles/{profile['id']}")
    assert deleted.status_code == 204, deleted.text
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) is None

    with client.app.state.session_factory() as session:
        historical_conversation = session.get(AIConversationModel, conversation["id"])
        assert historical_conversation is not None
        assert historical_conversation.status == "ARCHIVED"
        assert historical_conversation.provider_profile_id is None


@pytest.mark.integration
def test_provider_profile_delete_restores_key_when_database_commit_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, credential_store = profile_client
    secret = "commit-compensation-secret-8642"
    profile = _create_profile(
        client,
        display_name="Compensated deletion",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="test-model",
        api_key=secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])
    original_commit = Session.commit
    fail_once = {"pending": True}

    def fail_first_commit(session: Session) -> None:
        if fail_once["pending"]:
            fail_once["pending"] = False
            raise RuntimeError("simulated provider-profile database commit failure")
        original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_first_commit)

    with pytest.raises(
        RuntimeError,
        match="simulated provider-profile database commit failure",
    ):
        client.delete(f"/api/ai/provider-profiles/{profile['id']}")

    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == secret
    remaining = client.get("/api/ai/provider-profiles").json()
    assert [item["id"] for item in remaining] == [profile["id"]]
    assert remaining[0]["has_api_key"] is True


@pytest.mark.integration
def test_provider_profile_delete_restores_key_when_vault_delete_mutates_then_fails(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, credential_store = profile_client
    secret = "vault-delete-compensation-secret-7531"
    profile = _create_profile(
        client,
        display_name="Vault compensated deletion",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="test-model",
        api_key=secret,
    )
    owner_id = _profile_owner_id(client, profile["id"])
    original_delete = credential_store.delete

    def delete_then_fail(*, user_id: str, profile_id: str) -> None:
        original_delete(user_id=user_id, profile_id=profile_id)
        raise CredentialStoreError("simulated credential-vault delete failure")

    monkeypatch.setattr(credential_store, "delete", delete_then_fail)

    response = client.delete(f"/api/ai/provider-profiles/{profile['id']}")

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "ai_configuration_error"
    assert credential_store.get(user_id=owner_id, profile_id=profile["id"]) == secret
    remaining = client.get("/api/ai/provider-profiles").json()
    assert [item["id"] for item in remaining] == [profile["id"]]
    assert remaining[0]["has_api_key"] is True
    assert remaining[0]["key_last4"] == "7531"


@pytest.mark.integration
def test_provider_profiles_and_credentials_are_isolated_by_user(
    profile_client: ProfileClient,
) -> None:
    client, credential_store = profile_client
    first_secret = "first-user-secret-1111"
    first = _create_profile(
        client,
        display_name="Shared profile name",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="first-model",
        api_key=first_secret,
    )
    first_user_id = _profile_owner_id(client, first["id"])

    second_user_id = _create_second_user(client)
    second_headers = {"X-User-ID": second_user_id}
    assert client.get("/api/ai/provider-profiles", headers=second_headers).json() == []

    second_secret = "second-user-secret-2222"
    second = _create_profile(
        client,
        display_name="Shared profile name",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="second-model",
        api_key=second_secret,
        headers=second_headers,
    )

    second_list = client.get("/api/ai/provider-profiles", headers=second_headers)
    assert second_list.status_code == 200, second_list.text
    assert [item["id"] for item in second_list.json()] == [second["id"]]
    assert [item["id"] for item in client.get("/api/ai/provider-profiles").json()] == [first["id"]]

    foreign_update = client.patch(
        f"/api/ai/provider-profiles/{first['id']}",
        headers=second_headers,
        json={"display_name": "Unauthorized rename"},
    )
    foreign_delete = client.delete(
        f"/api/ai/provider-profiles/{first['id']}",
        headers=second_headers,
    )
    assert foreign_update.status_code == 404
    assert foreign_delete.status_code == 404

    assert credential_store.get(user_id=first_user_id, profile_id=first["id"]) == first_secret
    assert credential_store.get(user_id=second_user_id, profile_id=second["id"]) == second_secret


@pytest.mark.integration
def test_generate_can_select_mock_profile_and_only_creates_suggestion(
    profile_client: ProfileClient,
) -> None:
    client, _ = profile_client
    profile = _create_profile(
        client,
        display_name="Selected offline profile",
        model="selected-mock-model",
    )
    spaces_before = client.get("/api/spaces").json()
    suggestions_before = client.get("/api/ai/suggestions").json()

    response = client.post(
        "/api/ai/suggestions/generate",
        json={
            "source_text": "Build a selected-profile learning map",
            "provider_profile_id": profile["id"],
        },
    )

    assert response.status_code == 201, response.text
    suggestion = response.json()
    assert suggestion["review_status"] == "PENDING"
    assert suggestion["provider"] == "mock"
    assert suggestion["model"] == "selected-mock-model"
    assert client.get("/api/spaces").json() == spaces_before
    suggestions_after = client.get("/api/ai/suggestions").json()
    assert len(suggestions_after) == len(suggestions_before) + 1
    assert suggestions_after[0]["id"] == suggestion["id"]


@pytest.mark.integration
def test_unconfirmed_external_profile_is_rejected_without_network_call(
    profile_client: ProfileClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = profile_client
    profile = _create_profile(
        client,
        display_name="Unconfirmed external profile",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="external-test-model",
        api_key="external-secret-9999",
    )
    request_spy = AsyncMock(side_effect=AssertionError("external network must not be called"))
    monkeypatch.setattr(client.app.state.ai_http_client, "request", request_spy)

    response = client.post(
        "/api/ai/suggestions/generate",
        json={
            "source_text": "Do not send this material",
            "provider_profile_id": profile["id"],
            "confirmed_external_ai": False,
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "ai_configuration_error"
    assert "Confirm external AI processing" in response.json()["detail"]["message"]
    request_spy.assert_not_awaited()
    assert client.get("/api/ai/suggestions").json() == []
