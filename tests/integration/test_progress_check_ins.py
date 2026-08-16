"""Durable daily progress check-ins stay scoped, monotonic and explicitly correctable."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from learning_navigator.infrastructure.database.models import (
    AuditLogModel,
    LearnerNodeStateModel,
    LearningEvidenceModel,
    LearningSessionModel,
    NodeProgressCheckInModel,
    ProgressCheckInAttachmentModel,
    ProgressCheckInClearBatchModel,
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


@pytest.mark.integration
def test_check_in_attachments_stream_persist_download_and_delete_without_size_limit(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="带附件的打卡")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["变量"])
    check_in_url = _check_in_url(goal["id"], node_id)
    created = client.post(check_in_url, json={"score": 2, "note": "上传学习截图"})
    assert created.status_code == 201, created.text
    assert created.json()["duration_minutes"] == 60
    check_in_id = created.json()["id"]

    # Larger-than-a-thumbnail payload verifies raw streaming rather than JSON/Base64.
    content = b"\x89PNG\r\n\x1a\n" + (b"frame-attachment" * 262_144)
    filename = "数学推导截图.png"
    uploaded = client.post(
        f"/api/progress-check-ins/{check_in_id}/attachments",
        content=content,
        headers={
            "Content-Type": "image/png",
            "X-File-Name": quote(filename, safe=""),
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    assert attachment["original_name"] == filename
    assert attachment["media_type"] == "image/png"
    assert attachment["size_bytes"] == len(content)
    assert attachment["sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage_key" not in attachment

    timeline = client.get(check_in_url)
    assert timeline.status_code == 200, timeline.text
    timeline_attachment = timeline.json()["items"][0]["attachments"][0]
    assert timeline_attachment == attachment
    assert timeline.json()["today_check_in"]["attachments"] == [attachment]

    growth = client.get("/api/growth?days=7")
    assert growth.status_code == 200, growth.text
    growth_summary = growth.json()["summary"]
    assert growth_summary["upload_event_count"] == 1
    assert growth_summary["uploaded_file_count"] == 1
    assert growth_summary["total_learning_minutes"] == 60

    viewed = client.get(attachment["content_url"])
    assert viewed.status_code == 200, viewed.text
    assert viewed.content == content
    assert viewed.headers["content-type"] == "image/png"
    assert viewed.headers["content-disposition"].startswith("inline")
    downloaded = client.get(attachment["download_url"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content
    assert downloaded.headers["content-disposition"].startswith("attachment")

    with client.app.state.session_factory() as session:
        persisted = session.get(ProgressCheckInAttachmentModel, attachment["id"])
        assert persisted is not None
        stored_path = client.app.state.check_in_attachment_storage.path_for(persisted.storage_key)
        assert stored_path.is_file()
        assert stored_path.stat().st_size == len(content)

    removed = client.delete(f"/api/progress-check-in-attachments/{attachment['id']}")
    assert removed.status_code == 204, removed.text
    assert not stored_path.exists()
    assert client.get(attachment["content_url"]).status_code == 404
    after = client.get(check_in_url).json()
    assert after["items"][0]["attachments"] == []


@pytest.mark.integration
def test_check_in_ai_evaluation_uses_note_files_and_time_without_mutating_mastery(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="AI 评语边界")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["变量"])
    check_in_url = _check_in_url(goal["id"], node_id)

    created = client.post(
        check_in_url,
        json={
            "score": 3,
            "note": "完成了三道练习，第二题的分数运算仍会出错。",
            "duration_minutes": 75,
        },
    )
    assert created.status_code == 201, created.text
    check_in_id = created.json()["id"]

    uploaded = client.post(
        f"/api/progress-check-ins/{check_in_id}/attachments",
        content="题目一正确；题目二通分错误；订正后结果正确。".encode(),
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-File-Name": quote("练习订正.txt", safe=""),
        },
    )
    assert uploaded.status_code == 201, uploaded.text

    evaluated = client.post(
        f"/api/progress-check-ins/{check_in_id}/ai-evaluation",
        json={"confirmed_external_ai": True},
    )
    assert evaluated.status_code == 200, evaluated.text
    payload = evaluated.json()
    assert payload["duration_minutes"] == 75
    assert payload["ai_evaluated_at"] is not None
    assert payload["ai_evaluation"]["summary"]
    assert payload["ai_evaluation"]["concept_understanding"]["comment"]
    assert payload["ai_evaluation"]["limitations"]
    assert len(payload["attachments"]) == 1

    timeline = client.get(check_in_url).json()
    assert timeline["items"][0]["ai_evaluation"] == payload["ai_evaluation"]
    assert timeline["items"][0]["duration_minutes"] == 75

    exact = client.get(f"{check_in_url}/{check_in_id}")
    assert exact.status_code == 200, exact.text
    assert exact.json()["id"] == check_in_id
    assert exact.json()["ai_evaluation"] == payload["ai_evaluation"]
    assert exact.json()["attachments"] == payload["attachments"]

    other_goal = _create_goal(client, python_map, title="另一个项目不能读取这次打卡")
    wrong_scope = client.get(f"{_check_in_url(other_goal['id'], node_id)}/{check_in_id}")
    assert wrong_scope.status_code == 404, wrong_scope.text

    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(LearningSessionModel)) == 0
        assert session.scalar(select(func.count()).select_from(LearningEvidenceModel)) == 0
        assert session.scalar(select(func.count()).select_from(LearnerNodeStateModel)) == 0
        audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "EVALUATE_PROGRESS_CHECK_IN",
                AuditLogModel.entity_id == check_in_id,
            )
        )
        assert audit is not None
        assert audit.details is not None
        assert audit.details["attachment_count"] == 1
        assert audit.details["text_excerpt_count"] == 1


@pytest.mark.integration
def test_attachment_upload_requires_an_owned_check_in_and_a_file_name(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="附件边界")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(nodes["变量"])
    created = client.post(
        _check_in_url(goal["id"], node_id),
        json={"score": 1},
    ).json()

    missing_name = client.post(
        f"/api/progress-check-ins/{created['id']}/attachments",
        content=b"content",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert missing_name.status_code == 400, missing_name.text
    assert missing_name.json()["detail"]["code"] == "attachment_name_required"

    unknown = client.post(
        "/api/progress-check-ins/not-owned/attachments",
        content=b"content",
        headers={
            "Content-Type": "application/octet-stream",
            "X-File-Name": "evidence.txt",
        },
    )
    assert unknown.status_code == 404, unknown.text


@pytest.mark.integration
def test_active_image_formats_are_forced_to_download(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="SVG attachment boundary")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    created = client.post(
        _check_in_url(goal["id"], node_id),
        json={"score": 1, "note": "SVG safety boundary"},
    )
    assert created.status_code == 201, created.text

    uploaded = client.post(
        f"/api/progress-check-ins/{created.json()['id']}/attachments",
        content=b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        headers={
            "Content-Type": "image/svg+xml",
            "X-File-Name": "diagram.svg",
        },
    )
    assert uploaded.status_code == 201, uploaded.text

    viewed = client.get(uploaded.json()["content_url"])
    assert viewed.status_code == 200
    assert viewed.headers["content-disposition"].startswith("attachment")


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
def test_progress_check_in_is_daily_scoped_updates_growth_without_mutating_learning_state(
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
    assert growth_before["summary"]["total_check_ins"] == 0
    assert growth_after["summary"]["total_check_ins"] == 1
    assert growth_after["summary"]["tracked_nodes"] == 1
    assert growth_after["summary"]["touched_nodes"] == 1
    assert growth_after["check_ins"][0]["id"] == check_in["id"]
    assert growth_after["check_ins"][0]["note"] == "完成基础梳理"
    assert sum(item["check_in_count"] for item in growth_after["series"]) == 1
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
def test_completed_check_in_satisfies_route_prerequisite_and_uses_live_node_title(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="打卡与路径统一投影")
    generated = client.post(f"/api/goals/{goal['id']}/paths")
    assert generated.status_code == 200, generated.text
    overview = next(
        item
        for item in client.get("/api/dashboard").json()["goal_overviews"]
        if item["goal"]["id"] == goal["id"]
    )
    dependent = next(item for item in overview["route_overview"] if item["unmet_prerequisites"])
    prerequisite_id = dependent["unmet_prerequisites"][0]

    completed = client.post(
        _check_in_url(goal["id"], prerequisite_id),
        json={"score": 10, "note": "完成前置"},
    )
    assert completed.status_code == 201, completed.text

    new_title = "手工编辑后的前置名称"
    updated = client.patch(
        f"/api/spaces/{goal['space_id']}/nodes/{prerequisite_id}",
        json={"title": new_title},
    )
    assert updated.status_code == 200, updated.text

    refreshed = next(
        item
        for item in client.get("/api/dashboard").json()["goal_overviews"]
        if item["goal"]["id"] == goal["id"]
    )
    by_id = {item["node_id"]: item for item in refreshed["route_overview"]}
    assert by_id[prerequisite_id]["title"] == new_title
    assert by_id[prerequisite_id]["status"] == "MASTERED"
    assert prerequisite_id in by_id[dependent["node_id"]]["satisfied_prerequisites"]
    assert prerequisite_id not in by_id[dependent["node_id"]]["unmet_prerequisites"]
    assert refreshed["recent_check_ins"][0]["title"] == new_title


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
def test_clear_without_history_is_an_idempotent_no_op(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Empty progress clear")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    clear_url = f"{_check_in_url(goal['id'], node_id)}/clear"

    assert (
        client.post(
            clear_url,
            json={"expected_check_in_id": "stale-id", "expected_revision": None},
        ).status_code
        == 422
    )
    response = client.post(
        clear_url,
        json={"expected_check_in_id": None, "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "current_score": None,
        "display_progress_state": "NOT_STARTED",
        "changed": False,
        "clear_recovery": None,
    }
    assert client.get(_check_in_url(goal["id"], node_id)).json()["total"] == 0


@pytest.mark.integration
def test_clear_moves_the_complete_timeline_out_of_live_views_and_restores_it(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Clear today's progress")
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
    attachment_content = b"recoverable progress evidence"
    uploaded = client.post(
        f"/api/progress-check-ins/{created['id']}/attachments",
        content=attachment_content,
        headers={"Content-Type": "text/plain", "X-File-Name": "evidence.txt"},
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()

    with client.app.state.session_factory() as session:
        untouched_counts = {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (LearningSessionModel, LearningEvidenceModel, LearnerNodeStateModel)
        }

    clear_url = f"{check_in_url}/clear"
    payload = {
        "expected_check_in_id": created["id"],
        "expected_revision": created["row_version"],
    }
    cleared = client.post(clear_url, json=payload)
    assert cleared.status_code == 200, cleared.text
    result = cleared.json()
    assert result["changed"] is True
    assert result["current_score"] is None
    assert result["display_progress_state"] == "NOT_STARTED"
    recovery = result["clear_recovery"]
    assert recovery["record_count"] == 1
    assert recovery["attachment_count"] == 1

    # A fresh empty-snapshot clear is idempotent and exposes the same recovery batch.
    repeated = client.post(
        clear_url,
        json={"expected_check_in_id": None, "expected_revision": None},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["changed"] is False
    assert repeated.json()["clear_recovery"]["id"] == recovery["id"]

    timeline = client.get(check_in_url).json()
    assert timeline["total"] == 0
    assert timeline["current_score"] is None
    assert timeline["items"] == []
    assert timeline["clear_recovery"]["id"] == recovery["id"]
    assert client.get(attachment["content_url"]).status_code == 404
    assert client.post(check_in_url, json={"score": 0}).status_code == 422
    with client.app.state.session_factory() as session:
        assert session.get(NodeProgressCheckInModel, created["id"]) is None

    refreshed = client.get("/api/dashboard").json()
    refreshed_overview = next(
        item for item in refreshed["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    route_item = next(
        item for item in refreshed_overview["route_overview"] if item["node_id"] == node_id
    )
    assert route_item["progress_score"] is None
    assert route_item["display_progress_state"] == "NOT_STARTED"
    assert refreshed_overview["current_position"]["node_id"] == node_id
    assert all(item["node_id"] != node_id for item in refreshed_overview["recent_check_ins"])
    cleared_growth = client.get("/api/growth?days=7").json()
    assert all(item["id"] != created["id"] for item in cleared_growth["check_ins"])
    assert cleared_growth["summary"]["total_check_ins"] == 0
    assert cleared_growth["summary"]["total_learning_minutes"] == 0
    assert cleared_growth["summary"]["upload_event_count"] == 0
    assert cleared_growth["summary"]["uploaded_file_count"] == 0

    with client.app.state.session_factory() as session:
        assert {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (LearningSessionModel, LearningEvidenceModel, LearnerNodeStateModel)
        } == untouched_counts
        clear_audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "CLEAR_PROGRESS_CHECK_INS",
                    AuditLogModel.entity_id == recovery["id"],
                )
            )
        )
        assert len(clear_audits) == 1
        assert clear_audits[0].details["record_count"] == 1
        assert clear_audits[0].details["recoverable"] is True

    restored = client.post(f"{check_in_url}/clear-recovery/{recovery['id']}/restore")
    assert restored.status_code == 200, restored.text
    restored_timeline = restored.json()
    assert restored_timeline["total"] == 1
    assert restored_timeline["current_score"] == 6
    assert restored_timeline["items"][0]["id"] == created["id"]
    assert restored_timeline["items"][0]["note"] == "keep this note"
    assert restored_timeline["items"][0]["attachments"][0]["id"] == attachment["id"]
    restored_content = client.get(attachment["content_url"])
    assert restored_content.status_code == 200, restored_content.text
    assert restored_content.content == attachment_content
    assert restored_timeline["clear_recovery"] is None
    restored_growth = client.get("/api/growth?days=7").json()
    assert restored_growth["check_ins"][0]["id"] == created["id"]
    assert restored_growth["summary"]["total_check_ins"] == 1
    assert restored_growth["summary"]["upload_event_count"] == 1
    assert restored_growth["summary"]["uploaded_file_count"] == 1


@pytest.mark.integration
def test_recycled_progress_can_be_permanently_deleted_without_touching_the_project(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Permanent recycle-bin deletion")
    generated = client.post(f"/api/goals/{goal['id']}/paths")
    assert generated.status_code == 200, generated.text
    before_dashboard = client.get("/api/dashboard").json()
    before_overview = next(
        item for item in before_dashboard["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    before_route_node_ids = [item["node_id"] for item in before_overview["route_overview"]]
    node_id = str(before_route_node_ids[0])
    check_in_url = _check_in_url(goal["id"], node_id)

    created = client.post(
        check_in_url,
        json={"score": 4, "note": "private note that must leave the recycle bin"},
    )
    assert created.status_code == 201, created.text
    uploaded = client.post(
        f"/api/progress-check-ins/{created.json()['id']}/attachments",
        content=b"private recycled attachment",
        headers={"Content-Type": "text/plain", "X-File-Name": "private.txt"},
    )
    assert uploaded.status_code == 201, uploaded.text

    with client.app.state.session_factory() as session:
        attachment = session.get(ProgressCheckInAttachmentModel, uploaded.json()["id"])
        assert attachment is not None
        storage_key = attachment.storage_key
        stored_path = client.app.state.check_in_attachment_storage.path_for(storage_key)
        assert stored_path.is_file()

    cleared = client.post(
        f"{check_in_url}/clear",
        json={
            "expected_check_in_id": created.json()["id"],
            "expected_revision": created.json()["row_version"],
        },
    )
    assert cleared.status_code == 200, cleared.text
    recovery = cleared.json()["clear_recovery"]
    delete_url = f"{check_in_url}/clear-recovery/{recovery['id']}"
    assert stored_path.is_file(), "clearing must retain attachment bytes until a final decision"

    with client.app.state.session_factory.begin() as session:
        other = UserModel(display_name="Recycle-bin intruder")
        session.add(other)
        session.flush()
        other_user_id = other.id
    denied = client.delete(delete_url, headers={"X-User-ID": other_user_id})
    assert denied.status_code == 404, denied.text
    assert stored_path.is_file()
    assert client.get(check_in_url).json()["clear_recovery"]["id"] == recovery["id"]

    removed = client.delete(delete_url)
    assert removed.status_code == 204, removed.text
    assert not stored_path.exists()
    timeline = client.get(check_in_url).json()
    assert timeline["total"] == 0
    assert timeline["items"] == []
    assert timeline["clear_recovery"] is None
    assert client.post(f"{delete_url}/restore").status_code == 404
    assert client.delete(delete_url).status_code == 404

    after_dashboard = client.get("/api/dashboard").json()
    after_overview = next(
        item for item in after_dashboard["goal_overviews"] if item["goal"]["id"] == goal["id"]
    )
    assert [item["node_id"] for item in after_overview["route_overview"]] == before_route_node_ids

    with client.app.state.session_factory() as session:
        assert session.get(ProgressCheckInClearBatchModel, recovery["id"]) is None
        audit = session.scalar(
            select(AuditLogModel).where(
                AuditLogModel.action == "DELETE_CLEARED_PROGRESS_CHECK_INS",
                AuditLogModel.entity_id == recovery["id"],
            )
        )
        assert audit is not None
        assert audit.before_state is None
        assert audit.after_state is None
        assert audit.details == {
            "goal_id": goal["id"],
            "node_id": node_id,
            "record_count": 1,
            "attachment_count": 1,
            "permanent": True,
            "content_deleted": True,
        }
        assert "private note" not in str(audit.details)
        assert storage_key not in str(audit.details)


@pytest.mark.integration
def test_restore_ignores_a_legacy_synthetic_zero_reset_marker(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    """A pre-recycle-bin zero marker must never return as fabricated progress."""

    goal = _create_goal(client, python_map, title="Legacy reset marker recovery")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    check_in_url = _check_in_url(goal["id"], node_id)
    created = client.post(check_in_url, json={"score": 5, "note": "real progress"})
    assert created.status_code == 201, created.text

    cleared = client.post(
        f"{check_in_url}/clear",
        json={
            "expected_check_in_id": created.json()["id"],
            "expected_revision": created.json()["row_version"],
        },
    )
    assert cleared.status_code == 200, cleared.text
    recovery_id = cleared.json()["clear_recovery"]["id"]

    # Model a migrated old timeline: one real entry plus the synthetic zero
    # reset marker that old releases appended.  The marker is intentionally
    # incomplete because restore must ignore it before payload validation.
    with client.app.state.session_factory() as session:
        batch = session.get(ProgressCheckInClearBatchModel, recovery_id)
        assert batch is not None
        snapshot = dict(batch.snapshot)
        items = list(snapshot["check_ins"])
        items.append(
            {
                "check_in": {"score": 1},
                "attachments": [],
                "legacy_reset_marker": True,
            }
        )
        snapshot["check_ins"] = items
        batch.snapshot = snapshot
        batch.record_count = 2
        session.commit()

    restored = client.post(f"{check_in_url}/clear-recovery/{recovery_id}/restore")
    assert restored.status_code == 200, restored.text
    payload = restored.json()
    assert payload["total"] == 1
    assert payload["current_score"] == 5
    assert payload["items"][0]["id"] == created.json()["id"]
    assert payload["items"][0]["note"] == "real progress"


@pytest.mark.integration
def test_clear_checks_snapshot_and_coalesces_new_progress_into_one_recovery_batch(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Clear prior progress")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    prior = _seed_prior_check_in(client, goal=goal, node_id=node_id, score=8)
    check_in_url = _check_in_url(goal["id"], node_id)
    clear_url = f"{check_in_url}/clear"

    missing_snapshot = client.post(
        clear_url,
        json={"expected_check_in_id": None, "expected_revision": None},
    )
    assert missing_snapshot.status_code == 409, missing_snapshot.text
    assert missing_snapshot.json()["detail"]["current_check_in_id"] == prior.id

    stale = client.post(
        clear_url,
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

    cleared = client.post(
        clear_url,
        json={"expected_check_in_id": prior.id, "expected_revision": prior.row_version},
    )
    assert cleared.status_code == 200, cleared.text
    result = cleared.json()
    assert result["changed"] is True
    recovery = result["clear_recovery"]
    assert recovery["record_count"] == 1

    timeline = client.get(check_in_url).json()
    assert timeline["total"] == 0
    assert timeline["items"] == []

    new_progress = client.post(
        check_in_url,
        json={"score": 3, "note": "new work after clearing"},
    )
    assert new_progress.status_code == 201, new_progress.text
    blocked_restore = client.post(f"{check_in_url}/clear-recovery/{recovery['id']}/restore")
    assert blocked_restore.status_code == 409, blocked_restore.text

    cleared_again = client.post(
        clear_url,
        json={
            "expected_check_in_id": new_progress.json()["id"],
            "expected_revision": new_progress.json()["row_version"],
        },
    )
    assert cleared_again.status_code == 200, cleared_again.text
    merged_recovery = cleared_again.json()["clear_recovery"]
    assert merged_recovery["id"] == recovery["id"]
    assert merged_recovery["record_count"] == 2

    restored = client.post(f"{check_in_url}/clear-recovery/{recovery['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["total"] == 2
    assert [item["score"] for item in restored.json()["items"]] == [3, 8]
    with client.app.state.session_factory() as session:
        audits = list(
            session.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "CLEAR_PROGRESS_CHECK_INS",
                    AuditLogModel.entity_id == recovery["id"],
                )
            )
        )
        assert len(audits) == 2


@pytest.mark.integration
def test_repeated_same_day_clear_restores_one_latest_row_and_all_attachments(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    goal = _create_goal(client, python_map, title="Repeated same-day clear")
    nodes = python_map["nodes"]
    assert isinstance(nodes, dict)
    node_id = str(next(iter(nodes.values())))
    check_in_url = _check_in_url(goal["id"], node_id)
    clear_url = f"{check_in_url}/clear"

    first = client.post(check_in_url, json={"score": 4, "note": "older same-day work"})
    assert first.status_code == 201, first.text
    first_attachment = client.post(
        f"/api/progress-check-ins/{first.json()['id']}/attachments",
        content=b"first evidence",
        headers={"Content-Type": "text/plain", "X-File-Name": "first.txt"},
    )
    assert first_attachment.status_code == 201, first_attachment.text
    first_clear = client.post(
        clear_url,
        json={
            "expected_check_in_id": first.json()["id"],
            "expected_revision": first.json()["row_version"],
        },
    )
    assert first_clear.status_code == 200, first_clear.text
    recovery_id = first_clear.json()["clear_recovery"]["id"]

    latest = client.post(check_in_url, json={"score": 7, "note": "latest same-day work"})
    assert latest.status_code == 201, latest.text
    latest_attachment = client.post(
        f"/api/progress-check-ins/{latest.json()['id']}/attachments",
        content=b"latest evidence",
        headers={"Content-Type": "text/plain", "X-File-Name": "latest.txt"},
    )
    assert latest_attachment.status_code == 201, latest_attachment.text
    second_clear = client.post(
        clear_url,
        json={
            "expected_check_in_id": latest.json()["id"],
            "expected_revision": latest.json()["row_version"],
        },
    )
    assert second_clear.status_code == 200, second_clear.text
    recovery = second_clear.json()["clear_recovery"]
    assert recovery["id"] == recovery_id
    assert recovery["record_count"] == 1
    assert recovery["attachment_count"] == 2

    restored = client.post(f"{check_in_url}/clear-recovery/{recovery_id}/restore")
    assert restored.status_code == 200, restored.text
    payload = restored.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == latest.json()["id"]
    assert payload["items"][0]["score"] == 7
    assert payload["items"][0]["note"] == "latest same-day work"
    assert {item["id"] for item in payload["items"][0]["attachments"]} == {
        first_attachment.json()["id"],
        latest_attachment.json()["id"],
    }
