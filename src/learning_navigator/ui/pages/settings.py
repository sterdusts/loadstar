"""Provider-oriented AI connection management and JSON portability controls."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError

PROVIDER_DESCRIPTIONS = {
    "mock": "离线演示与测试，不会向外部服务发送内容。",
    "openai": "OpenAI 官方接口。",
    "anthropic": "Anthropic Claude 官方接口。",
    "gemini": "Google Gemini 官方接口。",
    "deepseek": "DeepSeek 官方接口。",
    "qwen": "阿里云百炼 Qwen 兼容接口。",
    "kimi": "Moonshot Kimi 官方接口。",
    "zhipu": "智谱 GLM 官方接口。",
    "openrouter": "通过 OpenRouter 使用其支持的模型。",
    "ollama": "连接本机 Ollama，适合本地模型。",
    "openai-compatible": "连接任意 OpenAI 兼容服务。",
}

SETTINGS_CSS = """
.ln-ai-settings-head {
  align-items:end; display:flex; gap:1rem; justify-content:space-between; width:100%;
}
.ln-provider-manager { overflow:hidden; padding:0!important; }
.ln-provider-summary {
  align-items:center; background:linear-gradient(145deg,var(--ln-surface-soft),var(--ln-surface));
  border-bottom:1px solid var(--ln-line); display:flex; flex-wrap:wrap; gap:.65rem 1rem;
  justify-content:space-between; padding:1rem 1.25rem; width:100%;
}
.ln-provider-row {
  display:grid; gap:1.4rem; grid-template-columns:minmax(230px,.72fr) minmax(0,1.75fr);
  padding:1.35rem 1.25rem; width:100%;
}
.ln-provider-row + .ln-provider-row { border-top:1px solid var(--ln-line); }
.ln-provider-meta { align-self:start; min-width:0; }
.ln-provider-name { font-size:1rem; font-weight:900; line-height:1.35; }
.ln-provider-description { color:var(--ln-muted); font-size:.8rem; line-height:1.55; }
.ln-provider-badges { align-items:center; display:flex; flex-wrap:wrap; gap:.4rem; }
.ln-provider-badge {
  background:var(--ln-surface-soft); border:1px solid var(--ln-line); border-radius:999px;
  color:var(--ln-muted); font-size:.69rem; font-weight:850; line-height:1; padding:.35rem .55rem;
}
.ln-provider-badge-ready {
  background:var(--ln-positive-soft); border-color:transparent; color:var(--ln-positive-text);
}
.ln-provider-badge-default {
  background:var(--ln-info-soft); border-color:transparent; color:var(--ln-info-text);
}
.ln-provider-badge-warning {
  background:var(--ln-warning-soft); border-color:transparent; color:var(--ln-warning-text);
}
.ln-provider-editor { min-width:0; width:100%; }
.ln-provider-fields {
  display:grid; gap:.75rem; grid-template-columns:minmax(130px,.65fr) minmax(150px,.75fr)
    minmax(180px,1fr) minmax(210px,1.2fr); width:100%;
}
.ln-provider-fields > * { min-width:0; }
.ln-provider-actions { align-items:center; display:flex; flex-wrap:wrap; gap:.45rem; }
.ln-provider-result {
  color:var(--ln-muted); font-size:.76rem; line-height:1.45; min-height:1.1rem;
}
.ln-provider-key-state { color:var(--ln-muted); font-size:.72rem; line-height:1.4; }
.ln-provider-empty {
  align-items:center; background:var(--ln-surface-soft); border:1px dashed var(--ln-line);
  border-radius:14px; display:flex; flex-wrap:wrap; gap:.7rem; justify-content:space-between;
  min-height:76px; padding:.85rem 1rem;
}
.ln-provider-dialog { max-width:min(720px,calc(100vw - 2rem)); width:720px; }
.ln-data-tools .q-expansion-item__container { width:100%; }
html[data-ln-theme="dark"] .ln-provider-manager,
html[data-ln-theme="dark"] .ln-provider-dialog { background:var(--ln-surface); }
@media (max-width:1100px) {
  .ln-provider-row { grid-template-columns:1fr; gap:.9rem; }
  .ln-provider-fields { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .ln-provider-fields > :last-child { grid-column:1 / -1; }
}
@media (max-width:700px) {
  .ln-ai-settings-head { align-items:stretch; flex-direction:column; }
  .ln-provider-row { padding:1.05rem .9rem; }
  .ln-provider-summary { align-items:flex-start; flex-direction:column; padding:.9rem; }
  .ln-provider-fields { grid-template-columns:1fr; }
  .ln-provider-fields > :last-child { grid-column:auto; }
  .ln-provider-actions .q-btn { flex:1 1 auto; }
}
"""


def _provider_key(preset: dict[str, Any]) -> str:
    """Return the stable provider identifier from an API catalog item."""

    if preset.get("provider"):
        return str(preset["provider"])
    if preset.get("id"):
        return str(preset["id"])
    if preset.get("name"):
        return str(preset["name"])
    return str(preset.get("adapter", "openai-compatible"))


def _group_profiles(profiles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group profiles without collapsing multiple connections to the same provider."""

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles:
        grouped[str(profile["provider"])].append(profile)
    return dict(grouped)


def _model_options(*values: object) -> list[str]:
    """Build a stable, de-duplicated model list while preserving the current value."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidates = value if isinstance(value, list | tuple) else [value]
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
    return result


def _profile_status(profile: dict[str, Any] | None, *, requires_key: bool) -> tuple[str, str]:
    if profile is None:
        return "未配置", ""
    if requires_key and not profile.get("has_api_key"):
        return "缺少 Key", "ln-provider-badge-warning"
    return "已配置", "ln-provider-badge-ready"


def _profile_key_hint(profile: dict[str, Any], *, requires_key: bool) -> str:
    if profile.get("has_api_key"):
        return f"凭据已安全保存 · 末四位 {profile.get('key_last4') or '未知'}"
    return "无需 API Key" if not requires_key else "尚未保存 API Key"


def register(client: UIAPIClient) -> None:
    @ui.page("/settings")
    async def settings_page() -> None:
        ui.add_css(SETTINGS_CSS)
        with page_shell("AI 模型", "管理 API 连接，并为每个连接选择独立模型。"):
            try:
                catalog = await client.get("/ai/providers")
                profiles: list[dict[str, Any]] = await client.get("/ai/provider-profiles")
            except UIAPIError as exc:
                error_notice(f"无法加载 AI 配置：{exc}")
                catalog = {"providers": [], "environment_fallback": {}}
                profiles = []

            presets = [
                item | {"provider": _provider_key(item)} for item in catalog.get("providers", [])
            ]
            presets_by_provider = {item["provider"]: item for item in presets}
            grouped_profiles = _group_profiles(profiles)
            configured_provider_count = len(grouped_profiles)
            fallback = catalog.get("environment_fallback", {})

            # Configured and default services appear first while catalog order remains stable.
            default_provider = next(
                (item["provider"] for item in profiles if item.get("is_default")), None
            )
            preset_order = {item["provider"]: index for index, item in enumerate(presets)}
            presets.sort(
                key=lambda item: (
                    item["provider"] != default_provider,
                    item["provider"] not in grouped_profiles,
                    preset_order[item["provider"]],
                )
            )

            with (
                ui.dialog() as create_dialog,
                ui.card().classes("ln-provider-dialog ln-card gap-4 p-5 sm:p-6"),
            ):
                with ui.row().classes("w-full items-start justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label("新增 API 连接").classes("ln-section-title")
                        ui.label("保存后可从服务端刷新模型列表。").classes("ln-supporting")
                    ui.button(icon="close", on_click=create_dialog.close).props("flat round")

                provider_options = {
                    item["provider"]: item["label"]
                    for item in presets
                    if item["provider"] != "mock"
                }
                if "mock" in presets_by_provider:
                    provider_options["mock"] = presets_by_provider["mock"]["label"]
                create_provider = ui.select(
                    provider_options,
                    value=next(iter(provider_options), None),
                    label="API 服务",
                ).classes("w-full")
                create_name = ui.input("连接名称").classes("w-full")
                create_url = ui.input("Base URL").classes("w-full")
                create_model = ui.select(
                    [],
                    label="模型",
                    with_input=True,
                    new_value_mode="add-unique",
                ).classes("w-full")
                create_key = (
                    ui.input("API Key", password=True, password_toggle_button=True)
                    .classes("w-full")
                    .props("autocomplete=new-password")
                )
                create_default = ui.checkbox("设为默认连接", value=not profiles)

                def apply_create_preset() -> None:
                    provider_key = str(create_provider.value or "")
                    preset = presets_by_provider.get(provider_key)
                    if preset is None:
                        return
                    create_name.set_value(preset["label"])
                    create_url.set_value(preset["base_url"])
                    options = _model_options(preset["default_model"])
                    create_model.set_options(
                        options,
                        value=preset["default_model"] or None,
                    )
                    create_key.set_value("")

                def open_create_dialog(provider_key: str | None = None) -> None:
                    selected = provider_key if provider_key in provider_options else None
                    create_provider.set_value(selected or next(iter(provider_options), None))
                    apply_create_preset()
                    create_dialog.open()

                async def create_profile() -> None:
                    preset = presets_by_provider.get(str(create_provider.value or ""))
                    if preset is None:
                        ui.notify("请选择 API 服务。", type="warning")
                        return
                    selected_model = str(create_model.value or "").strip()
                    if not selected_model:
                        ui.notify("请填写或选择模型。", type="warning")
                        return
                    if preset["requires_key"] and not str(create_key.value or "").strip():
                        ui.notify("这个服务需要 API Key。", type="warning")
                        return
                    payload: dict[str, Any] = {
                        "display_name": str(create_name.value or "").strip(),
                        "provider": preset["provider"],
                        "base_url": str(create_url.value or "").strip(),
                        "model": selected_model,
                        "is_default": bool(create_default.value),
                    }
                    if create_key.value:
                        payload["api_key"] = create_key.value
                    try:
                        await client.post("/ai/provider-profiles", json=payload)
                        create_key.set_value("")
                        ui.notify("API 连接已保存。", type="positive")
                        create_dialog.close()
                        ui.navigate.to("/settings")
                    except UIAPIError as exc:
                        ui.notify(f"保存失败：{exc}", type="negative")

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("取消", on_click=create_dialog.close).props("flat")
                    ui.button("保存连接", icon="save", on_click=create_profile).props(
                        "color=positive"
                    )
                create_provider.on("update:model-value", lambda _: apply_create_preset())
                apply_create_preset()

            with ui.row().classes("ln-ai-settings-head"):
                with ui.column().classes("gap-1"):
                    ui.label("API 管理").classes("ln-section-title")
                    ui.label("密钥只保存在系统凭据库，页面不会回显完整内容。").classes(
                        "ln-supporting"
                    )
                ui.button("新增 API", icon="add", on_click=open_create_dialog).props(
                    "color=positive unelevated"
                )

            with ui.card().classes("ln-card ln-provider-manager w-full"):
                with ui.row().classes("ln-provider-summary"):
                    ui.label(
                        f"{configured_provider_count} 个服务 · {len(profiles)} 条连接"
                    ).classes("font-bold")
                    ui.label(
                        "无已保存连接时使用环境默认："
                        f"{fallback.get('provider', '未知')} / {fallback.get('model', '未知')}"
                    ).classes("ln-provider-description")

                if not presets:
                    ui.label("没有可用的 API 服务预设。").classes("ln-empty m-4")

                def open_provider_dialog(provider_key: str) -> Callable[[], None]:
                    def open_dialog() -> None:
                        open_create_dialog(provider_key)

                    return open_dialog

                for preset in presets:
                    provider_profiles = grouped_profiles.get(preset["provider"], [])
                    if provider_profiles:
                        for profile in provider_profiles:
                            _render_provider_row(
                                client=client,
                                preset=preset,
                                profile=profile,
                                open_create=open_provider_dialog(str(preset["provider"])),
                            )
                    else:
                        _render_unconfigured_provider_row(
                            preset,
                            open_create=open_provider_dialog(str(preset["provider"])),
                        )

            _render_data_tools(client)


def _render_unconfigured_provider_row(
    preset: dict[str, Any], *, open_create: Callable[[], None]
) -> None:
    status, status_class = _profile_status(None, requires_key=bool(preset["requires_key"]))
    with ui.element("section").classes("ln-provider-row"):
        with ui.column().classes("ln-provider-meta gap-2"):
            with ui.row().classes("ln-provider-badges"):
                ui.label(preset["label"]).classes("ln-provider-name")
                ui.label(status).classes(f"ln-provider-badge {status_class}")
            ui.label(
                PROVIDER_DESCRIPTIONS.get(preset["provider"], "可配置的 AI 模型服务。")
            ).classes("ln-provider-description")
        with ui.element("div").classes("ln-provider-empty"):
            with ui.column().classes("min-w-0 gap-1"):
                ui.label("尚未保存连接").classes("font-bold")
                default_model = preset.get("default_model") or "保存时填写模型"
                ui.label(f"建议模型：{default_model}").classes("ln-provider-description")
            ui.button("配置", icon="tune", on_click=open_create).props("outline color=positive")


def _render_provider_row(
    *,
    client: UIAPIClient,
    preset: dict[str, Any],
    profile: dict[str, Any],
    open_create: Callable[[], None],
) -> None:
    requires_key = bool(preset["requires_key"])
    status, status_class = _profile_status(profile, requires_key=requires_key)
    current_model = str(profile.get("model") or "")

    with ui.element("section").classes("ln-provider-row"):
        with ui.column().classes("ln-provider-meta gap-2"):
            with ui.row().classes("ln-provider-badges"):
                ui.label(preset["label"]).classes("ln-provider-name")
                ui.label(status).classes(f"ln-provider-badge {status_class}")
                if profile.get("is_default"):
                    ui.label("默认").classes("ln-provider-badge ln-provider-badge-default")
            if profile["display_name"] != preset["label"]:
                ui.label(profile["display_name"]).classes("font-bold text-sm")
            ui.label(
                PROVIDER_DESCRIPTIONS.get(preset["provider"], "可配置的 AI 模型服务。")
            ).classes("ln-provider-description")
            ui.button("添加同类连接", icon="add", on_click=open_create).props(
                "flat dense color=positive"
            ).classes("self-start")

        with ui.column().classes("ln-provider-editor gap-2"):
            with ui.element("div").classes("ln-provider-fields"):
                display_name = ui.input("连接名称", value=profile["display_name"]).classes("w-full")
                api_key = (
                    ui.input("更新 API Key", password=True, password_toggle_button=True)
                    .classes("w-full")
                    .props("autocomplete=new-password")
                )
                model = ui.select(
                    _model_options(current_model, preset.get("default_model")),
                    value=current_model,
                    label="模型",
                    with_input=True,
                    new_value_mode="add-unique",
                ).classes("w-full")
                base_url = ui.input("Base URL", value=profile["base_url"]).classes("w-full")
            ui.label(_profile_key_hint(profile, requires_key=requires_key)).classes(
                "ln-provider-key-state"
            )
            result = ui.label("模型可搜索，也可以直接输入完整模型名。").classes(
                "ln-provider-result"
            )

            async def save_profile() -> None:
                selected_model = str(model.value or "").strip()
                if not selected_model:
                    ui.notify("模型不能为空。", type="warning")
                    return
                payload: dict[str, Any] = {
                    "display_name": str(display_name.value or "").strip(),
                    "base_url": str(base_url.value or "").strip(),
                    "model": selected_model,
                }
                if api_key.value:
                    payload["api_key"] = api_key.value
                try:
                    await client.patch(f"/ai/provider-profiles/{profile['id']}", json=payload)
                    api_key.set_value("")
                    ui.notify(f"{profile['display_name']} 已保存。", type="positive")
                    ui.navigate.to("/settings")
                except UIAPIError as exc:
                    ui.notify(f"保存失败：{exc}", type="negative")

            async def load_models() -> None:
                selected_before = str(model.value or current_model).strip()
                models_button.props("loading disable")
                try:
                    response = await client.get(f"/ai/provider-profiles/{profile['id']}/models")
                    remote_models = list(response.get("models", []))
                    model.set_options(
                        _model_options(selected_before, remote_models),
                        value=selected_before,
                    )
                    result.set_text(
                        f"已加载 {len(remote_models)} 个模型；选择后点击保存。"
                        if remote_models
                        else "服务未返回模型列表，可继续手动填写。"
                    )
                except UIAPIError as exc:
                    result.set_text("加载失败，当前模型已保留；仍可手动填写。")
                    ui.notify(f"无法加载模型：{exc}", type="negative")
                finally:
                    models_button.props(remove="loading disable")

            async def test_connection() -> None:
                test_button.props("loading disable")
                try:
                    response = await client.post(f"/ai/provider-profiles/{profile['id']}/test")
                    availability = (
                        "当前模型可用"
                        if response.get("model_available")
                        else "连接成功，但当前模型未出现在列表中"
                    )
                    result.set_text(f"{availability} · {response.get('latency_ms', 0)} ms")
                    remote_models = list(response.get("models", []))
                    if remote_models:
                        selected_before = str(model.value or current_model).strip()
                        model.set_options(
                            _model_options(selected_before, remote_models),
                            value=selected_before,
                        )
                except UIAPIError as exc:
                    result.set_text("连接测试失败，配置未被修改。")
                    ui.notify(f"测试失败：{exc}", type="negative")
                finally:
                    test_button.props(remove="loading disable")

            async def set_default() -> None:
                try:
                    await client.patch(
                        f"/ai/provider-profiles/{profile['id']}",
                        json={"is_default": True},
                    )
                    ui.notify("默认连接已更新。", type="positive")
                    ui.navigate.to("/settings")
                except UIAPIError as exc:
                    ui.notify(f"设置默认连接失败：{exc}", type="negative")

            def restore_preset() -> None:
                base_url.set_value(preset.get("base_url") or "")
                default_model = str(preset.get("default_model") or "").strip()
                if default_model:
                    model.set_options(
                        _model_options(default_model, model.value),
                        value=default_model,
                    )
                    result.set_text("已恢复服务预设；点击保存后生效。")
                else:
                    result.set_text("此服务没有固定模型预设，请手动填写模型名。")

            async def clear_key() -> None:
                try:
                    await client.patch(
                        f"/ai/provider-profiles/{profile['id']}",
                        json={"clear_api_key": True},
                    )
                    clear_key_dialog.close()
                    ui.notify("API Key 已从系统凭据库清除。", type="positive")
                    ui.navigate.to("/settings")
                except UIAPIError as exc:
                    ui.notify(f"清除失败：{exc}", type="negative")

            async def delete_profile() -> None:
                try:
                    await client.delete(f"/ai/provider-profiles/{profile['id']}")
                    delete_dialog.close()
                    ui.notify("API 连接及其凭据已删除。", type="positive")
                    ui.navigate.to("/settings")
                except UIAPIError as exc:
                    ui.notify(f"删除失败：{exc}", type="negative")

            with ui.dialog() as clear_key_dialog, ui.card().classes("ln-card gap-4 p-5"):
                ui.label("清除已保存的 API Key？").classes("ln-section-title")
                ui.label("连接和模型设置会保留，但外部服务将无法使用，直到重新保存 Key。")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("取消", on_click=clear_key_dialog.close).props("flat")
                    ui.button("清除 Key", on_click=clear_key).props("color=negative")

            with ui.dialog() as delete_dialog, ui.card().classes("ln-card gap-4 p-5"):
                ui.label("删除这条 API 连接？").classes("ln-section-title")
                ui.label("连接设置和系统凭据会一并删除；已有对话记录仍会保留。")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("取消", on_click=delete_dialog.close).props("flat")
                    ui.button("删除连接", on_click=delete_profile).props("color=negative")

            with ui.row().classes("ln-provider-actions"):
                ui.button("保存", icon="save", on_click=save_profile).props(
                    "color=positive unelevated"
                )
                models_button = ui.button("刷新模型", icon="refresh", on_click=load_models).props(
                    "outline color=positive"
                )
                test_button = ui.button("测试", icon="bolt", on_click=test_connection).props(
                    "flat color=positive"
                )
                if not profile.get("is_default"):
                    ui.button("设为默认", on_click=set_default).props("flat")
                with ui.button(icon="more_horiz").props("flat round"):
                    with ui.menu():
                        ui.menu_item("恢复服务预设", on_click=restore_preset)
                        if profile.get("has_api_key"):
                            ui.menu_item("清除 API Key", on_click=clear_key_dialog.open)
                        ui.menu_item("删除连接", on_click=delete_dialog.open)


def _render_data_tools(client: UIAPIClient) -> None:
    with ui.expansion("数据管理", icon="inventory_2").classes("ln-card ln-data-tools w-full px-2"):
        ui.label("导出或导入框架数据；API Key 不会包含在导出内容中。").classes("ln-supporting")
        export_box = ui.textarea("导出 JSON").classes("w-full font-mono").props("rows=8")
        import_box = ui.textarea("导入 JSON").classes("w-full font-mono").props("rows=8")

        async def export_data() -> None:
            try:
                data = await client.get("/data/export")
                export_box.value = json.dumps(data, ensure_ascii=False, indent=2)
            except UIAPIError as exc:
                ui.notify(f"导出失败：{exc}", type="negative")

        async def import_data() -> None:
            try:
                payload_value = json.loads(import_box.value or "")
                await client.post("/data/import", json={"payload": payload_value})
                ui.notify("框架已导入为新的人工锁定草稿。", type="positive")
            except (ValueError, UIAPIError) as exc:
                ui.notify(f"导入失败：{exc}", type="negative")

        with ui.row().classes("gap-2"):
            ui.button("生成导出", icon="download", on_click=export_data).props("color=positive")
            ui.button("导入框架", icon="upload", on_click=import_data).props("outline")
