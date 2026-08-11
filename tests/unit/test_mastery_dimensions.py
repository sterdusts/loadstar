"""Unit coverage for replayable multi-dimensional mastery rules."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from learning_navigator.application.dto.mastery_dimensions import (
    MasteryEvidenceDTO,
    NodeMasteryStateDTO,
    RouteGateResultDTO,
)
from learning_navigator.domain.services.mastery_dimensions import (
    DimensionRequirement,
    EvidenceMeasurement,
    MasteryDimension,
    MasteryDimensionsService,
    MasteryEvidence,
    MasteryEvidenceKind,
    RouteGateBlockReason,
    VerificationStatus,
)

NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


def evidence(
    evidence_id: str,
    kind: MasteryEvidenceKind,
    *measurements: tuple[MasteryDimension, float],
    observed_at: datetime = NOW,
    confidence: float = 1.0,
) -> MasteryEvidence:
    return MasteryEvidence(
        evidence_id=evidence_id,
        node_id="quadratic-functions",
        kind=kind,
        observed_at=observed_at,
        measurements=tuple(
            EvidenceMeasurement(dimension=dimension, score=score)
            for dimension, score in measurements
        ),
        evidence_confidence=confidence,
    )


def test_missing_data_is_explicitly_unassessed_in_all_four_dimensions() -> None:
    state = MasteryDimensionsService().empty_state("quadratic-functions", projected_at=NOW)

    assert {item.dimension for item in state.dimensions} == set(MasteryDimension)
    assert all(
        item.verification_status is VerificationStatus.UNASSESSED for item in state.dimensions
    )
    assert all(item.score == 0 and item.confidence == 0 for item in state.dimensions)
    assert all(item.evidence_count == 0 for item in state.dimensions)


def test_self_report_creates_a_low_confidence_non_verified_estimate() -> None:
    service = MasteryDimensionsService()
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "self-1",
                MasteryEvidenceKind.SELF_REPORT,
                (MasteryDimension.CONCEPT_UNDERSTANDING, 82),
            )
        ],
        as_of=NOW,
    )

    concept = state.state_for(MasteryDimension.CONCEPT_UNDERSTANDING)
    assert concept.score == 82
    assert concept.confidence == pytest.approx(0.15)
    assert concept.verification_status is VerificationStatus.SELF_REPORTED
    assert concept.evidence_count == 1
    assert concept.verified_evidence_count == 0
    assert concept.next_review_at == NOW + timedelta(days=3)


def test_first_objective_evidence_replaces_instead_of_averaging_self_report() -> None:
    service = MasteryDimensionsService()
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "self-1",
                MasteryEvidenceKind.SELF_REPORT,
                (MasteryDimension.PROCEDURAL_SKILL, 95),
                observed_at=NOW,
            ),
            evidence(
                "exercise-1",
                MasteryEvidenceKind.EXERCISE,
                (MasteryDimension.PROCEDURAL_SKILL, 40),
                observed_at=NOW + timedelta(hours=1),
            ),
        ],
        as_of=NOW + timedelta(hours=1),
    )

    procedural = state.state_for(MasteryDimension.PROCEDURAL_SKILL)
    assert procedural.score == 40
    assert procedural.confidence == pytest.approx(0.35)
    assert procedural.verification_status is VerificationStatus.VERIFIED
    assert procedural.evidence_count == 2
    assert procedural.verified_evidence_count == 1


@pytest.mark.parametrize(
    ("kind", "review_days"),
    [
        pytest.param(MasteryEvidenceKind.EXERCISE, 14, id="exercise"),
        pytest.param(MasteryEvidenceKind.PROJECT, 30, id="project"),
        pytest.param(MasteryEvidenceKind.RECALL, 7, id="recall"),
    ],
)
def test_objective_evidence_kinds_verify_and_set_explicit_review_date(
    kind: MasteryEvidenceKind,
    review_days: int,
) -> None:
    state = MasteryDimensionsService().replay(
        "quadratic-functions",
        [evidence("objective-1", kind, (MasteryDimension.APPLICATION_SKILL, 78))],
        as_of=NOW,
    )

    application = state.state_for(MasteryDimension.APPLICATION_SKILL)
    assert application.verification_status is VerificationStatus.VERIFIED
    assert application.verified_evidence_count == 1
    assert application.next_review_at == NOW + timedelta(days=review_days)


def test_self_report_cannot_overwrite_or_extend_verified_mastery() -> None:
    service = MasteryDimensionsService()
    verified_at = NOW
    self_reported_at = NOW + timedelta(days=1)
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "exercise-1",
                MasteryEvidenceKind.EXERCISE,
                (MasteryDimension.CONCEPT_UNDERSTANDING, 60),
                observed_at=verified_at,
            ),
            evidence(
                "self-1",
                MasteryEvidenceKind.SELF_REPORT,
                (MasteryDimension.CONCEPT_UNDERSTANDING, 100),
                observed_at=self_reported_at,
            ),
        ],
        as_of=self_reported_at,
    )

    concept = state.state_for(MasteryDimension.CONCEPT_UNDERSTANDING)
    assert concept.score == 60
    assert concept.confidence == pytest.approx(0.35)
    assert concept.verification_status is VerificationStatus.VERIFIED
    assert concept.next_review_at == verified_at + timedelta(days=14)
    assert concept.last_learning_time == self_reported_at
    assert concept.evidence_count == 2


def test_replay_is_order_independent_and_reports_algorithm_version() -> None:
    service = MasteryDimensionsService(algorithm_version="mastery-dimensions-test")
    events = [
        evidence(
            "later",
            MasteryEvidenceKind.EXERCISE,
            (MasteryDimension.PROCEDURAL_SKILL, 20),
            observed_at=NOW + timedelta(hours=2),
        ),
        evidence(
            "earlier",
            MasteryEvidenceKind.EXERCISE,
            (MasteryDimension.PROCEDURAL_SKILL, 80),
            observed_at=NOW,
        ),
    ]

    forward = service.replay("quadratic-functions", events, as_of=NOW + timedelta(hours=2))
    reversed_input = service.replay(
        "quadratic-functions", reversed(events), as_of=NOW + timedelta(hours=2)
    )

    assert forward == reversed_input
    assert forward.state_for(MasteryDimension.PROCEDURAL_SKILL).score == pytest.approx(59)
    assert forward.algorithm_version == "mastery-dimensions-test"
    assert all(item.algorithm_version == "mastery-dimensions-test" for item in forward.dimensions)


def test_point_in_time_replay_excludes_future_evidence() -> None:
    state = MasteryDimensionsService().replay(
        "quadratic-functions",
        [
            evidence(
                "future",
                MasteryEvidenceKind.PROJECT,
                (MasteryDimension.APPLICATION_SKILL, 100),
                observed_at=NOW + timedelta(days=1),
            )
        ],
        as_of=NOW,
    )

    assert (
        state.state_for(MasteryDimension.APPLICATION_SKILL).verification_status
        is VerificationStatus.UNASSESSED
    )
    assert state.applied_evidence_ids == ()


def test_due_evidence_becomes_stale_without_erasing_score() -> None:
    state = MasteryDimensionsService().replay(
        "quadratic-functions",
        [
            evidence(
                "recall-1",
                MasteryEvidenceKind.RECALL,
                (MasteryDimension.MEMORY_STRENGTH, 90),
            )
        ],
        as_of=NOW + timedelta(days=7),
    )

    memory = state.state_for(MasteryDimension.MEMORY_STRENGTH)
    assert memory.score == 90
    assert memory.verification_status is VerificationStatus.STALE


def test_route_readiness_uses_the_weakest_dimension_not_an_average() -> None:
    service = MasteryDimensionsService()
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "project-1",
                MasteryEvidenceKind.PROJECT,
                (MasteryDimension.CONCEPT_UNDERSTANDING, 100),
                (MasteryDimension.PROCEDURAL_SKILL, 100),
                (MasteryDimension.APPLICATION_SKILL, 40),
            )
        ],
        as_of=NOW,
    )
    requirements = [
        DimensionRequirement(dimension, minimum_score=80)
        for dimension in (
            MasteryDimension.CONCEPT_UNDERSTANDING,
            MasteryDimension.PROCEDURAL_SKILL,
            MasteryDimension.APPLICATION_SKILL,
        )
    ]

    result = service.evaluate_route_gate(state, requirements)

    assert result.allowed is False
    assert result.readiness_score == 50
    assert result.blocking_dimensions == (MasteryDimension.APPLICATION_SKILL,)
    assert result.gaps[0].reasons == (RouteGateBlockReason.SCORE_BELOW_THRESHOLD,)


def test_route_gate_does_not_treat_self_report_as_verified_by_default() -> None:
    service = MasteryDimensionsService()
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "self-1",
                MasteryEvidenceKind.SELF_REPORT,
                (MasteryDimension.CONCEPT_UNDERSTANDING, 100),
            )
        ],
        as_of=NOW,
    )

    strict = service.evaluate_route_gate(
        state,
        [DimensionRequirement(MasteryDimension.CONCEPT_UNDERSTANDING, 70)],
    )
    permissive = service.evaluate_route_gate(
        state,
        [
            DimensionRequirement(
                MasteryDimension.CONCEPT_UNDERSTANDING,
                70,
                require_verified=False,
            )
        ],
    )

    assert strict.allowed is False
    assert strict.gaps[0].reasons == (RouteGateBlockReason.VERIFICATION_INSUFFICIENT,)
    assert permissive.allowed is True


def test_route_gate_reports_stale_and_confidence_failures_separately() -> None:
    service = MasteryDimensionsService()
    state = service.replay(
        "quadratic-functions",
        [
            evidence(
                "recall-1",
                MasteryEvidenceKind.RECALL,
                (MasteryDimension.MEMORY_STRENGTH, 95),
                confidence=0.5,
            )
        ],
        as_of=NOW + timedelta(days=8),
    )

    result = service.evaluate_route_gate(
        state,
        [DimensionRequirement(MasteryDimension.MEMORY_STRENGTH, 80, minimum_confidence=0.5)],
    )

    assert result.allowed is False
    assert RouteGateBlockReason.STALE in result.gaps[0].reasons
    assert RouteGateBlockReason.CONFIDENCE_BELOW_THRESHOLD in result.gaps[0].reasons


def test_duplicate_evidence_id_is_rejected_during_replay() -> None:
    duplicate = evidence(
        "same-id",
        MasteryEvidenceKind.EXERCISE,
        (MasteryDimension.CONCEPT_UNDERSTANDING, 70),
    )

    with pytest.raises(ValueError, match="evidence_id values must be unique"):
        MasteryDimensionsService().replay("quadratic-functions", [duplicate, duplicate], as_of=NOW)


def test_state_evidence_and_gate_dtos_round_trip_as_json() -> None:
    service = MasteryDimensionsService()
    source_evidence = evidence(
        "project-1",
        MasteryEvidenceKind.PROJECT,
        (MasteryDimension.APPLICATION_SKILL, 88),
    )
    state = service.replay("quadratic-functions", [source_evidence], as_of=NOW)
    gate = service.evaluate_route_gate(
        state,
        [DimensionRequirement(MasteryDimension.APPLICATION_SKILL, 80, minimum_confidence=0.4)],
    )

    evidence_json = MasteryEvidenceDTO.from_domain(source_evidence).model_dump_json()
    state_json = NodeMasteryStateDTO.from_domain(state).model_dump_json()
    gate_json = RouteGateResultDTO.from_domain(gate).model_dump_json()

    assert MasteryEvidenceDTO.model_validate_json(evidence_json).to_domain() == source_evidence
    assert NodeMasteryStateDTO.model_validate_json(state_json).to_domain() == state
    assert RouteGateResultDTO.model_validate_json(gate_json).allowed is True


def test_persistence_dto_rejects_an_impossible_unassessed_state() -> None:
    with pytest.raises(ValidationError, match="UNASSESSED state cannot contain inferred"):
        NodeMasteryStateDTO.model_validate(
            {
                "node_id": "quadratic-functions",
                "dimensions": [
                    {
                        "dimension": dimension.value,
                        "score": 20 if dimension is MasteryDimension.CONCEPT_UNDERSTANDING else 0,
                    }
                    for dimension in MasteryDimension
                ],
            }
        )
