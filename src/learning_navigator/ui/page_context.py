"""Safe, explicit context passed from a page to the global AI assistant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MAX_PAGE_STEPS = 40


def _bounded(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized[:limit] or None


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return min(max(normalized, minimum), maximum)


def _safe_page_node(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    node: dict[str, Any] = {}
    for key, limit in (("node_id", 128), ("name", 240), ("status", 64)):
        item = _bounded(value.get(key), limit)
        if item:
            node[key] = item
    position = _bounded_int(value.get("path_position"), minimum=1, maximum=10_000)
    if position is not None:
        node["path_position"] = position
    score = _bounded_int(value.get("score"), minimum=0, maximum=10)
    if score is not None:
        node["score"] = score
    return node or None


def _safe_page_state(value: Any) -> dict[str, Any] | None:
    """Keep visible state useful to AI without accepting arbitrary page or DOM data."""

    if not isinstance(value, dict):
        return None
    state: dict[str, Any] = {}
    project_title = _bounded(value.get("project_title"), 240)
    if project_title:
        state["project_title"] = project_title
    current_node = _safe_page_node(value.get("current_node"))
    if current_node:
        state["current_node"] = current_node

    raw_path = value.get("path_summary")
    if isinstance(raw_path, dict):
        path: dict[str, Any] = {}
        for key in ("total", "completed", "in_progress", "not_started"):
            item = _bounded_int(raw_path.get(key), minimum=0, maximum=10_000)
            if item is not None:
                path[key] = item
        raw_steps = raw_path.get("steps")
        if isinstance(raw_steps, list):
            steps: list[dict[str, Any]] = []
            for raw in raw_steps[:_MAX_PAGE_STEPS]:
                node = _safe_page_node(raw)
                if node is not None:
                    steps.append(node)
            if steps:
                path["steps"] = steps
        if path:
            state["path_summary"] = path

    raw_progress = value.get("progress_summary")
    if isinstance(raw_progress, dict):
        progress: dict[str, Any] = {}
        percent = _bounded_int(raw_progress.get("percent"), minimum=0, maximum=100)
        if percent is not None:
            progress["percent"] = percent
        for key in ("completed", "total"):
            item = _bounded_int(raw_progress.get(key), minimum=0, maximum=10_000)
            if item is not None:
                progress[key] = item
        if progress:
            state["progress_summary"] = progress
    return state or None


@dataclass(frozen=True, slots=True)
class AssistantPageContext:
    """A whitelist-only page snapshot; it never inspects page DOM or form values."""

    page_key: str
    page_kind: str
    page_title: str
    section: str | None = None
    space_id: str | None = None
    goal_id: str | None = None
    node_id: str | None = None
    path_revision_id: str | None = None
    page_state: dict[str, Any] | None = None

    @classmethod
    def page(
        cls,
        *,
        page_key: str,
        page_title: str,
        page_kind: str = "PAGE",
        section: str | None = None,
        page_state: dict[str, Any] | None = None,
    ) -> AssistantPageContext:
        return cls(
            page_key=_bounded(page_key, 120) or "home",
            page_kind=_bounded(page_kind, 32) or "PAGE",
            page_title=_bounded(page_title, 160) or "当前页面",
            section=_bounded(section, 64),
            page_state=_safe_page_state(page_state),
        )

    @classmethod
    def project(
        cls,
        *,
        goal_id: str,
        space_id: str,
        page_title: str,
        section: str,
        node_id: str | None = None,
        path_revision_id: str | None = None,
        page_state: dict[str, Any] | None = None,
    ) -> AssistantPageContext:
        return cls(
            page_key="project",
            page_kind="PROJECT",
            page_title=_bounded(page_title, 160) or "当前项目",
            section=_bounded(section, 64),
            space_id=_bounded(space_id, 80),
            goal_id=_bounded(goal_id, 80),
            node_id=_bounded(node_id, 80),
            path_revision_id=_bounded(path_revision_id, 80),
            page_state=_safe_page_state(page_state),
        )

    @property
    def purpose(self) -> str:
        return "PROJECT_ASSISTANT" if self.goal_id and self.space_id else "PAGE_ASSISTANT"

    @property
    def context_key(self) -> str:
        if self.goal_id and self.space_id:
            return f"project:{self.goal_id}"
        return f"page:{self.page_key}"

    @property
    def display_label(self) -> str:
        if self.section:
            return f"{self.page_title} · {self.section_label}"
        return self.page_title

    @property
    def section_label(self) -> str:
        labels = {
            "overview": "概览",
            "collaboration": "AI 协作",
            "map": "框架",
            "path": "路径",
            "progress": "进展",
        }
        return labels.get(str(self.section or ""), str(self.section or "当前页面"))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page_key": self.page_key,
            "page_kind": self.page_kind,
            "page_title": self.page_title,
        }
        for key in (
            "section",
            "space_id",
            "goal_id",
            "node_id",
            "path_revision_id",
        ):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.page_state:
            payload["page_state"] = self.page_state
        return payload
