"""Human review queue for AI-generated framework proposals."""

import json
from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError

ENVIRONMENT_PROFILE = "__environment__"


def register(client: UIAPIClient) -> None:
    @ui.page("/ai-review")
    async def review_page() -> None:
        with page_shell(
            "AI 框架审核",
            "AI 只生成草稿；接受或修改后才会进入正式框架。",
        ):
            try:
                catalog = await client.get("/ai/providers")
                profiles: list[dict[str, Any]] = await client.get("/ai/provider-profiles")
                spaces = await client.get("/spaces")
            except UIAPIError as exc:
                error_notice(f"无法加载 AI 调用配置：{exc}")
                return

            fallback = catalog["environment_fallback"]
            profile_by_id = {item["id"]: item for item in profiles}
            profile_options = {
                ENVIRONMENT_PROFILE: (f"环境默认 · {fallback['provider']} / {fallback['model']}")
            } | {
                item["id"]: (
                    f"{item['display_name']} · {item['provider']} / {item['model']}"
                    + (" · 默认" if item["is_default"] else "")
                )
                for item in profiles
            }
            default_profile = next(
                (item["id"] for item in profiles if item["is_default"]),
                ENVIRONMENT_PROFILE,
            )
            space_options = {"": "创建新的框架空间"} | {
                item["id"]: item["title"] for item in spaces
            }

            with ui.card().classes("ln-card w-full p-5 gap-3"):
                ui.label("生成框架建议").classes("text-xl font-bold")
                profile_select = ui.select(
                    profile_options, value=default_profile, label="AI 配置"
                ).classes("w-full")
                provider_status = ui.label().classes("text-sm text-gray-600")
                space_select = ui.select(space_options, value="", label="应用到框架空间").classes(
                    "w-full"
                )
                source_text = ui.textarea(
                    "目标、资料或现有大纲",
                    placeholder="例如：了解生成式 AI 行业，或完成一次产品发布",
                ).classes("w-full")
                external_confirm = ui.checkbox(
                    "我确认将上述文本发送给所选外部 AI 服务商。",
                    value=False,
                )
                ui.label("Mock 在本地运行，不会发送文本；其他配置只有勾选确认后才能调用。").classes(
                    "text-sm text-amber-800"
                )

                def selected_provider() -> tuple[str, str]:
                    profile = profile_by_id.get(profile_select.value)
                    if profile is None:
                        return str(fallback["provider"]), str(fallback["model"])
                    return str(profile["provider"]), str(profile["model"])

                def update_provider_status() -> None:
                    provider, model = selected_provider()
                    provider_status.set_text(f"当前调用：{provider} / {model}")
                    is_mock = provider == "mock"
                    external_confirm.set_visibility(not is_mock)
                    if is_mock:
                        external_confirm.set_value(False)

                async def generate() -> None:
                    provider, _ = selected_provider()
                    if not (source_text.value or "").strip():
                        ui.notify("请先输入目标或资料。", type="warning")
                        return
                    if provider != "mock" and not external_confirm.value:
                        ui.notify("调用外部 AI 前必须确认发送文本。", type="warning")
                        return
                    generate_button.props("loading disable")
                    try:
                        profile_id = (
                            None
                            if profile_select.value == ENVIRONMENT_PROFILE
                            else profile_select.value
                        )
                        await client.post(
                            "/ai/suggestions/generate",
                            json={
                                "source_text": source_text.value,
                                "space_id": space_select.value or None,
                                "provider_profile_id": profile_id,
                                "confirmed_external_ai": provider != "mock",
                            },
                        )
                        ui.notify("框架草稿已进入审核队列。", type="positive")
                        await refresh_queue()
                    except UIAPIError as exc:
                        error_notice(f"生成建议失败：{exc}")
                    finally:
                        generate_button.props(remove="loading disable")

                profile_select.on("update:model-value", lambda _: update_provider_status())
                generate_button = ui.button("生成框架草稿", on_click=generate).props(
                    "color=positive"
                )
                update_provider_status()

            queue = ui.column().classes("w-full gap-4")

            async def refresh_queue() -> None:
                queue.clear()
                try:
                    suggestions = await client.get("/ai/suggestions")
                except UIAPIError as exc:
                    error_notice(f"无法刷新审核队列：{exc}")
                    return
                with queue:
                    if not suggestions:
                        ui.label("审核队列为空。")
                    for suggestion in suggestions:
                        with ui.card().classes("ln-card w-full p-5"):
                            ui.label(
                                f"{suggestion['suggestion_type']} · {suggestion['review_status']}"
                            ).classes("font-bold")
                            ui.label(
                                f"{suggestion['provider']} / {suggestion['model']}"
                                f" · 置信度 {suggestion['confidence']:.2f}"
                            ).classes("text-sm text-gray-600")
                            ui.label("结构化变更").classes("font-medium mt-2")
                            ui.code(
                                json.dumps(
                                    suggestion["proposed_changes"],
                                    ensure_ascii=False,
                                    indent=2,
                                )
                            ).classes("w-full")
                            conflicts = suggestion["proposed_changes"].get("conflicts", [])
                            if conflicts:
                                ui.label("冲突").classes("font-medium text-red-700")
                                for conflict in conflicts:
                                    with ui.card().classes("w-full p-3 bg-red-50"):
                                        ui.label(conflict["reason"]).classes("text-red-800")
                                        if conflict.get("cycle_path"):
                                            ui.label(
                                                "循环路径：" + " → ".join(conflict["cycle_path"])
                                            ).classes("text-sm text-red-700")
                            editor = (
                                ui.textarea(
                                    "AI 原始输出 / 可编辑 JSON",
                                    value=json.dumps(
                                        suggestion["raw_structured_output"],
                                        ensure_ascii=False,
                                        indent=2,
                                    ),
                                )
                                .classes("w-full font-mono")
                                .props("rows=12")
                            )

                            async def review(
                                action: str,
                                suggestion_id: str = suggestion["id"],
                                payload_editor: Any = editor,
                            ) -> None:
                                try:
                                    edited = (
                                        json.loads(payload_editor.value)
                                        if action == "modify_accept"
                                        else None
                                    )
                                    await client.post(
                                        f"/ai/suggestions/{suggestion_id}/review",
                                        json={
                                            "action": action,
                                            "edited_draft": edited,
                                            "review_note": None,
                                        },
                                    )
                                    ui.notify("审核结果已保存。", type="positive")
                                    await refresh_queue()
                                except (UIAPIError, ValueError) as exc:
                                    error_notice(f"保存审核结果失败：{exc}")

                            async def revert(suggestion_id: str = suggestion["id"]) -> None:
                                try:
                                    await client.post(f"/ai/suggestions/{suggestion_id}/revert")
                                    ui.notify("已撤销建议应用的变更。", type="positive")
                                    await refresh_queue()
                                except UIAPIError as exc:
                                    error_notice(f"撤销失败：{exc}")

                            if suggestion["review_status"] in {"PENDING", "CONFLICT"}:
                                with ui.row():
                                    ui.button(
                                        "接受原稿", on_click=lambda _, r=review: r("accept")
                                    ).props("color=positive")
                                    ui.button(
                                        "编辑后接受",
                                        on_click=lambda _, r=review: r("modify_accept"),
                                    ).props("outline")
                                    ui.button(
                                        "拒绝", on_click=lambda _, r=review: r("reject")
                                    ).props("color=negative flat")
                            elif suggestion["review_status"] in {
                                "ACCEPTED",
                                "MODIFIED_ACCEPTED",
                            }:
                                ui.button("撤销应用", on_click=revert).props(
                                    "color=negative outline"
                                )

            await refresh_queue()
