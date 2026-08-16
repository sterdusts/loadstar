"""Focused goal-element page."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request
from nicegui import ui

from learning_navigator.ui.components.layout import error_notice, page_shell
from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError
from learning_navigator.ui.view_models import (
    DEFAULT_INTENT_MODE,
    intent_action_label,
    intent_mode_for_goal,
    intent_profile,
    intent_progress_label,
    intent_status_label,
    localize_route_reason,
    normalize_intent_mode,
)

DIMENSION_LABELS = {
    "concept_understanding": "概念理解",
    "procedural_skill": "操作 / 计算能力",
    "application_skill": "应用与迁移",
    "memory_strength": "记忆保持",
}

VERIFICATION_LABELS = {
    "UNASSESSED": "待评估",
    "SELF_REPORTED": "已自评",
    "VERIFIED": "已有证据",
    "STALE": "需要复习",
}

MODE_VERIFICATION_LABELS = {
    "LEARN": VERIFICATION_LABELS,
    "UNDERSTAND": {
        "UNASSESSED": "待判断",
        "SELF_REPORTED": "已自评",
        "VERIFIED": "已有依据",
        "STALE": "待核验",
    },
    "DO": {
        "UNASSESSED": "待检查",
        "SELF_REPORTED": "已自评",
        "VERIFIED": "已有交付",
        "STALE": "待复查",
    },
}

NODE_TYPE_LABELS = {
    "MODULE": "目标模块",
    "CONCEPT": "核心概念",
    "SKILL": "关键技能",
    "PROCEDURE": "实践方法",
    "PROJECT": "交付项目",
    "ASSESSMENT": "验证环节",
}

DIFFICULTY_LABELS = {
    1: "入门",
    2: "基础",
    3: "中等",
    4: "进阶",
    5: "挑战",
}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _relation_item(
    edge: dict[str, Any],
    *,
    node_key: str,
    names: dict[str, str],
) -> dict[str, str]:
    related_id = str(edge.get(node_key) or "")
    return {
        "id": related_id,
        "title": names.get(related_id, related_id or "未命名要素"),
        "reason": str(edge.get("reason") or ""),
    }


def _build_node_detail_view_model(
    node: dict[str, Any],
    learning_context: dict[str, Any],
    mastery_profile: dict[str, Any],
    incoming: list[dict[str, Any]],
    outgoing: list[dict[str, Any]],
    names: dict[str, str],
    *,
    route_item: dict[str, Any] | None = None,
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> dict[str, Any]:
    """Keep only information that helps a learner decide what to do next."""

    mode = (
        intent_mode_for_goal(intent_context)
        if isinstance(intent_context, dict)
        else normalize_intent_mode(intent_context)
    )
    mode_copy = intent_profile(intent_context)
    dimension_labels = mode_copy["dimension_labels"]
    verification_labels = MODE_VERIFICATION_LABELS[mode]

    module_context = [
        _relation_item(edge, node_key="source_node_id", names=names)
        for edge in incoming
        if edge.get("relation_type") == "CONTAINS"
    ]
    prerequisites = [
        _relation_item(edge, node_key="source_node_id", names=names)
        for edge in incoming
        if edge.get("relation_type") == "PREREQUISITE"
    ]
    unlocks = [
        _relation_item(edge, node_key="target_node_id", names=names)
        for edge in outgoing
        if edge.get("relation_type") == "PREREQUISITE"
    ]

    related: list[dict[str, str]] = []
    seen_related: set[str] = set()
    for edge, node_key in [
        *((edge, "source_node_id") for edge in incoming),
        *((edge, "target_node_id") for edge in outgoing),
    ]:
        relation = str(edge.get("relation_type") or "")
        if relation == "PREREQUISITE" or (relation == "CONTAINS" and node_key == "source_node_id"):
            continue
        item = _relation_item(edge, node_key=node_key, names=names)
        if item["id"] and item["id"] not in seen_related:
            related.append(item)
            seen_related.add(item["id"])

    display_status = str(
        (route_item or {}).get("status") or node.get("computed_status") or "NOT_RELEVANT"
    )
    route_reason_source: dict[str, Any] | None = route_item
    if route_reason_source is None:
        route_reasons = _dict_items(learning_context.get("route_reasons"))
        route_reason_source = route_reasons[0] if route_reasons else None
    required_mastery_level = int((route_reason_source or {}).get("required_mastery_level") or 3)
    unmet_ids = [
        str(item) for item in (route_reason_source or {}).get("unmet_prerequisites", []) if item
    ]
    prerequisite_by_id = {item["id"]: item for item in prerequisites}
    unmet_prerequisites = [
        prerequisite_by_id.get(
            unmet_id,
            {"id": unmet_id, "title": names.get(unmet_id, "未满足的前置要素"), "reason": ""},
        )
        for unmet_id in unmet_ids
    ]
    route_reason = None
    if route_reason_source:
        raw_reason = str(route_reason_source.get("reason") or "")
        route_reason = localize_route_reason(
            raw_reason,
            status=display_status,
            required_mastery_level=required_mastery_level,
            unmet_titles=[item["title"] for item in unmet_prerequisites],
            intent_mode=mode,
        )

    raw_profile_status = mastery_profile.get("status")
    profile_status: dict[str, Any] = (
        raw_profile_status if isinstance(raw_profile_status, dict) else {}
    )
    dimension_summaries: list[dict[str, Any]] = []
    any_assessed = False
    for dimension, label in dimension_labels.items():
        state = profile_status.get(dimension, {})
        if not isinstance(state, dict):
            state = {}
        verification_status = str(state.get("verification_status") or "UNASSESSED")
        any_assessed = any_assessed or verification_status != "UNASSESSED"
        dimension_summaries.append(
            {
                "label": label,
                "score": round(float(state.get("score") or 0)),
                "progress_label": intent_progress_label(
                    state.get("score"),
                    intent_context,
                ),
                "verification_label": verification_labels.get(
                    verification_status,
                    verification_labels["UNASSESSED"],
                ),
            }
        )

    raw_readiness = mastery_profile.get("readiness")
    readiness: dict[str, Any] = raw_readiness if isinstance(raw_readiness, dict) else {}
    readiness_score = round(float(readiness.get("readiness_score") or 0))
    readiness_noun = {"LEARN": "学习", "UNDERSTAND": "理解", "DO": "执行"}[mode]
    readiness_label = (
        f"{readiness_noun}就绪度 {readiness_score}% · "
        f"{intent_progress_label(readiness_score, intent_context)}"
        if any_assessed
        else f"{readiness_noun}状态尚未评估"
    )

    activity_sections: list[dict[str, Any]] = []
    resources = [
        {
            "title": str(item.get("title") or "参考资源"),
            "uri": str(item.get("uri") or "").strip() or None,
        }
        for item in _dict_items(learning_context.get("resources"))
        if item.get("title")
    ]
    if resources:
        resource_title = {
            "LEARN": "学习资源",
            "UNDERSTAND": "参考材料",
            "DO": "执行资源",
        }[mode]
        activity_sections.append({"key": "resources", "title": resource_title, "items": resources})

    sessions = [
        {
            "title": str(item.get("note") or "已记录一次推进"),
            "uri": None,
        }
        for item in _dict_items(learning_context.get("sessions"))
    ]
    if sessions:
        activity_sections.append(
            {"key": "sessions", "title": mode_copy["record_label"], "items": sessions}
        )

    evidence = [
        {
            "title": str(item.get("title") or item.get("evidence_type") or "验证证据"),
            "uri": None,
        }
        for item in _dict_items(learning_context.get("evidence"))
    ]
    if evidence:
        activity_sections.append(
            {"key": "evidence", "title": mode_copy["evidence_label"], "items": evidence}
        )

    source_labels: list[str] = []
    for source in _dict_items(node.get("source_basis")):
        reference = str(source.get("reference") or "").strip()
        label = reference or (
            "AI 生成的目标方案"
            if any(source.get(key) for key in ("suggestion_id", "provider", "model"))
            else ""
        )
        if label and label not in source_labels:
            source_labels.append(label)

    difficulty = node.get("difficulty")
    difficulty_label = (
        DIFFICULTY_LABELS.get(difficulty, "未标注")
        if isinstance(difficulty, int) and not isinstance(difficulty, bool)
        else "未标注"
    )

    return {
        "title": str(node.get("title") or "未命名要素"),
        "description": str(node.get("description") or "尚未添加一句话说明。"),
        "display_status": display_status,
        "objectives": [
            str(item)
            for item in node.get("learning_objectives", [])
            if isinstance(item, str) and item.strip()
        ],
        "module_context": module_context,
        "prerequisites": prerequisites,
        "unmet_prerequisites": unmet_prerequisites,
        "unlocks": unlocks,
        "related": related,
        "route_reason": route_reason,
        "required_mastery_level": required_mastery_level,
        "dimension_summaries": dimension_summaries,
        "readiness_label": readiness_label,
        "activity_sections": activity_sections,
        "source_labels": source_labels,
        "node_type_label": NODE_TYPE_LABELS.get(str(node.get("node_type") or ""), "目标要素"),
        "difficulty_label": difficulty_label,
        "intent_mode": mode,
        "intent_copy": mode_copy,
    }


def _route_context_for_node(
    dashboard: dict[str, Any],
    *,
    space_id: str,
    node_id: str,
    preferred_goal_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    """Find this node's route without assuming the first active goal owns it."""

    overviews = _dict_items(dashboard.get("goal_overviews"))
    if not overviews:
        overviews = [
            {
                "goal": dashboard.get("current_goal"),
                "route_overview": dashboard.get("route_overview"),
            }
        ]

    matching_goal: dict[str, Any] | None = None
    for overview in overviews:
        goal = overview.get("goal")
        if not isinstance(goal, dict) or str(goal.get("space_id") or "") != space_id:
            continue
        if preferred_goal_id and str(goal.get("id") or "") != preferred_goal_id:
            continue
        matching_goal = matching_goal or goal
        route = _dict_items(overview.get("route_overview"))
        route_item = next(
            (item for item in route if str(item.get("node_id") or "") == node_id),
            None,
        )
        if route_item is not None:
            return route_item, route, goal
    return None, [], matching_goal


def _primary_action(
    view: dict[str, Any],
    *,
    space_id: str,
    node_id: str,
    route: list[dict[str, Any]],
    intent_context: Any = DEFAULT_INTENT_MODE,
) -> dict[str, str]:
    """Return one truthful next action for the learner-visible node state."""

    status = str(view.get("display_status") or "NOT_RELEVANT")
    mode = (
        intent_mode_for_goal(intent_context)
        if isinstance(intent_context, dict)
        else normalize_intent_mode(intent_context)
    )
    copy = intent_profile(intent_context)
    workbench_href = f"/workbench?node_id={node_id}"
    map_href = f"/maps/{space_id}"
    if status in {"AVAILABLE", "IN_PROGRESS", "NEEDS_REVIEW"}:
        return {
            "label": intent_action_label(status, intent_context),
            "href": workbench_href,
            "icon": "replay" if status == "NEEDS_REVIEW" else "play_arrow",
        }
    if status == "BLOCKED":
        return {
            "label": {
                "LEARN": "仍然开始学习",
                "UNDERSTAND": "仍然开始探索",
                "DO": "仍然开始执行",
            }[mode],
            "href": workbench_href,
            "icon": "play_arrow",
        }
    if status == "MASTERED":
        candidate_statuses = {"AVAILABLE", "IN_PROGRESS", "NEEDS_REVIEW"}
        current_index = next(
            (
                index
                for index, item in enumerate(route)
                if str(item.get("node_id") or "") == node_id
            ),
            -1,
        )
        ordered_candidates = route[current_index + 1 :] + route[: max(current_index, 0)]
        next_item = next(
            (
                item
                for item in ordered_candidates
                if str(item.get("status") or "") in candidate_statuses and item.get("node_id")
            ),
            None,
        )
        if next_item is not None:
            next_id = str(next_item["node_id"])
            next_title = str(next_item.get("title") or "下一要素")
            return {
                "label": f"{copy['route_label']}下一步：{next_title}",
                "href": f"/maps/{space_id}/nodes/{next_id}",
                "icon": "near_me",
            }
        return {"label": "返回框架地图", "href": map_href, "icon": "account_tree"}
    return {"label": "返回框架地图", "href": map_href, "icon": "account_tree"}


def _render_relation_links(
    title: str,
    items: list[dict[str, str]],
    *,
    space_id: str,
    empty_text: str,
) -> None:
    with ui.column().classes("min-w-0 flex-1 gap-2"):
        ui.label(title).classes("text-sm font-bold text-gray-500")
        if items:
            with ui.row().classes("flex-wrap gap-2"):
                for item in items:
                    ui.link(
                        item["title"],
                        f"/maps/{space_id}/nodes/{item['id']}",
                    ).classes(
                        "rounded-full border border-green-200 bg-green-50 px-3 py-1 "
                        "font-medium no-underline text-green-800"
                    )
        else:
            ui.label(empty_text).classes("text-sm text-gray-600")


def _render_node_load_error(space_id: str, message: str) -> None:
    with ui.card().classes("ln-card w-full items-center gap-4 p-7 text-center"):
        ui.icon("cloud_off", color="negative").classes("text-4xl")
        ui.label("暂时无法打开这个要素").classes("text-xl font-black")
        ui.label(message).classes("max-w-xl text-sm leading-6 text-gray-600")
        ui.button(
            "返回目标地图",
            on_click=lambda: ui.navigate.to(f"/maps/{space_id}"),
            icon="account_tree",
        ).classes("ln-action-button").props("color=positive")


def register(client: UIAPIClient) -> None:
    @ui.page("/maps/{space_id}/nodes/{node_id}")
    async def node_page(space_id: str, node_id: str, request: Request) -> None:
        requested_goal_id = str(request.query_params.get("goal_id") or "").strip()
        requested_check_in_id = str(request.query_params.get("check_in_id") or "").strip()
        with page_shell(
            "目标要素",
            "查看当前状态、前后关系和验证标准。",
            active_path="/map",
        ):
            try:
                graph, learning_context, mastery_profile, dashboard = await asyncio.gather(
                    client.get(f"/spaces/{space_id}/graph"),
                    client.get(f"/nodes/{node_id}/learning-context"),
                    client.get(f"/nodes/{node_id}/mastery-profile"),
                    client.get("/dashboard"),
                )
            except UIAPIError:
                _render_node_load_error(space_id, "服务暂时没有返回完整数据，请稍后再试。")
                return
            node = next((item for item in graph["nodes"] if item["id"] == node_id), None)
            if node is None:
                _render_node_load_error(space_id, "这个要素不存在，或已经从目标地图中移除。")
                return

            incoming = [edge for edge in graph["edges"] if edge["target_node_id"] == node_id]
            outgoing = [edge for edge in graph["edges"] if edge["source_node_id"] == node_id]
            names = {item["id"]: item["title"] for item in graph["nodes"]}
            route_item, route, goal_context = _route_context_for_node(
                dashboard,
                space_id=space_id,
                node_id=node_id,
                preferred_goal_id=requested_goal_id or None,
            )
            view = _build_node_detail_view_model(
                node,
                learning_context,
                mastery_profile,
                incoming,
                outgoing,
                names,
                route_item=route_item,
                intent_context=goal_context or DEFAULT_INTENT_MODE,
            )
            intent_mode = view["intent_mode"]
            mode_copy = view["intent_copy"]
            dimension_labels = mode_copy["dimension_labels"]
            selected_check_in: dict[str, Any] | None = None
            selected_check_in_missing = False
            goal_id = str((goal_context or {}).get("id") or "")
            if goal_id:
                try:
                    if requested_check_in_id:
                        selected_check_in = await client.get(
                            f"/goals/{goal_id}/nodes/{node_id}/check-ins/{requested_check_in_id}"
                        )
                    else:
                        check_in_history = await client.get(
                            f"/goals/{goal_id}/nodes/{node_id}/check-ins?limit=1&offset=0"
                        )
                        check_in_items = _dict_items(check_in_history.get("items"))
                        selected_check_in = check_in_items[0] if check_in_items else None
                except UIAPIError:
                    # The element page remains useful even when its optional progress
                    # commentary cannot be loaded.
                    selected_check_in = None
                    selected_check_in_missing = bool(requested_check_in_id)

            raw_ai_evaluation = (selected_check_in or {}).get("ai_evaluation")
            ai_evaluation: dict[str, Any] | None = (
                raw_ai_evaluation if isinstance(raw_ai_evaluation, dict) else None
            )

            score_inputs: dict[str, Any] = {}
            with (
                ui.dialog() as assessment_dialog,
                ui.card().classes("gap-5 p-6").style("width:min(720px, calc(100vw - 32px))"),
            ):
                with ui.row().classes("w-full items-start justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label(mode_copy["assessment_heading"]).classes("text-2xl font-black")
                        ui.label(mode_copy["assessment_note"]).classes("text-sm text-gray-600")
                    ui.button(icon="close", on_click=assessment_dialog.close).props(
                        "flat round dense aria-label='关闭评估'"
                    )

                ui.label("0 表示尚未具备，50 表示能处理基础情况，100 表示能独立迁移。 ").classes(
                    "text-sm text-gray-600"
                )
                with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-2"):
                    for dimension, summary in zip(
                        dimension_labels,
                        view["dimension_summaries"],
                        strict=True,
                    ):
                        with ui.column().classes("gap-1"):
                            ui.label(summary["label"]).classes("font-bold")
                            score_inputs[dimension] = ui.slider(
                                min=0,
                                max=100,
                                step=25,
                                value=round(float(summary["score"]) / 25) * 25,
                            ).props(f"label-always aria-label='{summary['label']}'")
                assessment_note = ui.input(
                    "补充说明（可选）",
                    placeholder={
                        "LEARN": "例如：能独立完成基础题，但应用题还需要提示",
                        "UNDERSTAND": "例如：能解释核心机制，但部分判断仍缺少依据",
                        "DO": "例如：能独立完成基础交付，但复杂情况仍需协助",
                    }[intent_mode],
                ).classes("w-full")

                async def save_self_assessment() -> None:
                    try:
                        await client.post(
                            f"/nodes/{node_id}/mastery-profile/evidence",
                            json={
                                "kind": "SELF_REPORT",
                                "measurements": [
                                    {
                                        "dimension": dimension,
                                        "score": float(slider.value),
                                    }
                                    for dimension, slider in score_inputs.items()
                                ],
                                "evidence_confidence": 1.0,
                                "note": assessment_note.value or None,
                            },
                        )
                        ui.notify("状态已保存，当前位置已更新", type="positive")
                        assessment_dialog.close()
                        ui.navigate.to(f"/maps/{space_id}/nodes/{node_id}")
                    except UIAPIError as exc:
                        error_notice(str(exc))

                ui.button(
                    "保存评估",
                    on_click=save_self_assessment,
                    icon="fact_check",
                ).classes("ln-action-button self-start").props("color=positive")

                with ui.expansion(
                    {
                        "LEARN": "已有可验证的学习结果？",
                        "UNDERSTAND": "已有可靠依据？",
                        "DO": "已有可验收结果？",
                    }[intent_mode],
                    icon="verified",
                ).classes("w-full rounded-xl border border-gray-200 bg-gray-50"):
                    ui.label(
                        {
                            "LEARN": "仅在完成测试、练习或作品后，确认达到学习要求。",
                            "UNDERSTAND": "仅在有可靠材料或事实支持时，确认达到理解要求。",
                            "DO": "仅在结果可检查或已验收时，确认达到行动要求。",
                        }[intent_mode]
                    ).classes("text-sm text-gray-600")

                    async def confirm_route_level() -> None:
                        try:
                            await client._request(
                                "PUT",
                                f"/nodes/{node_id}/mastery",
                                json={
                                    "update_kind": "manual_review",
                                    "value": int(view["required_mastery_level"]),
                                    "override": False,
                                    "reason": "用户确认已有结果达到当前路线要求",
                                },
                            )
                            ui.notify("验证结果已记录，路径已重新计算", type="positive")
                            assessment_dialog.close()
                            ui.navigate.to(f"/maps/{space_id}/nodes/{node_id}")
                        except UIAPIError as exc:
                            error_notice(str(exc))

                    ui.button(
                        {
                            "LEARN": "确认达到掌握标准",
                            "UNDERSTAND": "确认依据充分",
                            "DO": "确认结果达标",
                        }[intent_mode],
                        on_click=confirm_route_level,
                        icon="verified_user",
                    ).props("outline color=positive")

            with ui.row().classes("w-full items-center justify-between gap-3"):
                ui.link("← 返回目标地图", f"/maps/{space_id}").classes(
                    "font-medium no-underline text-green-800"
                )
                if view["module_context"]:
                    module = view["module_context"][0]
                    ui.link(
                        f"所属模块 · {module['title']}",
                        f"/maps/{space_id}/nodes/{module['id']}",
                    ).classes("text-sm no-underline text-gray-500")

            with ui.card().classes("ln-card w-full gap-5 p-6 sm:p-7"):
                with ui.row().classes(
                    "w-full flex-wrap items-start justify-between gap-5 max-sm:flex-col"
                ):
                    with ui.column().classes("min-w-0 flex-1 gap-2"):
                        ui.label(mode_copy["detail_title"]).classes("ln-kicker")
                        with ui.row().classes("flex-wrap items-center gap-3"):
                            ui.label(view["title"]).classes("text-3xl font-black")
                            ui.label(
                                intent_status_label(
                                    view["display_status"],
                                    goal_context or DEFAULT_INTENT_MODE,
                                )
                            ).classes(
                                f"ln-status-{view['display_status']} rounded-full px-3 py-1 "
                                "text-xs font-bold"
                            )
                            ui.label(view["difficulty_label"]).classes(
                                "rounded-full bg-gray-100 px-3 py-1 text-sm font-bold text-gray-600"
                            )
                        ui.label(view["description"]).classes(
                            "max-w-3xl text-base leading-7 text-gray-600"
                        )

                    primary = _primary_action(
                        view,
                        space_id=space_id,
                        node_id=node_id,
                        route=route,
                        intent_context=goal_context or DEFAULT_INTENT_MODE,
                    )
                    primary_label = primary["label"]
                    primary_href = primary["href"]
                    ui.button(
                        primary_label,
                        on_click=lambda: ui.navigate.to(primary_href),
                        icon=primary["icon"],
                    ).classes("ln-action-button shrink-0 max-sm:w-full").props("color=positive")

                with ui.row().classes(
                    "w-full items-start gap-3 rounded-2xl border border-green-100 bg-green-50 p-4"
                ):
                    ui.icon("near_me", color="positive").classes("mt-0.5")
                    with ui.column().classes("gap-1"):
                        ui.label(mode_copy["reason_heading"]).classes("font-bold text-green-900")
                        ui.label(
                            view["route_reason"]
                            or f"这是框架中的扩展{mode_copy['node_label']}，"
                            f"当前{mode_copy['route_label']}暂未安排。"
                        ).classes("text-sm leading-6 text-green-900")

            with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-2"):
                if view["objectives"]:
                    with ui.card().classes("ln-card gap-3 p-5"):
                        ui.label(mode_copy["objectives_heading"]).classes("text-xl font-black")
                        for objective in view["objectives"]:
                            with ui.row().classes("items-start gap-2"):
                                ui.icon("check_circle", color="positive").classes("mt-0.5")
                                ui.label(objective).classes("min-w-0 flex-1 leading-6")

                with ui.card().classes("ln-card gap-4 p-5"):
                    ui.label(mode_copy["relations_heading"]).classes("text-xl font-black")
                    with ui.row().classes("w-full flex-wrap items-start gap-5"):
                        _render_relation_links(
                            mode_copy["prerequisite_heading"],
                            view["prerequisites"],
                            space_id=space_id,
                            empty_text=mode_copy["prerequisite_empty"],
                        )
                        ui.icon("arrow_forward", color="positive").classes("mt-8 max-md:hidden")
                        _render_relation_links(
                            mode_copy["unlock_heading"],
                            view["unlocks"],
                            space_id=space_id,
                            empty_text=mode_copy["unlock_empty"],
                        )

            with ui.card().classes("ln-card w-full gap-4 p-5"):
                with ui.row().classes("w-full flex-wrap items-start justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label("AI 学习评语").classes("text-xl font-black")
                        ui.label(
                            "依据最近一次打卡的备注与上传材料生成，不会改动掌握状态。"
                        ).classes("text-sm text-gray-600")
                    if selected_check_in:
                        duration = int(selected_check_in.get("duration_minutes") or 0)
                        attachment_count = len(_dict_items(selected_check_in.get("attachments")))
                        checked_in_at = str(selected_check_in.get("checked_in_at") or "")
                        scope_label = "对应打卡" if requested_check_in_id else "最近打卡"
                        ui.label(
                            f"{scope_label} · {checked_in_at[:16].replace('T', ' ')} · "
                            f"{duration} 分钟 · {attachment_count} 个文件"
                        ).classes("text-xs font-bold text-gray-500")

                if ai_evaluation:
                    ui.label(str(ai_evaluation.get("summary") or "暂无综合评语")).classes(
                        "max-w-4xl text-base font-bold leading-7 text-green-900"
                    )
                    evaluation_dimensions = (
                        ("concept_understanding", "概念理解"),
                        ("procedural_skill", "操作 / 计算能力"),
                        ("application_skill", "应用与迁移"),
                        ("memory_strength", "记忆保持"),
                    )
                    with ui.grid().classes(
                        "w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
                    ):
                        for key, label in evaluation_dimensions:
                            value = ai_evaluation.get(key)
                            detail = value if isinstance(value, dict) else {}
                            score = max(0, min(100, int(detail.get("score") or 0)))
                            with ui.column().classes(
                                "gap-2 rounded-xl border border-green-100 bg-green-50 p-3"
                            ):
                                with ui.row().classes("w-full items-center justify-between gap-2"):
                                    ui.label(label).classes("font-bold")
                                    ui.label(f"{score}%").classes(
                                        "text-xs font-black text-green-800"
                                    )
                                ui.linear_progress(value=score / 100).props(
                                    "rounded color=positive"
                                )
                                ui.label(str(detail.get("comment") or "暂无评语")).classes(
                                    "text-sm leading-6 text-gray-700"
                                )
                    if ai_evaluation.get("limitations"):
                        ui.label(f"评估边界：{ai_evaluation['limitations']}").classes(
                            "text-xs text-gray-500"
                        )
                elif selected_check_in_missing:
                    ui.label("没有找到这次打卡记录，可能已被删除或不属于当前项目。").classes(
                        "rounded-xl bg-red-50 p-4 text-sm font-bold text-red-800"
                    )
                else:
                    ui.label(
                        "完成一次打卡并填写备注或上传材料后，系统会自动生成简短评语。"
                    ).classes("rounded-xl bg-gray-50 p-4 text-sm text-gray-600")

            with ui.expansion("自评与验证（高级）", icon="tune").classes(
                "ln-card w-full rounded-2xl px-2"
            ):
                with ui.row().classes("w-full flex-wrap items-center justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label(mode_copy["state_heading"]).classes("text-xl font-black")
                        ui.label(view["readiness_label"]).classes(
                            "text-sm font-bold text-green-800"
                        )
                    ui.button(
                        mode_copy["update_state"],
                        on_click=assessment_dialog.open,
                        icon="tune",
                    ).props("outline color=positive")

                with ui.grid().classes("w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"):
                    for summary in view["dimension_summaries"]:
                        with ui.column().classes(
                            "gap-2 rounded-xl border border-gray-200 bg-white p-3"
                        ):
                            with ui.row().classes("w-full items-center justify-between gap-2"):
                                ui.label(summary["label"]).classes("font-bold")
                                ui.label(summary["verification_label"]).classes(
                                    "text-xs text-gray-500"
                                )
                            if (
                                summary["verification_label"]
                                == MODE_VERIFICATION_LABELS[intent_mode]["UNASSESSED"]
                            ):
                                ui.label("尚无有效记录").classes("text-sm text-gray-500")
                            else:
                                ui.linear_progress(value=summary["score"] / 100).props(
                                    "rounded color=positive"
                                )
                                ui.label(
                                    f"{summary['score']}% · {summary['progress_label']}"
                                ).classes("text-sm font-bold text-green-800")

            if view["activity_sections"]:
                with ui.expansion(mode_copy["activity_heading"], icon="history").classes(
                    "ln-card w-full rounded-2xl px-2"
                ):
                    with ui.grid().classes("w-full grid-cols-1 gap-4 md:grid-cols-3"):
                        for section in view["activity_sections"]:
                            with ui.column().classes("gap-2 p-3"):
                                ui.label(section["title"]).classes("font-bold")
                                for item in section["items"]:
                                    if item.get("uri"):
                                        ui.link(item["title"], item["uri"])
                                    else:
                                        ui.label(item["title"]).classes("text-sm text-gray-600")

            with ui.expansion("更多信息", icon="info_outline").classes(
                "ln-card w-full rounded-2xl px-2"
            ):
                with ui.column().classes("gap-3 p-3"):
                    ui.label(
                        f"{view['node_type_label']} · 难度：{view['difficulty_label']}"
                    ).classes("text-sm text-gray-600")
                    if view["related"]:
                        ui.label("更多关联").classes("font-bold")
                        with ui.row().classes("flex-wrap gap-2"):
                            for item in view["related"]:
                                ui.link(
                                    item["title"],
                                    f"/maps/{space_id}/nodes/{item['id']}",
                                ).classes("text-sm")
                    if view["source_labels"]:
                        ui.label("内容依据").classes("font-bold")
                        for source_label in view["source_labels"]:
                            ui.label(source_label).classes("text-sm text-gray-600")
