"""Regression coverage for versioning, portability, AI reverts and ownership."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from learning_navigator.domain.exceptions import InvalidStateTransitionError
from learning_navigator.infrastructure.database.models import KnowledgeMapVersionModel
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)


def _create_space_with_node(
    client: TestClient,
    *,
    space_title: str = "Regression map",
    node_title: str = "Foundation",
    learning_objectives: list[str] | None = None,
    source_basis: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    space_response = client.post("/api/spaces", json={"title": space_title})
    assert space_response.status_code == 201, space_response.text
    space = space_response.json()
    node_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={
            "title": node_title,
            "learning_objectives": learning_objectives or [],
            "source_basis": source_basis or [],
        },
    )
    assert node_response.status_code == 201, node_response.text
    return space, node_response.json()


def _accept_mock_suggestion(client: TestClient) -> dict[str, Any]:
    generated = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "Build a deterministic regression-test learning map."},
    )
    assert generated.status_code == 201, generated.text
    reviewed = client.post(
        f"/api/ai/suggestions/{generated.json()['id']}/review",
        json={"action": "accept"},
    )
    assert reviewed.status_code == 200, reviewed.text
    result = reviewed.json()
    assert result["review_status"] == "ACCEPTED"
    assert result["accepted_changes"]["node_ids"]
    return result


@pytest.mark.integration
def test_node_intro_and_detailed_description_stay_in_sync_across_graph_edits(
    client: TestClient,
) -> None:
    space_response = client.post("/api/spaces", json={"title": "Node explanation map"})
    assert space_response.status_code == 201, space_response.text
    space = space_response.json()

    created_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={
            "title": "Gradient descent",
            "description": "An optimization method that follows the local slope.",
            "detailed_description": (
                "It connects derivatives to iterative optimization, explains why learning-rate "
                "selection matters, and prepares the learner to reason about model training."
            ),
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["description"].startswith("An optimization method")
    assert created["detailed_description"].startswith("It connects derivatives")

    graph_response = client.get(f"/api/spaces/{space['id']}/graph")
    assert graph_response.status_code == 200, graph_response.text
    graph_node = next(
        item for item in graph_response.json()["nodes"] if item["id"] == created["id"]
    )
    assert graph_node["description"] == created["description"]
    assert graph_node["detailed_description"] == created["detailed_description"]

    updated_response = client.patch(
        f"/api/spaces/{space['id']}/nodes/{created['id']}",
        json={
            "description": "A short updated introduction.",
            "detailed_description": "A longer updated explanation for practical learning.",
        },
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["description"] == "A short updated introduction."
    assert updated["detailed_description"] == (
        "A longer updated explanation for practical learning."
    )

    refreshed_graph = client.get(f"/api/spaces/{space['id']}/graph").json()
    refreshed_node = next(item for item in refreshed_graph["nodes"] if item["id"] == created["id"])
    assert refreshed_node["description"] == updated["description"]
    assert refreshed_node["detailed_description"] == updated["detailed_description"]


@pytest.mark.integration
def test_publish_compare_and_restore_keep_version_history_immutable(
    client: TestClient,
) -> None:
    space, original_node = _create_space_with_node(client)
    original_draft_id = space["draft_version_id"]

    publish_response = client.post(
        f"/api/spaces/{space['id']}/versions/publish",
        json={"change_summary": "Reviewed baseline"},
    )
    assert publish_response.status_code == 200, publish_response.text
    publication = publish_response.json()
    published = publication["published"]
    editable = publication["new_draft"]
    assert published["id"] == original_draft_id
    assert published["status"] == "PUBLISHED"
    assert editable["status"] == "DRAFT"
    assert editable["id"] != published["id"]

    with client.app.state.session_factory() as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        with pytest.raises(InvalidStateTransitionError, match="immutable"):
            repository.update_node(
                space_id=space["id"],
                map_version_id=published["id"],
                node_id=original_node["id"],
                user_id=space["owner_id"],
                changes={"title": "Forbidden historical edit"},
            )

    changed_title = "Foundation edited in the new draft"
    update_response = client.patch(
        f"/api/spaces/{space['id']}/nodes/{original_node['id']}",
        json={"title": changed_title},
    )
    assert update_response.status_code == 200, update_response.text
    added_response = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": "Draft-only node"},
    )
    assert added_response.status_code == 201, added_response.text

    comparison_response = client.get(
        f"/api/spaces/{space['id']}/versions/compare",
        params={
            "base_version_id": published["id"],
            "head_version_id": editable["id"],
        },
    )
    assert comparison_response.status_code == 200, comparison_response.text
    comparison = comparison_response.json()
    assert {item["id"] for item in comparison["nodes"]["added"]} == {added_response.json()["id"]}
    changed = {item["node_id"]: item for item in comparison["nodes"]["changed"]}
    assert changed[original_node["id"]]["before"]["title"] == "Foundation"
    assert changed[original_node["id"]]["after"]["title"] == changed_title

    restore_response = client.post(
        f"/api/spaces/{space['id']}/versions/{published['id']}/restore",
        json={"change_summary": "Restore reviewed baseline"},
    )
    assert restore_response.status_code == 200, restore_response.text
    restored = restore_response.json()
    assert restored["status"] == "DRAFT"
    assert restored["id"] not in {published["id"], editable["id"]}
    assert restored["parent_version_id"] == published["id"]

    versions_response = client.get(f"/api/spaces/{space['id']}/versions")
    assert versions_response.status_code == 200, versions_response.text
    versions = {item["id"]: item for item in versions_response.json()}
    assert versions[published["id"]]["status"] == "PUBLISHED"
    assert versions[editable["id"]]["status"] == "SUPERSEDED"
    assert versions[restored["id"]]["status"] == "DRAFT"

    restored_graph = client.get(f"/api/spaces/{space['id']}/graph")
    assert restored_graph.status_code == 200, restored_graph.text
    active_nodes = {
        item["id"]: item for item in restored_graph.json()["nodes"] if item["status"] != "ARCHIVED"
    }
    assert active_nodes[original_node["id"]]["title"] == "Foundation"
    assert added_response.json()["id"] not in active_nodes


@pytest.mark.integration
def test_direct_edit_recovers_legacy_map_without_editable_draft(client: TestClient) -> None:
    """Old maps without a successor draft remain directly editable."""
    space, node = _create_space_with_node(client, space_title="Legacy direct edit")
    published_response = client.post(
        f"/api/spaces/{space['id']}/versions/publish",
        json={"change_summary": "Publish before legacy import"},
    )
    assert published_response.status_code == 200, published_response.text
    published = published_response.json()["published"]
    draft_id = published_response.json()["new_draft"]["id"]

    # Reproduce a legacy/imported project where publication has no successor draft.
    with client.app.state.session_factory() as session:
        draft = session.get(KnowledgeMapVersionModel, draft_id)
        assert draft is not None
        draft.status = "SUPERSEDED"
        session.commit()

    readable_graph = client.get(f"/api/spaces/{space['id']}/graph")
    assert readable_graph.status_code == 200, readable_graph.text

    changed = client.patch(
        f"/api/spaces/{space['id']}/nodes/{node['id']}",
        json={"title": "Edited without a draft"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "Edited without a draft"

    module = client.post(
        f"/api/spaces/{space['id']}/nodes",
        json={"title": "New module", "node_type": "MODULE"},
    )
    assert module.status_code == 201, module.text

    versions = client.get(f"/api/spaces/{space['id']}/versions")
    assert versions.status_code == 200, versions.text
    current_drafts = [item for item in versions.json() if item["status"] == "DRAFT"]
    assert len(current_drafts) == 1
    assert current_drafts[0]["parent_version_id"] == published["id"]
    assert published["status"] == "PUBLISHED"


@pytest.mark.integration
def test_export_contract_contains_complete_portability_sections(client: TestClient) -> None:
    space, node = _create_space_with_node(client, space_title="Portable map")
    goal = client.post(
        "/api/goals",
        json={
            "space_id": space["id"],
            "target_node_id": node["id"],
            "title": "Portable goal",
        },
    )
    assert goal.status_code == 201, goal.text
    path = client.post(f"/api/goals/{goal.json()['id']}/paths")
    assert path.status_code == 200, path.text
    suggestion = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "A pending portable proposal", "space_id": space["id"]},
    )
    assert suggestion.status_code == 201, suggestion.text

    response = client.get("/api/data/export")
    assert response.status_code == 200, response.text
    payload = response.json()
    required_sections = {
        "learning_paths",
        "path_nodes",
        "ai_suggestions",
        "audit",
        "resources",
        "assessments",
    }
    assert required_sections <= payload.keys()
    assert payload["learning_paths"]
    assert payload["path_nodes"]
    assert any(item["id"] == suggestion.json()["id"] for item in payload["ai_suggestions"])
    assert payload["audit"]
    assert isinstance(payload["resources"], list)
    assert isinstance(payload["assessments"], list)


@pytest.mark.integration
def test_export_imports_two_maps_and_preserves_node_provenance(client: TestClient) -> None:
    metadata = {
        "Map alpha": (
            "Alpha node",
            ["Explain alpha"],
            [{"kind": "url", "url": "https://example.test/alpha"}],
        ),
        "Map beta": (
            "Beta node",
            ["Apply beta"],
            [{"kind": "book", "title": "Beta reference"}],
        ),
    }
    for space_title, (node_title, objectives, basis) in metadata.items():
        _create_space_with_node(
            client,
            space_title=space_title,
            node_title=node_title,
            learning_objectives=objectives,
            source_basis=basis,
        )

    exported_response = client.get("/api/data/export")
    assert exported_response.status_code == 200, exported_response.text
    exported = exported_response.json()
    assert len(exported["maps"]) == 2
    exported_nodes = {
        node["title"]: node for map_payload in exported["maps"] for node in map_payload["nodes"]
    }
    for node_title, objectives, basis in metadata.values():
        assert exported_nodes[node_title]["learning_objectives"] == objectives
        assert exported_nodes[node_title]["source_basis"] == basis

    imported_response = client.post("/api/data/import", json={"payload": exported})
    assert imported_response.status_code == 201, imported_response.text
    imported = imported_response.json()
    assert imported["imported_map_count"] == 2
    assert len(imported["maps"]) == 2
    imported_nodes = {
        node["title"]: node
        for graph in imported["maps"]
        for node in graph["nodes"]
        if node["status"] != "ARCHIVED"
    }
    for node_title, objectives, basis in metadata.values():
        assert imported_nodes[node_title]["learning_objectives"] == objectives
        assert imported_nodes[node_title]["source_basis"] == basis
    assert len(client.get("/api/spaces").json()) == 4


@pytest.mark.integration
def test_unmodified_accepted_ai_suggestion_can_be_reverted(client: TestClient) -> None:
    suggestion = _accept_mock_suggestion(client)
    changes = suggestion["accepted_changes"]

    revert = client.post(f"/api/ai/suggestions/{suggestion['id']}/revert")
    assert revert.status_code == 200, revert.text
    assert revert.json()["review_status"] == "REVERTED"

    graph_response = client.get(f"/api/spaces/{changes['space_id']}/graph")
    assert graph_response.status_code == 200, graph_response.text
    graph = graph_response.json()
    accepted_node_ids = set(changes["node_ids"])
    accepted_edge_ids = set(changes["edge_ids"])
    assert {
        item["id"] for item in graph["nodes"] if item["status"] == "ARCHIVED"
    } >= accepted_node_ids
    assert {
        item["id"] for item in graph["edges"] if item["status"] == "ARCHIVED"
    } >= accepted_edge_ids


@pytest.mark.integration
def test_ai_revert_refuses_to_archive_a_later_human_node_edit(client: TestClient) -> None:
    suggestion = _accept_mock_suggestion(client)
    changes = suggestion["accepted_changes"]
    node_id = changes["node_ids"][0]
    human_title = "Human-owned revision"
    edited = client.patch(
        f"/api/spaces/{changes['space_id']}/nodes/{node_id}",
        json={"title": human_title},
    )
    assert edited.status_code == 200, edited.text

    revert = client.post(f"/api/ai/suggestions/{suggestion['id']}/revert")
    assert revert.status_code == 409, revert.text
    assert revert.json()["detail"]["code"] == "suggestion_review_error"

    graph = client.get(f"/api/spaces/{changes['space_id']}/graph").json()
    retained = next(item for item in graph["nodes"] if item["id"] == node_id)
    assert retained["title"] == human_title
    assert retained["status"] != "ARCHIVED"
    assert all(
        item["status"] != "ARCHIVED"
        for item in graph["edges"]
        if item["id"] in set(changes["edge_ids"])
    )


@pytest.mark.integration
def test_ai_revert_refuses_to_archive_a_later_human_relationship(
    client: TestClient,
) -> None:
    suggestion = _accept_mock_suggestion(client)
    changes = suggestion["accepted_changes"]
    human_node = client.post(
        f"/api/spaces/{changes['space_id']}/nodes",
        json={"title": "Human-added extension"},
    )
    assert human_node.status_code == 201, human_node.text
    human_edge = client.post(
        f"/api/spaces/{changes['space_id']}/edges",
        json={
            "source_node_id": changes["node_ids"][0],
            "target_node_id": human_node.json()["id"],
            "relation_type": "RELATED",
            "reason": "Added after AI review",
        },
    )
    assert human_edge.status_code == 201, human_edge.text

    revert = client.post(f"/api/ai/suggestions/{suggestion['id']}/revert")
    assert revert.status_code == 409, revert.text
    assert revert.json()["detail"]["code"] == "suggestion_review_error"

    graph = client.get(f"/api/spaces/{changes['space_id']}/graph").json()
    retained_node = next(item for item in graph["nodes"] if item["id"] == human_node.json()["id"])
    retained_edge = next(item for item in graph["edges"] if item["id"] == human_edge.json()["id"])
    assert retained_node["status"] != "ARCHIVED"
    assert retained_edge["status"] != "ARCHIVED"
    assert all(
        item["status"] != "ARCHIVED"
        for item in graph["nodes"]
        if item["id"] in set(changes["node_ids"])
    )


@pytest.mark.integration
def test_user_header_enforces_space_and_ai_suggestion_ownership(client: TestClient) -> None:
    first_space, first_node = _create_space_with_node(client, space_title="Private map")
    first_suggestion_response = client.post(
        "/api/ai/suggestions/generate",
        json={"source_text": "Private suggestion", "space_id": first_space["id"]},
    )
    assert first_suggestion_response.status_code == 201, first_suggestion_response.text
    first_suggestion = first_suggestion_response.json()

    with client.app.state.session_factory() as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        second_user = repository.ensure_user(
            display_name="Second learner", email="second-learner@example.test"
        )
        second_user_id = second_user.id
        session.commit()
    second_headers = {"X-User-ID": second_user_id}

    assert client.get("/api/spaces", headers=second_headers).json() == []
    foreign_graph = client.get(f"/api/spaces/{first_space['id']}/graph", headers=second_headers)
    assert foreign_graph.status_code == 404
    foreign_edit = client.patch(
        f"/api/spaces/{first_space['id']}/nodes/{first_node['id']}",
        headers=second_headers,
        json={"title": "Unauthorized edit"},
    )
    assert foreign_edit.status_code == 404

    assert client.get("/api/ai/suggestions", headers=second_headers).json() == []
    scoped_foreign_list = client.get(
        "/api/ai/suggestions",
        headers=second_headers,
        params={"space_id": first_space["id"]},
    )
    assert scoped_foreign_list.status_code == 404
    foreign_review = client.post(
        f"/api/ai/suggestions/{first_suggestion['id']}/review",
        headers=second_headers,
        json={"action": "reject"},
    )
    assert foreign_review.status_code == 404

    owner_graph = client.get(f"/api/spaces/{first_space['id']}/graph").json()
    assert (
        next(item for item in owner_graph["nodes"] if item["id"] == first_node["id"])["title"]
        == "Foundation"
    )
    owner_suggestions = client.get("/api/ai/suggestions").json()
    retained_suggestion = next(
        item for item in owner_suggestions if item["id"] == first_suggestion["id"]
    )
    assert retained_suggestion["review_status"] == "PENDING"


@pytest.mark.integration
@pytest.mark.parametrize(
    "field",
    [
        "title",
        "description",
        "detailed_description",
        "node_type",
        "difficulty",
        "depth_level",
        "learning_objectives",
        "source_basis",
    ],
)
def test_node_update_rejects_explicit_null(client: TestClient, field: str) -> None:
    space, node = _create_space_with_node(client)
    response = client.patch(
        f"/api/spaces/{space['id']}/nodes/{node['id']}",
        json={field: None},
    )
    assert response.status_code == 422, response.text
