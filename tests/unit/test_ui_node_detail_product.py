"""Product contracts for the compact node-detail experience."""

from __future__ import annotations

import inspect
from typing import Any

from learning_navigator.ui.pages import node_detail


def _node() -> dict[str, Any]:
    return {
        "id": "node-functions",
        "title": "函数图像",
        "description": "理解函数输入、输出与图像变化之间的关系。",
        "node_type": "CONCEPT",
        "difficulty": 2,
        "depth_level": 3,
        "computed_status": "AVAILABLE",
        "learning_objectives": ["识别常见函数图像", "解释参数变化的影响"],
        "source_basis": [
            {"reference": "初中数学教材"},
            {
                "suggestion_id": "suggestion-secret-id",
                "provider": "deepseek",
                "model": "provider-internal-model",
                "prompt_version": "learning-plan-prompt-v3",
            },
        ],
    }


def _learning_context(*, with_activity: bool) -> dict[str, Any]:
    return {
        "route_reasons": [
            {
                "goal_title": "掌握微积分",
                "reason": "导数学习前需要先理解函数图像。",
                "required_mastery_level": 3,
            }
        ],
        "resources": (
            [{"title": "函数图像练习", "uri": "https://example.test/functions"}]
            if with_activity
            else []
        ),
        "sessions": (
            [{"id": "session-1", "note": "完成一次图像变换练习"}] if with_activity else []
        ),
        "evidence": [],
    }


def _mastery_profile() -> dict[str, Any]:
    return {
        "status": {
            "concept_understanding": {"score": 65, "verification_status": "SELF_REPORTED"},
            "procedural_skill": {"score": 45, "verification_status": "UNASSESSED"},
            "application_skill": {"score": 30, "verification_status": "STALE"},
            "memory_strength": {"score": 55, "verification_status": "VERIFIED"},
        },
        "readiness": {"readiness_score": 30},
    }


def _goal_with_custom_semantics() -> dict[str, Any]:
    return {
        "intent_mode": "UNDERSTAND",
        "semantic_profile": {
            "template_id": "UNDERSTAND_FAMILIARITY_V1",
            "node_label": "判断题",
            "module_label": "问题组",
            "route_label": "求证路径",
            "record_label": "调查笔记",
            "evidence_label": "事实依据",
            "status_labels": {
                "AVAILABLE": "可以了解",
                "BLOCKED": "前提待补",
                "MASTERED": "已深入了解",
                "IN_PROGRESS": "了解中",
                "NEEDS_REVIEW": "待更新",
                "NOT_RELEVANT": "暂不关注",
            },
            "action_labels": {
                "AVAILABLE": "开始了解",
                "IN_PROGRESS": "继续了解",
                "NEEDS_REVIEW": "重新核验",
            },
            "dimension_labels": {
                "concept_understanding": "事实认识",
                "procedural_skill": "机制认识",
                "application_skill": "判断能力",
                "memory_strength": "认知保持",
            },
            "progress_levels": [
                {"min_score": 0, "label": "不知道"},
                {"min_score": 25, "label": "听说过"},
                {"min_score": 55, "label": "了解"},
                {"min_score": 85, "label": "非常了解"},
            ],
        },
    }


def _relations() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    incoming = [
        {
            "source_node_id": "module-math",
            "target_node_id": "node-functions",
            "relation_type": "CONTAINS",
            "reason": "函数图像属于数学基础模块。",
        },
        {
            "source_node_id": "node-algebra",
            "target_node_id": "node-functions",
            "relation_type": "PREREQUISITE",
            "reason": "代数是理解函数表达的前置。",
        },
        {
            "source_node_id": "node-coordinate",
            "target_node_id": "node-functions",
            "relation_type": "RELATED",
            "reason": "坐标系用于展示函数图像。",
        },
    ]
    outgoing = [
        {
            "source_node_id": "node-functions",
            "target_node_id": "node-derivative",
            "relation_type": "PREREQUISITE",
            "reason": "理解函数图像后才能学习导数。",
        },
        {
            "source_node_id": "node-functions",
            "target_node_id": "node-modeling",
            "relation_type": "RELATED",
            "reason": "函数图像可用于解释模型。",
        },
    ]
    names = {
        "module-math": "数学基础",
        "node-algebra": "代数式",
        "node-coordinate": "平面坐标系",
        "node-functions": "函数图像",
        "node-derivative": "导数",
        "node-modeling": "函数建模",
    }
    return incoming, outgoing, names


def _build_view(*, with_activity: bool) -> dict[str, Any]:
    incoming, outgoing, names = _relations()
    return node_detail._build_node_detail_view_model(
        _node(),
        _learning_context(with_activity=with_activity),
        _mastery_profile(),
        incoming,
        outgoing,
        names,
    )


def test_node_detail_view_model_prioritizes_navigation_information() -> None:
    view = _build_view(with_activity=False)

    assert view["objectives"] == ["识别常见函数图像", "解释参数变化的影响"]
    assert "数学基础" in str(view["module_context"])
    assert "代数式" in str(view["prerequisites"])
    assert "导数" in str(view["unlocks"])
    assert "平面坐标系" in str(view["related"])
    assert "函数建模" in str(view["related"])
    assert "导数学习前需要先理解函数图像" in str(view["route_reason"])


def test_empty_learning_activity_does_not_create_placeholder_sections() -> None:
    empty_view = _build_view(with_activity=False)
    populated_view = _build_view(with_activity=True)

    assert empty_view["activity_sections"] == []
    assert "函数图像练习" in str(populated_view["activity_sections"])
    assert "完成一次图像变换练习" in str(populated_view["activity_sections"])
    assert "验证证据" not in str(populated_view["activity_sections"])


def test_source_labels_hide_provider_and_generation_internals() -> None:
    labels = str(_build_view(with_activity=False)["source_labels"])

    assert "初中数学教材" in labels
    assert "suggestion-secret-id" not in labels
    assert "deepseek" not in labels
    assert "provider-internal-model" not in labels
    assert "learning-plan-prompt-v3" not in labels


def test_four_dimension_state_is_a_read_only_summary() -> None:
    view = _build_view(with_activity=False)
    summaries = view["dimension_summaries"]

    assert len(summaries) == 4
    assert {item["label"] for item in summaries} == {
        "概念理解",
        "操作 / 计算能力",
        "应用与迁移",
        "记忆保持",
    }
    assert {item["score"] for item in summaries} == {65, 45, 30, 55}
    assert "30" in view["readiness_label"]
    assert all("slider" not in item and "input" not in item for item in summaries)


def test_page_source_has_one_primary_action_and_one_assessment_entry() -> None:
    source = inspect.getsource(node_detail.register)

    assert source.count("primary_label,") == 1
    assert source.count('mode_copy["update_state"]') == 1
    assert '"更多信息"' in source
    assert "人工确认状态" not in source
    assert "掌握证据与状态" not in source


def test_page_source_removes_empty_cards_and_legacy_dual_slider_ui() -> None:
    source = inspect.getsource(node_detail.register)

    assert "暂无资源。" not in source
    assert "暂无学习记录。" not in source
    assert "暂无证据。" not in source
    assert "level = ui.slider" not in source
    assert "confidence = ui.slider" not in source
    assert "evidence_confidence = ui.slider" not in source


def test_primary_action_matches_each_progress_state() -> None:
    expected = {
        "AVAILABLE": ("开始学习", "/workbench?node_id=node-functions"),
        "IN_PROGRESS": ("继续学习", "/workbench?node_id=node-functions"),
        "NEEDS_REVIEW": ("开始复习", "/workbench?node_id=node-functions"),
        "NOT_RELEVANT": ("返回框架地图", "/maps/space-math"),
    }

    for status, (label, href) in expected.items():
        action = node_detail._primary_action(
            {"display_status": status, "unmet_prerequisites": []},
            space_id="space-math",
            node_id="node-functions",
            route=[],
        )
        assert (action["label"], action["href"]) == (label, href)


def test_prerequisite_warning_never_replaces_the_primary_start_action() -> None:
    action = node_detail._primary_action(
        {
            "display_status": "BLOCKED",
            "prerequisites": [{"id": "first-listed", "title": "第一个前置"}],
            "unmet_prerequisites": [{"id": "actually-unmet", "title": "真正缺少的基础"}],
        },
        space_id="space-math",
        node_id="node-functions",
        route=[],
    )

    assert action["label"] == "仍然开始学习"
    assert action["href"] == "/workbench?node_id=node-functions"


def test_mastered_primary_action_leads_to_the_next_learnable_route_node() -> None:
    action = node_detail._primary_action(
        {"display_status": "MASTERED", "unmet_prerequisites": []},
        space_id="space-math",
        node_id="node-functions",
        route=[
            {"node_id": "node-functions", "title": "函数图像", "status": "MASTERED"},
            {"node_id": "node-derivative", "title": "导数", "status": "AVAILABLE"},
        ],
    )

    assert action["label"] == "学习路径下一步：导数"
    assert action["href"] == "/maps/space-math/nodes/node-derivative"


def test_node_page_has_inline_load_failure_and_map_navigation_state() -> None:
    source = inspect.getsource(node_detail.register)

    assert 'active_path="/map"' in source
    assert "except UIAPIError:" in source
    assert "_render_node_load_error(space_id" in source
    assert "aria-label='关闭评估'" in source


def test_primary_action_uses_understanding_and_execution_language() -> None:
    understand = node_detail._primary_action(
        {"display_status": "NEEDS_REVIEW", "unmet_prerequisites": []},
        space_id="space-industry",
        node_id="question-chain",
        route=[],
        intent_context={"intent_mode": "UNDERSTAND"},
    )
    execute = node_detail._primary_action(
        {
            "display_status": "BLOCKED",
            "unmet_prerequisites": [{"id": "brief", "title": "确认需求"}],
        },
        space_id="space-launch",
        node_id="ship",
        route=[],
        intent_context={"intent_mode": "DO"},
    )

    assert understand["label"] == "重新核验"
    assert execute["label"] == "仍然开始执行"
    assert execute["href"] == "/workbench?node_id=ship"


def test_node_view_model_adapts_dimensions_and_evidence_without_changing_data() -> None:
    incoming, outgoing, names = _relations()
    view = node_detail._build_node_detail_view_model(
        _node(),
        _learning_context(with_activity=True),
        _mastery_profile(),
        incoming,
        outgoing,
        names,
        intent_context={"intent_mode": "UNDERSTAND"},
    )

    assert view["intent_mode"] == "UNDERSTAND"
    assert {item["label"] for item in view["dimension_summaries"]} == {
        "概念理解",
        "关系与机制",
        "判断与迁移",
        "认知保持",
    }
    assert "判断依据" in str(view["intent_copy"])
    assert {item["score"] for item in view["dimension_summaries"]} == {65, 45, 30, 55}


def test_node_view_uses_valid_goal_specific_dimensions_and_progress_levels() -> None:
    incoming, outgoing, names = _relations()
    goal = _goal_with_custom_semantics()
    view = node_detail._build_node_detail_view_model(
        _node(),
        _learning_context(with_activity=True),
        _mastery_profile(),
        incoming,
        outgoing,
        names,
        intent_context=goal,
    )
    action = node_detail._primary_action(
        {"display_status": "AVAILABLE", "unmet_prerequisites": []},
        space_id="space-industry",
        node_id="question",
        route=[],
        intent_context=goal,
    )

    assert [item["label"] for item in view["dimension_summaries"]] == [
        "事实认识",
        "机制认识",
        "判断能力",
        "认知保持",
    ]
    assert view["dimension_summaries"][0]["progress_label"] == "了解"
    assert "听说过" in view["readiness_label"]
    assert action["label"] == "开始了解"
    assert action["href"] == "/workbench?node_id=question"
