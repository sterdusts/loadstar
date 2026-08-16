"""Pure unit tests for dashboard current-item prioritization."""

import pytest

from learning_navigator.application.services import _select_current_dashboard_item


@pytest.mark.parametrize(
    ("items", "expected_node_id"),
    [
        pytest.param(
            [
                {"node_id": "available", "status": "AVAILABLE"},
                {"node_id": "progress", "status": "IN_PROGRESS"},
                {"node_id": "review", "status": "NEEDS_REVIEW"},
            ],
            "review",
            id="review-before-progress-and-available",
        ),
        pytest.param(
            [
                {"node_id": "available", "status": "AVAILABLE"},
                {"node_id": "progress", "status": "IN_PROGRESS"},
            ],
            "progress",
            id="progress-before-available",
        ),
        pytest.param(
            [{"node_id": "available", "status": "AVAILABLE"}],
            "available",
            id="available-fallback",
        ),
        pytest.param(
            [
                {"node_id": "mastered", "status": "MASTERED"},
                {"node_id": "blocked", "status": "BLOCKED"},
            ],
            None,
            id="no-actionable-item",
        ),
        pytest.param([], None, id="empty-route"),
    ],
)
def test_select_current_dashboard_item_uses_explicit_status_priority(
    items: list[dict[str, str]],
    expected_node_id: str | None,
) -> None:
    current = _select_current_dashboard_item(items)

    assert (current or {}).get("node_id") == expected_node_id


def test_select_current_dashboard_item_preserves_route_order_within_status() -> None:
    items = [
        {"node_id": "first-review", "status": "NEEDS_REVIEW"},
        {"node_id": "second-review", "status": "NEEDS_REVIEW"},
    ]

    assert _select_current_dashboard_item(items) == items[0]


def test_select_current_dashboard_item_uses_check_in_progress_and_skips_completed() -> None:
    items = [
        {
            "node_id": "completed",
            "status": "NEEDS_REVIEW",
            "progress_score": 10,
            "display_progress_state": "COMPLETED",
        },
        {
            "node_id": "checked-in",
            "status": "AVAILABLE",
            "progress_score": 4,
            "display_progress_state": "IN_PROGRESS",
        },
        {
            "node_id": "legacy-review",
            "status": "NEEDS_REVIEW",
            "progress_score": None,
            "display_progress_state": "IN_PROGRESS",
        },
    ]

    assert _select_current_dashboard_item(items) == items[1]


def test_select_current_dashboard_item_can_advance_to_unstarted_soft_blocked_step() -> None:
    items = [
        {
            "node_id": "completed",
            "status": "AVAILABLE",
            "progress_score": 10,
            "display_progress_state": "COMPLETED",
        },
        {
            "node_id": "next",
            "status": "BLOCKED",
            "progress_score": None,
            "display_progress_state": "NOT_STARTED",
        },
    ]

    assert _select_current_dashboard_item(items) == items[1]


def test_select_current_dashboard_item_does_not_special_case_legacy_zero_markers() -> None:
    items = [
        {
            "node_id": "reset",
            "status": "MASTERED",
            "progress_score": 0,
            "display_progress_state": "NOT_STARTED",
        },
        {
            "node_id": "available",
            "status": "AVAILABLE",
            "progress_score": None,
            "display_progress_state": "NOT_STARTED",
        },
    ]

    assert _select_current_dashboard_item(items) == items[1]
