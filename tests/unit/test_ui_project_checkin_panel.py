"""Product contracts for the focused node check-in inspector."""

from __future__ import annotations

import inspect
import re

from learning_navigator.ui.components import layout
from learning_navigator.ui.pages import projects


def _inspector_source() -> str:
    return inspect.getsource(projects._render_inspector)


def _checkin_source() -> str:
    """Include optional focused helpers without prescribing one implementation shape."""

    parts = [_inspector_source()]
    for name in (
        "_render_checkin_panel",
        "_render_checkin_timeline",
        "_render_checkin_edit_dialog",
        "_render_checkin_clear_dialog",
        "_render_checkin_attachments",
        "_render_attachment_uploader",
        "_upload_checkin_files",
    ):
        helper = getattr(projects, name, None)
        if helper is not None:
            parts.append(inspect.getsource(helper))
    return "\n".join(parts)


def _project_source() -> str:
    return inspect.getsource(projects)


def _slider_arguments(source: str) -> list[str]:
    return re.findall(r"ui\.slider\((.*?)\)\s*\.props", source, re.DOTALL)


def test_inspector_defaults_to_one_focused_checkin_surface() -> None:
    inspector = _inspector_source()
    source = _checkin_source()

    assert 'node.get("title")' in source
    assert all(label in source for label in ("当前进度", "打卡", "备注", "修改"))
    assert "ln-checkin-panel" in inspector
    assert all(label not in inspector for label in ("框架属性", "路径设置", "状态与记录", "关系 ·"))


def test_inspector_identifies_the_node_position_in_the_single_active_route() -> None:
    source = _inspector_source()

    assert "for index, item in enumerate(route, start=1)" in source
    assert 'f"路径 {route_position}/{len(route)} · {node_type_label}"' in source
    assert 'f"未加入当前路径 · {node_type_label}"' in source
    assert 'ui.label(position_label).classes("ln-kicker")' in source
    assert "aria-label='当前路径位置：{position_label}'" in source


def test_checkin_timeline_renders_date_note_and_an_edit_action_per_entry() -> None:
    source = _checkin_source()

    assert "checkins" in source
    assert "checked_in_at" in source
    assert "note" in source
    assert re.search(r"for\s+\w+\s+in\s+\w*checkins", source)
    assert 'ui.button("修改", on_click=edit_dialog.open)' in source


def test_each_checkin_date_links_directly_to_its_own_ai_evaluation() -> None:
    source = _checkin_source()

    assert "detail_href: str" in source
    assert 'check_in_id = str(checkin.get("id") or "")' in source
    assert "check_in_detail_href" in source
    assert "urlencode({'check_in_id': check_in_id})" in source
    assert "_checkin_time_label(checked_in_at)," in source
    assert "ln-checkin-evaluation-link" in source
    assert "quote(space_id, safe='')" in source
    assert "quote(node_id, safe='')" in source
    assert "urlencode({'goal_id': project_id})" in source
    assert '"查看 AI 学习评语"' not in source


def test_checkin_timeline_collapses_each_record_detail_and_reports_attachment_count() -> None:
    source = _checkin_source()
    theme = inspect.getsource(layout.install_theme)

    assert 'attachments = _dict_items(checkin.get("attachments"))' in source
    assert 'f"{movement} · {len(attachments)} 个附件"' in source
    assert source.index('note = str(checkin.get("note") or "").strip()') < source.index(
        "展开或收起打卡附件"
    )
    assert "ui.expansion(" in source
    assert "value=False" in source
    assert "展开或收起打卡附件" in source
    assert "if attachments:" in source
    assert 'classes("ln-checkin-details w-full")' in source
    assert ".ln-checkin-details" in theme


def test_checkin_summary_is_compact_and_does_not_duplicate_the_node_detail_entry() -> None:
    source = inspect.getsource(projects._render_checkin_panel)
    theme = inspect.getsource(layout.install_theme)

    assert "查看要素详情与 AI 评语" not in source
    assert "ln-checkin-summary-main" in source
    assert "ln-checkin-summary-footer" in source
    assert "最近打卡" in source
    assert ".ln-checkin-summary-footer" in theme
    assert ".q-expansion-item__content" in theme


def test_node_intro_is_visible_and_details_are_collapsed_above_score() -> None:
    source = inspect.getsource(projects._render_checkin_panel)
    module_source = inspect.getsource(projects)
    theme = inspect.getsource(layout.install_theme)

    assert source.index('ui.label("简介")') < source.index('classes("ln-checkin-summary")')
    assert source.index('ui.expansion("详细说明"') < source.index('classes("ln-checkin-summary")')
    assert 'ui.expansion("详细说明", icon="description", value=False)' in source
    assert "展开或收起详细说明" in source
    assert 'node.get("description")' in source
    assert 'node.get("detailed_description")' in source
    assert "ln-node-explanation" in source
    assert "AI 后台补录说明" in source
    assert "node-explanations/backfill" in module_source
    assert "on_nodes_updated" in source
    assert ".ln-node-explanation" in theme


def test_project_overview_can_batch_backfill_legacy_node_explanations() -> None:
    source = inspect.getsource(projects._render_overview)
    module_source = inspect.getsource(projects)

    assert "missing_explanation_nodes" in source
    assert "missing_explanation_nodes[:80]" in source
    assert "AI 后台补齐节点说明" in source
    assert "node-explanations/backfill" in module_source
    assert "assistant_handle.start_context_prompt" not in source
    assert "on_nodes_updated" in source


def test_framework_node_forms_edit_intro_and_details_in_the_same_node_record() -> None:
    source = _project_source()

    assert 'ui.textarea("简介")' in source or '"简介",' in source
    assert 'ui.textarea("详细说明")' in source or '"详细说明",' in source
    assert '"description": str(' in source
    assert '"detailed_description": str(' in source


def test_checkin_ui_uses_dedicated_clear_restore_and_permanent_delete_endpoints() -> None:
    source = _project_source()

    assert re.search(
        r'client\.get\(\s*f"/goals/\{[^}]+\}/nodes/\{[^}]+\}/check-ins"',
        source,
        re.DOTALL,
    )
    assert re.search(
        r'client\.post\(\s*f"/goals/\{[^}]+\}/nodes/\{[^}]+\}/check-ins"',
        source,
        re.DOTALL,
    )
    assert re.search(
        r'client\.patch\(\s*f"/progress-check-ins/\{[^}]+\}"',
        source,
        re.DOTALL,
    )
    assert re.search(
        r'client\.post\(\s*f"/goals/\{[^}]+\}/nodes/\{[^}]+\}/check-ins/clear"',
        source,
        re.DOTALL,
    )
    assert '"expected_check_in_id": latest_checkin_id' in source
    assert '"expected_revision": latest_revision' in source
    assert "clear-recovery/{batch_id}/restore" in source
    assert re.search(
        r'client\.delete\(\s*f"/goals/\{[^}]+\}/nodes/\{[^}]+\}/check-ins/'
        r'clear-recovery/\{batch_id\}"',
        source,
        re.DOTALL,
    )
    assert '"/learning-sessions"' not in _inspector_source()


def test_new_checkin_score_is_one_to_ten_and_starts_at_the_current_score() -> None:
    source = _checkin_source()
    slider_arguments = _slider_arguments(source)

    create_sliders = [item for item in slider_arguments if "create_score" in item]
    assert create_sliders
    assert "create_score = max(1, current_score)" in source
    assert any(re.search(r"\bmin\s*=\s*create_score", item) for item in create_sliders)
    assert any(re.search(r"\bmax\s*=\s*10\b", item) for item in create_sliders)
    assert any(re.search(r"\bvalue\s*=\s*create_score", item) for item in create_sliders)
    assert "label-always" in source


def test_explicit_edit_stays_positive_and_sends_expected_revision() -> None:
    source = _checkin_source()
    slider_arguments = _slider_arguments(source)

    assert any(
        re.search(r"\bmin\s*=\s*1\b", item) and re.search(r"\bmax\s*=\s*10\b", item)
        for item in slider_arguments
    )
    assert 'ui.label("修改打卡")' in source
    assert "expected_revision" in source
    assert re.search(
        r'client\.patch\(\s*f"/progress-check-ins/\{[^}]+\}"',
        source,
        re.DOTALL,
    )


def test_checkin_submit_and_edit_controls_guard_against_accidental_repeat_clicks() -> None:
    source = _checkin_source()

    assert source.count('props("loading disable")') >= 4
    assert 'clear_button.props(remove="loading disable")' in source
    assert 'restore_button.props(remove="loading disable")' in source
    assert 'permanent_delete_button.props(remove="loading disable")' in source
    assert "ui.notify" in source


def test_all_live_progress_can_be_deleted_with_confirmation_and_recovery() -> None:
    source = _checkin_source()

    assert "if checkins:" in source
    assert 'ui.button("删除全部进度"' in source
    assert 'ui.button("确认删除全部进度"' in source
    assert "全部打卡、备注、AI 评语和附件会从进度、统计与时间线中移除" in source
    assert "本地回收站保留一份恢复副本" in source
    assert '.props("outline color=negative")' in source
    assert 'if clearing["active"]:' in source
    assert "_refresh_checkin_surface(on_refresh, current_href)" in source


def test_deleted_progress_is_absent_from_the_timeline_and_restored_explicitly() -> None:
    source = _checkin_source()

    assert "int(raw_current_score) if raw_current_score is not None else 0" in source
    assert "int(raw_score) if raw_score is not None else 1" in source
    assert "int(raw_original_score) if raw_original_score is not None else 1" in source
    assert "if score == 0:" not in source
    assert 'f"{score}/10 · {intent_progress_label(score * 10, goal or {})}"' in source
    assert 'ui.label("未评分")' in source
    assert 'ui.button("修改", on_click=edit_dialog.open)' in source
    assert 'ui.button("修改今日打卡"' in source
    assert "value=max(1, original_score)" in source
    assert "if not checkins and clear_recovery:" in source
    assert "恢复已删除进度" in source


def test_recycled_progress_has_an_explicit_confirmed_permanent_delete_action() -> None:
    source = _checkin_source()

    assert 'ui.button(\n            "彻底删除"' in source
    assert "彻底删除已回收进度？" in source
    assert "确认彻底删除" in source
    assert "且无法恢复。框架、路径及其他节点不会被修改。" in source
    assert (
        "permanent_delete_dialog.props(\"aria-label='彻底删除已回收进度确认' role='alertdialog'\")"
        in source
    )
    assert 'if deleting_recovery["active"]:' in source
    assert "已彻底删除回收的进度和附件" in source
    assert "_refresh_checkin_surface(on_refresh, current_href)" in source


def test_checkin_mutations_refresh_only_the_mounted_inspector_when_available() -> None:
    source = _checkin_source()
    project_page = inspect.getsource(projects._render_project_page)
    refresh = inspect.getsource(projects._refresh_checkin_surface)

    assert "on_refresh: Callable[[], Awaitable[None]] | None" in source
    assert source.count("_refresh_checkin_surface(on_refresh, current_href)") >= 6
    assert "await on_refresh()" in refresh
    assert "on_refresh=lambda: render_inspector_for(node)" in project_page
    assert "on_refresh=lambda: render_inspector_for(selected_node)" in project_page


def test_checkin_panel_has_explicit_dark_and_narrow_screen_styles() -> None:
    source = inspect.getsource(layout.install_theme)

    assert ".ln-checkin-panel" in source
    assert 'html[data-ln-theme="dark"] .ln-checkin-panel' in source
    assert ".ln-checkin-reset" in source
    assert 'html[data-ln-theme="dark"] .ln-checkin-reset' in source
    narrow = source.split("@media (max-width: 767px)", maxsplit=1)
    assert len(narrow) == 2
    assert ".ln-checkin-panel" in narrow[1]
    assert ".ln-checkin-reset" in narrow[1]


def test_checkins_support_streamed_multi_file_uploads_without_an_app_size_limit() -> None:
    source = _checkin_source()
    api_source = inspect.getsource(projects.UIAPIClient.upload)

    assert "ui.upload(" in source
    assert "multiple=True" in source
    assert "auto_upload=True" in source
    assert "max_file_size" not in source
    assert "max_total_size" not in source
    assert "uploaded.iterate()" in source
    assert "client.upload(" in source
    assert "timeout=None" in api_source
    assert "不限制文件大小" in source


def test_checkin_dialog_accepts_clipboard_images_through_the_existing_upload_queue() -> None:
    source = _checkin_source()
    project_source = inspect.getsource(projects)

    assert "_CHECKIN_CLIPBOARD_PASTE_BOOTSTRAP" in source
    assert "document.addEventListener('paste'" in project_source
    assert "event.clipboardData?.files" in project_source
    assert "new DataTransfer()" in project_source
    assert "input.dispatchEvent(new Event('change'" in project_source
    assert "直接按 Ctrl+V 粘贴截图" in source


def test_attachment_urls_are_absolute_and_thumbnail_cards_cannot_overflow() -> None:
    source = _checkin_source()
    theme = inspect.getsource(layout.install_theme)
    url_helper = inspect.getsource(projects._attachment_browser_url)

    assert "_attachment_browser_url" in source
    assert "client.base_url.rstrip" in url_helper
    assert 'ui.image(content_url).props("fit=cover loading=lazy")' in source
    assert "查看大图" in source
    assert ".ln-checkin-attachment-body" in theme
    assert "grid-template-columns:64px minmax(0,1fr)" in theme
    assert "overflow:hidden" in theme


def test_checkin_timeline_shows_preview_download_and_confirmed_attachment_deletion() -> None:
    source = _checkin_source()

    assert 'checkin.get("attachments")' in source
    assert "_SAFE_PREVIEW_IMAGE_TYPES" in source
    assert "media_type.lower() in _SAFE_PREVIEW_IMAGE_TYPES" in source
    assert 'ui.link("下载"' in source
    assert "删除这个附件？" in source
    assert "/progress-check-in-attachments/{item_id}" in source
