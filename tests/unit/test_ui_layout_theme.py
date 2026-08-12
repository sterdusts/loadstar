"""Product contracts for the shared responsive theme shell."""

from __future__ import annotations

import inspect

from learning_navigator.ui.components import layout


def test_theme_is_bootstrapped_before_shared_css() -> None:
    source = inspect.getsource(layout.install_theme)

    assert source.index("ui.add_head_html") < source.index("ui.add_css")
    assert "ln-theme-bootstrap" in layout._THEME_BOOTSTRAP
    assert "ln-color-mode" in layout._THEME_BOOTSTRAP


def test_theme_supports_system_persistence_and_quasar_sync() -> None:
    script = layout._THEME_BOOTSTRAP

    assert "prefers-color-scheme: dark" in script
    assert "window.localStorage.getItem(storageKey)" in script
    assert "window.localStorage.setItem(storageKey, mode)" in script
    assert "window.Quasar.Dark.set(isDark)" in script
    assert "data-ln-color-mode" in script
    assert "system" in script and "light" in script and "dark" in script


def test_theme_announces_changes_and_rethemes_late_charts() -> None:
    script = layout._THEME_BOOTSTRAP

    assert "window.lnApplyChartTheme" in script
    assert ".nicegui-echart" in script
    assert "new MutationObserver" in script
    assert "new CustomEvent('ln-theme-change', {detail: {theme}})" in script
    assert "vueComponent?.proxy?.chart" in script
    assert "backgroundColor: surface" in script
    assert "extraCssText" in script
    assert "item.emphasis?.label" in script


def test_shared_css_has_semantic_dark_tokens_and_responsive_ranges() -> None:
    source = inspect.getsource(layout.install_theme)

    assert "--ln-container:1480px" in source
    assert 'html[data-ln-theme="dark"]' in source
    assert "--ln-bg:#0b1210" in source
    assert "--ln-surface:#131d18" in source
    assert "@media (min-width: 768px) and (max-width: 1099px)" in source
    assert "@media (max-width: 767px)" in source
    assert ".ln-header-row" in source and ".ln-shell" in source


def test_route_progress_states_use_semantic_tokens_and_visible_markers() -> None:
    source = inspect.getsource(layout.install_theme)

    assert ".ln-route-state-completed" in source
    assert ".ln-route-state-active" in source
    assert ".ln-route-state-pending" in source
    assert "--ln-route-state-text:var(--ln-danger-text)" in source
    assert "--ln-route-state-text:var(--ln-warning-text)" in source
    assert "--ln-route-state-text:var(--ln-positive-text)" in source
    assert ".ln-route-state-label::before" in source
    assert "content:var(--ln-route-state-symbol)" in source
    assert '"\\\\2713"' in source
    assert '"\\\\25cf"' in source
    assert '"\\\\25cb"' in source
    assert ".ln-status-AVAILABLE" in source


def test_navigation_separates_creation_from_the_three_primary_destinations() -> None:
    assert layout.PRIMARY_NAV == (
        ("导航", "/", "explore"),
        ("项目", "/projects", "view_quilt"),
        ("动态", "/activity", "timeline"),
    )
    assert layout.CREATE_ACTION == ("新建", "/projects/new", "add_circle_outline")
    assert (
        layout.PRIMARY_NAV[0],
        layout.PRIMARY_NAV[1],
        layout.CREATE_ACTION,
        layout.PRIMARY_NAV[2],
    ) == layout.MOBILE_NAV


def test_header_exposes_direct_toggle_and_three_explicit_modes() -> None:
    controls = inspect.getsource(layout._theme_controls)
    options = inspect.getsource(layout._theme_options)
    shell = inspect.getsource(layout.page_shell)

    assert "_toggle_color_mode" in controls
    assert "aria-label='切换浅色与深色'" in controls
    assert all(label in options for label in ("跟随系统", "浅色", "深色"))
    assert "_theme_controls()" in shell
    assert "CREATE_ACTION" in shell


def test_shared_branding_is_domain_neutral() -> None:
    shell = inspect.getsource(layout.page_shell)

    assert 'ui.label("Frame")' in shell
    assert "看清全局，找到下一步" in shell
    assert 'kicker: str = "全局导航"' in shell
    assert "Learning Navigator" not in shell
    assert "退出学习" not in shell
    assert ("框架库", "/spaces") in layout.ADVANCED_NAV
    assert "focus_mode" not in inspect.signature(layout.page_shell).parameters
