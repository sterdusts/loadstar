"""Pure presentation models shared by the NiceGUI pages.

The UI deliberately treats API payloads as untrusted presentation input.  These
helpers keep response-shape fallbacks and product wording out of page callbacks,
and are intentionally independent from NiceGUI so they can be tested cheaply.
"""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import Any
from unicodedata import category, normalize

from learning_navigator.application.dto.ai import semantic_profile_payload_or_none

DEFAULT_INTENT_MODE = "LEARN"
INTENT_MODES = frozenset({"LEARN", "UNDERSTAND", "DO"})
SEMANTIC_PROFILE_KEYS = frozenset(
    {
        "template_id",
        "node_label",
        "module_label",
        "route_label",
        "record_label",
        "evidence_label",
        "status_labels",
        "action_labels",
        "dimension_labels",
        "progress_levels",
    }
)
CANONICAL_STATUS_KEYS = frozenset(
    {"AVAILABLE", "BLOCKED", "MASTERED", "IN_PROGRESS", "NEEDS_REVIEW", "NOT_RELEVANT"}
)
ACTION_STATUS_KEYS = frozenset({"AVAILABLE", "IN_PROGRESS", "NEEDS_REVIEW"})
CANONICAL_DIMENSION_KEYS = frozenset(
    {"concept_understanding", "procedural_skill", "application_skill", "memory_strength"}
)
SEMANTIC_PROGRESS_SCORE_BANDS: dict[int, tuple[tuple[int, int], ...]] = {
    3: ((0, 0), (30, 55), (70, 100)),
    4: ((0, 0), (15, 40), (45, 70), (75, 100)),
    5: ((0, 0), (10, 30), (35, 55), (55, 80), (80, 100)),
    6: ((0, 0), (8, 25), (20, 45), (35, 65), (55, 85), (80, 100)),
}

# The product shell stays general (Next / Map / Progress), while the active
# goal restores the vocabulary users actually need for the job at hand.  Keep
# this presentation profile in one place so pages cannot drift into a mixture
# of learning, research and execution language.
INTENT_MODE_PROFILES: dict[str, dict[str, Any]] = {
    "LEARN": {
        "mode_label": "学习",
        "node_label": "知识点",
        "node_plural": "知识点",
        "module_label": "学习模块",
        "route_label": "学习路径",
        "record_label": "学习记录",
        "evidence_label": "掌握证据",
        "next_kicker": "现在先学",
        "map_next_kicker": "下一学习点",
        "detail_title": "知识点",
        "detail_subtitle": "查看学习目标、前置知识和掌握状态。",
        "workbench_title": "专注学习",
        "workbench_subtitle": "聚焦当前知识点，结束时留下学习记录。",
        "workbench_kicker": "本次学习",
        "workbench_select": "先选择要学习的知识点",
        "workbench_prompt": "这次学会了什么？",
        "workbench_result": "学习结果或发现",
        "workbench_placeholder": "例如：理解了核心概念；完成一道练习；仍有一个疑问",
        "finish_action": "完成学习并保存",
        "saved_notice": "学习记录已保存",
        "reason_heading": "为什么现在学",
        "objectives_heading": "学会后你将能够",
        "relations_heading": "知识衔接",
        "prerequisite_heading": "前置知识",
        "prerequisite_empty": "这是当前学习模块的起点",
        "unlock_heading": "后续知识",
        "unlock_empty": "这是当前学习分支的终点",
        "state_heading": "四维能力",
        "update_state": "更新掌握状态",
        "assessment_heading": "掌握评估",
        "assessment_note": "自评帮助定位掌握程度，不会直接解锁学习路径。",
        "activity_heading": "学习材料与记录",
        "dimension_labels": {
            "concept_understanding": "概念理解",
            "procedural_skill": "操作 / 计算能力",
            "application_skill": "应用与迁移",
            "memory_strength": "记忆保持",
        },
        "progress_levels": [
            {"min_score": 0, "label": "尚未掌握"},
            {"min_score": 20, "label": "开始理解"},
            {"min_score": 45, "label": "基本掌握"},
            {"min_score": 70, "label": "能够应用"},
            {"min_score": 90, "label": "熟练迁移"},
        ],
        "status_labels": {
            "AVAILABLE": "现在可学",
            "BLOCKED": "建议先补前置",
            "MASTERED": "已掌握",
            "IN_PROGRESS": "学习中",
            "NEEDS_REVIEW": "需要复习",
            "NOT_RELEVANT": "非当前学习路径",
        },
        "action_labels": {
            "AVAILABLE": "开始学习",
            "IN_PROGRESS": "继续学习",
            "NEEDS_REVIEW": "开始复习",
        },
        "priority_reasons": {
            "AVAILABLE": "前置知识已掌握",
            "IN_PROGRESS": "延续上次学习",
            "NEEDS_REVIEW": "记忆或能力需要巩固",
        },
    },
    "UNDERSTAND": {
        "mode_label": "理解",
        "node_label": "关键问题",
        "node_plural": "关键问题",
        "module_label": "认知模块",
        "route_label": "认知路径",
        "record_label": "探索记录",
        "evidence_label": "判断依据",
        "next_kicker": "现在先探索",
        "map_next_kicker": "下一关键问题",
        "detail_title": "关键问题",
        "detail_subtitle": "查看问题定义、前置认识和证据状态。",
        "workbench_title": "专注探索",
        "workbench_subtitle": "聚焦当前问题，结束时留下发现与依据。",
        "workbench_kicker": "本次探索",
        "workbench_select": "先选择要探索的关键问题",
        "workbench_prompt": "这次弄清了什么？",
        "workbench_result": "发现或判断",
        "workbench_placeholder": "例如：确认了关键机制；找到一条证据；仍有一个假设待核验",
        "finish_action": "完成探索并保存",
        "saved_notice": "探索记录已保存",
        "reason_heading": "为什么现在探索",
        "objectives_heading": "弄清后你将能够",
        "relations_heading": "问题关联",
        "prerequisite_heading": "前置认识",
        "prerequisite_empty": "这是当前认知分支的起点",
        "unlock_heading": "后续问题",
        "unlock_empty": "这是当前认知分支的边界",
        "state_heading": "理解与证据",
        "update_state": "更新理解状态",
        "assessment_heading": "理解评估",
        "assessment_note": "自评帮助定位理解程度，不会替代事实核验。",
        "activity_heading": "材料、依据与记录",
        "dimension_labels": {
            "concept_understanding": "概念理解",
            "procedural_skill": "关系与机制",
            "application_skill": "判断与迁移",
            "memory_strength": "认知保持",
        },
        "progress_levels": [
            {"min_score": 0, "label": "不知道"},
            {"min_score": 25, "label": "听说过"},
            {"min_score": 55, "label": "了解"},
            {"min_score": 85, "label": "非常了解"},
        ],
        "status_labels": {
            "AVAILABLE": "可探索",
            "BLOCKED": "建议先厘清前提",
            "MASTERED": "已理解",
            "IN_PROGRESS": "理解中",
            "NEEDS_REVIEW": "待核验",
            "NOT_RELEVANT": "非当前认知路径",
        },
        "action_labels": {
            "AVAILABLE": "开始探索",
            "IN_PROGRESS": "继续理解",
            "NEEDS_REVIEW": "重新核验",
        },
        "priority_reasons": {
            "AVAILABLE": "前置问题已厘清",
            "IN_PROGRESS": "延续已有认识",
            "NEEDS_REVIEW": "结论或依据需要核验",
        },
    },
    "DO": {
        "mode_label": "行动",
        "node_label": "行动项",
        "node_plural": "行动项",
        "module_label": "行动模块",
        "route_label": "行动路径",
        "record_label": "执行记录",
        "evidence_label": "交付证据",
        "next_kicker": "现在先做",
        "map_next_kicker": "下一行动项",
        "detail_title": "行动项",
        "detail_subtitle": "查看交付要求、前置条件和执行状态。",
        "workbench_title": "专注执行",
        "workbench_subtitle": "聚焦当前行动，结束时留下结果与证据。",
        "workbench_kicker": "本次执行",
        "workbench_select": "先选择要执行的行动项",
        "workbench_prompt": "这次完成了什么？",
        "workbench_result": "结果或交付物",
        "workbench_placeholder": "例如：完成第一版方案；确认两个约束；仍需等待外部数据",
        "finish_action": "完成执行并保存",
        "saved_notice": "执行记录已保存",
        "reason_heading": "为什么现在做",
        "objectives_heading": "完成后你将获得",
        "relations_heading": "行动衔接",
        "prerequisite_heading": "前置条件",
        "prerequisite_empty": "这是当前行动路径的起点",
        "unlock_heading": "后续行动",
        "unlock_empty": "这是当前行动路径的终点",
        "state_heading": "执行状态",
        "update_state": "更新执行状态",
        "assessment_heading": "结果评估",
        "assessment_note": "自评帮助定位执行进度，不会替代交付验收。",
        "activity_heading": "资源、交付与记录",
        "dimension_labels": {
            "concept_understanding": "目标与约束",
            "procedural_skill": "执行能力",
            "application_skill": "应用与交付",
            "memory_strength": "经验保持",
        },
        "progress_levels": [
            {"min_score": 0, "label": "尚未开始"},
            {"min_score": 25, "label": "已准备"},
            {"min_score": 50, "label": "进行中"},
            {"min_score": 80, "label": "已完成"},
        ],
        "status_labels": {
            "AVAILABLE": "可执行",
            "BLOCKED": "建议先处理前置",
            "MASTERED": "已完成",
            "IN_PROGRESS": "进行中",
            "NEEDS_REVIEW": "待检查",
            "NOT_RELEVANT": "非当前行动路径",
        },
        "action_labels": {
            "AVAILABLE": "开始执行",
            "IN_PROGRESS": "继续执行",
            "NEEDS_REVIEW": "检查结果",
        },
        "priority_reasons": {
            "AVAILABLE": "前置条件已满足",
            "IN_PROGRESS": "延续上次执行",
            "NEEDS_REVIEW": "结果需要检查或验收",
        },
    },
}

# Compatibility name: callers without a goal context must remain learning-first
# so old goals do not silently lose the semantics they were created with.
STATUS_LABELS = INTENT_MODE_PROFILES[DEFAULT_INTENT_MODE]["status_labels"]

STATUS_COLORS = {
    "AVAILABLE": "#2f9e67",
    "BLOCKED": "#d3634d",
    "MASTERED": "#4776bd",
    "IN_PROGRESS": "#d89a35",
    "NEEDS_REVIEW": "#8b5bb5",
    "NOT_RELEVANT": "#9aa69f",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, fallback: str = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _number(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int | float):
        return float(value)
    return fallback


def _percentage(value: Any) -> float:
    """Clamp the read-model percentage contract to a display-safe range."""

    number = _number(value)
    return round(max(0.0, min(100.0, number)), 1)


def normalize_intent_mode(value: Any) -> str:
    """Return a safe goal mode; legacy and malformed goals stay learning-first."""

    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in INTENT_MODES:
            return normalized
    return DEFAULT_INTENT_MODE


def intent_mode_for_goal(goal: Any) -> str:
    """Read mode only from the goal contract and protect old goal payloads."""

    return normalize_intent_mode(_dict(goal).get("intent_mode"))


def _semantic_label(value: Any) -> str | None:
    """Accept the bounded label contract without trusting transport validation."""

    if not isinstance(value, str):
        return None
    compatibility_normalized = normalize("NFKC", value)
    if any(category(character) in {"Cc", "Cf"} for character in compatibility_normalized):
        return None
    normalized = " ".join(compatibility_normalized.strip().split())
    if not normalized or len(normalized) > 32:
        return None
    if not normalized.isprintable() or "<" in normalized or ">" in normalized:
        return None
    return normalized


def _semantic_label_map(
    value: Any,
    *,
    exact_keys: frozenset[str] | None = None,
    allowed_keys: frozenset[str] | None = None,
    required_keys: frozenset[str] | None = None,
) -> dict[str, str] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    keys = frozenset(value)
    if exact_keys is not None and keys != exact_keys:
        return None
    if allowed_keys is not None and not keys.issubset(allowed_keys):
        return None
    if required_keys is not None and not required_keys.issubset(keys):
        return None
    labels = {key: _semantic_label(label) for key, label in value.items()}
    if any(label is None for label in labels.values()):
        return None
    return {key: str(label) for key, label in labels.items()}


def _semantic_progress_levels(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not 3 <= len(value) <= 6:
        return None
    levels: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"min_score", "label"}:
            return None
        score = item.get("min_score")
        label = _semantic_label(item.get("label"))
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            return None
        if label is None:
            return None
        levels.append({"min_score": score, "label": label})
    scores = [int(item["min_score"]) for item in levels]
    labels = [str(item["label"]).casefold() for item in levels]
    if scores[0] != 0 or any(current <= previous for previous, current in pairwise(scores)):
        return None
    if len(labels) != len(set(labels)):
        return None
    score_bands = SEMANTIC_PROGRESS_SCORE_BANDS[len(levels)]
    if any(
        not minimum <= int(level["min_score"]) <= maximum
        for level, (minimum, maximum) in zip(levels, score_bands, strict=True)
    ):
        return None
    return levels


def intent_profile(value: Any) -> dict[str, Any]:
    """Merge a validated goal vocabulary over its deterministic intent fallback.

    AI-authored vocabulary remains display-only: this function never changes a
    canonical status, score, route or action target.
    """

    goal = _dict(value)
    mode = intent_mode_for_goal(goal) if goal else normalize_intent_mode(value)
    baseline = INTENT_MODE_PROFILES[mode]
    merged = {
        **baseline,
        "status_labels": dict(baseline["status_labels"]),
        "action_labels": dict(baseline["action_labels"]),
        "priority_reasons": dict(baseline["priority_reasons"]),
        "dimension_labels": dict(baseline["dimension_labels"]),
        "progress_levels": [dict(item) for item in baseline["progress_levels"]],
    }
    raw_profile = goal.get("semantic_profile") if goal else None
    if not isinstance(raw_profile, dict) or frozenset(raw_profile) != SEMANTIC_PROFILE_KEYS:
        return merged
    raw_profile = semantic_profile_payload_or_none(raw_profile, mode)
    if raw_profile is None:
        return merged

    scalar_keys = (
        "node_label",
        "module_label",
        "route_label",
        "record_label",
        "evidence_label",
    )
    scalar_labels = {key: _semantic_label(raw_profile.get(key)) for key in scalar_keys}

    status_labels = _semantic_label_map(
        raw_profile.get("status_labels"),
        exact_keys=CANONICAL_STATUS_KEYS,
    )
    action_labels = _semantic_label_map(
        raw_profile.get("action_labels"),
        exact_keys=ACTION_STATUS_KEYS,
    )
    dimension_labels = _semantic_label_map(
        raw_profile.get("dimension_labels"),
        exact_keys=CANONICAL_DIMENSION_KEYS,
    )
    progress_levels = _semantic_progress_levels(raw_profile.get("progress_levels"))
    if (
        any(label is None for label in scalar_labels.values())
        or status_labels is None
        or action_labels is None
        or dimension_labels is None
        or progress_levels is None
    ):
        return merged

    merged.update({key: str(label) for key, label in scalar_labels.items()})
    merged["status_labels"] = status_labels
    merged["action_labels"] = action_labels
    merged["dimension_labels"] = dimension_labels
    merged["progress_levels"] = progress_levels
    return merged


def intent_progress_label(score: Any, context: Any = DEFAULT_INTENT_MODE) -> str:
    profile = intent_profile(context)
    normalized_score = max(0.0, min(100.0, _number(score)))
    level = profile["progress_levels"][0]
    for candidate in profile["progress_levels"]:
        if normalized_score < candidate["min_score"]:
            break
        level = candidate
    return str(level["label"])


def intent_status_label(status: Any, intent_mode: Any = DEFAULT_INTENT_MODE) -> str:
    normalized_status = _text(status, "NOT_RELEVANT")
    labels = intent_profile(intent_mode)["status_labels"]
    return str(labels.get(normalized_status, normalized_status.replace("_", " ")))


def intent_action_label(status: Any, intent_mode: Any = DEFAULT_INTENT_MODE) -> str:
    normalized_status = _text(status, "AVAILABLE")
    labels = intent_profile(intent_mode)["action_labels"]
    return str(labels.get(normalized_status, "查看下一步"))


def intent_priority_reason(status: Any, intent_mode: Any = DEFAULT_INTENT_MODE) -> str:
    normalized_status = _text(status, "AVAILABLE")
    reasons = intent_profile(intent_mode)["priority_reasons"]
    return str(reasons.get(normalized_status, "现在可以继续"))


def localize_route_reason(
    reason: Any,
    *,
    status: str = "",
    required_mastery_level: Any = None,
    unmet_titles: list[str] | None = None,
    intent_mode: Any = DEFAULT_INTENT_MODE,
) -> str:
    """Render deterministic route-engine explanations in learner-facing Chinese.

    Provider-authored or already localized explanations are kept verbatim.  The
    status argument lets a persisted route explanation follow the learner's
    latest evidence instead of describing the state at route creation time.
    """

    mode = normalize_intent_mode(intent_mode)
    raw = _text(
        reason,
        {
            "LEARN": "根据学习目标、前置知识与掌握证据安排。",
            "UNDERSTAND": "根据理解目标、前置问题与判断依据安排。",
            "DO": "根据行动目标、前置条件与交付证据安排。",
        }[mode],
    )
    engine_prefixes = (
        "All hard prerequisites are satisfied",
        "You have started this node",
        "The review date has arrived",
        "Scheduled review is due",
        "Complete unmet prerequisites first",
        "Required mastery is already demonstrated",
    )
    if not raw.startswith(engine_prefixes):
        return raw

    if status == "MASTERED" or raw.startswith("Required mastery is already demonstrated"):
        return {
            "LEARN": "已有掌握证据达到当前学习路径要求。",
            "UNDERSTAND": "已有依据支持当前理解要求。",
            "DO": "已有交付证据达到当前行动要求。",
        }[mode]
    if status == "NEEDS_REVIEW" or raw.startswith(
        ("The review date has arrived", "Scheduled review is due")
    ):
        return {
            "LEARN": "记忆或能力需要复习；完成一次复习验证后再继续。",
            "UNDERSTAND": "结论或依据需要重新核验；确认后再继续。",
            "DO": "执行结果需要检查；完成验收后再继续。",
        }[mode]
    if status == "IN_PROGRESS" or raw.startswith("You have started this node"):
        return {
            "LEARN": "已经开始学习；完成一次练习或产出即可继续。",
            "UNDERSTAND": "已经开始探索；补充一条发现或依据即可继续。",
            "DO": "已经开始执行；完成一次可检查的交付即可继续。",
        }[mode]
    if status == "BLOCKED" or raw.startswith("Complete unmet prerequisites first"):
        names = [name for name in (unmet_titles or []) if name]
        if not names and ":" in raw:
            embedded = raw.split(":", 1)[1].split(";", 1)[0].strip()
            names = [embedded] if embedded else []
        prerequisite_text = (
            "、".join(names)
            if names
            else {
                "LEARN": "尚未掌握的前置知识",
                "UNDERSTAND": "尚未厘清的前置问题",
                "DO": "尚未完成的前置条件",
            }[mode]
        )
        if mode == "LEARN":
            return f"建议先掌握：{prerequisite_text}；也可以直接开始，过程中再补齐。"
        if mode == "UNDERSTAND":
            return f"建议先弄清：{prerequisite_text}；也可以直接探索，过程中再补齐。"
        return f"建议先完成：{prerequisite_text}；也可以直接执行，并自行承担依赖风险。"
    return {
        "LEARN": "前置知识已掌握，可以开始学习。",
        "UNDERSTAND": "前置问题已厘清，可以开始探索。",
        "DO": "前置条件已满足，可以开始执行。",
    }[mode]


def _saved_plan_title(item: dict[str, Any]) -> str:
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    raw = item.get("raw_structured_output")
    if isinstance(raw, dict):
        space = raw.get("space")
        if isinstance(space, dict):
            space_title = space.get("title")
            if isinstance(space_title, str) and space_title.strip():
                return space_title.strip()
    return "未命名目标框架"


def _saved_plan_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "保存时间未知"
    return text.replace("T", " ")[:16]


def _saved_plan_stats(item: dict[str, Any]) -> str:
    labels = (
        ("module_count", "模块"),
        ("node_count", "节点"),
        ("stage_count", "阶段"),
    )
    parts = [f"{item[key]} 个{label}" for key, label in labels if isinstance(item.get(key), int)]
    return " · ".join(parts) if parts else "完整框架与推进导航"


def extract_learning_plan(suggestion: Any) -> dict[str, Any]:
    """Validate the minimum legacy-plan shape needed by the onboarding preview."""

    if not isinstance(suggestion, dict):
        raise ValueError("响应格式无效")
    plan = suggestion.get("raw_structured_output")
    if not isinstance(plan, dict):
        raise ValueError("缺少计划内容")
    if not isinstance(plan.get("space"), dict) or not isinstance(plan.get("nodes"), list):
        raise ValueError("缺少目标框架")
    navigation = plan.get("navigation")
    if not isinstance(navigation, dict) or not isinstance(navigation.get("stages"), list):
        raise ValueError("缺少推进导航")
    return plan


def uses_mock_provider(status: dict[str, Any]) -> bool:
    provider = status.get("provider") or status.get("active_provider") or status.get("mode")
    return str(provider).casefold() == "mock" or status.get("is_mock") is True


def build_dashboard_view_model(payload: Any) -> dict[str, Any]:
    """Turn the dashboard contract into one learner-facing navigation snapshot."""

    dashboard = _dict(payload)
    goal = _dict(dashboard.get("current_goal"))
    intent_mode = intent_mode_for_goal(goal)
    raw_route = [item for item in _list(dashboard.get("route_overview")) if isinstance(item, dict)]
    title_by_id = {
        str(item.get("node_id")): _text(item.get("title"), "未命名节点")
        for item in raw_route
        if item.get("node_id") is not None
    }

    def route_item(item: Any) -> dict[str, Any] | None:
        raw = _dict(item)
        node_id = _text(raw.get("node_id"))
        if not node_id:
            return None
        status = _text(raw.get("status"), "NOT_RELEVANT")
        raw_score = raw.get("progress_score")
        progress_score = (
            int(raw_score)
            if isinstance(raw_score, int | float)
            and not isinstance(raw_score, bool)
            and 0 <= raw_score <= 10
            else None
        )
        display_progress_state = _text(raw.get("display_progress_state")).upper()
        if display_progress_state not in {"COMPLETED", "IN_PROGRESS", "NOT_STARTED"}:
            if progress_score is not None:
                if progress_score <= 0:
                    display_progress_state = "NOT_STARTED"
                else:
                    display_progress_state = "COMPLETED" if progress_score >= 10 else "IN_PROGRESS"
            elif status == "MASTERED":
                display_progress_state = "COMPLETED"
            elif status in {"IN_PROGRESS", "NEEDS_REVIEW"}:
                display_progress_state = "IN_PROGRESS"
            else:
                display_progress_state = "NOT_STARTED"
        unresolved = [str(value) for value in _list(raw.get("unmet_prerequisites"))]
        unlock_ids = [str(value) for value in _list(raw.get("unlocks"))]
        unmet_titles = [title_by_id.get(value, value) for value in unresolved]
        return {
            "node_id": node_id,
            "title": _text(raw.get("title"), title_by_id.get(node_id, "未命名节点")),
            "status": status,
            "status_label": intent_status_label(status, goal),
            "reason": localize_route_reason(
                raw.get("reason"),
                status=status,
                required_mastery_level=raw.get("required_mastery_level"),
                unmet_titles=unmet_titles,
                intent_mode=intent_mode,
            ),
            "unmet_prerequisites": unresolved,
            "unmet_titles": unmet_titles,
            "unlocks": unlock_ids,
            "unlock_titles": [title_by_id.get(value, value) for value in unlock_ids],
            "required_mastery_level": raw.get("required_mastery_level"),
            "progress_score": progress_score,
            "progress_checked_in_at": _text(raw.get("progress_checked_in_at")) or None,
            "display_progress_state": display_progress_state,
        }

    route = [prepared for item in raw_route if (prepared := route_item(item)) is not None]
    next_step = route_item(dashboard.get("next_step"))
    current_position = route_item(dashboard.get("current_position"))
    blocked = [
        prepared
        for item in _list(dashboard.get("blocked"))
        if (prepared := route_item(item)) is not None
    ]
    if not blocked:
        blocked = [item for item in route if item["status"] == "BLOCKED"]

    completed = sum(item["display_progress_state"] == "COMPLETED" for item in route)
    in_progress = sum(item["display_progress_state"] == "IN_PROGRESS" for item in route)
    reviewed = sum(item["status"] == "NEEDS_REVIEW" for item in route)
    total = len(route)
    progress_points = sum(
        item["progress_score"]
        if item["progress_score"] is not None
        else 10
        if item["display_progress_state"] == "COMPLETED"
        else 0
        for item in route
    )
    progress = round(progress_points / (total * 10) * 100) if total else 0
    space_id = _text(goal.get("space_id"))
    recent_sessions = [
        item for item in _list(dashboard.get("recent_sessions")) if isinstance(item, dict)
    ]
    recent_check_ins = [
        {
            "id": _text(item.get("id")),
            "node_id": _text(item.get("node_id")),
            "title": _text(item.get("title"), title_by_id.get(_text(item.get("node_id")), "")),
            "score": item.get("score"),
            "note": item.get("note"),
            "checked_in_at": _text(item.get("checked_in_at")),
            "check_in_date": _text(item.get("check_in_date")),
            "display_progress_state": _text(item.get("display_progress_state")),
        }
        for item in _list(dashboard.get("recent_check_ins"))
        if isinstance(item, dict)
    ]

    return {
        "has_goal": bool(goal),
        "goal": goal,
        "goal_title": _text(
            goal.get("title"),
            {
                "LEARN": "当前学习目标",
                "UNDERSTAND": "当前理解目标",
                "DO": "当前行动目标",
            }[intent_mode],
        ),
        "intent_mode": intent_mode,
        "intent_copy": intent_profile(goal),
        "space_id": space_id,
        "target_node_id": _text(goal.get("target_node_id")),
        "current_position": current_position,
        "next_step": next_step,
        "blocked": blocked,
        "route": route,
        "completed_count": completed,
        "in_progress_count": in_progress,
        "review_count": reviewed,
        "total_count": total,
        "progress_percent": progress,
        "recent_sessions": recent_sessions,
        "recent_check_ins": recent_check_ins,
        "map_href": f"/maps/{space_id}" if space_id else "/map",
    }


def build_parallel_dashboard_view_model(
    payload: Any,
    *,
    focused_goal_id: str | None = None,
) -> dict[str, Any]:
    """Normalize every active goal without mixing their routes or progress."""

    dashboard = _dict(payload)
    raw_overviews = [
        item for item in _list(dashboard.get("goal_overviews")) if isinstance(item, dict)
    ]
    if not raw_overviews and _dict(dashboard.get("current_goal")):
        raw_overviews = [
            {
                "goal": dashboard.get("current_goal"),
                "is_current": True,
                "current_position": dashboard.get("current_position"),
                "next_step": dashboard.get("next_step"),
                "blocked": dashboard.get("blocked"),
                "route_overview": dashboard.get("route_overview"),
                "recent_check_ins": dashboard.get("recent_check_ins"),
            }
        ]

    goals: list[dict[str, Any]] = []
    seen_goal_ids: set[str] = set()
    for overview in raw_overviews:
        goal = _dict(overview.get("goal"))
        goal_id = _text(goal.get("id"))
        # The dashboard is a transport projection, not the source of truth.  A
        # stale cache must never resurrect a project that the user moved to the
        # recycle bin, and duplicate rows must not create conflicting cards.
        if (
            not goal_id
            or _text(goal.get("status")).upper() == "ARCHIVED"
            or goal_id in seen_goal_ids
        ):
            continue
        seen_goal_ids.add(goal_id)
        single = build_dashboard_view_model(
            {
                "current_goal": goal,
                "current_position": overview.get("current_position"),
                "next_step": overview.get("next_step"),
                "blocked": overview.get("blocked"),
                "route_overview": overview.get("route_overview"),
                "recent_check_ins": overview.get("recent_check_ins"),
                "recent_sessions": [],
            }
        )
        goals.append(
            {
                **single,
                "goal_id": goal_id,
                "is_focused": False,
                "is_current": overview.get("is_current") is True,
            }
        )

    recent_sessions = [
        item for item in _list(dashboard.get("recent_sessions")) if isinstance(item, dict)
    ]
    if not goals:
        return {
            "has_goals": False,
            "goals": [],
            "focused_goal_id": None,
            "recent_sessions": recent_sessions,
        }

    available_ids = {item["goal_id"] for item in goals}
    current_goal_id = _text(dashboard.get("current_goal_id")) or _text(
        _dict(dashboard.get("current_goal")).get("id")
    )
    selected_id = (
        focused_goal_id
        if focused_goal_id in available_ids
        else current_goal_id
        if current_goal_id in available_ids
        else next(
            (item["goal_id"] for item in goals if item["is_current"]),
            goals[0]["goal_id"],
        )
    )
    for item in goals:
        item["is_focused"] = item["goal_id"] == selected_id

    return {
        "has_goals": True,
        "goals": goals,
        "focused_goal_id": selected_id,
        "recent_sessions": recent_sessions,
    }


def _session_minutes(session: dict[str, Any]) -> int:
    explicit = session.get("duration_minutes")
    if isinstance(explicit, int | float) and not isinstance(explicit, bool):
        return max(0, round(explicit))
    try:
        start = datetime.fromisoformat(str(session.get("started_at")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(session.get("ended_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0
    return max(0, round((end - start).total_seconds() / 60))


def build_growth_view_model(growth_payload: Any, sessions_payload: Any) -> dict[str, Any]:
    """Build growth metrics and a readable, newest-first learning timeline."""

    growth = _dict(growth_payload)
    summary = _dict(growth.get("summary"))
    raw_series = [item for item in _list(growth.get("series")) if isinstance(item, dict)]
    series = [
        {
            "date": _text(item.get("date"), "未知日期"),
            "coverage_percent": _percentage(item.get("coverage_rate")),
            "learning_minutes": round(
                _number(item.get("learning_minutes", item.get("total_learning_minutes")))
            ),
            "sessions": round(_number(item.get("session_count", item.get("total_sessions")))),
        }
        for item in raw_series
    ]
    series.sort(key=lambda item: str(item["date"]))

    sessions_container = _dict(sessions_payload)
    source_sessions = (
        _list(sessions_container.get("items")) if sessions_container else _list(sessions_payload)
    )
    timeline: list[dict[str, Any]] = []
    for item in source_sessions:
        if not isinstance(item, dict):
            continue
        node = _dict(item.get("node"))
        started_at = _text(item.get("started_at"))
        timeline.append(
            {
                "id": _text(item.get("id")),
                "node_id": _text(node.get("id"), _text(item.get("node_id"))),
                "space_id": _text(node.get("space_id")),
                "node_title": _text(node.get("title"), "未命名节点"),
                "started_at": started_at,
                "display_time": started_at.replace("T", " ")[:16] if started_at else "时间未知",
                "minutes": _session_minutes(item),
                "note": _text(item.get("note"), "本次未填写记录"),
                "difficulties": _text(item.get("difficulties")),
                "next_step": _text(item.get("next_step")),
                "evidence_count": round(_number(item.get("evidence_count"))),
            }
        )
    timeline.sort(key=lambda item: item["started_at"], reverse=True)

    return {
        "summary": {
            "tracked_nodes": round(_number(summary.get("tracked_nodes"))),
            "mastered_nodes": round(_number(summary.get("mastered_nodes"))),
            "coverage_percent": _percentage(summary.get("coverage_rate")),
            "mastery_percent": _percentage(summary.get("average_mastery_score")),
            "total_sessions": round(_number(summary.get("total_sessions"))),
            "total_evidence": round(_number(summary.get("total_evidence"))),
            "total_learning_minutes": round(_number(summary.get("total_learning_minutes"))),
        },
        "series": series,
        "timeline": timeline,
        "total": round(_number(sessions_container.get("total"), len(timeline))),
    }


# Backwards-compatible names used by existing UI tests and third-party imports.
_extract_learning_plan = extract_learning_plan
