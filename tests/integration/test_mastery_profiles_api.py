"""API coverage for the evidence-backed four-dimensional learner profile."""

from typing import Any

from fastapi.testclient import TestClient

DIMENSIONS = (
    "concept_understanding",
    "procedural_skill",
    "application_skill",
    "memory_strength",
)


def _measurements(score: float) -> list[dict[str, Any]]:
    return [{"dimension": dimension, "score": score} for dimension in DIMENSIONS]


def test_missing_profile_is_unassessed_instead_of_assumed_zero_mastery(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    node_id = str(python_map["nodes"]["变量"])  # type: ignore[index]

    response = client.get(f"/api/nodes/{node_id}/mastery-profile")

    assert response.status_code == 200, response.text
    profile = response.json()
    assert set(profile["status"]) == set(DIMENSIONS)
    assert all(item["verification_status"] == "UNASSESSED" for item in profile["status"].values())
    assert profile["readiness"]["allowed"] is False


def test_self_report_is_visible_but_does_not_unlock_verified_route_mastery(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space_id = str(python_map["space"]["id"])  # type: ignore[index]
    node_id = str(python_map["nodes"]["变量"])  # type: ignore[index]

    response = client.post(
        f"/api/nodes/{node_id}/mastery-profile/evidence",
        json={
            "kind": "SELF_REPORT",
            "measurements": _measurements(90),
            "evidence_confidence": 1,
            "note": "基线自评",
        },
    )

    assert response.status_code == 201, response.text
    profile = response.json()["profile"]
    assert all(
        item["verification_status"] == "SELF_REPORTED" for item in profile["status"].values()
    )
    assert profile["readiness"]["allowed"] is False
    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    node = next(item for item in graph["nodes"] if item["id"] == node_id)
    assert node["mastery"]["mastery_level"] == 0


def test_verified_multi_dimension_evidence_advances_the_legacy_route_projection(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    space_id = str(python_map["space"]["id"])  # type: ignore[index]
    node_id = str(python_map["nodes"]["变量"])  # type: ignore[index]

    response = client.post(
        f"/api/nodes/{node_id}/mastery-profile/evidence",
        json={
            "kind": "PROJECT",
            "measurements": _measurements(85),
            "evidence_confidence": 1,
            "note": "完成综合项目验证",
        },
    )

    assert response.status_code == 201, response.text
    profile = response.json()["profile"]
    assert profile["readiness"]["allowed"] is True
    assert all(item["verification_status"] == "VERIFIED" for item in profile["status"].values())
    graph = client.get(f"/api/spaces/{space_id}/graph").json()
    node = next(item for item in graph["nodes"] if item["id"] == node_id)
    assert node["mastery"]["mastery_level"] == 4
    assert profile["algorithm_version"] == "mastery-dimensions-v1"


def test_duplicate_dimension_measurements_are_rejected(
    client: TestClient,
    python_map: dict[str, object],
) -> None:
    node_id = str(python_map["nodes"]["变量"])  # type: ignore[index]
    duplicate = [
        {"dimension": "concept_understanding", "score": 70},
        {"dimension": "concept_understanding", "score": 80},
    ]

    response = client.post(
        f"/api/nodes/{node_id}/mastery-profile/evidence",
        json={"kind": "EXERCISE", "measurements": duplicate},
    )

    assert response.status_code == 422
