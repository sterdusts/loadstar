"""Long-term progress timeline and evidence overview."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    build_growth_view_model,
    intent_action_label,
    intent_mode_for_goal,
    intent_profile,
)


def _duration_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remainder = divmod(minutes, 60)
    return f"{hours} 小时 {remainder} 分" if remainder else f"{hours} 小时"


def _time_record_label(*, sessions: int, check_ins: int) -> str:
    """Explain exactly which durable records contributed to invested time."""

    parts: list[str] = []
    if sessions:
        parts.append(f"{sessions} 次学习会话")
    if check_ins:
        parts.append(f"{check_ins} 次打卡")
    return " · ".join(parts) if parts else "暂无投入记录"


def _consensus_goal_context(dashboard: Any) -> dict[str, Any] | None:
    """Use specific copy only when every aggregated goal shares one vocabulary."""

    if not isinstance(dashboard, dict):
        return None
    goals = [
        item.get("goal")
        for item in dashboard.get("goal_overviews", [])
        if isinstance(item, dict) and isinstance(item.get("goal"), dict)
    ]
    if not goals and isinstance(dashboard.get("current_goal"), dict):
        goals = [dashboard["current_goal"]]
    if not goals:
        return None
    first_goal = goals[0]
    first_profile = intent_profile(first_goal)
    if all(intent_profile(goal) == first_profile for goal in goals[1:]):
        return first_goal
    return None


def _consensus_intent_mode(dashboard: Any) -> str | None:
    goal = _consensus_goal_context(dashboard)
    return intent_mode_for_goal(goal) if goal is not None else None


def _growth_copy(intent_context: Any = None) -> dict[str, str]:
    has_context = intent_context is not None
    intent_mode = (
        intent_mode_for_goal(intent_context)
        if isinstance(intent_context, dict)
        else str(intent_context)
        if isinstance(intent_context, str)
        else None
    )
    profile = intent_profile(intent_context) if has_context else None
    if intent_mode == "LEARN" and profile is not None:
        return {
            "progress": "学习进度",
            "progress_detail": f"已推进 {{touched}}/{{total}} 个{profile['node_label']}",
            "activity": "累计学习天数",
            "activity_detail": "有学习记录的日期",
            "coverage_trend": "学习进度",
            "sessions": f"共 {{count}} 条{profile['record_label']}",
            "evidence": str(profile["evidence_label"]),
            "evidence_detail": "用于更新掌握状态",
            "timeline": f"{profile['record_label']}时间线",
            "empty": "还没有学习记录。保存后，这里会长期保留时间、结果和疑问。",
        }
    if intent_mode == "UNDERSTAND" and profile is not None:
        return {
            "progress": "了解进度",
            "progress_detail": f"已探索 {{touched}}/{{total}} 个{profile['node_label']}",
            "activity": "累计探索天数",
            "activity_detail": "有探索记录的日期",
            "coverage_trend": "了解进度",
            "sessions": f"共 {{count}} 条{profile['record_label']}",
            "evidence": str(profile["evidence_label"]),
            "evidence_detail": "用于更新理解状态",
            "timeline": f"{profile['record_label']}时间线",
            "empty": "还没有探索记录。保存后，这里会长期保留发现、依据和疑问。",
        }
    if intent_mode == "DO" and profile is not None:
        return {
            "progress": "执行进度",
            "progress_detail": f"已推进 {{touched}}/{{total}} 个{profile['node_label']}",
            "activity": "累计推进天数",
            "activity_detail": "有推进记录的日期",
            "coverage_trend": "执行进度",
            "sessions": f"共 {{count}} 条{profile['record_label']}",
            "evidence": str(profile["evidence_label"]),
            "evidence_detail": "用于更新执行状态",
            "timeline": f"{profile['record_label']}时间线",
            "empty": "还没有执行记录。保存后，这里会长期保留结果、交付和阻碍。",
        }
    return {
        "progress": "整体进度",
        "progress_detail": "已推进 {touched}/{total} 个要素",
        "activity": "累计活跃天数",
        "activity_detail": "有推进记录的日期",
        "coverage_trend": "整体进度",
        "sessions": "共 {count} 次推进",
        "evidence": "验证证据",
        "evidence_detail": "用于更新当前状态",
        "timeline": "推进时间线",
        "empty": "还没有推进记录。保存后，这里会长期保留时间、结果和阻碍。",
    }


def build_growth_chart_options(
    series: list[dict[str, Any]],
    intent_context: Any = None,
) -> dict[str, Any]:
    dates = [item["date"] for item in series]
    coverage_label = _growth_copy(intent_context)["coverage_trend"]
    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "axis", "confine": True},
        "legend": {"data": [coverage_label, "投入分钟"], "bottom": 0},
        "grid": {"left": 42, "right": 24, "top": 36, "bottom": 52},
        "xAxis": {
            "type": "category",
            "data": dates,
            "boundaryGap": False,
            "axisLabel": {"color": "#66746c"},
        },
        "yAxis": [
            {
                "type": "value",
                "min": 0,
                "max": 100,
                "axisLabel": {"formatter": "{value}%", "color": "#66746c"},
                "splitLine": {"lineStyle": {"color": "#e6ebe7"}},
            },
            {
                "type": "value",
                "min": 0,
                "axisLabel": {"formatter": "{value} 分", "color": "#66746c"},
                "splitLine": {"show": False},
            },
        ],
        "series": [
            {
                "name": coverage_label,
                "type": "line",
                "smooth": 0.35,
                "symbolSize": 8,
                "data": [item["coverage_percent"] for item in series],
                "lineStyle": {"color": "#1f6b4f", "width": 3},
                "itemStyle": {"color": "#1f6b4f"},
                "areaStyle": {"color": "rgba(31,107,79,.13)"},
            },
            {
                "name": "投入分钟",
                "type": "bar",
                "yAxisIndex": 1,
                "barMaxWidth": 18,
                "data": [item["learning_minutes"] for item in series],
                "itemStyle": {"color": "#4776bd"},
            },
        ],
    }


def _growth_observation(view: dict[str, Any], intent_mode: str | None = None) -> str:
    summary = view["summary"]
    mode_key = intent_mode or ""
    if not summary["total_sessions"] and not summary["total_check_ins"]:
        action = {
            "LEARN": "完成第一次学习",
            "UNDERSTAND": "完成第一次探索",
            "DO": "完成第一次执行",
        }.get(mode_key, "完成第一次推进")
        return f"{action}并保存记录后，这里会开始积累进展轨迹。"
    if summary["overall_progress_percent"] >= 80:
        return "整体进度已经较高，接下来可完成剩余部分并核验关键成果。"
    if summary["active_days"] >= 3 and summary["overall_progress_percent"] < 20:
        return {
            "LEARN": "已经保持多日学习，但整体推进仍较慢；建议缩小单次目标并完成下一知识点。",
            "UNDERSTAND": "已经保持多日探索，但整体推进仍较慢；建议聚焦一个关键问题形成结论。",
            "DO": "已经保持多日执行，但整体推进仍较慢；建议聚焦一个可交付的下一步。",
        }.get(mode_key, "已经保持多日推进，但整体进度仍较低；建议缩小下一步并形成结果。")
    return {
        "LEARN": "继续围绕下一知识点学习并留下证据，系统会更新掌握趋势。",
        "UNDERSTAND": "继续围绕下一关键问题探索并留下依据，系统会更新认知趋势。",
        "DO": "继续围绕下一行动项执行并留下交付，系统会更新完成趋势。",
    }.get(mode_key, "继续围绕下一步行动并留下证据，系统会更新覆盖率和状态趋势。")


def register(client: UIAPIClient) -> None:
    @ui.page("/activity")
    @ui.page("/growth")
    async def growth_page() -> None:
        with page_shell(
            "进展",
            "查看位置变化、投入与验证记录。",
            active_path="/activity",
        ):
            growth_payload: Any = {}
            sessions_payload: Any = {"items": [], "total": 0}
            try:
                growth_payload = await client.get("/growth")
            except UIAPIError as exc:
                error_notice(f"进展摘要暂时不可用：{exc}")
            try:
                sessions_payload = await client.get(
                    "/learning-sessions",
                    params={"limit": 50, "offset": 0},
                )
            except UIAPIError as exc:
                error_notice(f"推进时间线暂时不可用：{exc}")

            try:
                dashboard = await client.get("/dashboard")
            except UIAPIError:
                dashboard = {}

            view = build_growth_view_model(growth_payload, sessions_payload)
            goal_context = _consensus_goal_context(dashboard)
            intent_mode = intent_mode_for_goal(goal_context) if goal_context else None
            mode_copy = _growth_copy(goal_context)
            record_label = (
                str(intent_profile(goal_context)["record_label"]) if goal_context else "推进记录"
            )
            summary = view["summary"]
            with ui.grid().classes("w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"):
                for label, value, detail, icon in (
                    (
                        mode_copy["progress"],
                        f"{summary['overall_progress_percent']:g}%",
                        mode_copy["progress_detail"].format(
                            touched=summary["touched_nodes"],
                            total=summary["total_nodes"],
                        ),
                        "trending_up",
                    ),
                    (
                        mode_copy["activity"],
                        f"{summary['active_days']} 天",
                        mode_copy["activity_detail"],
                        "calendar_month",
                    ),
                    (
                        "投入时间",
                        _duration_label(summary["total_learning_minutes"]),
                        _time_record_label(
                            sessions=summary["total_sessions"],
                            check_ins=summary["total_check_ins"],
                        ),
                        "schedule",
                    ),
                    (
                        "上传记录",
                        f"{summary['upload_event_count']} 次",
                        f"共上传 {summary['uploaded_file_count']} 个文件",
                        "upload_file",
                    ),
                ):
                    with ui.card().classes("ln-card min-w-0 p-4 sm:p-5"):
                        with ui.row().classes("items-center justify-between gap-2"):
                            ui.label(label).classes("text-sm font-bold text-gray-600")
                            ui.icon(icon).classes("text-xl text-green-700")
                        ui.label(value).classes("ln-metric mt-3 break-words")
                        ui.label(detail).classes("mt-1 text-xs text-gray-500")

            with ui.card().classes("ln-card ln-soft-card w-full p-5"):
                with ui.row().classes("items-start gap-3"):
                    ui.icon("auto_graph").classes("mt-1 text-2xl text-green-800")
                    with ui.column().classes("gap-1"):
                        ui.label("当前进展").classes("font-black")
                        ui.label(_growth_observation(view, intent_mode)).classes(
                            "text-sm text-gray-600"
                        )

            with ui.row().classes("w-full items-end justify-between gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label("覆盖与投入趋势").classes("text-2xl font-black")
                    ui.label("曲线来自真实推进记录。 ").classes("text-sm text-gray-600")
            if view["series"]:
                with ui.card().classes("ln-card w-full p-3 sm:p-5"):
                    ui.echart(build_growth_chart_options(view["series"], goal_context)).classes(
                        "w-full"
                    ).style("height:390px")
            else:
                ui.label("尚未形成趋势数据。完成一次推进后，变化会出现在这里。 ").classes(
                    "ln-empty w-full"
                )

            with ui.row().classes("w-full items-end justify-between gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label(mode_copy["timeline"]).classes("text-2xl font-black")
                    ui.label(
                        f"已保存 {view['total']} 条{record_label}，当前显示最近 50 条。"
                    ).classes("text-sm text-gray-600")
                ui.button(
                    intent_action_label("AVAILABLE", goal_context) if goal_context else "开始推进",
                    icon="play_arrow",
                    on_click=lambda: ui.navigate.to("/projects"),
                ).props("color=positive").classes("ln-action-button")
            if not view["timeline"]:
                ui.label(mode_copy["empty"]).classes("ln-empty w-full")
            else:
                with ui.column().classes("w-full gap-0"):
                    for index, session in enumerate(view["timeline"]):
                        with ui.row().classes("w-full flex-nowrap items-stretch gap-3"):
                            with ui.column().classes("items-center gap-0"):
                                ui.element("div").classes("ln-timeline-dot mt-1")
                                if index < len(view["timeline"]) - 1:
                                    ui.element("div").classes("ln-route-line grow")
                            with ui.card().classes("ln-card mb-3 min-w-0 grow p-4 sm:p-5"):
                                with ui.row().classes(
                                    "w-full flex-nowrap items-start justify-between gap-3"
                                ):
                                    with ui.column().classes("min-w-0 gap-1"):
                                        if session["space_id"] and session["node_id"]:
                                            ui.link(
                                                session["node_title"],
                                                f"/maps/{session['space_id']}/nodes/{session['node_id']}",
                                            ).classes("truncate text-base font-black no-underline")
                                        else:
                                            ui.label(session["node_title"]).classes(
                                                "truncate text-base font-black"
                                            )
                                        ui.label(session["note"]).classes("text-sm text-gray-600")
                                    with ui.column().classes("shrink-0 items-end gap-0"):
                                        ui.label(session["display_time"]).classes(
                                            "text-xs text-gray-500"
                                        )
                                        if session.get("event_kind") == "check_in":
                                            ui.label(f"打卡 {session['score']}/10").classes(
                                                "text-xs font-bold text-green-800"
                                            )
                                        if session["minutes"]:
                                            ui.label(_duration_label(session["minutes"])).classes(
                                                "text-xs font-bold text-green-800"
                                            )
                                if session["difficulties"] or session["next_step"]:
                                    with ui.row().classes("mt-3 flex-wrap gap-2"):
                                        if session["difficulties"]:
                                            ui.label(f"困难：{session['difficulties']}").classes(
                                                "rounded-lg bg-red-50 px-3 py-1 text-xs "
                                                "text-red-800"
                                            )
                                        if session["next_step"]:
                                            ui.label(f"下一步：{session['next_step']}").classes(
                                                "rounded-lg bg-green-50 px-3 py-1 text-xs "
                                                "text-green-800"
                                            )
