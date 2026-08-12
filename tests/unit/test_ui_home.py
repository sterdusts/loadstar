"""Pure response guards for the single-page learning-plan UI."""

import pytest

from learning_navigator.ui.pages.home import (
    _extract_learning_plan,
    _saved_plan_date,
    _saved_plan_stats,
    _saved_plan_title,
)


def _valid_suggestion() -> dict[str, object]:
    return {
        "raw_structured_output": {
            "space": {"title": "Python"},
            "nodes": [],
            "edges": [],
            "navigation": {"stages": []},
        }
    }


def test_extract_learning_plan_returns_validated_plan() -> None:
    suggestion = _valid_suggestion()

    assert _extract_learning_plan(suggestion) is suggestion["raw_structured_output"]


@pytest.mark.parametrize(
    ("suggestion", "message"),
    [
        (None, "响应格式无效"),
        ({}, "缺少计划内容"),
        ({"raw_structured_output": {"space": {}, "nodes": "invalid"}}, "缺少目标框架"),
        (
            {"raw_structured_output": {"space": {}, "nodes": [], "navigation": {}}},
            "缺少推进导航",
        ),
    ],
)
def test_extract_learning_plan_rejects_incomplete_response(
    suggestion: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _extract_learning_plan(suggestion)


def test_saved_plan_title_prefers_summary_and_falls_back_to_snapshot() -> None:
    assert _saved_plan_title({"title": "  数据分析路线  "}) == "数据分析路线"
    assert (
        _saved_plan_title({"raw_structured_output": {"space": {"title": "插画进阶"}}}) == "插画进阶"
    )
    assert _saved_plan_title({}) == "未命名目标框架"


def test_saved_plan_date_is_compact_and_tolerates_missing_values() -> None:
    assert _saved_plan_date("2026-08-01T18:45:30+08:00") == "2026-08-01 18:45"
    assert _saved_plan_date(None) == "保存时间未知"


def test_saved_plan_stats_uses_summary_counts_without_raw_payload() -> None:
    assert (
        _saved_plan_stats({"module_count": 4, "node_count": 16, "stage_count": 4})
        == "4 个模块 · 16 个节点 · 4 个阶段"
    )
    assert _saved_plan_stats({}) == "完整框架与推进导航"
