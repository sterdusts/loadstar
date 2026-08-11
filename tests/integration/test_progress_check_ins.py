"""Durable daily progress check-ins stay scoped, monotonic and explicitly correctable."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.infrastructure.database.models import (
    AuditLogModel,
    LearnerNodeStateModel,
    LearningEvidenceModel,
    LearningSessionModel,
    NodeProgressCheckInModel,
    UserModel,
)


def _create_goal(
    client: TestClient,
    python_map: dict[str, object],
    *,
    title: str,
) -> dict[str, Any]:
    space = python_map["space"]
    nodes = python_map["nodes"]
    assert isinstance(space, dict)
    assert isinstance(nodes, dict)
    response = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": nodes["小型文件处理项目"],
            "title": title,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _check_in_url(goal_id: str, node_id: str) -> str:
    return f"/api/goals/{goal_id}/nodes/{node_id}/check-ins"


def _seed_prior_check_in(
    client: TestClient,
    *,
    goal: dict[str, Any],
    node_id: str,
    score: int,
) -> NodeProgressCheckInModel:
    now = datetime.now(UTC)
    with client.app.state.session_factory.begin() as session:
        row = NodeProgressCheckInModel(
            user_id=goal["user_id"],
            goal_id=goal["id"],
            node_id=node_id,
            checked_in_at=now - timedelta(days=1),
            check_in_date=(now - timedelta(days=1)).astimezone().date(),
            score=score,
            note="昨天的记录",
            row_version=1,
        )
        session.add(row)
        session.flush()
        row_id = row.id
    with client.app.state.session_factory() as session:
        persisted = session.get(NodeProgressCheckInModel, row_id)
        assert persisted is not None
        session.expunge(persisted)
        return persisted


@pytest.mark.integration
def test_progress_check_in_is_daily_scoped_and_does_not_mutate_learning_state(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="每日打卡")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["变量"])
    url = _check_in_url(goal["id"], node_id)

    assert client.post(url, json={"score": 0}).status_code == 422
    assert client.post(url, json={"score": 11}).status_code == 422

    growth_before = client.get("/api/growth?days=7").json()
    created = client.post(url, json={"score": 4, "note": "  完成基础梳理  "})
    assert created.status_code == 201, created.text
    check_in = created.json()
    assert check_in["score"] == 4
    assert check_in["note"] == "完成基础梳理"
    assert check_in["row_version"] == 1
    assert check_in["corrected_at"] is None

    timeline = client.get(url)
    assert timeline.status_code == 200, timeline.text
    payload = timeline.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [check_in["id"]]
    assert payload["current_score"] == 4
    assert payload["today_check_in"]["id"] == check_in["id"]

    duplicate = client.post(url, json={"score": 4, "note": "重复点击"})
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"]["code"] == "duplicate_progress_check_in"

    growth_after = client.get("/api/growth?days=7").json()
    assert growth_after == growth_before
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(LearningSessionModel)) == 0
        assert session.scalar(select(func.count()).select_from(LearningEvidenceModel)) == 0
        assert session.scalar(select(func.count()).select_from(LearnerNodeStateModel)) == 0
        audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "CREATE_PROGRESS_CHECK_IN",
                AuditLogModel.entity_id == check_in["id"],
            )
        )
        assert audit is not None
        assert audit.after_state is not None and audit.after_state["score"] == 4


@pytest.mark.integration
def test_new_score_cannot_decrease_but_explicit_revision_checked_edit_can(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="允许纠错")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["条件"])
    url = _check_in_url(goal["id"], node_id)
    _seed_prior_check_in(client, goal=goal, node_id=node_id, score=7)

    regressed = client.post(url, json={"score": 6})
    assert regressed.status_code == 409, regressed.text
    assert regressed.json()["detail"]["code"] == "progress_score_regression"

    held = client.post(url, json={"score": 7, "note": "今天保持"})
    assert held.status_code == 201, held.text
    current = held.json()

    assert (
        client.patch(
            f"/api/progress-check-ins/{current['id']}",
            json={"expected_revision": 1},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/progress-check-ins/{current['id']}",
            json={"expected_revision": 1, "score": None},
        ).status_code
        == 422
    )

    corrected = client.patch(
        f"/api/progress-check-ins/{current['id']}",
        json={"expected_revision": 1, "score": 5, "note": "修正误点"},
    )
    assert corrected.status_code == 200, corrected.text
    correction = corrected.json()
    assert correction["score"] == 5
    assert correction["note"] == "修正误点"
    assert correction["row_version"] == 2
    assert correction["corrected_at"] is not None

    stale = client.patch(
        f"/api/progress-check-ins/{current['id']}",
        json={"expected_revision": 1, "score": 6},
    )
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "progress_check_in_revision_conflict"
    assert detail["expected_revision"] == 1
    assert detail["current_revision"] == 2

    timeline = client.get(url).json()
    assert timeline["current_score"] == 5
    assert timeline["today_check_in"]["row_version"] == 2

    rising_node_id = str(nodes["循环"])
    _seed_prior_check_in(client, goal=goal, node_id=rising_node_id, score=4)
    increased = client.post(
        _check_in_url(goal["id"], rising_node_id),
        json={"score": 8, "note": "进度提升"},
    )
    assert increased.status_code == 201, increased.text
    assert increased.json()["score"] == 8

    with client.app.state.session_factory() as session:
        audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "UPDATE_PROGRESS_CHECK_IN",
                AuditLogModel.entity_id == current["id"],
            )
        )
        assert audit is not None
        assert audit.details["score_decreased"] is True
        assert audit.before_state is not None and audit.before_state["score"] == 7
        assert audit.after_state is not None and audit.after_state["score"] == 5


@pytest.mark.integration
def test_progress_check_ins_are_isolated_by_goal_space_node_and_user(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    first_goal = _create_goal(client, python_map, title="项目一")
    second_goal = _create_goal(client, python_map, title="项目二")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["循环"])

    created = client.post(
        _check_in_url(first_goal["id"], node_id),
        json={"score": 3},
    )
    assert created.status_code == 201, created.text
    check_in_id = created.json()["id"]

    second_timeline = client.get(_check_in_url(second_goal["id"], node_id))
    assert second_timeline.status_code == 200, second_timeline.text
    assert second_timeline.json()["items"] == []
    assert second_timeline.json()["current_score"] is None

    foreign_space = client.post("/api/spaces", json={"title": "另一个空间"}).json()
    foreign_node = client.post(
        f"/api/spaces/{foreign_space['id']}/nodes",
        json={"title": "跨空间节点", "node_type": "CONCEPT", "difficulty": 1},
    ).json()
    mismatch = client.post(
        _check_in_url(first_goal["id"], foreign_node["id"]),
        json={"score": 2},
    )
    assert mismatch.status_code == 404, mismatch.text

    with client.app.state.session_factory.begin() as session:
        other = UserModel(display_name="Other user")
        session.add(other)
        session.flush()
        other_user_id = other.id
    headers = {"X-User-ID": other_user_id}
    assert client.get(_check_in_url(first_goal["id"], node_id), headers=headers).status_code == 404
    assert (
        client.patch(
            f"/api/progress-check-ins/{check_in_id}",
            headers=headers,
            json={"expected_revision": 1, "score": 2},
        ).status_code
        == 404
    )

    owner_timeline = client.get(_check_in_url(first_goal["id"], node_id)).json()
    assert owner_timeline["total"] == 1
    assert owner_timeline["items"][0]["score"] == 3


@pytest.mark.integration
def test_dashboard_projects_latest_active_route_check_in_and_recent_summary(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Dashboard progress projection")
    generated = client.post(f"/api/goals/{goal['id']}/paths")
    assert generated.status_code == 200, generated.text

    before = client.get("/api/dashboard")
    assert before.status_code == 200, before.text
    overview = next(
        item for item in before.json()["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    assert overview["route_overview"]
    node_id = overview["route_overview"][0]["node_id"]
    _seed_prior_check_in(client, goal=goal, node_id=node_id, score=4)

    created = client.post(
        _check_in_url(goal["id"], node_id),
        json={"score": 6, "note": "路线展示进度"},
    )
    assert created.status_code == 201, created.text

    after = client.get("/api/dashboard")
    assert after.status_code == 200, after.text
    refreshed = next(
        item for item in after.json()["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    route_item = next(item for item in refreshed["route_overview"] if item["node_id"] == node_id)
    assert route_item["progress_score"] == 6
    assert route_item["progress_checked_in_at"] == created.json()["checked_in_at"]
    assert route_item["display_progress_state"] == "IN_PROGRESS"
    assert refreshed["current_position"]["node_id"] == node_id
    assert refreshed["recent_check_ins"][0] == {
        "id": created.json()["id"],
        "node_id": node_id,
        "title": route_item["title"],
        "score": 6,
        "note": "路线展示进度",
        "checked_in_at": created.json()["checked_in_at"],
        "check_in_date": created.json()["check_in_date"],
        "display_progress_state": "IN_PROGRESS",
    }


@pytest.mark.integration
def test_reset_without_history_is_an_idempotent_no_op(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Empty progress reset")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    reset_url = f"{_check_in_url(goal['id'], node_id)}/reset"

    assert (
        client.post(
            reset_url,
            json={"expected_check_in_id": "stale-id", "expected_revision": None},
        ).status_code
        == 422
    )
    response = client.post(
        reset_url,
        json={"expected_check_in_id": None, "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "current_score": 0,
        "display_progress_state": "NOT_STARTED",
        "changed": False,
        "check_in": None,
    }
    assert client.get(_check_in_url(goal["id"], node_id)).json()["total"] == 0


@pytest.mark.integration
def test_reset_today_preserves_note_is_auditable_and_is_safely_repeatable(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Reset today's progress")
    generated = client.post(f"/api/goals/{goal['id']}/paths")
    assert generated.status_code == 200, generated.text
    dashboard = client.get("/api/dashboard").json()
    overview = next(
        item for item in dashboard["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    node_id = overview["route_overview"][0]["node_id"]
    check_in_url = _check_in_url(goal["id"], node_id)
    created_response = client.post(check_in_url, json={"score": 6, "note": "keep this note"})
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()

    with client.app.state.session_factory() as session:
        untouched_counts = {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (LearningSessionModel, LearningEvidenceModel, LearnerNodeStateModel)
        }

    reset_url = f"{check_in_url}/reset"
    payload = {
        "expected_check_in_id": created["id"],
        "expected_revision": created["row_version"],
    }
    reset = client.post(reset_url, json=payload)
    assert reset.status_code == 200, reset.text
    result = reset.json()
    assert result["changed"] is True
    assert result["current_score"] == 0
    assert result["display_progress_state"] == "NOT_STARTED"
    assert result["check_in"]["id"] == created["id"]
    assert result["check_in"]["score"] == 0
    assert result["check_in"]["note"] == "keep this note"
    assert result["check_in"]["row_version"] == 2
    assert result["check_in"]["corrected_at"] is not None

    # Replaying the pre-reset token is a no-op, not a second mutation.
    repeated = client.post(reset_url, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["changed"] is False
    assert repeated.json()["check_in"]["row_version"] == 2

    timeline = client.get(check_in_url).json()
    assert timeline["total"] == 1
    assert timeline["current_score"] == 0
    assert timeline["items"][0]["score"] == 0
    assert timeline["items"][0]["note"] == "keep this note"
    assert client.post(check_in_url, json={"score": 0}).status_code == 422
    assert (
        client.patch(
            f"/api/progress-check-ins/{created['id']}",
            json={"expected_revision": 2, "score": 0},
        ).status_code
        == 422
    )

    refreshed = client.get("/api/dashboard").json()
    refreshed_overview = next(
        item for item in refreshed["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    route_item = next(
        item for item in refreshed_overview["route_overview"] if item["node_id"] == node_id
    )
    assert route_item["progress_score"] == 0
    assert route_item["display_progress_state"] == "NOT_STARTED"
    assert refreshed_overview["current_position"]["node_id"] == node_id
    assert refreshed_overview["recent_check_ins"][0]["score"] == 0
    assert refreshed_overview["recent_check_ins"][0]["display_progress_state"] == "NOT_STARTED"

    with client.app.state.session_factory() as session:
        assert {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (LearningSessionModel, LearningEvidenceModel, LearnerNodeStateModel)
        } == untouched_counts
        reset_audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "RESET_PROGRESS_CHECK_IN",
                    AuditLogModel.entity_id == created["id"],
                )
            )
        )
        assert len(reset_audits) == 1
        assert reset_audits[0].before_state["score"] == 6
        assert reset_audits[0].after_state["score"] == 0
        assert reset_audits[0].details["reset_mode"] == "UPDATE_TODAY"


@pytest.mark.integration
def test_reset_after_an_older_check_in_creates_today_marker_and_checks_snapshot(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Reset prior progress")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    prior = _seed_prior_check_in(client, goal=goal, node_id=node_id, score=8)
    reset_url = f"{_check_in_url(goal['id'], node_id)}/reset"

    missing_snapshot = client.post(
        reset_url,
        json={"expected_check_in_id": None, "expected_revision": None},
    )
    assert missing_snapshot.status_code == 409, missing_snapshot.text
    assert missing_snapshot.json()["detail"]["current_check_in_id"] == prior.id

    stale = client.post(
        reset_url,
        json={"expected_check_in_id": "another-row", "expected_revision": 1},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"] == {
        "code": "progress_check_in_revision_conflict",
        "message": stale.json()["detail"]["message"],
        "expected_revision": 1,
        "current_revision": 1,
        "expected_check_in_id": "another-row",
        "current_check_in_id": prior.id,
    }

    reset = client.post(
        reset_url,
        json={"expected_check_in_id": prior.id, "expected_revision": prior.row_version},
    )
    assert reset.status_code == 200, reset.text
    result = reset.json()
    assert result["changed"] is True
    assert result["check_in"]["id"] != prior.id
    assert result["check_in"]["score"] == 0
    assert result["check_in"]["row_version"] == 1

    timeline = client.get(_check_in_url(goal["id"], node_id)).json()
    assert timeline["total"] == 2
    assert [item["score"] for item in timeline["items"]] == [0, 8]
    with client.app.state.session_factory() as session:
        audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "RESET_PROGRESS_CHECK_IN",
                AuditLogModel.entity_id == result["check_in"]["id"],
            )
        )
        assert audit is not None
        assert audit.details["reset_mode"] == "CREATE_RESET_MARKER"
        assert audit.details["previous_check_in_id"] == prior.id
