"""Unit tests for strict AI draft schemas and the deterministic mock provider."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from learning_navigator.application.dto.ai import (
    AnalyzedKnowledgeMapDraft,
    DraftConflict,
    KnowledgeEdgeDraft,
    KnowledgeMapDraft,
    KnowledgeNodeDraft,
    KnowledgeSpaceDraft,
    StrictModel,
    analyze_draft,
)
from learning_navigator.domain.enums import NodeType, RelationType
from learning_navigator.infrastructure.ai.providers import MockProvider


def _node(temp_id: str, title: str | None = None) -> dict[str, object]:
    return {"temp_id": temp_id, "title": title or temp_id.title()}


def _edge(
    source: str,
    target: str,
    *,
    relation_type: str = "PREREQUISITE",
    required_mastery_level: int = 3,
) -> dict[str, object]:
    return {
        "source_temp_id": source,
        "target_temp_id": target,
        "relation_type": relation_type,
        "required_mastery_level": required_mastery_level,
    }


def _map_payload() -> dict[str, object]:
    return {
        "space": {"title": "Test space"},
        "nodes": [_node("a"), _node("b")],
        "edges": [_edge("a", "b")],
    }


@pytest.mark.parametrize(
    ("model_type", "valid_payload"),
    [
        (StrictModel, {}),
        (KnowledgeSpaceDraft, {"title": "Test space"}),
        (KnowledgeNodeDraft, _node("a")),
        (KnowledgeEdgeDraft, _edge("a", "b")),
        (KnowledgeMapDraft, _map_payload()),
        (
            DraftConflict,
            {"edge": _edge("a", "b"), "reason": "Candidate would create a cycle"},
        ),
        (
            AnalyzedKnowledgeMapDraft,
            {"draft": _map_payload(), "accepted_edges": [], "conflicts": []},
        ),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_all_ai_models_reject_extra_fields(
    model_type: type[BaseModel], valid_payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        model_type.model_validate({**valid_payload, "unexpected": "must be rejected"})

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ("unexpected",)
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("source", "target", "missing_id"),
    [("missing-source", "a", "missing-source"), ("a", "missing-target", "missing-target")],
)
def test_map_rejects_dangling_temp_id_references(source: str, target: str, missing_id: str) -> None:
    payload = _map_payload()
    payload["edges"] = [_edge(source, target)]

    with pytest.raises(ValidationError) as exc_info:
        KnowledgeMapDraft.model_validate(payload)

    error = str(exc_info.value)
    assert "edge references unknown temp_id values" in error
    assert missing_id in error


def test_map_rejects_duplicate_node_temp_ids() -> None:
    payload = _map_payload()
    payload["nodes"] = [_node("duplicate", "First"), _node("duplicate", "Second")]
    payload["edges"] = []

    with pytest.raises(ValidationError, match="node temp_id values must be unique"):
        KnowledgeMapDraft.model_validate(payload)


def test_map_rejects_duplicate_edge_proposals() -> None:
    payload = _map_payload()
    payload["edges"] = [
        _edge("a", "b"),
        {**_edge("a", "b"), "reason": "Different prose does not make a distinct edge"},
    ]

    with pytest.raises(ValidationError, match="duplicate edge proposal"):
        KnowledgeMapDraft.model_validate(payload)


def test_edge_rejects_self_reference() -> None:
    with pytest.raises(ValidationError, match="self-referential edges are not allowed"):
        KnowledgeEdgeDraft.model_validate(_edge("a", "a"))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_edge("a", "b", required_mastery_level=-1), "greater than or equal to 0"),
        (_edge("a", "b", required_mastery_level=6), "less than or equal to 5"),
        (
            _edge("a", "b", required_mastery_level=0),
            "prerequisite edges require mastery level 1 through 5",
        ),
        (
            _edge("a", "b", relation_type="RELATED", required_mastery_level=1),
            "non-prerequisite edges must use required_mastery_level=0",
        ),
    ],
)
def test_edge_rejects_invalid_required_mastery_levels(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        KnowledgeEdgeDraft.model_validate(payload)

    assert message in str(exc_info.value)


def test_analyze_draft_partitions_candidate_prerequisite_cycle() -> None:
    draft = KnowledgeMapDraft.model_validate(
        {
            "space": {"title": "Cycle analysis"},
            "nodes": [_node("a"), _node("b"), _node("c"), _node("d")],
            "edges": [
                _edge("a", "b"),
                _edge("a", "c", relation_type="RELATED", required_mastery_level=0),
                _edge("b", "c"),
                _edge("c", "a"),
                _edge("c", "d"),
            ],
        }
    )

    analysis = analyze_draft(draft)

    assert analysis.draft == draft
    assert analysis.accepted_edges == [
        draft.edges[0],
        draft.edges[1],
        draft.edges[2],
        draft.edges[4],
    ]
    assert len(analysis.conflicts) == 1
    assert analysis.conflicts[0].edge == draft.edges[3]
    assert analysis.conflicts[0].reason == "Prerequisite proposal would create a cycle"
    assert analysis.conflicts[0].cycle_path == ["a", "b", "c", "a"]
    assert len(draft.edges) == 5


def _assert_valid_acyclic_mock_draft(draft: KnowledgeMapDraft) -> None:
    node_ids = {node.temp_id for node in draft.nodes}
    assert all(
        edge.source_temp_id in node_ids and edge.target_temp_id in node_ids for edge in draft.edges
    )
    assert all(edge.relation_type is RelationType.PREREQUISITE for edge in draft.edges)
    assert analyze_draft(draft).accepted_edges == draft.edges
    assert analyze_draft(draft).conflicts == []
    assert KnowledgeMapDraft.model_validate_json(draft.model_dump_json()) == draft


def test_mock_provider_returns_deterministic_valid_draft_for_normal_input() -> None:
    provider = MockProvider(model="unit-test-model")

    first = asyncio.run(provider.generate_knowledge_map("  Linear algebra  "))
    second = asyncio.run(provider.generate_knowledge_map("  Linear algebra  "))

    assert provider.name == "mock"
    assert provider.model == "unit-test-model"
    assert first == second
    assert first.space.title == "Linear algebra"
    assert first.space.scope_included == ["Linear algebra"]
    assert [node.temp_id for node in first.nodes] == ["foundation", "practice", "project"]
    assert [node.node_type for node in first.nodes] == [
        NodeType.CONCEPT,
        NodeType.SKILL,
        NodeType.PROJECT,
    ]
    _assert_valid_acyclic_mock_draft(first)


def test_mock_provider_uses_deterministic_fallback_for_empty_input() -> None:
    provider = MockProvider()

    empty = asyncio.run(provider.generate_knowledge_map(""))
    whitespace = asyncio.run(provider.generate_knowledge_map(" \n\t "))

    assert empty == whitespace
    assert empty.space.title == "自主学习目标"
    assert empty.space.scope_included == ["自主学习目标"]
    assert empty.nodes[0].title == "自主学习目标：基础"
    _assert_valid_acyclic_mock_draft(empty)


def test_mock_provider_returns_deterministic_pytorch_draft() -> None:
    provider = MockProvider()

    lower_case = asyncio.run(provider.generate_knowledge_map("pytorch"))
    mixed_case = asyncio.run(provider.generate_knowledge_map("Learn PyToRcH"))

    assert lower_case == mixed_case
    assert lower_case.space.title == "PyTorch 图像分类"
    assert [node.temp_id for node in lower_case.nodes] == [
        "python",
        "tensor",
        "autograd",
        "nn",
        "data",
        "train",
        "project",
    ]
    assert len(lower_case.edges) == 8
    assert lower_case.nodes[-1].node_type is NodeType.PROJECT
    _assert_valid_acyclic_mock_draft(lower_case)


def test_mock_provider_other_async_methods_return_stable_review_only_results() -> None:
    provider = MockProvider()
    context: dict[str, Any] = {"nodes": ["a", "b"], "reviewed": False}

    async def invoke_methods() -> tuple[dict[str, Any], ...]:
        return (
            await provider.suggest_missing_nodes(context),
            await provider.suggest_edges(context),
            await provider.suggest_node_merge(context),
            await provider.explain_learning_path(context),
            await provider.evaluate_explanation(context),
        )

    missing_nodes, edges, merges, explanation, evaluation = asyncio.run(invoke_methods())

    assert missing_nodes == {
        "suggestions": [],
        "reason": "Offline provider has no additional evidence.",
    }
    assert edges == {
        "suggestions": [],
        "reason": "Offline provider has no additional evidence.",
    }
    assert merges == {"suggestions": [], "reason": "No deterministic synonym was found."}
    assert explanation == {
        "explanation": "The route follows reviewed hard prerequisites.",
        "context": context,
    }
    assert evaluation == {"evaluation": "manual_review_required", "context": context}
