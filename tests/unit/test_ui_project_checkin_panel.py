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
        "_render_checkin_reset_dialog",
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
    assert 'edit_label = "恢复" if score == 0 else "修改"' in source
    assert "ui.button(edit_label" in source


def test_checkin_ui_uses_dedicated_get_post_patch_and_reset_endpoints() -> None:
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
        r'client\.post\(\s*f"/goals/\{[^}]+\}/nodes/\{[^}]+\}/check-ins/reset"',
        source,
        re.DOTALL,
    )
    assert '"expected_check_in_id": latest_checkin_id' in source
    assert '"expected_revision": latest_revision' in source
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
    assert 'ui.label("恢复打卡" if is_reset_record else "修改打卡")' in source
    assert "expected_revision" in source
    assert re.search(
        r'client\.patch\(\s*f"/progress-check-ins/\{[^}]+\}"',
        source,
        re.DOTALL,
    )


def test_checkin_submit_and_edit_controls_guard_against_accidental_repeat_clicks() -> None:
    source = _checkin_source()

    assert source.count('props("loading disable")') >= 3
    assert 'reset_button.props(remove="loading disable")' in source
    assert "ui.notify" in source


def test_positive_progress_can_be_reset_with_an_explicit_safe_confirmation() -> None:
    source = _checkin_source()

    assert "if current_score > 0 and checkins:" in source
    assert 'ui.button("清零当前进度"' in source
    assert 'ui.button("确认清零"' in source
    assert "回到 0/10" in source
    assert "路径状态变为未进行" in source
    assert "保留一条清零记录" in source
    assert '.props("outline color=negative")' in source
    assert 'if resetting["active"]:' in source
    assert "ui.navigate.to(current_href)" in source


def test_zero_score_remains_zero_and_uses_an_explicit_restore_action() -> None:
    source = _checkin_source()

    assert "int(raw_current_score) if raw_current_score is not None else 0" in source
    assert "int(raw_score) if raw_score is not None else 1" in source
    assert "int(raw_original_score) if raw_original_score is not None else 1" in source
    assert 'if score == 0:\n                movement = "已清零"' in source
    assert 'f"{score}/10 · {intent_progress_label(score * 10, goal or {})}"' in source
    assert "ui.label(str(raw_current_score))" in source
    assert 'edit_label = "恢复" if score == 0 else "修改"' in source
    assert 'today_action = "恢复今日进度" if current_score == 0 else "修改今日打卡"' in source
    assert "value=max(1, original_score)" in source


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
