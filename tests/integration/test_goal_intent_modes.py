"""Goal intent is goal-local, persistent, and backward compatible."""

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from learning_navigator.application.dto.ai import LearningPlanDraft
from learning_navigator.domain.enums import GoalIntent, ReviewStatus, SuggestionType
from learning_navigator.infrastructure.database.models import AISuggestionModel, UserModel


def _legacy_plan_payload() -> dict[str, Any]:
    """Represent a saved draft created before intent_mode existed."""

    return {
        "space": {
            "title": "Legacy subject",
            "description": "",
            "target_audience": "",
            "scope_included": [],
            "scope_excluded": [],
        },
        "nodes": [
            {
                "temp_id": "target",
                "title": "Legacy target",
                "description": "",
                "node_type": "CONCEPT",
                "difficulty": 1,
                "learning_objectives": [],
                "source_basis": [],
                "confidence": 1.0,
            }
        ],
        "edges": [],
        "warnings": [],
        "uncertain_items": [],
        "navigation": {
            "goal_title": "Learn the legacy target",
            "target_temp_id": "target",
            "target_mastery_level": 3,
            "success_definition": "Explain and apply the target.",
            "stages": [
                {
                    "sequence": 1,
                    "title": "Learn",
                    "objective": "Understand the target.",
                    "node_temp_ids": ["target"],
                    "completion_criteria": ["Explain it accurately"],
                }
            ],
        },
    }


def _semantic_profile(prefix: str, intent_mode: str = "LEARN") -> dict[str, Any]:
    functional = {
        "LEARN": {
            "template_id": "LEARN_MASTERY_V1",
            "status_labels": {
                "AVAILABLE": "现在可学",
                "BLOCKED": "前置未满足",
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
            "progress_levels": [
                {"min_score": 0, "label": "尚未掌握"},
                {"min_score": 20, "label": "开始理解"},
                {"min_score": 45, "label": "基本掌握"},
                {"min_score": 70, "label": "能够应用"},
                {"min_score": 90, "label": "熟练迁移"},
            ],
        },
        "UNDERSTAND": {
            "template_id": "UNDERSTAND_FAMILIARITY_V1",
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
            "progress_levels": [
                {"min_score": 0, "label": "不知道"},
                {"min_score": 25, "label": "听说过"},
                {"min_score": 55, "label": "了解"},
                {"min_score": 85, "label": "非常了解"},
            ],
        },
        "DO": {
            "template_id": "DO_DELIVERY_V1",
            "status_labels": {
                "AVAILABLE": "可以执行",
                "BLOCKED": "条件未满足",
                "MASTERED": "已完成",
                "IN_PROGRESS": "进行中",
                "NEEDS_REVIEW": "待复核",
                "NOT_RELEVANT": "暂不执行",
            },
            "action_labels": {
                "AVAILABLE": "开始执行",
                "IN_PROGRESS": "继续执行",
                "NEEDS_REVIEW": "复核结果",
            },
            "progress_levels": [
                {"min_score": 0, "label": "未启动"},
                {"min_score": 20, "label": "已准备"},
                {"min_score": 45, "label": "进行中"},
                {"min_score": 75, "label": "基本完成"},
                {"min_score": 95, "label": "已交付"},
            ],
        },
    }[intent_mode]
    return {
        "template_id": functional["template_id"],
        "node_label": f"{prefix} item",
        "module_label": f"{prefix} group",
        "route_label": f"{prefix} route",
        "record_label": f"{prefix} record",
        "evidence_label": f"{prefix} evidence",
        "status_labels": functional["status_labels"],
        "action_labels": functional["action_labels"],
        "dimension_labels": {
            "concept_understanding": f"{prefix} concepts",
            "procedural_skill": f"{prefix} procedure",
            "application_skill": f"{prefix} application",
            "memory_strength": f"{prefix} retention",
        },
        "progress_levels": functional["progress_levels"],
    }


def _space_and_target(client: TestClient) -> tuple[str, str]:
    space_response = client.post("/api/spaces", json={"title": "Goal intent workspace"})
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]
    node_response = client.post(
        f"/api/spaces/{space_id}/nodes",
        json={"title": "Target", "node_type": "CONCEPT"},
    )
    assert node_response.status_code == 201, node_response.text
    return space_id, node_response.json()["id"]


def test_legacy_learning_plan_draft_defaults_to_learn() -> None:
    draft = LearningPlanDraft.model_validate(_legacy_plan_payload())

    assert draft.navigation.intent_mode is GoalIntent.LEARN
    assert draft.navigation.semantic_profile is None
    assert draft.model_dump(mode="json")["navigation"]["intent_mode"] == "LEARN"


@pytest.mark.parametrize(
    ("intent_mode", "prefix"),
    [
        ("LEARN", "study"),
        ("UNDERSTAND", "research"),
        ("DO", "delivery"),
    ],
)
def test_goal_semantic_profile_accepts_constrained_scene_specific_copy(
    intent_mode: str,
    prefix: str,
) -> None:
    payload = _legacy_plan_payload()
    payload["navigation"]["intent_mode"] = intent_mode
    payload["navigation"]["semantic_profile"] = _semantic_profile(prefix, intent_mode)

    draft = LearningPlanDraft.model_validate(payload)

    profile = draft.navigation.semantic_profile
    assert profile is not None
    assert (
        profile.template_id.value
        == {
            "LEARN": "LEARN_MASTERY_V1",
            "UNDERSTAND": "UNDERSTAND_FAMILIARITY_V1",
            "DO": "DO_DELIVERY_V1",
        }[intent_mode]
    )
    assert profile.node_label == f"{prefix} item"
    assert set(profile.status_labels.model_dump()) == {
        "AVAILABLE",
        "BLOCKED",
        "MASTERED",
        "IN_PROGRESS",
        "NEEDS_REVIEW",
        "NOT_RELEVANT",
    }
    assert [item.min_score for item in profile.progress_levels] == {
        "LEARN": [0, 20, 45, 70, 90],
        "UNDERSTAND": [0, 25, 55, 85],
        "DO": [0, 20, 45, 75, 95],
    }[intent_mode]


@pytest.mark.parametrize(
    ("field", "key", "value"),
    [
        ("status_labels", "AVAILABLE", "Do not start"),
        ("status_labels", "BLOCKED", "Ready now"),
        ("status_labels", "MASTERED", "Not learned"),
        ("action_labels", "AVAILABLE", "Do not start"),
        ("action_labels", "AVAILABLE", "Mark complete"),
        ("action_labels", "NEEDS_REVIEW", "No review needed"),
        ("status_labels", "MASTERED", "never mastered"),
        ("status_labels", "MASTERED", "not—mastered"),
        ("status_labels", "MASTERED", "绝非已掌握"),
        ("status_labels", "AVAILABLE", "not currently available"),
        ("action_labels", "AVAILABLE", "never start"),
        ("action_labels", "NEEDS_REVIEW", "never review"),
    ],
)
def test_goal_semantic_profile_rejects_inverted_functional_copy(
    field: str,
    key: str,
    value: str,
) -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile[field][key] = value
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_compressed_expert_scale() -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile["progress_levels"] = [
        {"min_score": 0, "label": "Expert"},
        {"min_score": 1, "label": "Master"},
        {"min_score": 2, "label": "Deep understanding"},
    ]
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_reordered_or_negated_controlled_scale() -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile["progress_levels"] = [
        {"min_score": 0, "label": "尚未掌握"},
        {"min_score": 20, "label": "Expert already"},
        {"min_score": 45, "label": "Completely unknown"},
        {"min_score": 70, "label": "Lost all progress"},
        {"min_score": 90, "label": "never mastered"},
    ]
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_cross_intent_functional_vocabulary() -> None:
    payload = _legacy_plan_payload()
    payload["navigation"]["intent_mode"] = "DO"
    payload["navigation"]["semantic_profile"] = _semantic_profile("study", "LEARN")

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_unknown_template_id() -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile["template_id"] = "LEARN_UNKNOWN_V9"
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_template_id_with_other_template_fields() -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile["template_id"] = "LEARN_PRACTICE_V1"
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


def test_goal_semantic_profile_rejects_mixed_functional_template_fields() -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("study")
    profile["status_labels"]["AVAILABLE"] = "可以学习"
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda profile: profile.__setitem__("unexpected_copy", "not allowed"),
        lambda profile: profile.__setitem__("node_label", "   "),
        lambda profile: profile.__setitem__("node_label", "bad\u200bcopy"),
        lambda profile: profile.__setitem__("route_label", "x" * 33),
        lambda profile: profile["status_labels"].__setitem__("READY", "ready"),
        lambda profile: profile["status_labels"].pop("BLOCKED"),
        lambda profile: profile["action_labels"].pop("AVAILABLE"),
        lambda profile: profile["dimension_labels"].__setitem__("confidence", "Confidence"),
        lambda profile: profile["progress_levels"][0].__setitem__("min_score", 1),
        lambda profile: profile["progress_levels"][1].__setitem__("min_score", 0),
        lambda profile: profile["progress_levels"][1].__setitem__("min_score", 101),
        lambda profile: profile["progress_levels"][1].__setitem__("label", "\n"),
        lambda profile: profile["progress_levels"][1].__setitem__(
            "label", profile["progress_levels"][0]["label"].upper()
        ),
    ],
)
def test_goal_semantic_profile_rejects_unbounded_or_ambiguous_copy(
    mutate: Any,
) -> None:
    payload = _legacy_plan_payload()
    profile = _semantic_profile("bounded")
    mutate(profile)
    payload["navigation"]["semantic_profile"] = profile

    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(payload)


@pytest.mark.integration
def test_saved_legacy_draft_summary_and_activation_default_to_learn(
    client: TestClient,
) -> None:
    # Establish the local user, then insert the shape persisted by the previous release.
    assert client.get("/api/dashboard").status_code == 200
    with client.app.state.session_factory() as session:
        user_id = session.scalar(select(UserModel.id))
        assert isinstance(user_id, str)
        suggestion = AISuggestionModel(
            user_id=user_id,
            space_id=None,
            suggestion_type=SuggestionType.LEARNING_PLAN.value,
            target_type="LearningPlan",
            target_id=None,
            provider="mock",
            model="legacy-model",
            prompt_version="learning-plan-prompt-v3",
            raw_structured_output=_legacy_plan_payload(),
            proposed_changes={},
            reason="Legacy saved draft",
            confidence=1.0,
            sources=[],
            review_status=ReviewStatus.PENDING.value,
        )
        session.add(suggestion)
        session.commit()
        plan_id = suggestion.id

    detail_response = client.get(f"/api/learning-plans/{plan_id}")
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["intent_mode"] == "LEARN"

    activation_response = client.post(f"/api/learning-plans/{plan_id}/activate")
    assert activation_response.status_code == 200, activation_response.text
    activation = activation_response.json()
    assert activation["goal"]["intent_mode"] == "LEARN"
    assert activation["activation"]["intent_mode"] == "LEARN"


@pytest.mark.integration
def test_invalid_saved_display_profile_falls_back_without_blocking_activation(
    client: TestClient,
) -> None:
    assert client.get("/api/dashboard").status_code == 200
    payload = _legacy_plan_payload()
    payload["navigation"]["semantic_profile"] = _semantic_profile("study")
    payload["navigation"]["semantic_profile"]["status_labels"].update(
        {
            "AVAILABLE": "Do not start",
            "BLOCKED": "Ready now",
            "MASTERED": "Not learned",
        }
    )
    with client.app.state.session_factory() as session:
        user_id = session.scalar(select(UserModel.id))
        assert isinstance(user_id, str)
        suggestion = AISuggestionModel(
            user_id=user_id,
            space_id=None,
            suggestion_type=SuggestionType.LEARNING_PLAN.value,
            target_type="LearningPlan",
            target_id=None,
            provider="remote",
            model="legacy-profile-model",
            prompt_version="goal-framework-prompt-v1",
            raw_structured_output=payload,
            proposed_changes={},
            reason="Valid map with unsafe optional display copy",
            confidence=1.0,
            sources=[],
            review_status=ReviewStatus.PENDING.value,
        )
        session.add(suggestion)
        session.commit()
        plan_id = suggestion.id

    detail = client.get(f"/api/learning-plans/{plan_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["semantic_profile"] is None

    activation_response = client.post(f"/api/learning-plans/{plan_id}/activate")
    assert activation_response.status_code == 200, activation_response.text
    activation = activation_response.json()
    assert activation["goal"]["semantic_profile"] is None
    assert activation["activation"]["semantic_profile"] is None


@pytest.mark.integration
def test_goal_api_rejects_inverted_client_supplied_display_profile(
    client: TestClient,
) -> None:
    space_id, target_node_id = _space_and_target(client)
    profile = _semantic_profile("study")
    profile["status_labels"]["MASTERED"] = "Not learned"

    response = client.post(
        "/api/goals",
        json={
            "space_id": space_id,
            "target_node_id": target_node_id,
            "title": "Unsafe labels",
            "intent_mode": "LEARN",
            "semantic_profile": profile,
        },
    )

    assert response.status_code == 422


@pytest.mark.integration
def test_all_goal_intents_persist_and_dashboard_exposes_goal_local_modes(
    client: TestClient,
) -> None:
    space_id, target_node_id = _space_and_target(client)
    created: list[dict[str, Any]] = []
    payloads = [
        {
            "title": "Learn it",
            "semantic_profile": _semantic_profile("study"),
        },  # Old clients may still omit intent_mode.
        {
            "title": "Understand it",
            "intent_mode": "UNDERSTAND",
            "semantic_profile": _semantic_profile("research", "UNDERSTAND"),
        },
        {
            "title": "Do it",
            "intent_mode": "DO",
            "semantic_profile": _semantic_profile("delivery", "DO"),
        },
    ]
    for payload in payloads:
        response = client.post(
            "/api/goals",
            json={"space_id": space_id, "target_node_id": target_node_id, **payload},
        )
        assert response.status_code == 201, response.text
        created.append(response.json())

    assert [goal["intent_mode"] for goal in created] == ["LEARN", "UNDERSTAND", "DO"]
    assert [goal["semantic_profile"]["node_label"] for goal in created] == [
        "study item",
        "research item",
        "delivery item",
    ]
    assert [goal["semantic_profile"]["template_id"] for goal in created] == [
        "LEARN_MASTERY_V1",
        "UNDERSTAND_FAMILIARITY_V1",
        "DO_DELIVERY_V1",
    ]

    dashboard_response = client.get("/api/dashboard")
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard = dashboard_response.json()
    overview_modes = {
        item["goal"]["id"]: (item["goal"]["intent_mode"], item["intent_mode"])
        for item in dashboard["goal_overviews"]
    }
    assert overview_modes == {
        goal["id"]: (goal["intent_mode"], goal["intent_mode"]) for goal in created
    }
    assert dashboard["intent_mode"] == dashboard["current_goal"]["intent_mode"]
    assert dashboard["semantic_profile"] == dashboard["current_goal"]["semantic_profile"]
    assert {
        item["goal"]["id"]: item["semantic_profile"] for item in dashboard["goal_overviews"]
    } == {goal["id"]: goal["semantic_profile"] for goal in created}


@pytest.mark.integration
def test_accepted_plan_intent_is_used_by_summary_activation_and_dashboard(
    client: TestClient,
) -> None:
    generated_response = client.post(
        "/api/ai/learning-plans/generate",
        json={
            "topic": "Quantum computing landscape",
            "requirements": (
                "Build a verified whole-field understanding and identify open questions"
            ),
        },
    )
    assert generated_response.status_code == 201, generated_response.text
    generated = generated_response.json()
    edited_draft = deepcopy(generated["raw_structured_output"])
    edited_draft["navigation"]["intent_mode"] = "UNDERSTAND"
    edited_draft["navigation"]["semantic_profile"] = _semantic_profile("quantum", "UNDERSTAND")

    review_response = client.post(
        f"/api/ai/suggestions/{generated['id']}/review",
        json={"action": "modify_accept", "edited_draft": edited_draft},
    )
    assert review_response.status_code == 200, review_response.text

    detail_response = client.get(f"/api/learning-plans/{generated['id']}")
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["intent_mode"] == "UNDERSTAND"
    assert detail_response.json()["semantic_profile"]["template_id"] == "UNDERSTAND_FAMILIARITY_V1"
    assert detail_response.json()["semantic_profile"]["node_label"] == "quantum item"
    summaries = client.get("/api/learning-plans")
    assert summaries.status_code == 200, summaries.text
    assert summaries.json()[0]["intent_mode"] == "UNDERSTAND"

    activation_response = client.post(f"/api/learning-plans/{generated['id']}/activate")
    assert activation_response.status_code == 200, activation_response.text
    activation = activation_response.json()
    assert activation["goal"]["intent_mode"] == "UNDERSTAND"
    assert activation["goal"]["semantic_profile"]["node_label"] == "quantum item"
    assert activation["activation"]["intent_mode"] == "UNDERSTAND"
    assert activation["activation"]["semantic_profile"]["node_label"] == "quantum item"

    dashboard_response = client.get("/api/dashboard")
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard = dashboard_response.json()
    assert dashboard["intent_mode"] == "UNDERSTAND"
    assert dashboard["current_goal"]["intent_mode"] == "UNDERSTAND"
    assert dashboard["semantic_profile"]["node_label"] == "quantum item"
    assert dashboard["goal_overviews"][0]["intent_mode"] == "UNDERSTAND"
