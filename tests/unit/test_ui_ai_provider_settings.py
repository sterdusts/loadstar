"""Product contracts for provider-oriented AI connection settings."""

from __future__ import annotations

import inspect

from learning_navigator.ui.pages import settings


def test_profiles_are_grouped_by_provider_without_collapsing_connections() -> None:
    profiles = [
        {"id": "openai-main", "provider": "openai", "model": "gpt-main"},
        {"id": "deepseek-main", "provider": "deepseek", "model": "deepseek-chat"},
        {"id": "openai-review", "provider": "openai", "model": "gpt-review"},
    ]

    grouped = settings._group_profiles(profiles)

    assert list(grouped) == ["openai", "deepseek"]
    assert [profile["id"] for profile in grouped["openai"]] == [
        "openai-main",
        "openai-review",
    ]
    assert grouped["deepseek"] == [profiles[1]]


def test_model_options_preserve_manual_current_value_and_stably_deduplicate() -> None:
    options = settings._model_options(
        "manual-model",
        "provider-default",
        ["provider-default", "remote-model", "", None, "manual-model"],
        ("remote-model", "another-model"),
    )

    assert options == [
        "manual-model",
        "provider-default",
        "remote-model",
        "another-model",
    ]
    assert settings._model_options("manual-model", []) == ["manual-model"]


def test_profile_status_and_key_hint_use_only_redacted_credential_metadata() -> None:
    configured = {
        "has_api_key": True,
        "key_last4": "2468",
        "api_key": "must-never-be-rendered",
    }

    assert settings._profile_status(configured, requires_key=True) == (
        "已配置",
        "ln-provider-badge-ready",
    )
    hint = settings._profile_key_hint(configured, requires_key=True)
    assert "2468" in hint
    assert configured["api_key"] not in hint

    assert settings._profile_status({"has_api_key": False}, requires_key=True) == (
        "缺少 Key",
        "ln-provider-badge-warning",
    )
    assert settings._profile_key_hint({"has_api_key": False}, requires_key=False) == "无需 API Key"


def test_saved_profile_editor_keeps_model_and_actions_scoped_to_its_profile_id() -> None:
    source = inspect.getsource(settings._render_provider_row)

    assert "f\"/ai/provider-profiles/{profile['id']}\"" in source
    assert "f\"/ai/provider-profiles/{profile['id']}/models\"" in source
    assert "f\"/ai/provider-profiles/{profile['id']}/test\"" in source
    assert "await client.delete(f\"/ai/provider-profiles/{profile['id']}\")" in source
    assert 'json={"is_default": True}' in source
    assert 'json={"clear_api_key": True}' in source

    assert "with_input=True" in source
    assert 'new_value_mode="add-unique"' in source
    assert "_model_options(selected_before, remote_models)" in source
    assert '"model": selected_model' in source


def test_saved_profile_key_is_password_only_and_blank_input_keeps_existing_secret() -> None:
    source = inspect.getsource(settings._render_provider_row)

    assert 'ui.input("更新 API Key", password=True, password_toggle_button=True)' in source
    assert 'props("autocomplete=new-password")' in source
    assert "if api_key.value:" in source
    assert 'payload["api_key"] = api_key.value' in source
    assert "api_key.set_value(profile" not in source
    assert 'profile["api_key"]' not in source


def test_new_connection_has_provider_preset_and_editable_initial_model() -> None:
    source = inspect.getsource(settings.register)

    assert 'label="API 服务"' in source
    assert 'label="模型"' in source
    assert "with_input=True" in source
    assert 'new_value_mode="add-unique"' in source
    assert 'await client.post("/ai/provider-profiles", json=payload)' in source
    assert '"provider": preset["provider"]' in source
    assert '"model": selected_model' in source


def test_settings_page_renders_each_saved_connection_and_has_no_legacy_master_selector() -> None:
    source = inspect.getsource(settings)

    assert "grouped_profiles = _group_profiles(profiles)" in source
    assert "for profile in provider_profiles:" in source
    assert "_render_provider_row(" in source
    assert "NEW_PROFILE" not in source
    assert "profile_select" not in source
    assert "profile_options" not in source
    assert 'label="已有配置"' not in source
