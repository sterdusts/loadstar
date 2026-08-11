"""Unit tests for deterministic graph rules and learning-route decisions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from learning_navigator.domain.entities import (
    GraphEdge,
    GraphNode,
    LearnerSnapshot,
    RouteRequest,
)
from learning_navigator.domain.enums import (
    ComputedNodeStatus,
    NodeType,
    RecordStatus,
    RelationType,
    RoutePreference,
)
from learning_navigator.domain.exceptions import (
    CircularPrerequisiteError,
    DuplicateEdgeError,
    EntityNotFoundError,
    InvalidEdgeError,
)
from learning_navigator.domain.services.graph import KnowledgeGraphService


def make_node(
    node_id: str,
    *,
    title: str | None = None,
    node_type: NodeType = NodeType.CONCEPT,
    difficulty: int = 1,
    depth_level: int = 0,
    status: RecordStatus = RecordStatus.ACTIVE,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        title=title or node_id,
        node_type=node_type,
        difficulty=difficulty,
        depth_level=depth_level,
        status=status,
    )


def make_edge(
    source: str,
    target: str,
    *,
    edge_id: str | None = None,
    relation_type: RelationType = RelationType.PREREQUISITE,
    required_mastery_level: int | None = None,
    hard: bool | None = None,
    status: RecordStatus = RecordStatus.ACTIVE,
) -> GraphEdge:
    is_prerequisite = relation_type is RelationType.PREREQUISITE
    return GraphEdge(
        id=edge_id or f"{source}-{relation_type.value}-{target}",
        source_node_id=source,
        target_node_id=target,
        relation_type=relation_type,
        required_mastery_level=(
            3 if is_prerequisite and required_mastery_level is None else required_mastery_level or 0
        ),
        is_hard_requirement=is_prerequisite if hard is None else hard,
        status=status,
    )


def node_ids(nodes: tuple[GraphNode, ...]) -> tuple[str, ...]:
    return tuple(node.id for node in nodes)


def chain_service() -> KnowledgeGraphService:
    nodes = [make_node(node_id) for node_id in ("a", "b", "c")]
    edges = [make_edge("a", "b"), make_edge("b", "c")]
    return KnowledgeGraphService(nodes, edges)


def diamond_service() -> KnowledgeGraphService:
    nodes = [make_node(node_id) for node_id in ("a", "b", "c", "d")]
    edges = [
        make_edge("a", "b"),
        make_edge("a", "c"),
        make_edge("b", "d"),
        make_edge("c", "d"),
    ]
    return KnowledgeGraphService(nodes, edges)


def test_normal_dag_queries_follow_prerequisite_direction() -> None:
    service = chain_service()

    assert node_ids(service.list_prerequisites("b")) == ("a",)
    assert node_ids(service.list_dependents("b")) == ("c",)
    assert node_ids(service.get_ancestors("c")) == ("a", "b")
    assert node_ids(service.get_descendants("a")) == ("b", "c")
    assert node_ids(service.calculate_target_subgraph("c")) == ("a", "b", "c")
    assert node_ids(service.topological_order()) == ("a", "b", "c")
    assert service.detect_cycle() is None


def test_single_node_is_preserved_and_immediately_unlockable() -> None:
    service = KnowledgeGraphService([make_node("only")])

    assert node_ids(service.nodes) == ("only",)
    assert node_ids(service.topological_order()) == ("only",)
    assert node_ids(service.calculate_target_subgraph("only")) == ("only",)
    assert node_ids(service.get_unlockable_nodes("only", {})) == ("only",)
    assert service.get_blocked_nodes("only", {}) == ()
    route = service.generate_route(RouteRequest(target_node_id="only"), {})
    assert tuple(item.node_id for item in route) == ("only",)
    assert route[0].status is ComputedNodeStatus.AVAILABLE


def test_node_creation_and_updates_validate_mutable_fields() -> None:
    service = KnowledgeGraphService()
    created = service.create_node(make_node("node", title="Original"))

    updated = service.update_node(
        "node",
        title="Updated",
        description="New description",
        node_type=NodeType.SKILL,
        difficulty=5,
        depth_level=2,
    )

    assert created.title == "Original"
    assert updated == GraphNode(
        id="node",
        title="Updated",
        description="New description",
        node_type=NodeType.SKILL,
        difficulty=5,
        depth_level=2,
    )
    assert service.nodes == (updated,)

    with pytest.raises(InvalidEdgeError, match="already exists"):
        service.create_node(make_node("node"))
    with pytest.raises(ValueError, match="difficulty"):
        service.create_node(make_node("too-easy", difficulty=0))
    with pytest.raises(ValueError, match="Unsupported node fields"):
        service.update_node("node", status=RecordStatus.ARCHIVED)
    with pytest.raises(ValueError, match="difficulty"):
        service.update_node("node", difficulty=6)


@pytest.mark.parametrize(
    "edge",
    [
        make_edge("a", "a"),
        make_edge("a", "b", required_mastery_level=-1),
        make_edge("a", "b", required_mastery_level=6),
        make_edge("a", "b", required_mastery_level=0, hard=True),
        make_edge("a", "b", relation_type=RelationType.RELATED, hard=True),
        make_edge(
            "a",
            "b",
            relation_type=RelationType.CONTAINS,
            required_mastery_level=3,
        ),
    ],
)
def test_edge_creation_rejects_invalid_unlock_fields(edge: GraphEdge) -> None:
    service = KnowledgeGraphService([make_node("a"), make_node("b")])

    with pytest.raises(InvalidEdgeError):
        service.create_edge(edge)


def test_multiple_roots_are_complete_and_stably_sorted() -> None:
    nodes = [
        make_node("target", difficulty=5),
        make_node("root-z", title="Zulu", difficulty=2),
        make_node("root-a", title="Alpha", difficulty=2),
    ]
    edges = [make_edge("root-z", "target"), make_edge("root-a", "target")]

    first = KnowledgeGraphService(nodes, edges)
    second = KnowledgeGraphService(list(reversed(nodes)), list(reversed(edges)))

    assert node_ids(first.topological_order()) == ("root-a", "root-z", "target")
    assert node_ids(second.topological_order()) == node_ids(first.topological_order())


def test_diamond_dependency_keeps_both_branches_before_join() -> None:
    service = diamond_service()

    order = node_ids(service.topological_order())
    positions = {node_id: index for index, node_id in enumerate(order)}

    assert set(order) == {"a", "b", "c", "d"}
    assert positions["a"] < positions["b"] < positions["d"]
    assert positions["a"] < positions["c"] < positions["d"]
    assert node_ids(service.calculate_target_subgraph("d")) == order


def test_contains_and_cross_module_prerequisite_have_separate_semantics() -> None:
    nodes = [
        make_node("module-a", node_type=NodeType.MODULE),
        make_node("module-b", node_type=NodeType.MODULE),
        make_node("concept-a", depth_level=1),
        make_node("concept-b", depth_level=1),
    ]
    edges = [
        make_edge("module-a", "concept-a", relation_type=RelationType.CONTAINS),
        make_edge("module-b", "concept-b", relation_type=RelationType.CONTAINS),
        make_edge("concept-a", "concept-b"),
    ]
    service = KnowledgeGraphService(nodes, edges)

    assert node_ids(service.list_children("module-a")) == ("concept-a",)
    assert node_ids(service.list_children("module-b")) == ("concept-b",)
    assert node_ids(service.list_prerequisites("concept-b")) == ("concept-a",)
    assert node_ids(service.calculate_target_subgraph("concept-b")) == (
        "concept-a",
        "concept-b",
    )


def test_cycle_creation_is_rejected_with_full_path_and_without_mutation() -> None:
    service = chain_service()

    with pytest.raises(CircularPrerequisiteError) as caught:
        service.create_edge(make_edge("c", "a"))

    assert caught.value.cycle_path == ("a", "b", "c", "a")
    assert service.detect_cycle() is None
    assert len(service.edges) == 2


def test_contains_cycle_is_rejected_without_changing_outline() -> None:
    service = KnowledgeGraphService([make_node("a"), make_node("b")])
    service.create_edge(
        make_edge("a", "b", edge_id="a-contains-b", relation_type=RelationType.CONTAINS)
    )

    with pytest.raises(InvalidEdgeError, match="CONTAINS edge would create outline cycle"):
        service.create_edge(
            make_edge(
                "b",
                "a",
                edge_id="b-contains-a",
                relation_type=RelationType.CONTAINS,
            )
        )

    assert node_ids(service.list_children("a")) == ("b",)
    assert service.list_children("b") == ()


def test_preloaded_cycle_is_detected_and_topological_sort_refuses_it() -> None:
    nodes = [make_node(node_id) for node_id in ("a", "b", "c")]
    edges = [make_edge("a", "b"), make_edge("b", "c"), make_edge("c", "a")]
    service = KnowledgeGraphService(nodes, edges)

    cycle = service.detect_cycle()

    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == {"a", "b", "c"}
    with pytest.raises(CircularPrerequisiteError):
        service.topological_order()


def test_duplicate_active_edge_is_rejected_but_another_relation_is_allowed() -> None:
    nodes = [make_node("a"), make_node("b")]
    service = KnowledgeGraphService(nodes)
    service.create_edge(make_edge("a", "b", edge_id="first"))

    with pytest.raises(DuplicateEdgeError):
        service.create_edge(make_edge("a", "b", edge_id="duplicate", required_mastery_level=4))

    related = make_edge(
        "a",
        "b",
        edge_id="related",
        relation_type=RelationType.RELATED,
    )
    assert service.create_edge(related) is related


def test_symmetric_relation_is_normalized_before_duplicate_detection() -> None:
    service = KnowledgeGraphService([make_node("a"), make_node("b")])

    normalized = service.create_edge(
        make_edge("b", "a", edge_id="reverse", relation_type=RelationType.RELATED)
    )

    assert (normalized.source_node_id, normalized.target_node_id) == ("a", "b")
    with pytest.raises(DuplicateEdgeError):
        service.create_edge(
            make_edge("a", "b", edge_id="forward", relation_type=RelationType.RELATED)
        )


def test_archived_edge_can_be_rebuilt_without_reviving_old_record() -> None:
    service = KnowledgeGraphService([make_node("a"), make_node("b")])
    original = service.create_edge(make_edge("a", "b", edge_id="old"))

    archived = service.remove_edge(original.id)
    replacement = service.create_edge(make_edge("a", "b", edge_id="new"))

    assert archived.status is RecordStatus.ARCHIVED
    assert replacement.status is RecordStatus.ACTIVE
    assert node_ids(service.list_prerequisites("b")) == ("a",)
    assert {edge.id: edge.status for edge in service.edges} == {
        "old": RecordStatus.ARCHIVED,
        "new": RecordStatus.ACTIVE,
    }


@pytest.mark.parametrize(
    "operation",
    [
        lambda service: service.update_node("missing", title="new"),
        lambda service: service.archive_node("missing"),
        lambda service: service.list_children("missing"),
        lambda service: service.list_prerequisites("missing"),
        lambda service: service.list_dependents("missing"),
        lambda service: service.get_ancestors("missing"),
        lambda service: service.get_descendants("missing"),
        lambda service: service.calculate_target_subgraph("missing"),
        lambda service: service.remove_edge("missing"),
    ],
)
def test_queries_and_mutations_reject_nonexistent_records(
    operation: Callable[[KnowledgeGraphService], object],
) -> None:
    service = KnowledgeGraphService([make_node("present")])

    with pytest.raises(EntityNotFoundError):
        operation(service)


@pytest.mark.parametrize("missing_endpoint", ["source", "target"])
def test_create_edge_rejects_nonexistent_endpoints(missing_endpoint: str) -> None:
    service = KnowledgeGraphService([make_node("present")])
    edge = (
        make_edge("missing", "present")
        if missing_endpoint == "source"
        else make_edge("present", "missing")
    )

    with pytest.raises(EntityNotFoundError):
        service.create_edge(edge)


def test_partial_mastery_keeps_all_nodes_available_and_explains_prerequisite_gaps() -> None:
    service = diamond_service()
    mastery = {"a": LearnerSnapshot("a", mastery_level=3)}

    assert node_ids(service.get_unlockable_nodes("d", mastery)) == ("b", "c", "d")
    assert service.get_blocked_nodes("d", mastery) == ()

    explanation = service.explain_blockage("d", mastery)
    assert tuple(blocker.node_id for blocker in explanation.blockers) == ("b", "c")
    assert all(blocker.required_level == 3 for blocker in explanation.blockers)
    assert explanation.recommended_first_node_id in {"b", "c"}
    assert explanation.dependency_chain[-1] == "d"

    route = service.generate_route(RouteRequest(target_node_id="d"), mastery)
    by_id = {item.node_id: item for item in route}
    assert set(by_id) == {"b", "c", "d"}
    assert by_id["b"].status is ComputedNodeStatus.AVAILABLE
    assert by_id["c"].status is ComputedNodeStatus.AVAILABLE
    assert by_id["d"].status is ComputedNodeStatus.AVAILABLE
    assert set(by_id["d"].unmet_prerequisites) == {"b", "c"}
    assert "may start" in by_id["d"].reason


def test_route_reports_in_progress_reason_and_satisfied_prerequisites() -> None:
    service = chain_service()
    mastery = {
        "a": LearnerSnapshot("a", mastery_level=3),
        "b": LearnerSnapshot("b", mastery_level=1, mastery_score=0.25),
    }

    route = service.generate_route(RouteRequest(target_node_id="c"), mastery)
    by_id = {item.node_id: item for item in route}

    assert tuple(item.node_id for item in route) == ("b", "c")
    assert by_id["b"].status is ComputedNodeStatus.IN_PROGRESS
    assert "started" in by_id["b"].reason
    assert by_id["b"].satisfied_prerequisites == ("a",)
    assert by_id["c"].status is ComputedNodeStatus.AVAILABLE
    assert by_id["c"].unmet_prerequisites == ("b",)
    assert "may start" in by_id["c"].reason


def test_route_uses_edge_requirement_for_satisfied_prerequisite() -> None:
    service = KnowledgeGraphService(
        [make_node("prerequisite"), make_node("target")],
        [make_edge("prerequisite", "target", required_mastery_level=3)],
    )
    mastery = {"prerequisite": LearnerSnapshot("prerequisite", mastery_level=3)}

    route = service.generate_route(
        RouteRequest(target_node_id="target", target_mastery_level=5), mastery
    )

    assert tuple(item.node_id for item in route) == ("target",)
    assert route[0].required_mastery_level == 5
    assert route[0].satisfied_prerequisites == ("prerequisite",)


def test_route_records_edge_requirement_for_unmet_prerequisite() -> None:
    service = KnowledgeGraphService(
        [make_node("prerequisite"), make_node("target")],
        [make_edge("prerequisite", "target", required_mastery_level=3)],
    )

    route = service.generate_route(
        RouteRequest(target_node_id="target", target_mastery_level=5), {}
    )
    by_id = {item.node_id: item for item in route}

    assert by_id["prerequisite"].required_mastery_level == 3
    assert by_id["target"].required_mastery_level == 5
    assert "required mastery level 3" in by_id["prerequisite"].reason


@pytest.mark.parametrize(
    ("preference", "expected_prefix"),
    [
        (RoutePreference.PROJECT_FIRST, ("project", "concept")),
        (RoutePreference.THEORY_FIRST, ("concept", "project")),
    ],
)
def test_route_preferences_break_ties_without_violating_dependencies(
    preference: RoutePreference,
    expected_prefix: tuple[str, str],
) -> None:
    nodes = [
        make_node("concept", node_type=NodeType.CONCEPT, difficulty=3),
        make_node("project", node_type=NodeType.PROJECT, difficulty=1),
        make_node("target", node_type=NodeType.SKILL),
    ]
    edges = [make_edge("concept", "target"), make_edge("project", "target")]
    service = KnowledgeGraphService(nodes, edges)

    route = service.generate_route(
        RouteRequest(target_node_id="target", preference=preference),
        {},
    )

    assert tuple(item.node_id for item in route[:2]) == expected_prefix
    assert route[-1].node_id == "target"


def test_all_mastered_target_subgraph_has_no_pending_route() -> None:
    service = diamond_service()
    mastery = {
        node_id: LearnerSnapshot(node_id, mastery_level=3) for node_id in ("a", "b", "c", "d")
    }

    assert service.get_unlockable_nodes("d", mastery) == ()
    assert service.get_blocked_nodes("d", mastery) == ()
    assert service.generate_route(RouteRequest(target_node_id="d"), mastery) == ()


def test_soft_prerequisite_does_not_block_target() -> None:
    nodes = [make_node("suggested"), make_node("target")]
    soft_edge = make_edge(
        "suggested",
        "target",
        hard=False,
        required_mastery_level=0,
    )
    service = KnowledgeGraphService(nodes, [soft_edge])

    assert node_ids(service.calculate_target_subgraph("target")) == ("target",)
    assert node_ids(service.get_unlockable_nodes("target", {})) == ("target",)
    assert service.classify_node("target", {"target"}, {}) is ComputedNodeStatus.AVAILABLE
    assert node_ids(service.get_blocked_nodes("target", {})) == ()


def test_overdue_prerequisite_warns_but_does_not_block_dependent() -> None:
    service = KnowledgeGraphService(
        [make_node("prerequisite"), make_node("dependent")],
        [make_edge("prerequisite", "dependent")],
    )
    now = datetime.now(UTC)
    mastery = {
        "prerequisite": LearnerSnapshot(
            "prerequisite",
            mastery_level=3,
            next_review_at=now - timedelta(days=1),
        )
    }
    relevant = {"prerequisite", "dependent"}

    assert (
        service.classify_node("prerequisite", relevant, mastery, now=now)
        is ComputedNodeStatus.NEEDS_REVIEW
    )
    assert (
        service.classify_node("dependent", relevant, mastery, now=now)
        is ComputedNodeStatus.AVAILABLE
    )
    assert service.get_blocked_nodes("dependent", mastery) == ()

    explanation = service.explain_blockage("dependent", mastery)
    assert tuple(blocker.node_id for blocker in explanation.blockers) == ("prerequisite",)
    assert explanation.blockers[0].status is ComputedNodeStatus.NEEDS_REVIEW


def test_incomplete_but_overdue_node_needs_review_before_in_progress() -> None:
    service = KnowledgeGraphService([make_node("node")])
    now = datetime(2026, 7, 31, tzinfo=UTC)
    mastery = {
        "node": LearnerSnapshot(
            "node",
            mastery_level=2,
            mastery_score=0.5,
            next_review_at=now - timedelta(seconds=1),
        )
    }

    assert (
        service.classify_node("node", {"node"}, mastery, now=now) is ComputedNodeStatus.NEEDS_REVIEW
    )


def test_archived_nodes_and_edges_are_excluded_when_graph_is_rebuilt() -> None:
    nodes = [
        make_node("active-root"),
        make_node("archived", status=RecordStatus.ARCHIVED),
        make_node("active-target"),
    ]
    edges = [
        make_edge("active-root", "archived", edge_id="to-archived"),
        make_edge("archived", "active-target", edge_id="from-archived"),
        make_edge(
            "active-root",
            "active-target",
            edge_id="archived-edge",
            status=RecordStatus.ARCHIVED,
        ),
    ]
    service = KnowledgeGraphService(nodes, edges)

    assert set(node_ids(service.topological_order())) == {"active-root", "active-target"}
    assert service.list_prerequisites("active-target") == ()
    assert service.classify_node("archived", {"archived"}, {}) is ComputedNodeStatus.NOT_RELEVANT


def test_archived_node_can_be_recreated_with_incident_edges_kept_archived() -> None:
    service = chain_service()

    archived = service.archive_node("b")
    rebuilt = service.create_node(make_node("b", title="B rebuilt"))

    assert archived.status is RecordStatus.ARCHIVED
    assert rebuilt.status is RecordStatus.ACTIVE
    assert service.list_prerequisites("b") == ()
    assert service.list_dependents("b") == ()
    assert all(edge.status is RecordStatus.ARCHIVED for edge in service.edges)

    service.create_edge(make_edge("a", "b", edge_id="new-a-b"))
    service.create_edge(make_edge("b", "c", edge_id="new-b-c"))
    assert node_ids(service.calculate_target_subgraph("c")) == ("a", "b", "c")


def test_classification_keeps_level_score_and_review_status_separate() -> None:
    now = datetime(2026, 7, 31, tzinfo=UTC)
    nodes = [
        make_node(node_id) for node_id in ("root", "blocked", "progress", "done", "future-review")
    ]
    service = KnowledgeGraphService(nodes, [make_edge("root", "blocked")])
    relevant = {node.id for node in nodes}
    mastery = {
        "progress": LearnerSnapshot("progress", mastery_level=0, mastery_score=0.99),
        "done": LearnerSnapshot(
            "done",
            mastery_level=3,
            mastery_score=0.1,
            next_review_at=now - timedelta(seconds=1),
        ),
        "future-review": LearnerSnapshot(
            "future-review",
            mastery_level=3,
            next_review_at=(now + timedelta(days=1)).replace(tzinfo=None),
        ),
    }

    assert service.classify_node("root", relevant, mastery, now=now) is ComputedNodeStatus.AVAILABLE
    assert (
        service.classify_node("blocked", relevant, mastery, now=now) is ComputedNodeStatus.AVAILABLE
    )
    assert (
        service.classify_node("progress", relevant, mastery, now=now)
        is ComputedNodeStatus.IN_PROGRESS
    )
    assert (
        service.classify_node("done", relevant, mastery, now=now) is ComputedNodeStatus.NEEDS_REVIEW
    )
    assert (
        service.classify_node("future-review", relevant, mastery, now=now)
        is ComputedNodeStatus.MASTERED
    )
    assert (
        service.classify_node("root", {"blocked"}, mastery, now=now)
        is ComputedNodeStatus.NOT_RELEVANT
    )


@st.composite
def dag_specs(draw: st.DrawFn) -> tuple[int, list[tuple[int, int]]]:
    size = draw(st.integers(min_value=1, max_value=10))
    candidates = [(source, target) for source in range(size) for target in range(source + 1, size)]
    if not candidates:
        return size, []
    edges = draw(
        st.lists(
            st.sampled_from(candidates),
            unique=True,
            max_size=min(24, len(candidates)),
        )
    )
    return size, edges


@given(dag_specs())
@settings(max_examples=75, deadline=None)
def test_topological_order_preserves_every_generated_dag_edge(
    spec: tuple[int, list[tuple[int, int]]],
) -> None:
    size, edge_pairs = spec
    nodes = [
        make_node(
            f"n{index}",
            title=f"Node {index:02d}",
            difficulty=index % 5 + 1,
        )
        for index in range(size)
    ]
    edges = [
        make_edge(f"n{source}", f"n{target}", edge_id=f"e-{source}-{target}")
        for source, target in edge_pairs
    ]
    service = KnowledgeGraphService(list(reversed(nodes)), list(reversed(edges)))

    order = node_ids(service.topological_order())
    position = {node_id: index for index, node_id in enumerate(order)}

    assert set(order) == {node.id for node in nodes}
    assert all(position[f"n{source}"] < position[f"n{target}"] for source, target in edge_pairs)
    assert node_ids(service.topological_order()) == order
