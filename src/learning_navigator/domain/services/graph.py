"""Explainable knowledge-graph rules and route planning.

Only active ``PREREQUISITE`` edges participate in route ordering and readiness advice. The
edge direction is always prerequisite -> dependent. Unmet prerequisites are advisory: they
remain visible in explanations but never prevent a user from starting a node.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import networkx as nx

from learning_navigator.domain.entities import (
    BlockageExplanation,
    Blocker,
    GraphEdge,
    GraphNode,
    LearnerSnapshot,
    RouteRecommendation,
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

SYMMETRIC_RELATIONS = {RelationType.RELATED, RelationType.ALTERNATIVE_TO}


class KnowledgeGraphService:
    """Mutable in-memory domain view built from relational node and edge records."""

    def __init__(self, nodes: list[GraphNode] | None = None, edges: list[GraphEdge] | None = None):
        self._nodes = {node.id: node for node in nodes or []}
        self._edges = {edge.id: edge for edge in edges or []}

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(self._nodes.values())

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(self._edges.values())

    def create_node(self, node: GraphNode) -> GraphNode:
        if node.id in self._nodes and self._nodes[node.id].is_active:
            raise InvalidEdgeError(f"Active node '{node.id}' already exists")
        if not 1 <= node.difficulty <= 5:
            raise ValueError("difficulty must be between 1 and 5")
        self._nodes[node.id] = node
        return node

    def update_node(self, node_id: str, **changes: Any) -> GraphNode:
        node = self._require_active_node(node_id)
        allowed = {"title", "description", "node_type", "difficulty", "depth_level"}
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(f"Unsupported node fields: {sorted(unexpected)}")
        updated = replace(node, **changes)
        if not 1 <= updated.difficulty <= 5:
            raise ValueError("difficulty must be between 1 and 5")
        self._nodes[node_id] = updated
        return updated

    def archive_node(self, node_id: str) -> GraphNode:
        node = self._require_active_node(node_id)
        archived = replace(node, status=RecordStatus.ARCHIVED)
        self._nodes[node_id] = archived
        for edge_id, edge in tuple(self._edges.items()):
            if edge.source_node_id == node_id or edge.target_node_id == node_id:
                self._edges[edge_id] = replace(edge, status=RecordStatus.ARCHIVED)
        return archived

    def create_edge(self, edge: GraphEdge) -> GraphEdge:
        if edge.relation_type in SYMMETRIC_RELATIONS and edge.source_node_id > edge.target_node_id:
            edge = replace(
                edge,
                source_node_id=edge.target_node_id,
                target_node_id=edge.source_node_id,
            )
        self._require_active_node(edge.source_node_id)
        self._require_active_node(edge.target_node_id)
        if edge.source_node_id == edge.target_node_id:
            raise InvalidEdgeError("Self-referential edges are not allowed")
        if not 0 <= edge.required_mastery_level <= 5:
            raise InvalidEdgeError("required_mastery_level must be between 0 and 5")
        if edge.relation_type is RelationType.PREREQUISITE:
            if edge.is_hard_requirement and edge.required_mastery_level == 0:
                raise InvalidEdgeError("Hard prerequisites require mastery level 1 through 5")
        elif edge.is_hard_requirement or edge.required_mastery_level != 0:
            raise InvalidEdgeError("Only PREREQUISITE edges can carry unlock requirements")
        if self._find_duplicate(edge) is not None:
            raise DuplicateEdgeError(
                edge.source_node_id, edge.target_node_id, edge.relation_type.value
            )
        if edge.relation_type is RelationType.PREREQUISITE:
            graph = self._directed_graph(RelationType.PREREQUISITE)
            if nx.has_path(graph, edge.target_node_id, edge.source_node_id):
                path = nx.shortest_path(graph, edge.target_node_id, edge.source_node_id)
                raise CircularPrerequisiteError([*path, edge.target_node_id])
        elif edge.relation_type is RelationType.CONTAINS:
            graph = self._directed_graph(RelationType.CONTAINS)
            if nx.has_path(graph, edge.target_node_id, edge.source_node_id):
                path = nx.shortest_path(graph, edge.target_node_id, edge.source_node_id)
                cycle = [*path, edge.target_node_id]
                raise InvalidEdgeError(
                    "CONTAINS edge would create outline cycle: " + " -> ".join(cycle)
                )
        self._edges[edge.id] = edge
        return edge

    def remove_edge(self, edge_id: str) -> GraphEdge:
        edge = self._edges.get(edge_id)
        if edge is None or not edge.is_active:
            raise EntityNotFoundError("edge", edge_id)
        archived = replace(edge, status=RecordStatus.ARCHIVED)
        self._edges[edge_id] = archived
        return archived

    def list_children(self, node_id: str) -> tuple[GraphNode, ...]:
        return self._neighbors(node_id, RelationType.CONTAINS, predecessors=False)

    def list_prerequisites(self, node_id: str) -> tuple[GraphNode, ...]:
        return self._neighbors(node_id, RelationType.PREREQUISITE, predecessors=True)

    def list_dependents(self, node_id: str) -> tuple[GraphNode, ...]:
        return self._neighbors(node_id, RelationType.PREREQUISITE, predecessors=False)

    def get_ancestors(
        self, node_id: str, relation_type: RelationType = RelationType.PREREQUISITE
    ) -> tuple[GraphNode, ...]:
        self._require_active_node(node_id)
        graph = self._directed_graph(relation_type)
        return self._ordered_nodes(nx.ancestors(graph, node_id))

    def get_descendants(
        self, node_id: str, relation_type: RelationType = RelationType.PREREQUISITE
    ) -> tuple[GraphNode, ...]:
        self._require_active_node(node_id)
        graph = self._directed_graph(relation_type)
        return self._ordered_nodes(nx.descendants(graph, node_id))

    def detect_cycle(self) -> tuple[str, ...] | None:
        graph = self._directed_graph(RelationType.PREREQUISITE)
        try:
            cycle = nx.find_cycle(graph, orientation="original")
        except nx.NetworkXNoCycle:
            return None
        node_path = [str(cycle[0][0]), *(str(item[1]) for item in cycle)]
        return tuple(node_path)

    def topological_order(self, node_ids: set[str] | None = None) -> tuple[GraphNode, ...]:
        graph = self._directed_graph(RelationType.PREREQUISITE)
        if node_ids is not None:
            graph = graph.subgraph(node_ids).copy()
        if not nx.is_directed_acyclic_graph(graph):
            cycle = self.detect_cycle() or ()
            raise CircularPrerequisiteError(cycle)
        order = nx.lexicographical_topological_sort(graph, key=self._route_sort_key)
        return tuple(self._nodes[str(node_id)] for node_id in order)

    def calculate_target_subgraph(self, target_node_id: str) -> tuple[GraphNode, ...]:
        self._require_active_node(target_node_id)
        graph = self._directed_graph(RelationType.PREREQUISITE, hard_only=True)
        ids = nx.ancestors(graph, target_node_id) | {target_node_id}
        return self.topological_order(ids)

    def get_unlockable_nodes(
        self,
        target_node_id: str,
        mastery: dict[str, LearnerSnapshot],
        target_mastery_level: int = 3,
    ) -> tuple[GraphNode, ...]:
        subgraph_ids = {node.id for node in self.calculate_target_subgraph(target_node_id)}
        required_levels = self._route_required_mastery_levels(
            target_node_id, target_mastery_level, subgraph_ids
        )
        unlockable: list[GraphNode] = []
        for node in self.topological_order(subgraph_ids):
            if self._snapshot_satisfies(
                mastery.get(node.id, LearnerSnapshot(node.id)), required_levels[node.id]
            ):
                continue
            unlockable.append(node)
        return tuple(unlockable)

    def get_blocked_nodes(
        self,
        target_node_id: str,
        mastery: dict[str, LearnerSnapshot],
        target_mastery_level: int = 3,
    ) -> tuple[GraphNode, ...]:
        # Prerequisites are guidance, not an access-control rule. Keep this compatibility
        # query, but do not report nodes as blocked solely because their prerequisites are
        # incomplete. Callers can use ``explain_blockage`` or route ``unmet_prerequisites``
        # to present the advisory context.
        self.calculate_target_subgraph(target_node_id)
        return ()

    def explain_blockage(
        self, node_id: str, mastery: dict[str, LearnerSnapshot]
    ) -> BlockageExplanation:
        self._require_active_node(node_id)
        direct = self._unmet_prerequisite_edges(node_id, mastery)
        blockers = tuple(
            Blocker(
                node_id=edge.source_node_id,
                title=self._nodes[edge.source_node_id].title,
                current_level=mastery.get(
                    edge.source_node_id, LearnerSnapshot(edge.source_node_id)
                ).mastery_level,
                required_level=edge.required_mastery_level,
                status=self.classify_node(
                    edge.source_node_id, {node_id, *self._active_node_ids()}, mastery
                ),
            )
            for edge in direct
        )
        chain = self._deepest_unmet_chain(node_id, mastery)
        recommended = chain[0] if chain else None
        return BlockageExplanation(
            blocked_node_id=node_id,
            blockers=blockers,
            recommended_first_node_id=recommended,
            dependency_chain=tuple(chain),
        )

    def classify_node(
        self,
        node_id: str,
        relevant_node_ids: set[str],
        mastery: dict[str, LearnerSnapshot],
        target_mastery_level: int = 3,
        now: datetime | None = None,
    ) -> ComputedNodeStatus:
        node = self._nodes.get(node_id)
        if node is None or not node.is_active or node_id not in relevant_node_ids:
            return ComputedNodeStatus.NOT_RELEVANT
        snapshot = mastery.get(node_id, LearnerSnapshot(node_id))
        comparison_time = now or datetime.now(UTC)
        next_review_at = snapshot.next_review_at
        if snapshot.mastery_level > 0 and next_review_at is not None:
            if next_review_at.tzinfo is None:
                next_review_at = next_review_at.replace(tzinfo=UTC)
            if next_review_at <= comparison_time:
                return ComputedNodeStatus.NEEDS_REVIEW
        if snapshot.mastery_level >= target_mastery_level:
            return ComputedNodeStatus.MASTERED
        if snapshot.mastery_level > 0 or snapshot.mastery_score > 0:
            return ComputedNodeStatus.IN_PROGRESS
        return ComputedNodeStatus.AVAILABLE

    def generate_route(
        self, request: RouteRequest, mastery: dict[str, LearnerSnapshot]
    ) -> tuple[RouteRecommendation, ...]:
        subgraph = self.calculate_target_subgraph(request.target_node_id)
        relevant_ids = {node.id for node in subgraph}
        required_levels = self._route_required_mastery_levels(
            request.target_node_id, request.target_mastery_level, relevant_ids
        )
        pending = [
            node
            for node in subgraph
            if not self._snapshot_satisfies(
                mastery.get(node.id, LearnerSnapshot(node.id)),
                required_levels[node.id],
            )
        ]
        pending = self._apply_preference(pending, request.preference)
        recommendations: list[RouteRecommendation] = []
        for node in pending:
            required_mastery_level = required_levels[node.id]
            prerequisite_edges = self._incoming_edges(node.id, RelationType.PREREQUISITE)
            satisfied = tuple(
                edge.source_node_id
                for edge in prerequisite_edges
                if self._snapshot_satisfies(
                    mastery.get(edge.source_node_id, LearnerSnapshot(edge.source_node_id)),
                    edge.required_mastery_level,
                )
            )
            unmet = tuple(
                edge.source_node_id
                for edge in prerequisite_edges
                if edge.source_node_id not in satisfied
            )
            unlocks = tuple(
                item.id for item in self.list_dependents(node.id) if item.id in relevant_ids
            )
            status = self.classify_node(node.id, relevant_ids, mastery, required_mastery_level)
            if unmet:
                names = ", ".join(self._nodes[item].title for item in unmet)
                reason = (
                    f"Recommended prerequisites are not yet satisfied: {names}. You may start "
                    "this node now, while reviewing those foundations to reduce gaps."
                )
            elif status is ComputedNodeStatus.AVAILABLE:
                reason = (
                    "All hard prerequisites are satisfied; this is the next foundational step "
                    f"toward required mastery level {required_mastery_level}."
                )
            elif status is ComputedNodeStatus.IN_PROGRESS:
                reason = (
                    "You have started this node but have not reached required mastery level "
                    f"{required_mastery_level}."
                )
            elif status is ComputedNodeStatus.NEEDS_REVIEW:
                reason = (
                    "The review date has arrived; refresh the evidence before continuing toward "
                    f"required mastery level {required_mastery_level}."
                )
            else:
                reason = (
                    "This node is available to start while its current evidence is being evaluated."
                )
            recommendations.append(
                RouteRecommendation(
                    node_id=node.id,
                    title=node.title,
                    required_mastery_level=required_mastery_level,
                    reason=reason,
                    satisfied_prerequisites=satisfied,
                    unmet_prerequisites=unmet,
                    unlocks=unlocks,
                    algorithm_version=request.algorithm_version,
                    status=status,
                )
            )
        return tuple(recommendations)

    def _route_required_mastery_levels(
        self,
        target_node_id: str,
        target_mastery_level: int,
        relevant_node_ids: set[str],
    ) -> dict[str, int]:
        """Resolve the mastery threshold for every node in one hard-prerequisite route."""

        required_levels: dict[str, int] = {}
        for edge in self._active_edges(RelationType.PREREQUISITE):
            if (
                edge.is_hard_requirement
                and edge.source_node_id in relevant_node_ids
                and edge.target_node_id in relevant_node_ids
            ):
                required_levels[edge.source_node_id] = max(
                    required_levels.get(edge.source_node_id, 0),
                    edge.required_mastery_level,
                )
        required_levels[target_node_id] = target_mastery_level
        return required_levels

    def _active_node_ids(self) -> set[str]:
        return {node.id for node in self._nodes.values() if node.is_active}

    def _require_active_node(self, node_id: str) -> GraphNode:
        node = self._nodes.get(node_id)
        if node is None or not node.is_active:
            raise EntityNotFoundError("node", node_id)
        return node

    def _active_edges(self, relation_type: RelationType | None = None) -> list[GraphEdge]:
        return [
            edge
            for edge in self._edges.values()
            if edge.is_active
            and (relation_type is None or edge.relation_type is relation_type)
            and edge.source_node_id in self._active_node_ids()
            and edge.target_node_id in self._active_node_ids()
        ]

    def _directed_graph(
        self, relation_type: RelationType, *, hard_only: bool = False
    ) -> nx.DiGraph[str]:
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(self._active_node_ids())
        graph.add_edges_from(
            (edge.source_node_id, edge.target_node_id)
            for edge in self._active_edges(relation_type)
            if not hard_only or edge.is_hard_requirement
        )
        return graph

    def _find_duplicate(self, candidate: GraphEdge) -> GraphEdge | None:
        symmetric = candidate.relation_type in SYMMETRIC_RELATIONS
        return next(
            (
                edge
                for edge in self._active_edges()
                if (
                    (
                        edge.source_node_id == candidate.source_node_id
                        and edge.target_node_id == candidate.target_node_id
                    )
                    or (
                        symmetric
                        and edge.source_node_id == candidate.target_node_id
                        and edge.target_node_id == candidate.source_node_id
                    )
                )
                and edge.relation_type is candidate.relation_type
            ),
            None,
        )

    def _incoming_edges(self, node_id: str, relation_type: RelationType) -> list[GraphEdge]:
        return sorted(
            (
                edge
                for edge in self._active_edges(relation_type)
                if edge.target_node_id == node_id
                and (relation_type is not RelationType.PREREQUISITE or edge.is_hard_requirement)
            ),
            key=lambda edge: self._route_sort_key(edge.source_node_id),
        )

    def _neighbors(
        self, node_id: str, relation_type: RelationType, *, predecessors: bool
    ) -> tuple[GraphNode, ...]:
        self._require_active_node(node_id)
        graph = self._directed_graph(relation_type)
        ids = graph.predecessors(node_id) if predecessors else graph.successors(node_id)
        return self._ordered_nodes(set(ids))

    def _ordered_nodes(self, node_ids: set[str]) -> tuple[GraphNode, ...]:
        return tuple(
            sorted((self._nodes[node_id] for node_id in node_ids), key=self._node_sort_key)
        )

    @staticmethod
    def _node_sort_key(node: GraphNode) -> tuple[int, int, str, str]:
        return (node.depth_level, node.difficulty, node.title.casefold(), node.id)

    def _route_sort_key(self, node_id: str) -> tuple[int, int, str, str]:
        return self._node_sort_key(self._nodes[node_id])

    def _all_prerequisites_satisfied(
        self, node_id: str, mastery: dict[str, LearnerSnapshot]
    ) -> bool:
        return not self._unmet_prerequisite_edges(node_id, mastery)

    def _unmet_prerequisite_edges(
        self, node_id: str, mastery: dict[str, LearnerSnapshot]
    ) -> list[GraphEdge]:
        return [
            edge
            for edge in self._incoming_edges(node_id, RelationType.PREREQUISITE)
            if not self._snapshot_satisfies(
                mastery.get(edge.source_node_id, LearnerSnapshot(edge.source_node_id)),
                edge.required_mastery_level,
            )
        ]

    @staticmethod
    def _snapshot_satisfies(
        snapshot: LearnerSnapshot,
        required_mastery_level: int,
        now: datetime | None = None,
    ) -> bool:
        if snapshot.mastery_level < required_mastery_level:
            return False
        if snapshot.mastery_level <= 0 or snapshot.next_review_at is None:
            return True
        comparison_time = now or datetime.now(UTC)
        next_review_at = snapshot.next_review_at
        if next_review_at.tzinfo is None:
            next_review_at = next_review_at.replace(tzinfo=UTC)
        return next_review_at > comparison_time

    def _deepest_unmet_chain(
        self,
        node_id: str,
        mastery: dict[str, LearnerSnapshot],
        seen: set[str] | None = None,
    ) -> list[str]:
        visited = set() if seen is None else set(seen)
        if node_id in visited:
            return []
        visited.add(node_id)
        unmet = self._unmet_prerequisite_edges(node_id, mastery)
        if not unmet:
            return [] if node_id not in self._nodes else [node_id]
        candidate_chains: list[list[str]] = []
        for edge in unmet:
            prefix = self._deepest_unmet_chain(edge.source_node_id, mastery, visited)
            candidate_chains.append(
                [*prefix, node_id] if prefix else [edge.source_node_id, node_id]
            )
        return max(candidate_chains, key=lambda chain: (len(chain), tuple(chain)))

    def _apply_preference(
        self, nodes: list[GraphNode], preference: RoutePreference
    ) -> list[GraphNode]:
        if preference not in {RoutePreference.PROJECT_FIRST, RoutePreference.THEORY_FIRST}:
            return nodes
        position = {node.id: index for index, node in enumerate(nodes)}
        graph = self._directed_graph(RelationType.PREREQUISITE).subgraph(position).copy()

        def preference_key(node_id: str) -> tuple[int, int, int]:
            node = self._nodes[node_id]
            if preference is RoutePreference.PROJECT_FIRST:
                type_rank = 0 if node.node_type is NodeType.PROJECT else 1
            else:
                type_rank = 0 if node.node_type in {NodeType.CONCEPT, NodeType.MODULE} else 1
            return (type_rank, node.difficulty, position[node_id])

        return [
            self._nodes[node_id]
            for node_id in nx.lexicographical_topological_sort(graph, key=preference_key)
        ]
