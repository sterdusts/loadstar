"""Shared navigation and presentation helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from nicegui import ui

from learning_navigator.ui.view_models import STATUS_LABELS

if TYPE_CHECKING:
    from learning_navigator.ui.components.global_ai_assistant import GlobalAssistantHandle
    from learning_navigator.ui.page_context import AssistantPageContext
    from learning_navigator.ui.state.api_client import UIAPIClient

_GLOBAL_AI_CLIENT: UIAPIClient | None = None

PRIMARY_NAV = (
    ("导航", "/", "explore"),
    ("项目", "/projects", "view_quilt"),
    ("动态", "/activity", "timeline"),
)

CREATE_ACTION = ("新建", "/projects/new", "add_circle_outline")
MOBILE_NAV = (PRIMARY_NAV[0], PRIMARY_NAV[1], CREATE_ACTION, PRIMARY_NAV[2])

ADVANCED_NAV = (
    ("框架库", "/spaces"),
    ("方案记录", "/goals"),
    ("AI 审核中心", "/ai-review"),
    ("数据与记录", "/records"),
)

_THEME_BOOTSTRAP = """
<script id="ln-theme-bootstrap">
(() => {
  if (window.LearningNavigatorTheme) return;
  const storageKey = 'ln-color-mode';
  const modes = new Set(['system', 'light', 'dark']);
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let mode;
  try {
    const stored = window.localStorage.getItem(storageKey);
    mode = modes.has(stored) ? stored : 'system';
  } catch (_) {
    mode = 'system';
  }

  const effectiveTheme = () => mode === 'system' ? (media.matches ? 'dark' : 'light') : mode;
  const root = document.documentElement;

  function syncViewportMetrics() {
    const scrollbarWidth = Math.max(0, window.innerWidth - root.clientWidth);
    root.style.setProperty('--ln-scrollbar-width', `${scrollbarWidth}px`);
  }
  syncViewportMetrics();
  window.addEventListener('resize', syncViewportMetrics, {passive: true});

  function updateControls(theme) {
    const icon = mode === 'system'
      ? 'brightness_auto'
      : (theme === 'dark' ? 'dark_mode' : 'light_mode');
    document.querySelectorAll('.ln-theme-toggle .q-icon').forEach(item => {
      item.textContent = icon;
    });
    document.querySelectorAll('[data-ln-color-mode]').forEach(item => {
      const selected = item.getAttribute('data-ln-color-mode') === mode;
      item.classList.toggle('ln-theme-option-active', selected);
      item.setAttribute('aria-current', selected ? 'true' : 'false');
    });
  }

  function syncQuasar(isDark, attempt = 0) {
    document.body?.classList.toggle('body--dark', isDark);
    document.body?.classList.toggle('body--light', !isDark);
    if (window.Quasar?.Dark?.set) {
      window.Quasar.Dark.set(isDark);
      return;
    }
    if (attempt < 30) window.setTimeout(() => syncQuasar(isDark, attempt + 1), 50);
  }

  window.lnApplyChartTheme = function(scope = document) {
    const theme = root.dataset.lnTheme || effectiveTheme();
    const dark = theme === 'dark';
    const text = dark ? '#edf5f0' : '#14221a';
    const muted = dark ? '#a8b7af' : '#59675f';
    const line = dark ? '#304239' : '#d8e3dc';
    const surface = dark ? '#131d18' : '#ffffff';
    const primary = dark ? '#62d8a2' : '#167653';
    const chartNodes = scope.matches?.('.nicegui-echart')
      ? [scope]
      : Array.from(scope.querySelectorAll?.('.nicegui-echart') || []);
    chartNodes.forEach(node => {
      const vueComponent = node.__vueParentComponent;
      const chart = vueComponent?.proxy?.chart ||
        vueComponent?.ctx?.chart ||
        window.echarts?.getInstanceByDom?.(node);
      if (!chart) return;
      const option = chart.getOption();
      const axisPatch = axis => ({
        axisLabel: {...axis.axisLabel, color: muted},
        axisLine: {...axis.axisLine, lineStyle: {...axis.axisLine?.lineStyle, color: line}},
        splitLine: {...axis.splitLine, lineStyle: {...axis.splitLine?.lineStyle, color: line}},
      });
      chart.setOption({
        textStyle: {color: text},
        title: (option.title || []).map(item => ({
          ...item,
          textStyle: {...item.textStyle, color: text},
        })),
        legend: (option.legend || []).map(item => ({
          ...item,
          textStyle: {...item.textStyle, color: muted},
        })),
        tooltip: (option.tooltip || [{}]).map(item => ({
          ...item,
          backgroundColor: surface,
          borderColor: line,
          extraCssText: `${item.extraCssText || ''};color:${text};`,
          textStyle: {...item.textStyle, color: text},
        })),
        toolbox: (option.toolbox || []).map(item => ({
          ...item,
          iconStyle: {...item.iconStyle, borderColor: muted},
          emphasis: {iconStyle: {...item.emphasis?.iconStyle, borderColor: primary}},
        })),
        xAxis: (option.xAxis || []).map(axisPatch),
        yAxis: (option.yAxis || []).map(axisPatch),
        series: (option.series || []).map(item => ({
          label: {...item.label, color: text, textBorderColor: surface},
          edgeLabel: {...item.edgeLabel, color: text, textBorderColor: surface},
          emphasis: {
            ...item.emphasis,
            label: {
              ...item.emphasis?.label,
              backgroundColor: surface,
              color: text,
              textBorderColor: surface,
            },
          },
        })),
      }, {notMerge: false, lazyUpdate: true});
    });
  };

  let chartFrame = 0;
  function scheduleChartTheme() {
    window.cancelAnimationFrame(chartFrame);
    chartFrame = window.requestAnimationFrame(() => {
      window.lnApplyChartTheme();
      window.setTimeout(() => window.lnApplyChartTheme(), 120);
    });
  }

  function apply(nextMode, {persist = true, announce = true} = {}) {
    mode = modes.has(nextMode) ? nextMode : 'system';
    if (persist) {
      try { window.localStorage.setItem(storageKey, mode); } catch (_) {}
    }
    const theme = effectiveTheme();
    root.dataset.lnColorMode = mode;
    root.dataset.lnTheme = theme;
    root.style.colorScheme = theme;
    syncQuasar(theme === 'dark');
    updateControls(theme);
    scheduleChartTheme();
    if (announce) {
      window.dispatchEvent(new CustomEvent('ln-theme-change', {detail: {theme}}));
    }
    return theme;
  }

  window.LearningNavigatorTheme = {
    getMode: () => mode,
    getTheme: effectiveTheme,
    setMode: nextMode => apply(nextMode),
    toggle: () => apply(effectiveTheme() === 'dark' ? 'light' : 'dark'),
  };
  apply(mode, {persist: false, announce: false});

  const assistantWidthKey = 'ln-ai-drawer-width';
  const assistantMinWidth = 360;
  const assistantMaxWidth = () => Math.max(
    assistantMinWidth,
    Math.min(900, Math.floor(window.innerWidth * 0.72)),
  );
  const clampAssistantWidth = value => Math.min(
    assistantMaxWidth(),
    Math.max(assistantMinWidth, Number(value) || 400),
  );
  const applyAssistantWidth = value => {
    let width = value;
    if (width == null) {
      try { width = window.localStorage.getItem(assistantWidthKey); } catch (_) {}
    }
    width = clampAssistantWidth(width);
    root.style.setProperty('--ln-ai-drawer-width', `${width}px`);
    return width;
  };
  let assistantResizeActive = false;
  const finishAssistantResize = () => {
    if (!assistantResizeActive) return;
    assistantResizeActive = false;
    root.classList.remove('ln-ai-resizing');
    const width = root.style.getPropertyValue('--ln-ai-drawer-width').replace('px', '');
    try { window.localStorage.setItem(assistantWidthKey, width); } catch (_) {}
  };
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest?.('.ln-ai-resize-handle')) return;
    assistantResizeActive = true;
    root.classList.add('ln-ai-resizing');
    event.preventDefault();
  });
  window.addEventListener('pointermove', event => {
    if (!assistantResizeActive) return;
    applyAssistantWidth(window.innerWidth - event.clientX);
  }, {passive: true});
  window.addEventListener('pointerup', finishAssistantResize, {passive: true});
  window.addEventListener('pointercancel', finishAssistantResize, {passive: true});
  window.LearningNavigatorAssistantLayout = {
    applyWidth: applyAssistantWidth,
    getWidth: () => root.style.getPropertyValue('--ln-ai-drawer-width'),
  };
  applyAssistantWidth();

  media.addEventListener('change', () => {
    if (mode === 'system') apply('system', {persist: false});
  });
  window.addEventListener('storage', event => {
    if (event.key === storageKey && modes.has(event.newValue)) {
      apply(event.newValue, {persist: false});
    }
  });
  window.addEventListener('resize', () => applyAssistantWidth(), {passive: true});
  document.addEventListener('DOMContentLoaded', () => {
    apply(mode, {persist: false, announce: false});
    syncViewportMetrics();
    window.setTimeout(syncViewportMetrics, 100);
    const viewportObserver = new MutationObserver(syncViewportMetrics);
    viewportObserver.observe(document.body, {attributes: true, attributeFilter: ['class']});
    const observer = new MutationObserver(records => {
      const hasNewControls = records.some(record => Array.from(record.addedNodes).some(node =>
        node.nodeType === 1 && (
          node.matches?.('.ln-theme-toggle, [data-ln-color-mode]') ||
          node.querySelector?.('.ln-theme-toggle, [data-ln-color-mode]')
        )
      ));
      const hasNewChart = records.some(record => Array.from(record.addedNodes).some(node =>
        node.nodeType === 1 && (
          node.matches?.('.nicegui-echart') ||
          node.closest?.('.nicegui-echart') ||
          node.querySelector?.('.nicegui-echart')
        )
      ));
      if (hasNewControls) updateControls(effectiveTheme());
      if (hasNewChart) scheduleChartTheme();
    });
    observer.observe(document.body, {childList: true, subtree: true});
  }, {once: true});
})();
</script>
"""


def install_theme() -> None:
    """Install the learner-facing product design system."""

    ui.add_head_html(_THEME_BOOTSTRAP)
    ui.add_css(
        """
        :root {
          --ln-container:1480px;
          --ln-ai-drawer-width:400px;
          --ln-bg:#f6f8f5; --ln-bg-end:#f3f5f1; --ln-bg-glow:rgba(218,241,229,.72);
          --ln-ink:#14221a; --ln-muted:#59675f; --ln-leaf:#167653;
          --ln-leaf-deep:#0f5f42; --ln-mint:#eaf7f0; --ln-mint-strong:#d5eee1;
          --ln-sand:#f7f4ec; --ln-coral:#c85c45; --ln-line:#d8e3dc;
          --ln-surface:#ffffff; --ln-surface-soft:#eff5f1;
          --ln-surface-raised:#ffffff; --ln-surface-alpha:rgba(255,255,255,.94);
          --ln-header-bg:rgba(255,255,255,.94); --ln-blue:#416db3;
          --ln-amber:#a96600; --ln-positive-soft:#e6f5ec; --ln-positive-text:#145f43;
          --ln-danger-soft:#fce6df; --ln-danger-text:#8b3223;
          --ln-info-soft:#e5efff; --ln-info-text:#2857a4;
          --ln-warning-soft:#fff0c2; --ln-warning-text:#7d5500;
          --ln-review-soft:#f0e4ff; --ln-review-text:#7950a3;
          --ln-shadow:0 16px 40px rgba(23,54,38,.10);
          --ln-shadow-soft:0 5px 18px rgba(23,54,38,.06);
          color-scheme:light;
        }
        html[data-ln-theme="dark"] {
          --ln-bg:#0b1210; --ln-bg-end:#101915; --ln-bg-glow:rgba(54,128,91,.18);
          --ln-ink:#edf5f0; --ln-muted:#a8b7af; --ln-leaf:#62d8a2;
          --ln-leaf-deep:#82e6b8; --ln-mint:#1a3026; --ln-mint-strong:#244435;
          --ln-sand:#211f18; --ln-coral:#ffaa9b; --ln-line:#304239;
          --ln-surface:#131d18; --ln-surface-soft:#192720;
          --ln-surface-raised:#203029; --ln-surface-alpha:rgba(19,29,24,.96);
          --ln-header-bg:rgba(11,18,16,.94); --ln-blue:#a4c8ff;
          --ln-amber:#f4cf73; --ln-positive-soft:#163829; --ln-positive-text:#91e8ba;
          --ln-danger-soft:#3d211d; --ln-danger-text:#ffaa9b;
          --ln-info-soft:#172d4d; --ln-info-text:#a4c8ff;
          --ln-warning-soft:#3a3016; --ln-warning-text:#f4cf73;
          --ln-review-soft:#302141; --ln-review-text:#d9b4fa;
          --ln-shadow:0 18px 46px rgba(0,0,0,.28);
          --ln-shadow-soft:0 6px 20px rgba(0,0,0,.20);
          color-scheme:dark;
        }
        html { scroll-behavior:smooth; }
        body {
          background:
            radial-gradient(circle at 6% 0%,var(--ln-bg-glow),transparent 30rem),
            linear-gradient(150deg,var(--ln-bg) 0%,var(--ln-bg-end) 100%);
          color:var(--ln-ink); min-height:100vh;
          font-family:Inter,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
          -webkit-font-smoothing:antialiased;
        }
        .ln-header {
          backdrop-filter:blur(16px); background:var(--ln-header-bg)!important;
          border-color:var(--ln-line)!important; box-shadow:0 1px 0 rgba(20,49,32,.03);
          padding:0!important; z-index:2000;
        }
        .ln-container { margin-inline:auto; max-width:var(--ln-container); width:100%; }
        .ln-header-row { margin-inline:auto; max-width:var(--ln-container); min-height:64px;
          padding-inline:clamp(1rem,2.4vw,2.25rem); width:100%; }
        .ln-brand { color:var(--ln-ink)!important; text-decoration:none!important; }
        .ln-brand-mark {
          align-items:center; background:linear-gradient(145deg,#0d6245,#18845d);
          border-radius:13px; box-shadow:0 6px 14px rgba(15,102,71,.20); color:white;
          display:flex; font-size:.84rem; font-weight:900; height:40px;
          justify-content:center; min-width:40px; width:40px;
        }
        .ln-shell { margin:0 auto; max-width:var(--ln-container);
          padding:2rem clamp(1rem,2.4vw,2.25rem) 4.5rem; }
        .ln-page-heading { margin-bottom:.25rem; }
        .ln-card {
          background:var(--ln-surface-alpha); border:1px solid var(--ln-line);
          box-shadow:none; border-radius:18px;
        }
        .ln-interactive-card {
          transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease;
        }
        .ln-interactive-card:hover {
          border-color:#acd3bd; box-shadow:var(--ln-shadow-soft); transform:translateY(-1px);
        }
        .ln-focus-card { border-color:var(--ln-leaf); box-shadow:var(--ln-shadow); }
        .ln-hero-card {
          background:linear-gradient(135deg,#104d39 0%,#1c7352 68%,#2f8964 100%);
          border:none; box-shadow:var(--ln-shadow); border-radius:24px; color:white;
        }
        .ln-today-hero {
          background:
            radial-gradient(circle at 86% 18%,rgba(255,255,255,.16) 0 5.5rem,transparent 5.65rem),
            radial-gradient(circle at 94% 86%,rgba(136,224,180,.18) 0 9rem,transparent 9.15rem),
            linear-gradient(128deg,#092f25 0%,#0d5b43 48%,#1f825d 100%);
          border:0; border-radius:28px; box-shadow:0 24px 58px rgba(8,65,45,.24);
          color:white; min-height:300px; position:relative;
        }
        .ln-today-hero::after {
          background:linear-gradient(90deg,#86e2ac,#f3cd76); border-radius:999px;
          content:""; height:5px; left:2rem; position:absolute; right:2rem; top:0;
        }
        .ln-today-hero .ln-kicker { color:#baf1cf; }
        .ln-today-title { color:white!important; font-size:clamp(2.1rem,4.2vw,3.65rem);
          letter-spacing:-.045em; line-height:1.02; text-decoration:none!important; }
        .ln-today-reason { color:#dcefe5; font-size:1rem; line-height:1.7; max-width:44rem; }
        .ln-today-side {
          background:rgba(255,255,255,.11); border:1px solid rgba(255,255,255,.20);
          border-radius:20px; backdrop-filter:blur(8px); min-width:250px;
        }
        .ln-today-action {
          background:white!important; color:#0d563d!important;
          box-shadow:0 9px 22px rgba(4,33,23,.22);
        }
        .ln-goal-deck {
          display:grid; gap:.8rem;
          grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); width:100%;
        }
        .ln-goal-card {
          background:var(--ln-surface-alpha); border:1px solid var(--ln-line); border-radius:17px;
          box-sizing:border-box; color:var(--ln-ink)!important; display:flex;
          flex-direction:column; min-height:118px; padding:1rem;
          text-decoration:none!important; transition:.18s ease; width:100%;
        }
        .ln-goal-card:hover { border-color:var(--ln-leaf); box-shadow:var(--ln-shadow-soft);
          transform:translateY(-2px); }
        .ln-goal-card-active {
          background:linear-gradient(145deg,var(--ln-mint-strong),var(--ln-surface));
          border-color:var(--ln-leaf);
          box-shadow:inset 0 0 0 1px rgba(58,145,95,.18);
        }
        .ln-goal-card-all {
          background:linear-gradient(145deg,var(--ln-mint),var(--ln-surface));
          border-color:var(--ln-line);
        }
        .ln-goal-card-all.ln-goal-card-active {
          background:linear-gradient(145deg,#183f32,#237a59); border-color:transparent;
          color:white!important;
        }
        .ln-goal-card-all.ln-goal-card-active .ln-goal-meta { color:#cae8d7!important; }
        .ln-goal-card-all.ln-goal-card-active .q-icon { color:#d9f5e4!important; }
        .ln-goal-count { background:var(--ln-positive-soft); color:var(--ln-positive-text); }
        .ln-goal-card-all.ln-goal-card-active .ln-goal-count {
          background:rgba(255,255,255,.15); color:white;
        }
        .ln-goal-title { font-size:.92rem; font-weight:850; line-height:1.35; }
        .ln-goal-meta { color:var(--ln-muted); font-size:.75rem; }
        .ln-alternative-section {
          background:linear-gradient(145deg,var(--ln-mint) 0%,var(--ln-sand) 100%);
          border:1px solid var(--ln-line); border-radius:24px; padding:1.35rem;
        }
        .ln-alternative-grid {
          display:grid; gap:1rem; grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .ln-alternative-card {
          background:var(--ln-surface-alpha); border:1px solid var(--ln-line);
          border-radius:18px; min-height:164px; padding:1.2rem; position:relative;
        }
        .ln-alternative-card::before {
          background:var(--ln-leaf); border-radius:999px; content:""; height:8px;
          left:1.2rem; position:absolute; top:1.15rem; width:8px;
        }
        .ln-overview-card { background:linear-gradient(145deg,var(--ln-sand),var(--ln-surface));
          border-color:var(--ln-line); }
        .ln-soft-card {
          background:linear-gradient(145deg,var(--ln-surface-soft),var(--ln-surface));
        }
        .ln-section-title { font-size:1.25rem; font-weight:900; line-height:1.25; }
        .ln-supporting { color:var(--ln-muted); font-size:.9rem; line-height:1.6; }
        .ln-kicker {
          color:var(--ln-leaf); letter-spacing:.08em; text-transform:uppercase;
          font-size:.7rem; font-weight:900;
        }
        .ln-page-title {
          font-size:clamp(1.85rem,3.4vw,2.5rem); letter-spacing:-.035em;
          line-height:1.1; font-weight:900;
        }
        .ln-nav-link {
          align-items:center; color:var(--ln-muted)!important; border-radius:12px; display:flex;
          min-height:42px; padding:.55rem .82rem; text-decoration:none!important;
          font-size:.9rem; font-weight:750; gap:.35rem; transition:.16s ease;
        }
        .ln-nav-link:hover { color:var(--ln-leaf)!important; background:var(--ln-mint); }
        .ln-nav-link-active {
          background:var(--ln-mint)!important; color:var(--ln-leaf-deep)!important;
          box-shadow:inset 0 0 0 1px var(--ln-line);
        }
        .ln-nav-icon { display:none!important; }
        .ln-header-actions { margin-left:auto; }
        .ln-create-action {
          align-items:center; background:var(--ln-leaf)!important; border-radius:12px;
          color:white!important; display:flex; font-size:.86rem; font-weight:850; gap:.35rem;
          min-height:42px; padding:.55rem .9rem; text-decoration:none!important;
        }
        .ln-create-action-active { box-shadow:0 0 0 3px var(--ln-mint-strong); }
        html[data-ln-theme="dark"] .ln-create-action { color:#07130e!important; }
        .ln-theme-controls { border:1px solid var(--ln-line); border-radius:12px; gap:0; }
        .ln-theme-controls .q-btn { color:var(--ln-muted)!important; min-height:40px; }
        .ln-theme-menu-trigger {
          border-left:1px solid var(--ln-line); border-radius:0 11px 11px 0;
        }
        .ln-theme-option-active { background:var(--ln-mint)!important;
          color:var(--ln-leaf-deep)!important; font-weight:800; }
        .ln-brand-copy, .ln-primary-nav { display:flex!important; }
        .ln-mobile-nav { display:none!important; }
        .ln-mobile-bottom-nav { display:none!important; }
        .ln-goal-switcher {
          overscroll-behavior-inline:contain; scrollbar-width:none; scroll-snap-type:x proximity;
        }
        .ln-goal-switcher::-webkit-scrollbar { display:none; }
        .ln-goal-switcher > * { scroll-snap-align:start; }
        .ln-empty {
          border:1px dashed var(--ln-leaf); border-radius:18px; background:var(--ln-mint);
          color:var(--ln-muted); padding:2rem; text-align:center;
        }
        .ln-metric { font-size:clamp(1.45rem,3vw,2rem); font-weight:900; line-height:1; }
        .ln-route-number {
          align-items:center; background:var(--ln-leaf); border-radius:999px; color:white;
          display:flex; font-size:.8rem; font-weight:900; height:2rem;
          justify-content:center; min-width:2rem; width:2rem;
        }
        .ln-route-row {
          align-items:center; border:1px solid transparent; border-radius:13px; color:inherit;
          display:flex; gap:.75rem; min-width:0; padding:.65rem .7rem;
          transition:background .16s ease,border-color .16s ease,transform .16s ease;
        }
        .ln-route-row:hover {
          background:var(--ln-surface-soft); border-color:var(--ln-line);
          transform:translateY(-1px);
        }
        .ln-route-step-title { color:var(--ln-route-state-text)!important; }
        .ln-route-progress-summary {
          align-self:start; background:var(--ln-surface-soft); border:1px solid var(--ln-line);
          border-radius:15px; padding:1rem; width:100%;
        }
        .ln-route-line { background:var(--ln-line); min-height:1.4rem; width:2px; }
        .ln-route-state-completed {
          --ln-route-state-text:var(--ln-danger-text);
          --ln-route-state-soft:var(--ln-danger-soft);
          --ln-route-state-symbol:"\\2713";
          color:var(--ln-route-state-text)!important;
        }
        .ln-route-state-active {
          --ln-route-state-text:var(--ln-warning-text);
          --ln-route-state-soft:var(--ln-warning-soft);
          --ln-route-state-symbol:"\\25cf";
          color:var(--ln-route-state-text)!important;
        }
        .ln-route-state-pending {
          --ln-route-state-text:var(--ln-positive-text);
          --ln-route-state-soft:var(--ln-positive-soft);
          --ln-route-state-symbol:"\\25cb";
          color:var(--ln-route-state-text)!important;
        }
        .ln-route-state-completed .ln-route-number,
        .ln-route-number.ln-route-state-completed,
        .ln-route-state-active .ln-route-number,
        .ln-route-number.ln-route-state-active,
        .ln-route-state-pending .ln-route-number,
        .ln-route-number.ln-route-state-pending {
          background:var(--ln-route-state-soft); border:2px solid var(--ln-route-state-text);
          color:var(--ln-route-state-text); box-shadow:0 0 0 3px var(--ln-surface);
        }
        .ln-route-state-label {
          align-items:center; background:var(--ln-route-state-soft); border:1px solid currentColor;
          border-radius:999px; color:var(--ln-route-state-text)!important; display:inline-flex;
          font-size:.72rem; font-weight:850; gap:.35rem; line-height:1.2;
          min-height:1.65rem; padding:.25rem .6rem; white-space:nowrap;
        }
        .ln-route-state-label::before {
          content:var(--ln-route-state-symbol); font-size:.76rem; font-weight:950; line-height:1;
        }
        .ln-status-AVAILABLE { color:var(--ln-positive-text); background:var(--ln-positive-soft); }
        .ln-status-BLOCKED { color:var(--ln-warning-text); background:var(--ln-warning-soft); }
        .ln-status-MASTERED { color:var(--ln-info-text); background:var(--ln-info-soft); }
        .ln-status-IN_PROGRESS { color:var(--ln-warning-text); background:var(--ln-warning-soft); }
        .ln-status-NEEDS_REVIEW { color:var(--ln-review-text); background:var(--ln-review-soft); }
        .ln-status-NOT_RELEVANT { color:var(--ln-muted); background:var(--ln-surface-soft); }
        .ln-action-button { min-height:46px; border-radius:13px!important; font-weight:850;
          padding-left:1rem!important; padding-right:1rem!important; }
        .ln-choice-group .q-btn { min-height:48px; border-radius:12px!important; }
        .ln-session-panel {
          background:linear-gradient(145deg,var(--ln-surface-soft) 0%,var(--ln-surface) 58%);
          border:1px solid var(--ln-line); border-radius:22px;
        }
        .ln-project-summary {
          align-items:center;
          background:linear-gradient(135deg,var(--ln-surface-soft),var(--ln-surface));
          border:1px solid var(--ln-line); border-radius:18px; display:flex; gap:1rem;
          justify-content:space-between; padding:1rem 1.15rem; width:100%;
        }
        .ln-project-tabs {
          align-items:center; border-bottom:1px solid var(--ln-line); display:flex; gap:.25rem;
          overflow-x:auto; scrollbar-width:none; width:100%;
        }
        .ln-project-tabs::-webkit-scrollbar { display:none; }
        .ln-project-tab {
          color:var(--ln-muted)!important; flex:0 0 auto; font-size:.88rem; font-weight:800;
          padding:.75rem .9rem; position:relative; text-decoration:none!important;
        }
        .ln-project-tab:hover { color:var(--ln-leaf)!important; }
        .ln-project-tab-active { color:var(--ln-leaf-deep)!important; }
        .ln-project-tab-active::after {
          background:var(--ln-leaf); border-radius:999px; bottom:-1px; content:""; height:3px;
          left:.7rem; position:absolute; right:.7rem;
        }
        .ln-project-workspace {
          display:grid; gap:1rem; grid-template-columns:minmax(0,1fr); width:100%;
        }
        .ln-project-workspace-has-inspector {
          grid-template-columns:minmax(0,1fr) minmax(300px,360px);
        }
        .ln-collaboration-grid {
          align-items:start; display:grid; gap:1rem;
          grid-template-columns:minmax(0,1.65fr) minmax(280px,.85fr); width:100%;
        }
        .ln-collaboration-main { width:100%; }
        .ln-collaboration-plan { position:sticky; top:80px; }
        .ln-chat-log {
          max-height:min(58vh,640px); min-height:280px; overflow-y:auto;
          overscroll-behavior:contain; scrollbar-gutter:stable;
        }
        .ln-chat-message {
          align-self:flex-start; background:var(--ln-surface-soft); border:1px solid var(--ln-line);
          border-radius:4px 16px 16px 16px; display:flex; flex-direction:column; gap:.45rem;
          max-width:min(88%,760px); padding:.75rem .9rem;
        }
        .ln-chat-message-user {
          align-self:flex-end; background:var(--ln-mint); border-radius:16px 4px 16px 16px;
        }
        .ln-ai-toggle {
          border:1px solid var(--ln-line); border-radius:12px!important;
          color:var(--ln-leaf)!important;
          font-weight:900; min-height:40px; padding-inline:.7rem!important;
        }
        .ln-ai-toggle:hover { background:var(--ln-mint)!important; }
        .ln-ai-drawer {
          background:var(--ln-surface)!important; color:var(--ln-ink)!important;
        }
        /* Quasar's mobile drawer backdrop uses z-index 2999. Keep the assistant
           itself above that layer so its controls remain interactive. */
        .q-drawer:has(> .ln-ai-drawer),
        .q-drawer.ln-ai-drawer {
          max-width:min(900px,72vw)!important; min-width:360px;
          width:var(--ln-ai-drawer-width)!important; z-index:3200!important;
        }
        .q-drawer:has(> .ln-ai-drawer-fullscreen),
        .q-drawer.ln-ai-drawer-fullscreen {
          left:0!important; max-width:none!important; min-width:0!important;
          transform:none!important; width:calc(100vw - var(--ln-scrollbar-width,0px))!important;
        }
        .q-drawer.ln-ai-drawer,
        .q-drawer:has(> .ln-ai-drawer) { height:100dvh!important; }
        .ln-ai-drawer .q-drawer__content,
        .q-drawer.ln-ai-drawer .q-drawer__content {
          display:flex; flex-direction:column; height:100%; min-height:0; overflow:hidden;
        }
        .ln-ai-assistant-root {
          background:var(--ln-surface); container-type:inline-size; display:flex!important;
          flex-direction:column; height:100%; max-height:100dvh; min-height:0;
          overflow:hidden; position:relative;
        }
        .ln-ai-resize-handle {
          bottom:0; cursor:ew-resize; left:-4px; position:absolute; top:0; width:9px; z-index:5;
        }
        .ln-ai-resize-handle::after {
          background:transparent; border-radius:999px; bottom:42%; content:""; left:3px;
          position:absolute; top:42%; transition:background .16s ease; width:3px;
        }
        .ln-ai-resize-handle:hover::after,
        .ln-ai-resizing .ln-ai-resize-handle::after { background:var(--ln-leaf); }
        .ln-ai-resizing, .ln-ai-resizing * {
          cursor:ew-resize!important; user-select:none!important;
        }
        .ln-ai-drawer-fullscreen .ln-ai-resize-handle { display:none; }
        .ln-ai-panel-header {
          align-items:center!important;
          background:var(--ln-surface-alpha); border-bottom:1px solid var(--ln-line);
          display:grid!important; flex:0 0 auto; gap:.75rem;
          grid-template-columns:minmax(0,1fr) auto; min-height:64px;
          position:relative; z-index:6;
        }
        .ln-ai-header-identity { min-width:0; overflow:hidden; }
        .ln-ai-header-actions,
        .ln-ai-header-tools {
          align-items:center; display:flex!important; flex:0 0 auto; flex-wrap:nowrap;
          gap:.25rem; justify-content:flex-end; min-width:0;
        }
        .ln-ai-header-primary-action {
          align-items:center; display:flex!important; flex:0 0 auto; padding:0!important;
        }
        .ln-ai-header-primary-action .q-btn {
          border-radius:10px!important; font-weight:850; min-height:38px;
          padding-inline:.72rem!important;
        }
        .ln-ai-header-icon-actions {
          align-items:center; display:flex!important; flex:0 0 auto; flex-wrap:nowrap; gap:.1rem;
        }
        .ln-ai-header-icon-actions .q-btn,
        .ln-ai-header-tools > .q-btn {
          border-radius:10px!important; height:38px; min-height:38px; min-width:38px;
        }
        .ln-ai-panel-body {
          display:flex!important; flex:1 1 auto; flex-direction:column; height:0;
          min-height:0; overflow:hidden;
        }
        .ln-ai-workspace {
          align-items:stretch; display:flex!important; flex:1 1 auto; height:100%;
          min-height:0; min-width:0; overflow:hidden;
        }
        .ln-ai-context-label { max-width:250px; }
        .ln-ai-local-badge {
          background:var(--ln-positive-soft); border-radius:999px; color:var(--ln-positive-text);
          font-size:.66rem; font-weight:850; padding:.18rem .45rem;
        }
        .ln-ai-message-log {
          align-content:flex-start; flex:1 1 auto; min-height:0; overflow-x:hidden;
          overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable;
        }
        .ln-ai-chat-pane {
          background:var(--ln-surface); display:flex!important; flex:1 1 auto;
          flex-direction:column; height:100%; max-height:100%; min-height:0;
          min-width:0; overflow:hidden;
        }
        .ln-ai-assistant-fullscreen .ln-ai-chat-pane {
          margin:0 auto; max-width:980px; width:min(980px,calc(100vw - 300px));
        }
        .ln-ai-assistant-fullscreen .ln-ai-workspace {
          background:var(--ln-surface); height:100%; min-height:0;
        }
        .ln-ai-history-rail {
          background:var(--ln-surface-soft); border-right:1px solid var(--ln-line);
          display:flex; flex:0 0 280px; flex-direction:column; gap:.75rem;
          height:100%; min-height:0; overflow:hidden; padding:1rem; width:280px;
        }
        .ln-ai-history-list {
          flex:1 1 auto; min-height:0; overflow-x:hidden; overflow-y:auto;
          overscroll-behavior:contain; padding-right:.2rem; scrollbar-gutter:stable;
        }
        .ln-ai-history-group {
          color:var(--ln-muted); font-size:.7rem; font-weight:900;
          padding:.8rem .55rem .25rem; text-transform:none;
        }
        .ln-ai-history-item {
          border-radius:11px!important; color:var(--ln-ink)!important;
          min-height:54px; padding:.55rem .65rem!important; width:100%;
        }
        .ln-ai-history-item:hover { background:var(--ln-mint)!important; }
        .ln-ai-history-item-active {
          background:var(--ln-mint-strong)!important; box-shadow:inset 3px 0 var(--ln-leaf);
        }
        .ln-ai-history-entry { border-radius:11px; min-width:0; }
        .ln-ai-history-entry > .q-btn { flex:0 0 auto; }
        .ln-ai-history-entry > .ln-ai-history-item { flex:1 1 auto; min-width:0; }
        .ln-ai-compact-history-row {
          border-radius:10px; min-width:0; padding:.15rem .25rem;
        }
        .ln-ai-compact-history-row:hover { background:var(--ln-mint); }
        .ln-ai-new-project-button { color:var(--ln-leaf)!important; font-weight:850; }
        .ln-ai-message-log .ln-chat-message {
          max-width:min(92%,760px); overflow-wrap:anywhere;
        }
        .ln-ai-assistant-fullscreen .ln-ai-message-log {
          margin-inline:auto; max-width:900px; padding-inline:clamp(1rem,3vw,2.5rem)!important;
          width:100%;
        }
        .ln-ai-assistant-fullscreen .ln-ai-message-log .ln-chat-message {
          max-width:min(86%,760px);
        }
        .ln-ai-welcome {
          background:linear-gradient(145deg,var(--ln-mint),var(--ln-surface-soft));
          border:1px solid var(--ln-line); border-radius:16px;
        }
        .ln-ai-composer {
          background:var(--ln-surface-alpha); border-top:1px solid var(--ln-line);
          bottom:0; box-shadow:0 -8px 24px rgba(23,54,38,.05); flex:0 0 auto;
          margin-top:auto; position:sticky; z-index:5;
        }
        .ln-ai-assistant-fullscreen .ln-ai-composer {
          margin-inline:auto; max-width:900px; padding-inline:clamp(1rem,3vw,2.5rem)!important;
          width:100%;
        }
        .ln-ai-composer-row {
          align-items:end; display:grid!important; gap:.65rem;
          grid-template-columns:minmax(0,1fr) auto;
        }
        .ln-ai-quick-prompts {
          flex:0 0 auto; overflow-x:auto; padding-bottom:.05rem; scrollbar-width:none;
        }
        .ln-ai-quick-prompts::-webkit-scrollbar { display:none; }
        .ln-ai-project-prompt-button {
          background:var(--ln-mint)!important; border:1px solid var(--ln-line);
          border-radius:999px!important; flex:0 0 auto; padding-inline:.7rem!important;
        }
        .ln-ai-composer-input { min-width:0; width:100%; }
        .ln-ai-composer-input .q-field__control {
          background:var(--ln-surface-soft); border-radius:18px!important;
        }
        .ln-ai-composer-input .q-field__native {
          max-height:min(28dvh,260px); overflow-y:auto!important; resize:none;
        }
        .ln-ai-inline-error {
          background:var(--ln-danger-soft); color:var(--ln-danger-text);
        }
        .ln-plan-chat-card {
          align-self:stretch; background:linear-gradient(145deg,var(--ln-mint),var(--ln-surface));
          border:1px solid var(--ln-line); border-left:4px solid var(--ln-leaf);
          border-radius:16px; display:flex; flex-direction:column; gap:.8rem;
          margin:.25rem 0; padding:1rem;
        }
        .ln-ai-history-menu { max-width:min(340px,88vw); min-width:240px; }
        .ln-ai-history-menu .q-item__section { overflow:hidden; text-overflow:ellipsis; }
        .ln-ai-send-button {
          align-self:end; border-radius:11px!important; font-weight:850;
          min-height:46px; min-width:84px;
        }
        @container (max-width: 520px) {
          .ln-ai-panel-header {
            align-items:stretch!important; grid-template-columns:minmax(0,1fr); row-gap:.55rem;
          }
          .ln-ai-header-actions,
          .ln-ai-header-tools { justify-content:space-between; width:100%; }
          .ln-ai-header-icon-actions { margin-left:auto; }
          .ln-ai-header-primary-action { justify-content:center; }
        }
        .ln-tool-run {
          align-self:stretch; background:var(--ln-positive-soft); border:1px solid var(--ln-line);
          border-left:3px solid var(--ln-leaf); border-radius:12px; color:var(--ln-positive-text);
          padding:.65rem .8rem;
        }
        .ln-tool-run-failed {
          background:var(--ln-danger-soft); border-left-color:var(--ln-danger-text);
          color:var(--ln-danger-text);
        }
        .ln-tool-run-pending {
          background:var(--ln-warning-soft); border-left-color:var(--ln-warning-text);
          color:var(--ln-warning-text);
        }
        .ln-chat-message-error {
          border-left:3px solid var(--ln-warning-text); background:var(--ln-warning-soft);
        }
        .ln-plan-stage-number {
          align-items:center; background:var(--ln-leaf); border-radius:999px; color:white;
          display:flex; font-size:.7rem; font-weight:900; height:1.5rem; justify-content:center;
          min-width:1.5rem; width:1.5rem;
        }
        .ln-project-main { min-width:0; width:100%; }
        .ln-node-inspector {
          align-self:start; background:var(--ln-surface-alpha); border:1px solid var(--ln-line);
          border-radius:18px; box-shadow:var(--ln-shadow-soft); max-height:calc(100vh - 96px);
          overflow:auto; padding:1rem; position:sticky; top:80px; width:100%;
        }
        .ln-checkin-panel { display:flex; flex-direction:column; gap:.75rem; }
        .ln-checkin-summary {
          align-items:flex-end;
          background:linear-gradient(145deg,var(--ln-mint),var(--ln-surface-soft));
          border:1px solid var(--ln-line); border-radius:15px; display:flex; gap:1rem;
          justify-content:space-between; min-height:92px; padding:.9rem 1rem; width:100%;
        }
        .ln-checkin-dialog {
          background:var(--ln-surface-raised)!important; color:var(--ln-ink)!important;
          max-width:480px; width:min(480px,calc(100vw - 24px));
        }
        .ln-checkin-timeline {
          display:flex; flex-direction:column; list-style:none; margin:0; padding:0 0 0 .15rem;
          width:100%;
        }
        .ln-checkin-entry {
          display:flex; gap:.75rem; min-width:0; padding:.15rem 0 1rem 1.35rem;
          position:relative; width:100%;
        }
        .ln-checkin-entry:not(:last-child)::before {
          background:var(--ln-line); content:""; left:.36rem; position:absolute;
          top:.9rem; bottom:-.1rem; width:2px;
        }
        .ln-checkin-dot {
          background:var(--ln-leaf); border:3px solid var(--ln-surface-raised);
          border-radius:999px; box-shadow:0 0 0 1px var(--ln-line); height:.76rem;
          left:0; position:absolute; top:.35rem; width:.76rem; z-index:1;
        }
        .ln-checkin-score {
          background:var(--ln-positive-soft); border-radius:999px; color:var(--ln-positive-text);
          flex:0 0 auto; font-size:.72rem; font-weight:900; padding:.2rem .5rem;
        }
        .ln-checkin-corrected {
          background:var(--ln-warning-soft); border-radius:999px; color:var(--ln-warning-text);
          font-size:.68rem; font-weight:850; padding:.15rem .45rem;
        }
        .ln-checkin-edit { min-height:36px; min-width:44px; }
        .ln-checkin-reset {
          border-color:var(--ln-danger-text)!important; color:var(--ln-danger-text)!important;
          min-height:42px; font-weight:850;
        }
        .ln-checkin-reset-dialog { border:1px solid var(--ln-danger-text); }
        .ln-checkin-empty {
          background:var(--ln-surface-soft); border:1px dashed var(--ln-line);
          border-radius:12px; padding:.8rem;
        }
        .ln-path-step {
          align-items:flex-start; background:var(--ln-surface-alpha);
          border:1px solid var(--ln-line); border-radius:14px; display:grid; gap:.75rem;
          grid-template-columns:auto minmax(0,1fr) auto;
          padding:.85rem; width:100%;
        }
        .ln-path-step-active { border-color:var(--ln-leaf); box-shadow:inset 3px 0 var(--ln-leaf); }
        .ln-timeline-dot {
          background:var(--ln-leaf); border:4px solid var(--ln-mint-strong); border-radius:999px;
          height:18px; min-width:18px; width:18px;
        }
        a { color:var(--ln-leaf); }
        a:focus-visible, button:focus-visible, [tabindex]:focus-visible,
        .q-field__control:focus-within {
          outline:3px solid rgba(36,122,87,.30)!important; outline-offset:3px;
        }
        .q-btn { letter-spacing:0; text-transform:none; }
        .q-field--outlined .q-field__control { border-radius:13px; }
        html[data-ln-theme="dark"] .ln-header.text-dark { color:var(--ln-ink)!important; }
        html[data-ln-theme="dark"] .ln-checkin-panel {
          background:var(--ln-surface-alpha); border-color:var(--ln-line);
        }
        html[data-ln-theme="dark"] .ln-checkin-reset {
          border-color:var(--ln-danger-text)!important; color:var(--ln-danger-text)!important;
        }
        html[data-ln-theme="dark"] .ln-hero-card {
          background:linear-gradient(135deg,#164b38 0%,#1d684b 100%);
          border:1px solid #32765a;
        }
        html[data-ln-theme="dark"] .ln-today-hero {
          background:
            radial-gradient(circle at 86% 18%,rgba(255,255,255,.10) 0 5.5rem,transparent 5.65rem),
            radial-gradient(circle at 94% 86%,rgba(98,216,162,.14) 0 9rem,transparent 9.15rem),
            linear-gradient(128deg,#102f25 0%,#164b38 48%,#1d684b 100%);
          border:1px solid #32765a;
        }
        html[data-ln-theme="dark"] .text-gray-950,
        html[data-ln-theme="dark"] .text-gray-900,
        html[data-ln-theme="dark"] .text-gray-800,
        html[data-ln-theme="dark"] .text-gray-700 { color:var(--ln-ink)!important; }
        html[data-ln-theme="dark"] .text-gray-600,
        html[data-ln-theme="dark"] .text-gray-500,
        html[data-ln-theme="dark"] .text-gray-400 { color:var(--ln-muted)!important; }
        html[data-ln-theme="dark"] .bg-white,
        html[data-ln-theme="dark"] .bg-gray-50,
        html[data-ln-theme="dark"] .bg-gray-100 { background-color:var(--ln-surface)!important; }
        html[data-ln-theme="dark"] .border-gray-100,
        html[data-ln-theme="dark"] .border-gray-200,
        html[data-ln-theme="dark"] .border-green-100,
        html[data-ln-theme="dark"] .border-green-200 { border-color:var(--ln-line)!important; }
        html[data-ln-theme="dark"] .border-green-700 { border-color:var(--ln-leaf)!important; }
        html[data-ln-theme="dark"] .bg-green-50,
        html[data-ln-theme="dark"] .bg-green-100 {
          background-color:var(--ln-positive-soft)!important;
        }
        html[data-ln-theme="dark"] .text-green-900,
        html[data-ln-theme="dark"] .text-green-800,
        html[data-ln-theme="dark"] .text-green-700 { color:var(--ln-positive-text)!important; }
        html[data-ln-theme="dark"] .bg-red-50,
        html[data-ln-theme="dark"] .bg-orange-50 {
          background-color:var(--ln-danger-soft)!important;
        }
        html[data-ln-theme="dark"] .text-red-900,
        html[data-ln-theme="dark"] .text-red-800,
        html[data-ln-theme="dark"] .text-red-700,
        html[data-ln-theme="dark"] .text-orange-800 { color:var(--ln-danger-text)!important; }
        html[data-ln-theme="dark"] .bg-amber-50 {
          background-color:var(--ln-warning-soft)!important;
        }
        html[data-ln-theme="dark"] .text-amber-800 { color:var(--ln-warning-text)!important; }
        html[data-ln-theme="dark"] .bg-blue-50 { background-color:var(--ln-info-soft)!important; }
        html[data-ln-theme="dark"] .text-blue-800 { color:var(--ln-info-text)!important; }
        html[data-ln-theme="dark"] .q-dialog .q-card,
        html[data-ln-theme="dark"] .q-menu,
        html[data-ln-theme="dark"] .q-tab-panels { background:var(--ln-surface-raised)!important;
          color:var(--ln-ink)!important; }
        html[data-ln-theme="dark"] .q-field__native,
        html[data-ln-theme="dark"] .q-field__input,
        html[data-ln-theme="dark"] .q-field__label { color:var(--ln-ink)!important; }
        html[data-ln-theme="dark"] .q-field--outlined .q-field__control::before {
          border-color:var(--ln-line)!important;
        }
        html[data-ln-theme="dark"] .q-separator { background:var(--ln-line); }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { scroll-behavior:auto!important; transition:none!important; }
        }
        @media (min-width: 1600px) {
          .ln-shell { padding-top:2.5rem; }
        }
        @media (max-width: 1099px) {
          .ln-collaboration-grid { grid-template-columns:minmax(0,1fr); }
          .ln-collaboration-plan { position:static; }
          .ln-project-workspace-has-inspector { grid-template-columns:minmax(0,1fr); }
          .ln-node-inspector {
            bottom:0; border-radius:20px 20px 0 0; box-shadow:0 -16px 44px rgba(0,0,0,.18);
            left:0; max-height:min(78vh,760px); overflow:auto; padding:1rem;
            position:fixed; right:0; top:auto; z-index:2050;
          }
        }
        @media (min-width: 768px) and (max-width: 1099px) {
          .ln-nav-label { display:none!important; }
          .ln-nav-icon { display:inline-flex!important; }
          .ln-primary-nav .ln-nav-link { justify-content:center; padding:.55rem; width:44px; }
          .ln-create-label { display:none!important; }
          .ln-create-action { justify-content:center; padding:.55rem; width:44px; }
          .ln-goal-deck { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .ln-today-side { min-width:210px; }
        }
        @media (min-width: 768px) and (max-width: 879px) {
          .ln-brand-copy { display:none!important; }
        }
        @media (max-width: 767px) {
          .ln-chat-log { max-height:none; min-height:220px; }
          .ln-chat-message { max-width:94%; }
          .ln-brand-copy, .ln-primary-nav { display:none!important; }
          .ln-mobile-nav { display:inline-flex!important; }
          .ln-mobile-bottom-nav {
            align-items:stretch; background:var(--ln-header-bg);
            border-top:1px solid var(--ln-line);
            bottom:0; box-shadow:0 -8px 24px rgba(24,54,39,.08); display:flex!important;
            justify-content:space-around; left:0;
            padding:.45rem .45rem calc(.45rem + env(safe-area-inset-bottom));
            position:fixed; right:0; z-index:2100;
          }
          .ln-mobile-nav-item {
            align-items:center; border-radius:12px; color:var(--ln-muted)!important; display:flex;
            flex:1; flex-direction:column; font-size:.7rem; font-weight:750; gap:.12rem;
            justify-content:center; min-height:48px; text-decoration:none!important;
          }
          .ln-mobile-nav-item-active { background:var(--ln-mint); color:var(--ln-leaf)!important; }
          .ln-mobile-nav-create .q-icon {
            align-items:center; background:var(--ln-leaf); border-radius:999px; color:white;
            display:flex; height:30px; justify-content:center; margin-top:-8px; width:30px;
          }
          html[data-ln-theme="dark"] .ln-mobile-nav-create .q-icon { color:#07130e; }
          .ln-create-action, .ln-theme-menu-trigger, .ln-desktop-control {
            display:none!important;
          }
          .ln-ai-toggle { min-height:38px; min-width:42px; padding-inline:.45rem!important; }
          .ln-ai-toggle .q-btn__content > span:not(.q-icon) { display:none; }
          .q-drawer:has(> .ln-ai-drawer),
          .q-drawer.ln-ai-drawer {
            max-width:none!important; min-width:0!important;
            width:calc(100vw - var(--ln-scrollbar-width,0px))!important;
          }
          .ln-ai-resize-handle, .ln-ai-history-rail { display:none!important; }
          .ln-ai-assistant-root {
            height:100dvh; max-height:100dvh; padding-bottom:0;
          }
          .ln-ai-panel-header {
            grid-template-columns:minmax(0,1fr); padding:.7rem .85rem!important;
            row-gap:.55rem;
          }
          .ln-ai-header-actions,
          .ln-ai-header-tools { justify-content:space-between; width:100%; }
          .ln-ai-header-icon-actions { margin-left:auto; }
          .ln-ai-message-log { padding:.85rem!important; }
          .ln-ai-composer {
            padding:.7rem .85rem calc(.7rem + env(safe-area-inset-bottom))!important;
          }
          .ln-ai-composer-row { gap:.5rem; }
          .ln-ai-send-button {
            border-radius:999px!important; min-width:46px; padding-inline:.65rem!important;
          }
          .ln-ai-assistant-fullscreen .ln-ai-chat-pane {
            max-width:none; width:100%;
          }
          .ln-header-row { min-height:56px; }
          .ln-shell { padding:1.25rem .85rem 6.5rem; }
          .ln-page-title { font-size:1.85rem; }
          .ln-card { border-radius:15px; }
          .ln-hero-card { border-radius:18px; }
          .ln-today-hero { border-radius:20px; min-height:0; }
          .ln-today-hero::after { left:1rem; right:1rem; }
          .ln-today-title { font-size:2.2rem; }
          .ln-today-side { min-width:0; width:100%; }
          .ln-goal-deck { display:flex; overflow-x:auto; padding-bottom:.35rem;
            scroll-snap-type:x mandatory; scrollbar-width:none; }
          .ln-goal-deck::-webkit-scrollbar { display:none; }
          .ln-goal-card { flex:0 0 78vw; min-height:108px; scroll-snap-align:start; }
          .ln-alternative-section { border-radius:18px; padding:1rem; }
          .ln-alternative-grid { display:flex; overflow-x:auto; padding-bottom:.35rem;
            scroll-snap-type:x mandatory; scrollbar-width:none; }
          .ln-alternative-grid::-webkit-scrollbar { display:none; }
          .ln-alternative-card { flex:0 0 82vw; scroll-snap-align:start; }
          .ln-route-row { gap:.55rem; }
          .ln-checkin-panel {
            bottom:calc(4.15rem + env(safe-area-inset-bottom));
            max-height:calc(86dvh - 4.15rem); padding-bottom:1rem;
          }
          .ln-checkin-summary { min-height:82px; }
          .ln-checkin-timeline { padding-bottom:.35rem; }
          .ln-checkin-reset { min-height:46px; width:100%; }
        }
        @media (max-width: 389px) {
          .ln-shell { padding-inline:.75rem; }
          .ln-header-row { padding-inline:.75rem; }
          .ln-goal-card { flex-basis:86vw; }
          .ln-alternative-card { flex-basis:88vw; }
        }
        """
    )


def _set_color_mode(mode: str) -> None:
    if mode not in {"system", "light", "dark"}:
        return
    ui.run_javascript(f"window.LearningNavigatorTheme?.setMode('{mode}')")


def _toggle_color_mode() -> None:
    ui.run_javascript("window.LearningNavigatorTheme?.toggle()")


def _theme_options() -> None:
    for label, mode in (
        ("跟随系统", "system"),
        ("浅色", "light"),
        ("深色", "dark"),
    ):
        ui.menu_item(
            label,
            on_click=lambda mode=mode: _set_color_mode(mode),
        ).props(f"data-ln-color-mode={mode} aria-label='{label}外观'").classes("ln-theme-option")


def _theme_controls() -> None:
    with ui.row().classes("ln-theme-controls shrink-0 items-center"):
        ui.button(icon="brightness_auto", on_click=_toggle_color_mode).classes(
            "ln-theme-toggle"
        ).props("flat round dense aria-label='切换浅色与深色'").tooltip("切换浅色与深色")
        with (
            ui.button(icon="arrow_drop_down")
            .classes("ln-theme-menu-trigger")
            .props("flat round dense aria-label='选择外观模式'")
        ):
            with ui.menu():
                ui.label("外观").classes("px-4 pt-3 text-xs font-bold text-gray-500")
                _theme_options()


def _advanced_menu() -> None:
    with (
        ui.button(icon="more_horiz")
        .classes("ln-desktop-control")
        .props("flat round aria-label='高级功能'")
    ):
        with ui.menu():
            ui.label("高级功能").classes("px-4 pt-3 text-xs font-bold text-gray-500")
            for label, href in ADVANCED_NAV:
                ui.menu_item(label, on_click=lambda target=href: ui.navigate.to(target))


def _mobile_menu() -> None:
    with ui.button(icon="menu").classes("ln-mobile-nav").props("flat round aria-label='高级功能'"):
        with ui.menu():
            ui.label("更多功能").classes("px-4 pt-3 text-xs font-bold text-gray-500")
            for label, href in ADVANCED_NAV:
                ui.menu_item(label, on_click=lambda target=href: ui.navigate.to(target))
            ui.separator()
            ui.menu_item("AI 与数据设置", on_click=lambda: ui.navigate.to("/settings"))
            ui.separator()
            ui.label("外观").classes("px-4 pt-3 text-xs font-bold text-gray-500")
            _theme_options()


def _mobile_bottom_navigation(
    active_path: str | None,
    assistant_handle: GlobalAssistantHandle | None,
) -> None:
    with ui.element("nav").classes("ln-mobile-bottom-nav").props("aria-label='主导航'"):
        for label, href, icon in MOBILE_NAV:
            classes = "ln-mobile-nav-item"
            if href == CREATE_ACTION[1]:
                classes += " ln-mobile-nav-create"
            if href == active_path:
                classes += " ln-mobile-nav-item-active"
            if href == CREATE_ACTION[1]:
                with (
                    ui.button(
                        on_click=(
                            assistant_handle.start_new_project
                            if assistant_handle is not None
                            else None
                        )
                    )
                    .classes(classes)
                    .props("flat no-caps aria-label='与 AI 共创新项目'")
                ):
                    ui.icon(icon).classes("text-xl")
                    ui.label(label)
                continue
            with ui.link("", href).classes(classes) as link:
                if href == active_path:
                    link.props("aria-current=page")
                ui.icon(icon).classes("text-xl")
                ui.label(label)


def configure_global_ai_assistant(client: UIAPIClient) -> None:
    """Configure the stateless HTTP client used by the shared assistant surface."""

    global _GLOBAL_AI_CLIENT
    _GLOBAL_AI_CLIENT = client


@contextmanager
def page_shell(
    title: str,
    subtitle: str = "",
    *,
    kicker: str = "全局导航",
    active_path: str | None = None,
    assistant_context: AssistantPageContext | None = None,
    assistant_enabled: bool = True,
) -> Iterator[GlobalAssistantHandle | None]:
    install_theme()
    assistant_handle = None
    if assistant_enabled and _GLOBAL_AI_CLIENT is not None:
        from learning_navigator.ui.components.global_ai_assistant import (
            mount_global_ai_assistant,
        )
        from learning_navigator.ui.page_context import AssistantPageContext

        resolved_context = assistant_context or AssistantPageContext.page(
            page_key=(active_path or title).strip("/") or "home",
            page_title=title,
        )
        assistant_handle = mount_global_ai_assistant(_GLOBAL_AI_CLIENT, resolved_context)
    with ui.header().classes("ln-header text-dark border-b border-gray-200"):
        with ui.row().classes("ln-header-row w-full items-center justify-between"):
            with ui.link("", "/").classes("ln-brand flex items-center gap-3"):
                ui.label("F").classes("ln-brand-mark")
                with ui.column().classes("ln-brand-copy gap-0"):
                    ui.label("Frame").classes("text-sm font-black")
                    ui.label("看清全局，找到下一步").classes("text-xs text-gray-500")
            with ui.row().classes("ln-header-actions items-center gap-1"):
                with (
                    ui.element("nav")
                    .classes("ln-primary-nav items-center gap-1")
                    .props("aria-label='主导航'")
                ):
                    for label, href, icon in PRIMARY_NAV:
                        classes = "ln-nav-link"
                        if href == active_path:
                            classes += " ln-nav-link-active"
                        with ui.link("", href).classes(classes) as link:
                            if href == active_path:
                                link.props("aria-current=page")
                            ui.icon(icon).classes("ln-nav-icon")
                            ui.label(label).classes("ln-nav-label")
                with (
                    ui.button(
                        on_click=(
                            assistant_handle.start_new_project
                            if assistant_handle is not None
                            else None
                        )
                    )
                    .classes("ln-create-action")
                    .props("flat no-caps aria-label='与 AI 共创新项目'")
                ):
                    ui.icon(CREATE_ACTION[2])
                    ui.label(CREATE_ACTION[0]).classes("ln-create-label")
                if assistant_handle is not None:
                    ui.button(
                        "AI",
                        icon="auto_awesome",
                        on_click=assistant_handle.toggle,
                    ).classes("ln-ai-toggle").props(
                        "flat no-caps aria-label='打开或关闭 AI 助手'"
                    ).tooltip("AI 助手")
                _theme_controls()
                _advanced_menu()
                ui.button(
                    icon="settings",
                    on_click=lambda: ui.navigate.to("/settings"),
                ).classes("ln-desktop-control").props(
                    "flat round aria-label='AI 与数据设置'"
                ).tooltip("AI 与数据设置")
                _mobile_menu()
    _mobile_bottom_navigation(active_path, assistant_handle)
    with ui.column().classes("ln-shell flex w-full flex-col gap-5"):
        with ui.column().classes("ln-page-heading gap-2"):
            ui.label(kicker).classes("ln-kicker")
            ui.label(title).classes("ln-page-title")
            if subtitle:
                ui.label(subtitle).classes("ln-supporting max-w-3xl")
        yield assistant_handle


def status_badge(status: str) -> None:
    label = STATUS_LABELS.get(status, status.replace("_", " "))
    ui.label(label).classes(f"ln-status-{status} shrink-0 rounded-full px-3 py-1 text-xs font-bold")


def error_notice(message: str) -> None:
    ui.notify(message, type="negative", multi_line=True, close_button=True)
