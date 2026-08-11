"""Persistence and AI boundaries consumed by application services."""

from __future__ import annotations

from typing import Protocol

from learning_navigator.domain.entities import GraphEdge, GraphNode, LearnerSnapshot


class KnowledgeRepository(Protocol):
    def load_graph(
        self, space_id: str, map_version_id: str | None = None
    ) -> tuple[str, list[GraphNode], list[GraphEdge]]: ...

    def get_mastery(self, user_id: str, node_ids: set[str]) -> dict[str, LearnerSnapshot]: ...
